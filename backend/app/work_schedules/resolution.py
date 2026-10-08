from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.shared.models import (
    BreakPeriod,
    Employee,
    EmployeeWorkAssignment,
    Shift,
    WorkSchedule,
    WorkScheduleDay,
)


@dataclass
class ResolvedDay:
    """The effective schedule of one employee on one date.

    ``start_time``/``end_time`` are the working window for the day (from
    the effective shift when one applies, otherwise from the schedule-day
    rule); both are ``None`` for rest days or unconfigured days. ``breaks``
    are the breaks that apply to this day (schedule-day breaks override
    shift breaks when both exist).
    """

    day: date
    weekday: int
    timezone: str
    assignment: EmployeeWorkAssignment | None = None
    schedule: WorkSchedule | None = None
    day_rule: WorkScheduleDay | None = None
    shift: Shift | None = None
    is_working: bool = False
    start_time: time | None = None
    end_time: time | None = None
    breaks: list[BreakPeriod] = field(default_factory=list)

    @property
    def crosses_midnight(self) -> bool:
        if self.start_time is None or self.end_time is None:
            return False
        return self.end_time < self.start_time

    @property
    def has_window(self) -> bool:
        return (
            self.is_working
            and self.start_time is not None
            and self.end_time is not None
        )


def _company_timezone(db: Session, company_id: int) -> str:
    from app.shared.models import Company

    company = db.get(Company, company_id)
    if company is not None and company.timezone:
        return company.timezone
    return "Asia/Riyadh"


def resolve_employee_schedule(
    db: Session, employee: Employee, target_date: date
) -> ResolvedDay:
    """Effective-dated schedule resolution (spec: resolve_employee_schedule).

    Priority for the working window:
    1. assignment.shift_id      (employee-specific shift override)
    2. work_schedule_days.shift_id (weekday shift pinned to the schedule)
    3. work_schedule_days start/end times (plain day window)

    An employee without an effective assignment resolves to "no schedule"
    (``schedule is None``, not working): attendance still records the
    check-in/out instants, but scheduled/late/early/overtime metrics stay
    at zero until an assignment exists.
    """
    assignment = db.execute(
        select(EmployeeWorkAssignment)
        .where(
            EmployeeWorkAssignment.employee_id == employee.id,
            EmployeeWorkAssignment.company_id == employee.company_id,
            EmployeeWorkAssignment.effective_from <= target_date,
            (
                EmployeeWorkAssignment.effective_to.is_(None)
                | (EmployeeWorkAssignment.effective_to >= target_date)
            ),
        )
        .order_by(EmployeeWorkAssignment.effective_from.desc())
        .limit(1)
    ).scalar_one_or_none()

    schedule = None
    timezone = _company_timezone(db, employee.company_id)
    if assignment is not None:
        schedule = db.get(WorkSchedule, assignment.schedule_id)
        if schedule is not None:
            timezone = schedule.timezone

    resolved = ResolvedDay(
        day=target_date,
        weekday=target_date.weekday(),  # ISO: Monday=0 ... Sunday=6
        timezone=timezone,
        assignment=assignment,
        schedule=schedule,
    )
    if schedule is None:
        return resolved

    day_rule = db.execute(
        select(WorkScheduleDay).where(
            WorkScheduleDay.schedule_id == schedule.id,
            WorkScheduleDay.weekday == resolved.weekday,
        )
    ).scalar_one_or_none()
    resolved.day_rule = day_rule
    if day_rule is None or not day_rule.is_working:
        return resolved

    resolved.is_working = True

    shift: Shift | None = None
    if assignment is not None and assignment.shift_id is not None:
        shift = db.get(Shift, assignment.shift_id)
    elif day_rule.shift_id is not None:
        shift = db.get(Shift, day_rule.shift_id)
    resolved.shift = shift

    if shift is not None:
        resolved.start_time = shift.start_time
        resolved.end_time = shift.end_time
    else:
        resolved.start_time = day_rule.start_time
        resolved.end_time = day_rule.end_time

    day_breaks = list(
        db.execute(
            select(BreakPeriod).where(
                BreakPeriod.schedule_day_id == day_rule.id
            )
        ).scalars()
    )
    if day_breaks:
        resolved.breaks = day_breaks
    elif shift is not None:
        resolved.breaks = list(
            db.execute(
                select(BreakPeriod).where(BreakPeriod.shift_id == shift.id)
            ).scalars()
        )
    return resolved
