from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.core.deps import Principal
from app.core.exceptions import (
    ConflictError,
    EmployeeNotFoundError,
    EmploymentHistoryDateRangeError,
    EmploymentHistoryOverlapError,
    ForbiddenError,
)
from app.core.pagination import PageParams
from app.employees.service import _validate_fk_fields
from app.employment_history.schemas import HistoryCreate
from app.shared.models import Employee, EmployeeEmploymentHistory


def _require(principal: Principal, code: str, company_id: int | None) -> None:
    """Company-scoped permission check (H1)."""
    if not principal.has_permission(code, company_id):
        raise ForbiddenError(f"Missing permission: {code}")


def _resolve_employee(db: Session, employee_id: int, principal: Principal) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None or not principal.can_access_company(employee.company_id):
        raise EmployeeNotFoundError("Employee not found")
    return employee


def _validate_dates(effective_from: date, effective_to: date | None) -> None:
    if effective_to is not None and effective_to < effective_from:
        raise EmploymentHistoryDateRangeError(
            "effective_to cannot be before effective_from"
        )


def _history_for(db: Session, employee_id: int) -> list[EmployeeEmploymentHistory]:
    stmt = (
        select(EmployeeEmploymentHistory)
        .where(EmployeeEmploymentHistory.employee_id == employee_id)
        .order_by(
            EmployeeEmploymentHistory.effective_from, EmployeeEmploymentHistory.id
        )
    )
    return list(db.execute(stmt).scalars())


def _overlaps(
    existing: EmployeeEmploymentHistory,
    new_from: date,
    new_to: date | None,
) -> bool:
    """Range overlap treating a NULL effective_to as +infinity
    (mirrors the daterange EXCLUDE constraint, closed-open intervals)."""
    if existing.effective_from > (new_to if new_to is not None else date.max):
        return False
    if existing.effective_to is None:
        return True
    return existing.effective_to >= new_from


def list_history(
    db: Session,
    principal: Principal,
    *,
    employee_id: int,
    page: PageParams | None = None,
) -> tuple[list[EmployeeEmploymentHistory], int]:
    employee = _resolve_employee(db, employee_id, principal)
    _require(principal, "employee_history.view", employee.company_id)
    stmt = select(EmployeeEmploymentHistory).where(
        EmployeeEmploymentHistory.employee_id == employee.id,
        EmployeeEmploymentHistory.company_id == employee.company_id,
    )
    count_stmt = (
        select(func.count())
        .select_from(EmployeeEmploymentHistory)
        .where(EmployeeEmploymentHistory.employee_id == employee.id)
    )
    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(
        EmployeeEmploymentHistory.effective_from.desc(),
        EmployeeEmploymentHistory.id.desc(),
    )
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


def create_history(
    db: Session,
    *,
    employee_id: int,
    payload: HistoryCreate,
    principal: Principal,
    ip: str | None,
) -> EmployeeEmploymentHistory:
    employee = _resolve_employee(db, employee_id, principal)
    _require(principal, "employee_history.create", employee.company_id)
    company_id = employee.company_id
    data = payload.model_dump()
    apply_to_employee = data.pop("apply_to_employee")
    new_from = data["effective_from"]
    new_to = data["effective_to"]
    _validate_dates(new_from, new_to)

    # Cross-table FKs must resolve inside the employee's company (404).
    _validate_fk_fields(
        db,
        {
            "branch_id": data["branch_id"],
            "department_id": data["department_id"],
            "job_position_id": data["position_id"],
            "job_grade_id": data["grade_id"],
            "manager_id": data["manager_id"],
        },
        company_id,
    )
    if data["manager_id"] is not None and data["manager_id"] == employee.id:
        raise ConflictError("An employee cannot be their own manager")

    # Overlap policy: a new period that starts AFTER the currently-open
    # record auto-closes it (yesterday); every other overlap is rejected.
    # The database EXCLUDE constraint backstops this logic.
    rows = _history_for(db, employee.id)
    open_row = next((r for r in rows if r.effective_to is None), None)
    if open_row is not None and new_from > open_row.effective_from:
        open_row.effective_to = new_from - timedelta(days=1)
        db.add(open_row)
        rows = [r for r in rows if r is not open_row] + [open_row]
    for row in rows:
        if _overlaps(row, new_from, new_to):
            raise EmploymentHistoryOverlapError(
                "Employment history records cannot overlap"
            )

    row = EmployeeEmploymentHistory(
        company_id=company_id,
        employee_id=employee.id,
        effective_from=new_from,
        effective_to=new_to,
        branch_id=data["branch_id"],
        department_id=data["department_id"],
        position_id=data["position_id"],
        grade_id=data["grade_id"],
        manager_id=data["manager_id"],
        employment_status=data["employment_status"],
        employment_type=data["employment_type"],
        change_reason=data["change_reason"],
        notes=data["notes"],
        created_by=principal.user_id,
    )
    db.add(row)
    db.flush()

    if apply_to_employee:
        # Full-snapshot apply: the history row becomes the employee master.
        _require(principal, "employee.update", company_id)
        employee.branch_id = data["branch_id"]
        employee.department_id = data["department_id"]
        employee.job_position_id = data["position_id"]
        employee.job_grade_id = data["grade_id"]
        employee.manager_id = data["manager_id"]
        employee.status = data["employment_status"]
        employee.employment_type = data["employment_type"]
        db.add(employee)

    record_audit(
        db,
        action="employment_history.create",
        entity="employee_employment_history",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=company_id,
        new_value={
            "employee_id": employee.id,
            "effective_from": row.effective_from.isoformat(),
            "effective_to": row.effective_to.isoformat() if row.effective_to else None,
            "change_reason": row.change_reason,
            "applied_to_employee": apply_to_employee,
        },
        ip_address=ip,
    )
    db.flush()
    return row


def record_employee_org_change(
    db: Session,
    *,
    employee: Employee,
    principal: Principal,
    changed_fields: list[str],
) -> None:
    """System bookkeeping called from ``update_employee`` when an
    organization-scope field changes (branch, department, position, grade,
    manager, status, employment_type).

    - no open record: open one effective today;
    - open record already started in the past: close it at today-1 and open
      a new record for today;
    - same-day or future-dated open record: amend it in place (a split
      would be meaningless or invalid).
    """
    today = date.today()
    rows = _history_for(db, employee.id)
    open_row = next((r for r in rows if r.effective_to is None), None)
    snapshot = dict(
        branch_id=employee.branch_id,
        department_id=employee.department_id,
        position_id=employee.job_position_id,
        grade_id=employee.job_grade_id,
        manager_id=employee.manager_id,
        employment_status=employee.status,
        employment_type=employee.employment_type,
    )
    amended = False
    if open_row is None:
        row = EmployeeEmploymentHistory(
            company_id=employee.company_id,
            employee_id=employee.id,
            effective_from=today,
            effective_to=None,
            change_reason="employee_update",
            created_by=principal.user_id,
            **snapshot,
        )
        db.add(row)
    elif today > open_row.effective_from:
        open_row.effective_to = today - timedelta(days=1)
        db.add(open_row)
        row = EmployeeEmploymentHistory(
            company_id=employee.company_id,
            employee_id=employee.id,
            effective_from=today,
            effective_to=None,
            change_reason="employee_update",
            created_by=principal.user_id,
            **snapshot,
        )
        db.add(row)
    else:
        for key, value in snapshot.items():
            setattr(open_row, key, value)
        db.add(open_row)
        row = open_row
        amended = True
    db.flush()
    record_audit(
        db,
        action=(
            "employment_history.update" if amended else "employment_history.create"
        ),
        entity="employee_employment_history",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=employee.company_id,
        new_value={
            "employee_id": employee.id,
            "fields": changed_fields,
            "auto": True,
            "reason": "employee_update",
            "effective_from": row.effective_from.isoformat(),
        },
    )
    db.flush()
