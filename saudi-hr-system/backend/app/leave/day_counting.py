from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from datetime import timezone as dt_timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.attendance.calculation import unpaid_break_minutes
from app.core.exceptions import (
    LeaveNoScheduleError,
    LeaveOnlyNonWorkingDaysError,
    LeaveRequestRangeError,
    LeaveRequestTimesError,
)
from app.shared.models import CompanyHoliday, Employee, LeaveType
from app.work_schedules.resolution import resolve_employee_schedule
from app.work_schedules.timeutils import minutes_into_window, window_total_minutes

# Safety guard: a single request may never span more than one year of
# calendar dates (keeps counting, previews and JSON snapshots bounded).
MAX_SPAN_DAYS = 366

_QUANT = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return value.quantize(_QUANT, rounding=ROUND_HALF_UP)


def _minutes_of(day_part: time) -> int:
    return day_part.hour * 60 + day_part.minute


@dataclass
class DayCountResult:
    days: Decimal
    mode: str
    entries: list[dict[str, Any]]

    def to_details(self) -> dict[str, Any]:
        """Snapshot stored on leave_requests.count_details (JSONB-safe)."""
        return {
            "mode": self.mode,
            "days": str(self.days),
            "entries": self.entries,
            "computed_at": datetime.now(dt_timezone.utc).isoformat(),
        }


def _holiday_dates(
    db: Session, company_id: int, start: date, end: date
) -> set[date]:
    rows = db.execute(
        select(CompanyHoliday.date).where(
            CompanyHoliday.company_id == company_id,
            CompanyHoliday.status == "active",
            CompanyHoliday.date >= start,
            CompanyHoliday.date <= end,
        )
    ).scalars()
    return set(rows)


def _fraction_for_times(
    resolved: Any, start_time: time, end_time: time
) -> Decimal:
    """Partial-day fraction of ONE working day covered by [start_time,
    end_time], relative to the resolved paid window.

    Raises LEAVE_REQUEST_INVALID_TIMES when the requested range does not
    overlap the working window, and LEAVE_NO_SCHEDULE when the day has no
    usable window or zero paid minutes.
    """
    if end_time <= start_time:
        raise LeaveRequestTimesError(
            "end_time must be later than start_time for partial-day leave"
        )
    if not resolved.has_window:
        raise LeaveNoScheduleError(
            "Partial-day leave requires a resolved working window for that date"
        )
    w_start = resolved.start_time
    w_end = resolved.end_time
    span = window_total_minutes(w_start, w_end)
    if span <= 0:
        raise LeaveNoScheduleError(
            "Resolved working window has no duration for that date"
        )
    if w_end < w_start:
        # Overnight window: work in offset space, clip to [0, span].
        off_start = minutes_into_window(start_time, w_start, w_end)
        off_end = minutes_into_window(end_time, w_start, w_end)
        if off_start is None and off_end is None:
            raise LeaveRequestTimesError(
                "Leave time range does not overlap the working window"
            )
        clip_start = 0 if off_start is None else off_start
        clip_end = span if off_end is None else off_end
        offsets = (clip_start, clip_end)
    else:
        s = _minutes_of(w_start)
        e = s + span
        rs = _minutes_of(start_time)
        re_ = _minutes_of(end_time)
        offsets = (max(rs, s), min(re_, e))
    clip_start, clip_end = offsets
    if clip_end <= clip_start:
        raise LeaveRequestTimesError(
            "Leave time range does not overlap the working window"
        )
    paid_total = span - unpaid_break_minutes(resolved)
    if paid_total <= 0:
        raise LeaveNoScheduleError(
            "Resolved working window has no paid minutes for that date"
        )
    # Deduct unpaid breaks inside the covered slice only.
    deducted = 0
    for brk in resolved.breaks:
        if brk.is_paid:
            continue
        b0 = minutes_into_window(brk.start_time, w_start, w_end)
        b1 = minutes_into_window(brk.end_time, w_start, w_end)
        if b0 is None or b1 is None or b1 <= b0:
            continue
        overlap = min(b1, clip_end) - max(b0, clip_start)
        if overlap > 0:
            deducted += overlap
    leave_minutes = max(1, (clip_end - clip_start) - deducted)
    fraction = _q(Decimal(leave_minutes) / Decimal(paid_total))
    if fraction <= 0:
        fraction = _QUANT
    if fraction > 1:
        fraction = Decimal("1.00")
    return fraction


def count_leave_days(
    db: Session,
    employee: Employee,
    leave_type: LeaveType,
    start_date: date,
    end_date: date,
    start_time: time | None = None,
    end_time: time | None = None,
) -> DayCountResult:
    """The single day-counting engine used by preview, create, submit,
    approve and the balance endpoints.

    Rules (docs/PHASE5.md):
    - ``working_days`` mode: a date counts only when the Phase 4 schedule
      resolver says it is a scheduled working day AND it is not an active
      company holiday; dates with NO configured schedule at all still count
      (there is no rest pattern to apply yet).
    - ``calendar_days`` mode: every date counts (weekends/holidays included)
      - configure this for statutory types whose entitlement is calendar
      based (verify against the cited source before configuring).
    - Same-day partial leave (start_time/end_time) yields a fraction of the
      resolved paid window; it requires a resolvable window.
    - Total must be > 0 or LEAVE_ONLY_NON_WORKING_DAYS is raised.
    """
    if end_date < start_date:
        raise LeaveRequestRangeError("end_date must not be before start_date")
    if (end_date - start_date).days + 1 > MAX_SPAN_DAYS:
        raise LeaveRequestRangeError(
            f"Leave requests may span at most {MAX_SPAN_DAYS} calendar days"
        )
    if (start_time is None) != (end_time is None):
        raise LeaveRequestTimesError(
            "start_time and end_time must be provided together"
        )
    if start_time is not None and start_date != end_date:
        raise LeaveRequestTimesError(
            "Partial-day leave applies to a single date only"
        )
    mode = leave_type.day_counting_mode
    holidays = _holiday_dates(db, employee.company_id, start_date, end_date)

    entries: list[dict[str, Any]] = []
    total = Decimal("0.00")
    day = start_date
    while day <= end_date:
        holiday = day in holidays
        resolved = resolve_employee_schedule(db, employee, day)
        if start_time is not None and end_time is not None:
            # Single-day partial leave.
            if mode == "working_days" and holiday:
                fraction = Decimal("0.00")
                reason = "holiday"
            elif mode == "working_days" and resolved.schedule is not None:
                if not resolved.is_working:
                    fraction = Decimal("0.00")
                    reason = "rest_day"
                else:
                    fraction = _fraction_for_times(resolved, start_time, end_time)
                    reason = "counted"
            elif mode == "working_days" and resolved.schedule is None:
                raise LeaveNoScheduleError(
                    "Partial-day leave requires a work schedule assignment"
                )
            else:  # calendar_days
                if resolved.has_window:
                    fraction = _fraction_for_times(resolved, start_time, end_time)
                    reason = "counted"
                else:
                    raise LeaveNoScheduleError(
                        "Partial-day leave requires a work schedule assignment"
                    )
        else:
            if mode == "working_days":
                if holiday:
                    fraction = Decimal("0.00")
                    reason = "holiday"
                elif resolved.schedule is None:
                    fraction = Decimal("1.00")
                    reason = "counted"
                elif not resolved.is_working:
                    fraction = Decimal("0.00")
                    reason = "rest_day"
                else:
                    fraction = Decimal("1.00")
                    reason = "counted"
            else:  # calendar_days
                fraction = Decimal("1.00")
                reason = "counted"
        entries.append(
            {"date": day.isoformat(), "fraction": str(fraction), "reason": reason}
        )
        total += fraction
        day = date.fromordinal(day.toordinal() + 1)

    days = _q(total)
    if days <= 0:
        raise LeaveOnlyNonWorkingDaysError(
            "The selected range contains no countable leave days"
        )
    return DayCountResult(days=days, mode=mode, entries=entries)


def counted_dates(entries: list[dict[str, Any]]) -> list[date]:
    """Dates with a non-zero fraction (used by conflict checks)."""
    out: list[date] = []
    for entry in entries:
        if Decimal(entry["fraction"]) > 0:
            out.append(date.fromisoformat(entry["date"]))
    return out
