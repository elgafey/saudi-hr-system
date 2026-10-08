from __future__ import annotations

from datetime import date, datetime

from app.work_schedules.resolution import ResolvedDay
from app.work_schedules.timeutils import minutes_into_window, window_instants


def _whole_minutes(start: datetime, end: datetime) -> int:
    """Whole minutes between two instants (floor, never negative)."""
    seconds = (end - start).total_seconds()
    return int(seconds // 60) if seconds >= 0 else 0


def unpaid_break_minutes(resolved: ResolvedDay) -> int:
    """Total UNPAID break minutes inside the resolved window. Paid breaks
    are never deducted. Breaks outside the window (misconfigured legacy
    data) are ignored rather than inflating the deduction."""
    if not resolved.has_window:
        return 0
    window_start = resolved.start_time
    window_end = resolved.end_time
    total = 0
    for brk in resolved.breaks:
        if brk.is_paid:
            continue
        offset_start = minutes_into_window(
            brk.start_time, window_start, window_end
        )
        offset_end = minutes_into_window(brk.end_time, window_start, window_end)
        if offset_start is None or offset_end is None:
            continue
        if offset_end > offset_start:
            total += offset_end - offset_start
    return total


def compute_metrics(
    resolved: ResolvedDay,
    work_date: date,
    check_in: datetime,
    check_out: datetime | None,
) -> dict[str, int] | None:
    """Computed minute columns for one attendance record.

    Returns ``None`` while the record is open (or administratively closed
    as missing_checkout) - those columns stay NULL. Rules (docs/PHASE4.md):

    - worked       = span(check_in -> check_out) - unpaid breaks (>= 0)
    - scheduled    = window length - unpaid breaks (0 without a window)
    - break        = unpaid break minutes deducted
    - late         = max(0, check_in - window_start)
    - early_leave  = max(0, window_end - check_out)
    - ot_candidate = max(0, check_out - window_end)  (never approved here)

    Without a resolved schedule the record still stores the raw span as
    worked time; scheduled/late/early/overtime stay zero.
    """
    if check_out is None:
        return None
    span = _whole_minutes(check_in, check_out)
    if not resolved.has_window:
        return {
            "scheduled_minutes": 0,
            "worked_minutes": span,
            "break_minutes": 0,
            "late_minutes": 0,
            "early_leave_minutes": 0,
            "overtime_candidate_minutes": 0,
        }
    window_start, window_end = window_instants(
        work_date,
        resolved.start_time,
        resolved.end_time,
        resolved.timezone,
    )
    unpaid = unpaid_break_minutes(resolved)
    window_length = _whole_minutes(window_start, window_end)
    return {
        "scheduled_minutes": max(0, window_length - unpaid),
        "worked_minutes": max(0, span - unpaid),
        "break_minutes": unpaid,
        "late_minutes": _whole_minutes(window_start, check_in),
        "early_leave_minutes": _whole_minutes(check_out, window_end),
        "overtime_candidate_minutes": _whole_minutes(window_end, check_out),
    }
