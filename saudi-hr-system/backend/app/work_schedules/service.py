from __future__ import annotations

from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.core.deps import Principal
from app.core.exceptions import (
    ConflictError,
    EmployeeNotFoundError,
    ForbiddenError,
    ShiftNotFoundError,
    WorkScheduleBreakError,
    WorkScheduleCodeExistsError,
    WorkScheduleDateRangeError,
    WorkScheduleInUseError,
    WorkScheduleNotFoundError,
    WorkScheduleTimeRangeError,
)
from app.core.pagination import PageParams
from app.shared.models import (
    BreakPeriod,
    Employee,
    EmployeeWorkAssignment,
    Shift,
    WorkSchedule,
    WorkScheduleDay,
)
from app.work_schedules.resolution import ResolvedDay, resolve_employee_schedule
from app.work_schedules.schemas import (
    DayIn,
    ScheduleCreate,
    ScheduleDaysPut,
    ScheduleUpdate,
)
from app.work_schedules.timeutils import validate_breaks, validate_timezone


def _require(principal: Principal, code: str, company_id: int | None) -> None:
    """Company-scoped permission check (H1)."""
    if not principal.has_permission(code, company_id):
        raise ForbiddenError(f"Missing permission: {code}")


def _resolve_employee(db: Session, employee_id: int, principal: Principal) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None or not principal.can_access_company(employee.company_id):
        raise EmployeeNotFoundError("Employee not found")
    return employee


def _get_schedule(
    db: Session, schedule_id: int, principal: Principal, code: str
) -> WorkSchedule:
    schedule = db.get(WorkSchedule, schedule_id)
    if schedule is None or not principal.can_access_company(schedule.company_id):
        raise WorkScheduleNotFoundError("Work schedule not found")
    _require(principal, code, schedule.company_id)
    return schedule


def _windows_overlap(
    start_a: date, end_a: date | None, start_b: date, end_b: date | None
) -> bool:
    end_a_cmp = end_a or date.max
    end_b_cmp = end_b or date.max
    return start_a <= end_b_cmp and start_b <= end_a_cmp


def _check_code_available(
    db: Session,
    company_id: int,
    code: str,
    effective_from: date,
    effective_to: date | None,
    exclude_id: int | None = None,
) -> None:
    stmt = select(WorkSchedule).where(
        WorkSchedule.company_id == company_id,
        WorkSchedule.code == code,
    )
    if exclude_id is not None:
        stmt = stmt.where(WorkSchedule.id != exclude_id)
    for existing in db.execute(stmt).scalars():
        if _windows_overlap(
            effective_from, effective_to, existing.effective_from, existing.effective_to
        ):
            raise WorkScheduleCodeExistsError(
                "A schedule with this code already covers the requested period"
            )


def _check_date_range(start: date, end: date | None) -> None:
    if end is not None and end < start:
        raise WorkScheduleDateRangeError(
            "effective_to cannot be before effective_from"
        )


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------


def list_schedules(
    db: Session,
    principal: Principal,
    *,
    company_id: int | None = None,
    status: str | None = None,
    search: str | None = None,
    page: PageParams | None = None,
) -> tuple[list[WorkSchedule], int]:
    stmt = select(WorkSchedule)
    count_stmt = select(func.count()).select_from(WorkSchedule)
    if company_id is not None:
        if not principal.can_access_company(company_id):
            raise ForbiddenError("You cannot access this company")
        _require(principal, "work_schedule.view", company_id)
        stmt = stmt.where(WorkSchedule.company_id == company_id)
        count_stmt = count_stmt.where(WorkSchedule.company_id == company_id)
    elif not principal.is_platform_admin:
        allowed = principal.permitted_company_ids("work_schedule.view")
        if not allowed:
            return [], 0
        stmt = stmt.where(WorkSchedule.company_id.in_(allowed))
        count_stmt = count_stmt.where(WorkSchedule.company_id.in_(allowed))
    if status:
        stmt = stmt.where(WorkSchedule.status == status)
        count_stmt = count_stmt.where(WorkSchedule.status == status)
    if search and search.strip():
        like = f"%{search.strip()}%"
        clause = or_(
            WorkSchedule.code.ilike(like),
            WorkSchedule.name_ar.ilike(like),
            WorkSchedule.name_en.ilike(like),
        )
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)
    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(WorkSchedule.id)
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


def get_schedule(
    db: Session, schedule_id: int, principal: Principal
) -> WorkSchedule:
    return _get_schedule(db, schedule_id, principal, "work_schedule.view")


def create_schedule(
    db: Session,
    *,
    payload: ScheduleCreate,
    principal: Principal,
    ip: str | None,
) -> WorkSchedule:
    if not principal.can_access_company(payload.company_id):
        raise ForbiddenError("You cannot create schedules in this company")
    _require(principal, "work_schedule.create", payload.company_id)
    validate_timezone(payload.timezone)
    _check_date_range(payload.effective_from, payload.effective_to)
    _check_code_available(
        db,
        payload.company_id,
        payload.code,
        payload.effective_from,
        payload.effective_to,
    )
    schedule = WorkSchedule(**payload.model_dump())
    db.add(schedule)
    try:
        db.flush()
    except IntegrityError as exc:
        # exq_work_schedule_code_no_overlap is the database-level backstop.
        raise WorkScheduleCodeExistsError(
            "A schedule with this code already covers the requested period"
        ) from exc
    record_audit(
        db,
        action="work_schedule.create",
        entity="work_schedule",
        record_id=schedule.id,
        actor_user_id=principal.user_id,
        company_id=payload.company_id,
        new_value={
            "code": schedule.code,
            "timezone": schedule.timezone,
            "effective_from": str(schedule.effective_from),
            "effective_to": str(schedule.effective_to)
            if schedule.effective_to
            else None,
        },
        ip_address=ip,
    )
    db.flush()
    return schedule


def update_schedule(
    db: Session,
    *,
    schedule_id: int,
    payload: ScheduleUpdate,
    principal: Principal,
    ip: str | None,
) -> WorkSchedule:
    schedule = _get_schedule(db, schedule_id, principal, "work_schedule.update")
    changes = payload.model_dump(exclude_unset=True)
    merged_from = changes.get("effective_from", schedule.effective_from)
    merged_to = changes.get("effective_to", schedule.effective_to)
    if "timezone" in changes:
        validate_timezone(changes["timezone"])
    _check_date_range(merged_from, merged_to)
    merged_code = changes.get("code", schedule.code)
    if merged_from != schedule.effective_from or merged_code != schedule.code:
        _check_code_available(
            db,
            schedule.company_id,
            merged_code,
            merged_from,
            merged_to,
            exclude_id=schedule.id,
        )
    for key, value in changes.items():
        setattr(schedule, key, value)
    db.add(schedule)
    try:
        db.flush()
    except IntegrityError as exc:
        raise WorkScheduleCodeExistsError(
            "A schedule with this code already covers the requested period"
        ) from exc
    record_audit(
        db,
        action="work_schedule.update",
        entity="work_schedule",
        record_id=schedule.id,
        actor_user_id=principal.user_id,
        company_id=schedule.company_id,
        new_value={"fields": sorted(changes)},
        ip_address=ip,
    )
    db.flush()
    return schedule


def delete_schedule(
    db: Session, *, schedule_id: int, principal: Principal, ip: str | None
) -> None:
    schedule = _get_schedule(db, schedule_id, principal, "work_schedule.delete")
    assignments = db.execute(
        select(EmployeeWorkAssignment.id).where(
            EmployeeWorkAssignment.schedule_id == schedule.id
        ).limit(1)
    ).scalar_one_or_none()
    if assignments is not None:
        raise WorkScheduleInUseError(
            "Schedule is referenced by an employee assignment"
        )
    record_audit(
        db,
        action="work_schedule.delete",
        entity="work_schedule",
        record_id=schedule.id,
        actor_user_id=principal.user_id,
        company_id=schedule.company_id,
        old_value={"code": schedule.code, "timezone": schedule.timezone},
        ip_address=ip,
    )
    db.delete(schedule)
    db.flush()


# ---------------------------------------------------------------------------
# Schedule days (weekday rules + breaks)
# ---------------------------------------------------------------------------


def _day_breaks(db: Session, day: WorkScheduleDay) -> list[BreakPeriod]:
    return list(
        db.execute(
            select(BreakPeriod).where(BreakPeriod.schedule_day_id == day.id)
        ).scalars()
    )


def _validate_day(
    db: Session, company_id: int, day: DayIn
) -> None:
    if not day.is_working:
        if day.start_time is not None or day.end_time is not None:
            raise WorkScheduleTimeRangeError(
                "Rest days cannot define a working window"
            )
        if day.breaks:
            raise WorkScheduleBreakError("Rest days cannot define breaks")
        return
    if day.shift_id is not None and (
        day.start_time is not None or day.end_time is not None
    ):
        raise WorkScheduleTimeRangeError(
            "A pinned shift defines the working window; "
            "do not set start/end times on the same day"
        )
    if (day.start_time is None) != (day.end_time is None):
        raise WorkScheduleTimeRangeError(
            "start_time and end_time must be provided together"
        )
    if day.start_time is not None and day.end_time is not None:
        if day.start_time == day.end_time:
            raise WorkScheduleTimeRangeError(
                "start and end cannot be identical"
            )
    if day.shift_id is not None:
        shift = db.get(Shift, day.shift_id)
        if shift is None or shift.company_id != company_id:
            raise ShiftNotFoundError("Shift not found")
    if day.breaks:
        if day.start_time is None or day.end_time is None:
            if day.shift_id is None:
                raise WorkScheduleBreakError(
                    "Breaks need a window or a pinned shift"
                )
            shift = db.get(Shift, day.shift_id)
            if shift is None:
                raise ShiftNotFoundError("Shift not found")
            window_start, window_end = shift.start_time, shift.end_time
        else:
            window_start, window_end = day.start_time, day.end_time
        validate_breaks(
            [(b.start_time, b.end_time, b.is_paid) for b in day.breaks],
            window_start,
            window_end,
        )


def list_days(
    db: Session, *, schedule_id: int, principal: Principal
) -> list[WorkScheduleDay]:
    schedule = _get_schedule(db, schedule_id, principal, "work_schedule.view")
    days = list(
        db.execute(
            select(WorkScheduleDay)
            .where(WorkScheduleDay.schedule_id == schedule.id)
            .order_by(WorkScheduleDay.weekday)
        ).scalars()
    )
    return days


def day_break_map(db: Session, days: list[WorkScheduleDay]) -> dict[int, list[BreakPeriod]]:
    return {day.id: _day_breaks(db, day) for day in days}


def put_days(
    db: Session,
    *,
    schedule_id: int,
    payload: ScheduleDaysPut,
    principal: Principal,
    ip: str | None,
) -> list[WorkScheduleDay]:
    schedule = _get_schedule(db, schedule_id, principal, "work_schedule.update")
    weekdays = [day.weekday for day in payload.days]
    if len(set(weekdays)) != len(weekdays):
        raise ConflictError("Duplicate weekday in payload")
    for day in payload.days:
        _validate_day(db, schedule.company_id, day)
        existing = db.execute(
            select(WorkScheduleDay).where(
                WorkScheduleDay.schedule_id == schedule.id,
                WorkScheduleDay.weekday == day.weekday,
            )
        ).scalar_one_or_none()
        if existing is None:
            existing = WorkScheduleDay(
                company_id=schedule.company_id,
                schedule_id=schedule.id,
                weekday=day.weekday,
            )
            db.add(existing)
        existing.is_working = day.is_working
        existing.start_time = day.start_time
        existing.end_time = day.end_time
        existing.shift_id = day.shift_id
        db.flush()
        # Breaks are replace-all for the updated weekday (simple, explicit).
        for old_break in _day_breaks(db, existing):
            db.delete(old_break)
        for brk in day.breaks:
            db.add(
                BreakPeriod(
                    company_id=schedule.company_id,
                    schedule_day_id=existing.id,
                    start_time=brk.start_time,
                    end_time=brk.end_time,
                    is_paid=brk.is_paid,
                )
            )
    db.flush()
    record_audit(
        db,
        action="work_schedule.update",
        entity="work_schedule",
        record_id=schedule.id,
        actor_user_id=principal.user_id,
        company_id=schedule.company_id,
        new_value={"fields": ["days"], "weekdays": sorted(set(weekdays))},
        ip_address=ip,
    )
    db.flush()
    return list_days(db, schedule_id=schedule.id, principal=principal)


# ---------------------------------------------------------------------------
# Resolution endpoint helper
# ---------------------------------------------------------------------------


def resolve_for_employee(
    db: Session, *, employee_id: int, on_date: date, principal: Principal
) -> ResolvedDay:
    employee = _resolve_employee(db, employee_id, principal)
    _require(principal, "employee_work_assignment.view", employee.company_id)
    return resolve_employee_schedule(db, employee, on_date)
