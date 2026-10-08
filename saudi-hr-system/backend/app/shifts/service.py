from __future__ import annotations

from datetime import time

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.core.deps import Principal
from app.core.exceptions import (
    ForbiddenError,
    ShiftCodeExistsError,
    ShiftInUseError,
    ShiftNotFoundError,
    ShiftTimeRangeError,
)
from app.core.pagination import PageParams
from app.shared.models import (
    BreakPeriod,
    EmployeeWorkAssignment,
    Shift,
    WorkScheduleDay,
)
from app.shifts.schemas import ShiftCreate, ShiftUpdate
from app.work_schedules.timeutils import (
    crosses_midnight,
    validate_breaks,
    validate_nonzero_window,
)


def _require(principal: Principal, code: str, company_id: int | None) -> None:
    """Company-scoped permission check (H1)."""
    if not principal.has_permission(code, company_id):
        raise ForbiddenError(f"Missing permission: {code}")


def _get_shift(
    db: Session, shift_id: int, principal: Principal, code: str
) -> Shift:
    shift = db.get(Shift, shift_id)
    if shift is None or not principal.can_access_company(shift.company_id):
        raise ShiftNotFoundError("Shift not found")
    _require(principal, code, shift.company_id)
    return shift


def _shift_breaks(db: Session, shift: Shift) -> list[BreakPeriod]:
    return list(
        db.execute(
            select(BreakPeriod).where(BreakPeriod.shift_id == shift.id)
        ).scalars()
    )


def shift_break_map(
    db: Session, shifts: list[Shift]
) -> dict[int, list[BreakPeriod]]:
    return {shift.id: _shift_breaks(db, shift) for shift in shifts}


def _check_code(db: Session, company_id: int, code: str, exclude_id=None) -> None:
    stmt = select(Shift.id).where(
        Shift.company_id == company_id, Shift.code == code
    )
    if exclude_id is not None:
        stmt = stmt.where(Shift.id != exclude_id)
    if db.execute(stmt.limit(1)).scalar_one_or_none() is not None:
        raise ShiftCodeExistsError("Shift code already exists in this company")


def _validate_window(start: time, end: time) -> None:
    validate_nonzero_window(start, end, error=ShiftTimeRangeError)


def _validate_breaks_against(start: time, end: time, breaks) -> None:
    """Breaks are validated against the shift window; failures surface as
    SCHEDULE_INVALID_BREAK (the shared break error code)."""
    if not breaks:
        return
    validate_breaks(
        [(b.start_time, b.end_time, b.is_paid) for b in breaks], start, end
    )


def list_shifts(
    db: Session,
    principal: Principal,
    *,
    company_id: int | None = None,
    status: str | None = None,
    search: str | None = None,
    page: PageParams | None = None,
) -> tuple[list[Shift], int]:
    stmt = select(Shift)
    count_stmt = select(func.count()).select_from(Shift)
    if company_id is not None:
        if not principal.can_access_company(company_id):
            raise ForbiddenError("You cannot access this company")
        _require(principal, "shift.view", company_id)
        stmt = stmt.where(Shift.company_id == company_id)
        count_stmt = count_stmt.where(Shift.company_id == company_id)
    elif not principal.is_platform_admin:
        allowed = principal.permitted_company_ids("shift.view")
        if not allowed:
            return [], 0
        stmt = stmt.where(Shift.company_id.in_(allowed))
        count_stmt = count_stmt.where(Shift.company_id.in_(allowed))
    if status:
        stmt = stmt.where(Shift.status == status)
        count_stmt = count_stmt.where(Shift.status == status)
    if search and search.strip():
        like = f"%{search.strip()}%"
        clause = or_(
            Shift.code.ilike(like),
            Shift.name_ar.ilike(like),
            Shift.name_en.ilike(like),
        )
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)
    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(Shift.id)
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


def get_shift(db: Session, shift_id: int, principal: Principal) -> Shift:
    return _get_shift(db, shift_id, principal, "shift.view")


def create_shift(
    db: Session, *, payload: ShiftCreate, principal: Principal, ip: str | None
) -> Shift:
    if not principal.can_access_company(payload.company_id):
        raise ForbiddenError("You cannot create shifts in this company")
    _require(principal, "shift.create", payload.company_id)
    _validate_window(payload.start_time, payload.end_time)
    _validate_breaks_against(
        payload.start_time, payload.end_time, payload.breaks
    )
    _check_code(db, payload.company_id, payload.code)
    data = payload.model_dump(exclude={"breaks"})
    shift = Shift(
        **data,
        crosses_midnight=crosses_midnight(payload.start_time, payload.end_time),
    )
    db.add(shift)
    try:
        db.flush()
    except IntegrityError as exc:
        raise ShiftCodeExistsError(
            "Shift code already exists in this company"
        ) from exc
    for brk in payload.breaks:
        db.add(
            BreakPeriod(
                company_id=payload.company_id,
                shift_id=shift.id,
                start_time=brk.start_time,
                end_time=brk.end_time,
                is_paid=brk.is_paid,
            )
        )
    db.flush()
    record_audit(
        db,
        action="shift.create",
        entity="shift",
        record_id=shift.id,
        actor_user_id=principal.user_id,
        company_id=payload.company_id,
        new_value={
            "code": shift.code,
            "start_time": str(shift.start_time),
            "end_time": str(shift.end_time),
            "crosses_midnight": shift.crosses_midnight,
        },
        ip_address=ip,
    )
    db.flush()
    return shift


def update_shift(
    db: Session,
    *,
    shift_id: int,
    payload: ShiftUpdate,
    principal: Principal,
    ip: str | None,
) -> Shift:
    shift = _get_shift(db, shift_id, principal, "shift.update")
    changes = payload.model_dump(exclude_unset=True, exclude={"breaks"})
    merged_start = changes.get("start_time", shift.start_time)
    merged_end = changes.get("end_time", shift.end_time)
    if "start_time" in changes or "end_time" in changes:
        _validate_window(merged_start, merged_end)
        shift.crosses_midnight = crosses_midnight(merged_start, merged_end)
    if payload.breaks is not None:
        _validate_breaks_against(merged_start, merged_end, payload.breaks)
    if "code" in changes and changes["code"] != shift.code:
        _check_code(db, shift.company_id, changes["code"], exclude_id=shift.id)
    for key, value in changes.items():
        setattr(shift, key, value)
    db.add(shift)
    try:
        db.flush()
    except IntegrityError as exc:
        raise ShiftCodeExistsError(
            "Shift code already exists in this company"
        ) from exc
    if payload.breaks is not None:
        for old_break in _shift_breaks(db, shift):
            db.delete(old_break)
        for brk in payload.breaks:
            db.add(
                BreakPeriod(
                    company_id=shift.company_id,
                    shift_id=shift.id,
                    start_time=brk.start_time,
                    end_time=brk.end_time,
                    is_paid=brk.is_paid,
                )
            )
    db.flush()
    record_audit(
        db,
        action="shift.update",
        entity="shift",
        record_id=shift.id,
        actor_user_id=principal.user_id,
        company_id=shift.company_id,
        new_value={"fields": sorted(changes) + (["breaks"] if payload.breaks is not None else [])},
        ip_address=ip,
    )
    db.flush()
    return shift


def delete_shift(
    db: Session, *, shift_id: int, principal: Principal, ip: str | None
) -> None:
    shift = _get_shift(db, shift_id, principal, "shift.delete")
    assignment = db.execute(
        select(EmployeeWorkAssignment.id)
        .where(EmployeeWorkAssignment.shift_id == shift.id)
        .limit(1)
    ).scalar_one_or_none()
    if assignment is not None:
        raise ShiftInUseError("Shift is referenced by an employee assignment")
    pinned = db.execute(
        select(WorkScheduleDay.id)
        .where(WorkScheduleDay.shift_id == shift.id)
        .limit(1)
    ).scalar_one_or_none()
    if pinned is not None:
        raise ShiftInUseError("Shift is pinned to schedule days")
    record_audit(
        db,
        action="shift.delete",
        entity="shift",
        record_id=shift.id,
        actor_user_id=principal.user_id,
        company_id=shift.company_id,
        old_value={"code": shift.code, "start_time": str(shift.start_time)},
        ip_address=ip,
    )
    db.delete(shift)
    db.flush()
