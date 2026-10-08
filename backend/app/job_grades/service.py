from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.core.deps import Principal
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.pagination import PageParams
from app.job_grades.schemas import JobGradeCreate, JobGradeUpdate
from app.shared.models import Employee, JobGrade


def _require(principal: Principal, code: str, company_id: int | None) -> None:
    """Company-scoped permission check (H1)."""
    if not principal.has_permission(code, company_id):
        raise ForbiddenError(f"Missing permission: {code}")


def list_job_grades(
    db: Session,
    principal: Principal,
    *,
    company_id: int | None = None,
    search: str | None = None,
    status: str | None = None,
    page: PageParams | None = None,
) -> tuple[list[JobGrade], int]:
    stmt = select(JobGrade)
    count_stmt = select(func.count()).select_from(JobGrade)
    if company_id is not None:
        if not principal.can_access_company(company_id):
            raise ForbiddenError("You cannot access this company")
        _require(principal, "job_grade.read", company_id)
        stmt = stmt.where(JobGrade.company_id == company_id)
        count_stmt = count_stmt.where(JobGrade.company_id == company_id)
    elif not principal.is_platform_admin:
        allowed = principal.permitted_company_ids("job_grade.read")
        if not allowed:
            return [], 0
        stmt = stmt.where(JobGrade.company_id.in_(allowed))
        count_stmt = count_stmt.where(JobGrade.company_id.in_(allowed))

    if search and search.strip():
        like = f"%{search.strip()}%"
        clause = or_(
            JobGrade.code.ilike(like),
            JobGrade.name_ar.ilike(like),
            JobGrade.name_en.ilike(like),
        )
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)
    if status:
        stmt = stmt.where(JobGrade.status == status)
        count_stmt = count_stmt.where(JobGrade.status == status)

    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(JobGrade.level, JobGrade.id)
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


def get_job_grade(db: Session, grade_id: int, principal: Principal) -> JobGrade:
    grade = db.get(JobGrade, grade_id)
    if grade is None or not principal.can_access_company(grade.company_id):
        raise NotFoundError("Job grade not found")
    _require(principal, "job_grade.read", grade.company_id)
    return grade


def create_job_grade(
    db: Session, *, payload: JobGradeCreate, principal: Principal, ip: str | None
) -> JobGrade:
    if not principal.can_access_company(payload.company_id):
        raise ForbiddenError("You cannot create job grades in this company")
    _require(principal, "job_grade.create", payload.company_id)

    exists = db.execute(
        select(JobGrade).where(
            JobGrade.company_id == payload.company_id,
            JobGrade.code == payload.code,
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise ConflictError("Job grade code already exists in this company")
    level_exists = db.execute(
        select(JobGrade).where(
            JobGrade.company_id == payload.company_id,
            JobGrade.level == payload.level,
        )
    ).scalar_one_or_none()
    if level_exists is not None:
        raise ConflictError("Job grade level already exists in this company")

    grade = JobGrade(**payload.model_dump())
    db.add(grade)
    db.flush()
    record_audit(
        db,
        action="job_grade.create",
        entity="job_grade",
        record_id=grade.id,
        actor_user_id=principal.user_id,
        company_id=payload.company_id,
        new_value={
            "code": payload.code,
            "level": payload.level,
            "status": payload.status,
        },
        ip_address=ip,
    )
    db.flush()
    return grade


def update_job_grade(
    db: Session,
    *,
    grade: JobGrade,
    payload: JobGradeUpdate,
    principal: Principal,
    ip: str | None,
) -> JobGrade:
    if not principal.can_access_company(grade.company_id):
        raise ForbiddenError("You cannot modify this job grade")
    _require(principal, "job_grade.update", grade.company_id)

    changes = payload.model_dump(exclude_unset=True)

    if "code" in changes and changes["code"] != grade.code:
        exists = db.execute(
            select(JobGrade).where(
                JobGrade.company_id == grade.company_id,
                JobGrade.code == changes["code"],
            )
        ).scalar_one_or_none()
        if exists is not None:
            raise ConflictError("Job grade code already exists in this company")
    if "level" in changes and changes["level"] != grade.level:
        exists = db.execute(
            select(JobGrade).where(
                JobGrade.company_id == grade.company_id,
                JobGrade.level == changes["level"],
            )
        ).scalar_one_or_none()
        if exists is not None:
            raise ConflictError("Job grade level already exists in this company")

    old = {k: getattr(grade, k) for k in changes}
    for key, value in changes.items():
        setattr(grade, key, value)
    db.add(grade)
    record_audit(
        db,
        action="job_grade.update",
        entity="job_grade",
        record_id=grade.id,
        actor_user_id=principal.user_id,
        company_id=grade.company_id,
        old_value=old,
        new_value=changes,
        ip_address=ip,
    )
    db.flush()
    return grade


def delete_job_grade(
    db: Session, *, grade: JobGrade, principal: Principal, ip: str | None
) -> None:
    if not principal.can_access_company(grade.company_id):
        raise ForbiddenError("You cannot delete this job grade")
    _require(principal, "job_grade.delete", grade.company_id)

    employees = int(
        db.execute(
            select(func.count())
            .select_from(Employee)
            .where(Employee.job_grade_id == grade.id)
        ).scalar_one()
    )
    if employees > 0:
        raise ConflictError("Employees are assigned to this job grade")

    old_value = {
        "code": grade.code,
        "level": grade.level,
        "name_ar": grade.name_ar,
        "name_en": grade.name_en,
    }
    grade_id = grade.id
    company_id = grade.company_id
    try:
        db.delete(grade)
        db.flush()
    except IntegrityError as exc:
        raise ConflictError("Job grade is still referenced") from exc
    record_audit(
        db,
        action="job_grade.delete",
        entity="job_grade",
        record_id=grade_id,
        actor_user_id=principal.user_id,
        company_id=company_id,
        old_value=old_value,
        ip_address=ip,
    )
    db.flush()
