from __future__ import annotations

from datetime import date, datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.exceptions import (
    ScheduleTimezoneError,
    WorkScheduleBreakError,
    WorkScheduleTimeRangeError,
)

DAY_MINUTES = 24 * 60


def validate_timezone(value: str) -> tzinfo:
    """Parse an IANA timezone name; raises a stable domain error when the
    zone is unknown (never hardcode Asia/Riyadh in business logic)."""
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        raise ScheduleTimezoneError(f"Unknown timezone: {value}") from exc


def crosses_midnight(start: time, end: time) -> bool:
    """True when the window runs into the next calendar day (22:00->06:00)."""
    return end < start


def window_total_minutes(start: time, end: time) -> int:
    """Length of a daily window in minutes; overnight aware."""
    span = (
        end.hour * 60 + end.minute - (start.hour * 60 + start.minute)
    ) % DAY_MINUTES
    return span


def validate_nonzero_window(
    start: time,
    end: time,
    error: type[Exception] = WorkScheduleTimeRangeError,
) -> None:
    """Zero-duration windows (start == end) are always invalid. Callers
    choose the domain error (shift window vs schedule-day window)."""
    if start == end:
        raise error("start and end cannot be identical")


def minutes_into_window(moment: time, start: time, end: time) -> int | None:
    """Offset (minutes) of ``moment`` from the window start, or ``None``
    when the moment falls outside the window. Overnight aware: for a
    22:00->06:00 window, 05:30 maps to 450 and 13:00 falls outside."""
    span = window_total_minutes(start, end)
    if span == 0:
        return None
    moment_minutes = moment.hour * 60 + moment.minute
    start_minutes = start.hour * 60 + start.minute
    offset = (moment_minutes - start_minutes) % DAY_MINUTES
    return offset if offset <= span else None


def validate_break_within_window(
    start: time, end: time, window_start: time, window_end: time
) -> int:
    """Validate one break against its parent window; returns its duration
    in minutes. Raises SCHEDULE_INVALID_BREAK when the break is
    zero-length, partially outside the window, or crosses its boundary."""
    if start == end:
        raise WorkScheduleBreakError("break start and end cannot be identical")
    offset_start = minutes_into_window(start, window_start, window_end)
    offset_end = minutes_into_window(end, window_start, window_end)
    if offset_start is None or offset_end is None:
        raise WorkScheduleBreakError(
            "break must fall entirely inside its window"
        )
    if offset_end <= offset_start:
        raise WorkScheduleBreakError("break end must follow its start")
    return offset_end - offset_start


def validate_breaks(
    breaks: list[tuple[time, time, bool]],
    window_start: time,
    window_end: time,
) -> int:
    """Validate a whole break list against one window: every break inside,
    no mutual overlaps. Returns the total UNPAID minutes (paid breaks are
    never deducted from worked time)."""
    positioned: list[tuple[int, int, bool]] = []
    for start, end, is_paid in breaks:
        duration = validate_break_within_window(
            start, end, window_start, window_end
        )
        offset_start = minutes_into_window(start, window_start, window_end)
        positioned.append((offset_start, offset_start + duration, is_paid))
    positioned.sort()
    previous_end: int | None = None
    for offset_start, offset_end, _paid in positioned:
        if previous_end is not None and offset_start < previous_end:
            raise WorkScheduleBreakError("breaks must not overlap each other")
        previous_end = offset_end
    return sum(
        offset_end - offset_start
        for offset_start, offset_end, is_paid in positioned
        if not is_paid
    )


def window_instants(
    day: date, start: time, end: time, timezone: str
) -> tuple[datetime, datetime]:
    """Materialize a daily window as timezone-aware instants for one
    ``work_date`` (the date the window STARTS on)."""
    tz = validate_timezone(timezone)
    start_at = datetime.combine(day, start, tzinfo=tz)
    if crosses_midnight(start, end):
        end_at = datetime.combine(day + timedelta(days=1), end, tzinfo=tz)
    else:
        end_at = datetime.combine(day, end, tzinfo=tz)
    return start_at, end_at
