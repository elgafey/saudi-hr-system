from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.core.deps import Principal
from app.core.exceptions import (
    EmployeeNotFoundError,
    ForbiddenError,
    ShiftNotFoundError,
    WorkAssignmentDateRangeError,
    WorkAssignmentNotFoundError,
    WorkAssignmentOverlapError,
    WorkScheduleNotFoundError,
)
from app.core.pagination import PageParams
from app.employee_work_assignments.schemas import (
    AssignmentCreate,
    AssignmentUpdate,
)
from app.shared.models import (
    Employee,
    EmployeeWorkAssignment,
    Shift,
    WorkSchedule,
)


def _require(principal: Principal, code: str, company_id: int | None) -> None:
    """Company-scoped permission check (H1)."""
    if not principal.has_permission(code, company_id):
        raise ForbiddenError(f"Missing permission: {code}")


def _resolve_employee(db: Session, employee_id: int, principal: Principal) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None or not principal.can_access_company(employee.company_id):
        raise EmployeeNotFoundError("Employee not found")
    return employee


def _ranges_overlap(
    start_a: date, end_a: date | None, start_b: date, end_b: date | None
) -> bool:
    end_a_cmp = end_a or date.max
    end_b_cmp = end_b or date.max
    return start_a <= end_b_cmp and start_b <= end_a_cmp


def _check_date_range(start: date, end: date | None) -> None:
    if end is not None and end < start:
        raise WorkAssignmentDateRangeError(
            "effective_to cannot be before effective_from"
        )


def _check_schedule(db: Session, schedule_id: int, company_id: int) -> WorkSchedule:
    schedule = db.get(WorkSchedule, schedule_id)
    if schedule is None or schedule.company_id != company_id:
        raise WorkScheduleNotFoundError("Work schedule not found")
    return schedule


def _check_shift(db: Session, shift_id: int, company_id: int) -> None:
    shift = db.get(Shift, shift_id)
    if shift is None or shift.company_id != company_id:
        raise ShiftNotFoundError("Shift not found")


def _fetch(
    db: Session, employee: Employee, assignment_id: int
) -> EmployeeWorkAssignment:
    row = db.get(EmployeeWorkAssignment, assignment_id)
    if (
        row is None
        or row.employee_id != employee.id
        or row.company_id != employee.company_id
    ):
        raise WorkAssignmentNotFoundError("Work assignment not found")
    return row


def _assert_no_overlap(
    db: Session,
    employee: Employee,
    start: date,
    end: date | None,
    exclude_id: int | None = None,
    *,
    close_open: bool | None = None,
) -> EmployeeWorkAssignment | None:
    """Reject overlapping ranges for the employee (SCHEDULE_ASSIGNMENT_OVERLAP).

    When ``close_open`` is the requested ``start`` (create flow), the single
    OPEN assignment is auto-closed the day before ``start`` instead of
    raising - mirroring the employment-history rule.
    """
    stmt = select(EmployeeWorkAssignment).where(
        EmployeeWorkAssignment.employee_id == employee.id
    )
    if exclude_id is not None:
        stmt = stmt.where(EmployeeWorkAssignment.id != exclude_id)
    open_row: EmployeeWorkAssignment | None = None
    for existing in db.execute(stmt).scalars():
        if existing.effective_to is None:
            open_row = existing
            continue
        if _ranges_overlap(start, end, existing.effective_from, existing.effective_to):
            raise WorkAssignmentOverlapError(
                "Assignment overlaps an existing effective period"
            )
    if open_row is not None:
        if close_open is not None and start > open_row.effective_from:
            open_row.effective_to = start - timedelta(days=1)
            db.add(open_row)
            db.flush()
            return open_row
        raise WorkAssignmentOverlapError(
            "Assignment overlaps an existing effective period"
        )
    return None


def list_assignments(
    db: Session,
    employee_id: int,
    principal: Principal,
    *,
    page: PageParams | None = None,
) -> tuple[list[EmployeeWorkAssignment], int]:
    employee = _resolve_employee(db, employee_id, principal)
    _require(principal, "employee_work_assignment.view", employee.company_id)
    base = select(EmployeeWorkAssignment).where(
        EmployeeWorkAssignment.employee_id == employee.id
    )
    count_stmt = select(func.count()).select_from(EmployeeWorkAssignment).where(
        EmployeeWorkAssignment.employee_id == employee.id
    )
    total = int(db.execute(count_stmt).scalar_one())
    stmt = base.order_by(EmployeeWorkAssignment.effective_from.desc())
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


def get_assignment(
    db: Session, employee_id: int, assignment_id: int, principal: Principal
) -> EmployeeWorkAssignment:
    employee = _resolve_employee(db, employee_id, principal)
    _require(principal, "employee_work_assignment.view", employee.company_id)
    return _fetch(db, employee, assignment_id)


def create_assignment(
    db: Session,
    *,
    employee_id: int,
    payload: AssignmentCreate,
    principal: Principal,
    ip: str | None,
) -> EmployeeWorkAssignment:
    employee = _resolve_employee(db, employee_id, principal)
    _require(
        principal, "employee_work_assignment.create", employee.company_id
    )
    _check_date_range(payload.effective_from, payload.effective_to)
    _check_schedule(db, payload.schedule_id, employee.company_id)
    if payload.shift_id is not None:
        _check_shift(db, payload.shift_id, employee.company_id)
    _assert_no_overlap(
        db,
        employee,
        payload.effective_from,
        payload.effective_to,
        close_open=payload.effective_from,
    )
    row = EmployeeWorkAssignment(
        company_id=employee.company_id,
        employee_id=employee.id,
        schedule_id=payload.schedule_id,
        shift_id=payload.shift_id,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        notes=payload.notes,
        created_by=principal.user_id,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        raise WorkAssignmentOverlapError(
            "Assignment overlaps an existing effective period"
        ) from exc
    record_audit(
        db,
        action="work_assignment.create",
        entity="employee_work_assignment",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=employee.company_id,
        new_value={
            "employee_id": employee.id,
            "schedule_id": row.schedule_id,
            "effective_from": str(row.effective_from),
            "effective_to": str(row.effective_to) if row.effective_to else None,
        },
        ip_address=ip,
    )
    db.flush()
    return row


def update_assignment(
    db: Session,
    *,
    employee_id: int,
    assignment_id: int,
    payload: AssignmentUpdate,
    principal: Principal,
    ip: str | None,
) -> EmployeeWorkAssignment:
    employee = _resolve_employee(db, employee_id, principal)
    _require(
        principal, "employee_work_assignment.update", employee.company_id
    )
    row = _fetch(db, employee, assignment_id)
    changes = payload.model_dump(exclude_unset=True)
    merged_from = changes.get("effective_from", row.effective_from)
    merged_to = changes.get("effective_to", row.effective_to)
    _check_date_range(merged_from, merged_to)
    if "schedule_id" in changes and changes["schedule_id"] is not None:
        _check_schedule(db, changes["schedule_id"], employee.company_id)
    if "shift_id" in changes and changes["shift_id"] is not None:
        _check_shift(db, changes["shift_id"], employee.company_id)
    if merged_from != row.effective_from or merged_to != row.effective_to:
        _assert_no_overlap(
            db, employee, merged_from, merged_to, exclude_id=row.id
        )
    for key, value in changes.items():
        setattr(row, key, value)
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        raise WorkAssignmentOverlapError(
            "Assignment overlaps an existing effective period"
        ) from exc
    record_audit(
        db,
        action="work_assignment.update",
        entity="employee_work_assignment",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=employee.company_id,
        new_value={"employee_id": employee.id, "fields": sorted(changes)},
        ip_address=ip,
    )
    db.flush()
    return row


def delete_assignment(
    db: Session,
    *,
    employee_id: int,
    assignment_id: int,
    principal: Principal,
    ip: str | None,
) -> None:
    employee = _resolve_employee(db, employee_id, principal)
    _require(
        principal, "employee_work_assignment.delete", employee.company_id
    )
    row = _fetch(db, employee, assignment_id)
    record_audit(
        db,
        action="work_assignment.delete",
        entity="employee_work_assignment",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=employee.company_id,
        old_value={
            "employee_id": employee.id,
            "schedule_id": row.schedule_id,
            "effective_from": str(row.effective_from),
            "effective_to": str(row.effective_to) if row.effective_to else None,
        },
        ip_address=ip,
    )
    db.delete(row)
    db.flush()
