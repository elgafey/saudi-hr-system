from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.core.deps import Principal
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.pagination import PageParams
from app.departments.schemas import DepartmentCreate, DepartmentUpdate
from app.shared.models import Department, Employee, JobPosition

_MAX_PARENT_DEPTH = 100


def _require(principal: Principal, code: str, company_id: int | None) -> None:
    """Company-scoped permission check (H1)."""
    if not principal.has_permission(code, company_id):
        raise ForbiddenError(f"Missing permission: {code}")


def _get_visible(db: Session, department_id: int, company_id: int) -> Department:
    """Department must exist and belong to the given company (404 otherwise)."""
    department = db.get(Department, department_id)
    if department is None or department.company_id != company_id:
        raise NotFoundError("Parent department not found")
    return department


def _count(db: Session, *criteria) -> int:
    stmt = select(func.count()).select_from(Department)
    if criteria:
        stmt = stmt.where(*criteria)
    return int(db.execute(stmt).scalar_one())


def list_departments(
    db: Session,
    principal: Principal,
    *,
    company_id: int | None = None,
    search: str | None = None,
    status: str | None = None,
    page: PageParams | None = None,
) -> tuple[list[Department], int]:
    stmt = select(Department)
    count_stmt = select(func.count()).select_from(Department)
    if company_id is not None:
        if not principal.can_access_company(company_id):
            raise ForbiddenError("You cannot access this company")
        _require(principal, "department.read", company_id)
        stmt = stmt.where(Department.company_id == company_id)
        count_stmt = count_stmt.where(Department.company_id == company_id)
    elif not principal.is_platform_admin:
        allowed = principal.permitted_company_ids("department.read")
        if not allowed:
            return [], 0
        stmt = stmt.where(Department.company_id.in_(allowed))
        count_stmt = count_stmt.where(Department.company_id.in_(allowed))

    if search and search.strip():
        like = f"%{search.strip()}%"
        clause = or_(
            Department.code.ilike(like),
            Department.name_ar.ilike(like),
            Department.name_en.ilike(like),
        )
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)
    if status:
        stmt = stmt.where(Department.status == status)
        count_stmt = count_stmt.where(Department.status == status)

    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(Department.id)
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


def get_department(db: Session, department_id: int, principal: Principal) -> Department:
    department = db.get(Department, department_id)
    if department is None or not principal.can_access_company(department.company_id):
        raise NotFoundError("Department not found")
    _require(principal, "department.read", department.company_id)
    return department


def create_department(
    db: Session, *, payload: DepartmentCreate, principal: Principal, ip: str | None
) -> Department:
    if not principal.can_access_company(payload.company_id):
        raise ForbiddenError("You cannot create departments in this company")
    _require(principal, "department.create", payload.company_id)

    if payload.parent_id is not None:
        _get_visible(db, payload.parent_id, payload.company_id)

    exists = db.execute(
        select(Department).where(
            Department.company_id == payload.company_id,
            Department.code == payload.code,
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise ConflictError("Department code already exists in this company")

    department = Department(**payload.model_dump())
    db.add(department)
    db.flush()
    record_audit(
        db,
        action="department.create",
        entity="department",
        record_id=department.id,
        actor_user_id=principal.user_id,
        company_id=payload.company_id,
        new_value={
            "code": payload.code,
            "parent_id": payload.parent_id,
            "status": payload.status,
        },
        ip_address=ip,
    )
    db.flush()
    return department


def update_department(
    db: Session,
    *,
    department: Department,
    payload: DepartmentUpdate,
    principal: Principal,
    ip: str | None,
) -> Department:
    if not principal.can_access_company(department.company_id):
        raise ForbiddenError("You cannot modify this department")
    _require(principal, "department.update", department.company_id)

    changes = payload.model_dump(exclude_unset=True)

    if "code" in changes and changes["code"] != department.code:
        exists = db.execute(
            select(Department).where(
                Department.company_id == department.company_id,
                Department.code == changes["code"],
            )
        ).scalar_one_or_none()
        if exists is not None:
            raise ConflictError("Department code already exists in this company")

    if "parent_id" in changes and changes["parent_id"] is not None:
        parent_id = changes["parent_id"]
        if parent_id == department.id:
            raise ConflictError("A department cannot be its own parent")
        parent = _get_visible(db, parent_id, department.company_id)
        cursor: Department | None = parent
        depth = 0
        while cursor is not None:
            if cursor.id == department.id:
                raise ConflictError(
                    "Department hierarchy cannot contain a cycle"
                )
            if cursor.parent_id is None:
                break
            cursor = db.get(Department, cursor.parent_id)
            depth += 1
            if depth > _MAX_PARENT_DEPTH:
                raise ConflictError("Department hierarchy is too deep")

    old = {k: getattr(department, k) for k in changes}
    for key, value in changes.items():
        setattr(department, key, value)
    db.add(department)
    record_audit(
        db,
        action="department.update",
        entity="department",
        record_id=department.id,
        actor_user_id=principal.user_id,
        company_id=department.company_id,
        old_value=old,
        new_value=changes,
        ip_address=ip,
    )
    db.flush()
    return department


def delete_department(
    db: Session, *, department: Department, principal: Principal, ip: str | None
) -> None:
    if not principal.can_access_company(department.company_id):
        raise ForbiddenError("You cannot delete this department")
    _require(principal, "department.delete", department.company_id)

    if _count(db, Department.parent_id == department.id) > 0:
        raise ConflictError("Department has sub-departments")
    positions = int(
        db.execute(
            select(func.count())
            .select_from(JobPosition)
            .where(JobPosition.department_id == department.id)
        ).scalar_one()
    )
    if positions > 0:
        raise ConflictError("Job positions are linked to this department")
    employees = int(
        db.execute(
            select(func.count())
            .select_from(Employee)
            .where(Employee.department_id == department.id)
        ).scalar_one()
    )
    if employees > 0:
        raise ConflictError("Employees are assigned to this department")

    old_value = {
        "code": department.code,
        "name_ar": department.name_ar,
        "name_en": department.name_en,
    }
    department_id = department.id
    company_id = department.company_id
    try:
        db.delete(department)
        db.flush()
    except IntegrityError as exc:
        raise ConflictError("Department is still referenced") from exc
    record_audit(
        db,
        action="department.delete",
        entity="department",
        record_id=department_id,
        actor_user_id=principal.user_id,
        company_id=company_id,
        old_value=old_value,
        ip_address=ip,
    )
    db.flush()
