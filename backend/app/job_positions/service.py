from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.core.deps import Principal
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.pagination import PageParams
from app.job_positions.schemas import JobPositionCreate, JobPositionUpdate
from app.shared.models import Department, Employee, JobPosition


def _require(principal: Principal, code: str, company_id: int | None) -> None:
    """Company-scoped permission check (H1)."""
    if not principal.has_permission(code, company_id):
        raise ForbiddenError(f"Missing permission: {code}")


def _require_department(
    db: Session, department_id: int | None, company_id: int
) -> None:
    if department_id is None:
        return
    department = db.get(Department, department_id)
    if department is None or department.company_id != company_id:
        raise NotFoundError("Department not found")


def list_job_positions(
    db: Session,
    principal: Principal,
    *,
    company_id: int | None = None,
    search: str | None = None,
    status: str | None = None,
    department_id: int | None = None,
    page: PageParams | None = None,
) -> tuple[list[JobPosition], int]:
    stmt = select(JobPosition)
    count_stmt = select(func.count()).select_from(JobPosition)
    if company_id is not None:
        if not principal.can_access_company(company_id):
            raise ForbiddenError("You cannot access this company")
        _require(principal, "job_position.read", company_id)
        stmt = stmt.where(JobPosition.company_id == company_id)
        count_stmt = count_stmt.where(JobPosition.company_id == company_id)
    elif not principal.is_platform_admin:
        allowed = principal.permitted_company_ids("job_position.read")
        if not allowed:
            return [], 0
        stmt = stmt.where(JobPosition.company_id.in_(allowed))
        count_stmt = count_stmt.where(JobPosition.company_id.in_(allowed))

    if search and search.strip():
        like = f"%{search.strip()}%"
        clause = or_(
            JobPosition.code.ilike(like),
            JobPosition.name_ar.ilike(like),
            JobPosition.name_en.ilike(like),
        )
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)
    if status:
        stmt = stmt.where(JobPosition.status == status)
        count_stmt = count_stmt.where(JobPosition.status == status)
    if department_id is not None:
        stmt = stmt.where(JobPosition.department_id == department_id)
        count_stmt = count_stmt.where(JobPosition.department_id == department_id)

    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(JobPosition.id)
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


def get_job_position(
    db: Session, position_id: int, principal: Principal
) -> JobPosition:
    position = db.get(JobPosition, position_id)
    if position is None or not principal.can_access_company(position.company_id):
        raise NotFoundError("Job position not found")
    _require(principal, "job_position.read", position.company_id)
    return position


def create_job_position(
    db: Session, *, payload: JobPositionCreate, principal: Principal, ip: str | None
) -> JobPosition:
    if not principal.can_access_company(payload.company_id):
        raise ForbiddenError("You cannot create job positions in this company")
    _require(principal, "job_position.create", payload.company_id)

    _require_department(db, payload.department_id, payload.company_id)

    exists = db.execute(
        select(JobPosition).where(
            JobPosition.company_id == payload.company_id,
            JobPosition.code == payload.code,
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise ConflictError("Job position code already exists in this company")

    position = JobPosition(**payload.model_dump())
    db.add(position)
    db.flush()
    record_audit(
        db,
        action="job_position.create",
        entity="job_position",
        record_id=position.id,
        actor_user_id=principal.user_id,
        company_id=payload.company_id,
        new_value={
            "code": payload.code,
            "department_id": payload.department_id,
            "status": payload.status,
        },
        ip_address=ip,
    )
    db.flush()
    return position


def update_job_position(
    db: Session,
    *,
    position: JobPosition,
    payload: JobPositionUpdate,
    principal: Principal,
    ip: str | None,
) -> JobPosition:
    if not principal.can_access_company(position.company_id):
        raise ForbiddenError("You cannot modify this job position")
    _require(principal, "job_position.update", position.company_id)

    changes = payload.model_dump(exclude_unset=True)

    if "code" in changes and changes["code"] != position.code:
        exists = db.execute(
            select(JobPosition).where(
                JobPosition.company_id == position.company_id,
                JobPosition.code == changes["code"],
            )
        ).scalar_one_or_none()
        if exists is not None:
            raise ConflictError(
                "Job position code already exists in this company"
            )
    if "department_id" in changes:
        _require_department(db, changes["department_id"], position.company_id)

    old = {k: getattr(position, k) for k in changes}
    for key, value in changes.items():
        setattr(position, key, value)
    db.add(position)
    record_audit(
        db,
        action="job_position.update",
        entity="job_position",
        record_id=position.id,
        actor_user_id=principal.user_id,
        company_id=position.company_id,
        old_value=old,
        new_value=changes,
        ip_address=ip,
    )
    db.flush()
    return position


def delete_job_position(
    db: Session, *, position: JobPosition, principal: Principal, ip: str | None
) -> None:
    if not principal.can_access_company(position.company_id):
        raise ForbiddenError("You cannot delete this job position")
    _require(principal, "job_position.delete", position.company_id)

    employees = int(
        db.execute(
            select(func.count())
            .select_from(Employee)
            .where(Employee.job_position_id == position.id)
        ).scalar_one()
    )
    if employees > 0:
        raise ConflictError("Employees are assigned to this job position")

    old_value = {
        "code": position.code,
        "name_ar": position.name_ar,
        "name_en": position.name_en,
    }
    position_id = position.id
    company_id = position.company_id
    try:
        db.delete(position)
        db.flush()
    except IntegrityError as exc:
        raise ConflictError("Job position is still referenced") from exc
    record_audit(
        db,
        action="job_position.delete",
        entity="job_position",
        record_id=position_id,
        actor_user_id=principal.user_id,
        company_id=company_id,
        old_value=old_value,
        ip_address=ip,
    )
    db.flush()
