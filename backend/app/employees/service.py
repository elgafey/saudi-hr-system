from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.core.deps import Principal
from app.core.exceptions import (
    ConflictError,
    DomainError,
    EmployeeNotFoundError,
    ForbiddenError,
    NotFoundError,
)
from app.core.pagination import PageParams
from app.employees.numbering import (
    next_employee_number,
)
from app.employees.schemas import EmployeeCreate, EmployeeUpdate
from app.shared.models import (
    Branch,
    Department,
    Employee,
    JobGrade,
    JobPosition,
)

_FK_LABELS: dict[str, tuple[str, type]] = {
    "branch_id": ("Branch", Branch),
    "department_id": ("Department", Department),
    "job_position_id": ("Job position", JobPosition),
    "job_grade_id": ("Job grade", JobGrade),
    "manager_id": ("Manager", Employee),
}


def _require(principal: Principal, code: str, company_id: int | None) -> None:
    """Company-scoped permission check (H1)."""
    if not principal.has_permission(code, company_id):
        raise ForbiddenError(f"Missing permission: {code}")


def _normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip().lower()


def _require_visible_in_company(
    db: Session, model: type, row_id: int | None, company_id: int, label: str
) -> None:
    """Cross-table FKs must resolve inside the target company (404 otherwise)."""
    if row_id is None:
        return
    row = db.get(model, row_id)
    if row is None or row.company_id != company_id:
        raise NotFoundError(f"{label} not found")


def _ensure_unique(
    db: Session,
    model: type,
    company_id: int,
    column,
    value: str | None,
    message: str,
    *,
    exclude_id: int | None = None,
) -> None:
    if value is None:
        return
    stmt = select(model.id).where(model.company_id == company_id, column == value)
    if exclude_id is not None:
        stmt = stmt.where(model.id != exclude_id)
    if db.execute(stmt).scalar_one_or_none() is not None:
        raise ConflictError(message)


def _validate_fk_fields(
    db: Session, data: dict, company_id: int, *, exclude_unset: bool = False
) -> None:
    if exclude_unset:
        fields = {k: v for k, v in data.items() if k in _FK_LABELS}
    else:
        fields = data
    for key, value in fields.items():
        if key not in _FK_LABELS:
            continue
        if value is None:
            continue
        label, model = _FK_LABELS[key]
        _require_visible_in_company(db, model, value, company_id, label)


def list_employees(
    db: Session,
    principal: Principal,
    *,
    company_id: int | None = None,
    search: str | None = None,
    status: str | None = None,
    department_id: int | None = None,
    branch_id: int | None = None,
    page: PageParams | None = None,
) -> tuple[list[Employee], int]:
    stmt = select(Employee)
    count_stmt = select(func.count()).select_from(Employee)
    if company_id is not None:
        if not principal.can_access_company(company_id):
            raise ForbiddenError("You cannot access this company")
        _require(principal, "employee.read", company_id)
        stmt = stmt.where(Employee.company_id == company_id)
        count_stmt = count_stmt.where(Employee.company_id == company_id)
    elif not principal.is_platform_admin:
        allowed = principal.permitted_company_ids("employee.read")
        if not allowed:
            return [], 0
        stmt = stmt.where(Employee.company_id.in_(allowed))
        count_stmt = count_stmt.where(Employee.company_id.in_(allowed))

    if search and search.strip():
        like = f"%{search.strip()}%"
        clause = or_(
            Employee.employee_number.ilike(like),
            Employee.first_name_ar.ilike(like),
            Employee.last_name_ar.ilike(like),
            Employee.first_name_en.ilike(like),
            Employee.last_name_en.ilike(like),
            Employee.work_email.ilike(like),
            Employee.personal_email.ilike(like),
        )
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)
    if status:
        stmt = stmt.where(Employee.status == status)
        count_stmt = count_stmt.where(Employee.status == status)
    if department_id is not None:
        stmt = stmt.where(Employee.department_id == department_id)
        count_stmt = count_stmt.where(Employee.department_id == department_id)
    if branch_id is not None:
        stmt = stmt.where(Employee.branch_id == branch_id)
        count_stmt = count_stmt.where(Employee.branch_id == branch_id)

    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(Employee.id)
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


def get_employee(db: Session, employee_id: int, principal: Principal) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None or not principal.can_access_company(employee.company_id):
        raise EmployeeNotFoundError("Employee not found")
    _require(principal, "employee.read", employee.company_id)
    return employee


def create_employee(
    db: Session, *, payload: EmployeeCreate, principal: Principal, ip: str | None
) -> Employee:
    company_id = payload.company_id
    if not principal.can_access_company(company_id):
        raise ForbiddenError("You cannot create employees in this company")
    _require(principal, "employee.create", company_id)

    data = payload.model_dump()
    _validate_fk_fields(db, data, company_id)

    if data["employee_number"] is None:
        data["employee_number"] = next_employee_number(db, company_id)
    _ensure_unique(
        db,
        Employee,
        company_id,
        Employee.employee_number,
        data["employee_number"],
        "Employee number already exists in this company",
    )

    data["personal_email"] = _normalize_email(data["personal_email"])
    data["work_email"] = _normalize_email(data["work_email"])
    _ensure_unique(
        db,
        Employee,
        company_id,
        Employee.work_email,
        data["work_email"],
        "Work email already exists in this company",
    )
    _ensure_unique(
        db,
        Employee,
        company_id,
        Employee.identity_number,
        data["identity_number"],
        "Identity number already exists in this company",
    )

    employee = Employee(**data)
    db.add(employee)
    db.flush()
    # Audit stores non-PII metadata only (employee number + status).
    record_audit(
        db,
        action="employee.create",
        entity="employee",
        record_id=employee.id,
        actor_user_id=principal.user_id,
        company_id=company_id,
        new_value={
            "employee_number": employee.employee_number,
            "status": employee.status,
        },
        ip_address=ip,
    )
    db.flush()
    return employee


def update_employee(
    db: Session,
    *,
    employee: Employee,
    payload: EmployeeUpdate,
    principal: Principal,
    ip: str | None,
) -> Employee:
    company_id = employee.company_id
    if not principal.can_access_company(company_id):
        raise ForbiddenError("You cannot modify this employee")
    _require(principal, "employee.update", company_id)

    changes = payload.model_dump(exclude_unset=True)
    _validate_fk_fields(db, changes, company_id, exclude_unset=True)

    if "manager_id" in changes and changes["manager_id"] == employee.id:
        raise ConflictError("An employee cannot be their own manager")

    if "employee_number" in changes and (
        changes["employee_number"] != employee.employee_number
    ):
        _ensure_unique(
            db,
            Employee,
            company_id,
            Employee.employee_number,
            changes["employee_number"],
            "Employee number already exists in this company",
            exclude_id=employee.id,
        )

    if "personal_email" in changes:
        changes["personal_email"] = _normalize_email(changes["personal_email"])
    if "work_email" in changes:
        changes["work_email"] = _normalize_email(changes["work_email"])
        if changes["work_email"] != employee.work_email:
            _ensure_unique(
                db,
                Employee,
                company_id,
                Employee.work_email,
                changes["work_email"],
                "Work email already exists in this company",
                exclude_id=employee.id,
            )

    if "identity_number" in changes:
        if changes["identity_number"] != employee.identity_number:
            _ensure_unique(
                db,
                Employee,
                company_id,
                Employee.identity_number,
                changes["identity_number"],
                "Identity number already exists in this company",
                exclude_id=employee.id,
            )

    # Merged-state validation for the identity pairing rule.
    merged_identity_number = changes.get(
        "identity_number", employee.identity_number
    )
    merged_identity_type = changes.get("identity_type", employee.identity_type)
    if merged_identity_number and not merged_identity_type:
        raise DomainError(
            "identity_type is required when identity_number is provided"
        )

    old = {k: getattr(employee, k) for k in changes}
    for key, value in changes.items():
        setattr(employee, key, value)
    db.add(employee)
    # PII policy: audit records changed field names and the employee number,
    # never the field values (names, emails, identity numbers, phones, DOB).
    record_audit(
        db,
        action="employee.update",
        entity="employee",
        record_id=employee.id,
        actor_user_id=principal.user_id,
        company_id=company_id,
        new_value={
            "fields": sorted(changes),
            "employee_number": employee.employee_number,
        },
        ip_address=ip,
    )
    if "status" in changes and changes["status"] != old["status"]:
        record_audit(
            db,
            action="employee.status_change",
            entity="employee",
            record_id=employee.id,
            actor_user_id=principal.user_id,
            company_id=company_id,
            old_value={"status": old["status"]},
            new_value={"status": employee.status},
            ip_address=ip,
        )
    # Phase 3: keep employment history in sync with organization-scope
    # changes. This is system bookkeeping on top of employee.update, so it
    # deliberately runs without any extra permission check; no extra history
    # audit record is written (the employee.update audit is authoritative).
    org_changed = sorted(
        key
        for key in changes
        if key in ("branch_id", "department_id", "job_position_id",
                   "job_grade_id", "manager_id", "status", "employment_type")
    )
    if org_changed:
        from app.employment_history.service import record_employee_org_change

        record_employee_org_change(
            db, employee=employee, principal=principal, changed_fields=org_changed
        )
    db.flush()
    return employee


def delete_employee(
    db: Session, *, employee: Employee, principal: Principal, ip: str | None
) -> None:
    company_id = employee.company_id
    if not principal.can_access_company(company_id):
        raise ForbiddenError("You cannot delete this employee")
    _require(principal, "employee.delete", company_id)

    reports = int(
        db.execute(
            select(func.count())
            .select_from(Employee)
            .where(Employee.manager_id == employee.id)
        ).scalar_one()
    )
    if reports > 0:
        raise ConflictError(
            "Employee manages other employees; reassign them first"
        )

    employee_id = employee.id
    old_value = {"employee_number": employee.employee_number}
    try:
        db.delete(employee)
        db.flush()
    except IntegrityError as exc:
        raise ConflictError("Employee is still referenced") from exc
    record_audit(
        db,
        action="employee.delete",
        entity="employee",
        record_id=employee_id,
        actor_user_id=principal.user_id,
        company_id=company_id,
        old_value=old_value,
        ip_address=ip,
    )
    db.flush()
