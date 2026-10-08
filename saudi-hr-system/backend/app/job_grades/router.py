from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import (
    Principal,
    client_ip,
    optional_company_header,
    require_permission,
)
from app.core.pagination import Page, PageParams, pagination_params
from app.job_grades.schemas import (
    JobGradeCreate,
    JobGradeOut,
    JobGradePage,
    JobGradeUpdate,
)
from app.job_grades.service import (
    create_job_grade,
    delete_job_grade,
    get_job_grade,
    list_job_grades,
    update_job_grade,
)

router = APIRouter(prefix="/job-grades", tags=["job_grades"])


@router.get("", response_model=JobGradePage)
def list_all(
    company_id: int | None = Query(default=None, ge=1),
    search: str | None = Query(default=None, max_length=100),
    status: str | None = Query(default=None, pattern="^(active|inactive)$"),
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(require_permission("job_grade.read")),
    scoped_company: int | None = Depends(optional_company_header),
    db: Session = Depends(get_db),
) -> JobGradePage:
    target = company_id if company_id is not None else scoped_company
    items, total = list_job_grades(
        db,
        principal,
        company_id=target,
        search=search,
        status=status,
        page=page_params,
    )
    return JobGradePage(
        items=[JobGradeOut.model_validate(i) for i in items],
        page=Page(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ),
    )


@router.get("/{grade_id}", response_model=JobGradeOut)
def read(
    grade_id: int,
    principal: Principal = Depends(require_permission("job_grade.read")),
    db: Session = Depends(get_db),
) -> JobGradeOut:
    return JobGradeOut.model_validate(get_job_grade(db, grade_id, principal))


@router.post("", response_model=JobGradeOut, status_code=201)
def create(
    payload: JobGradeCreate,
    request: Request,
    principal: Principal = Depends(require_permission("job_grade.create")),
    db: Session = Depends(get_db),
) -> JobGradeOut:
    grade = create_job_grade(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return JobGradeOut.model_validate(grade)


@router.patch("/{grade_id}", response_model=JobGradeOut)
def update(
    grade_id: int,
    payload: JobGradeUpdate,
    request: Request,
    principal: Principal = Depends(require_permission("job_grade.update")),
    db: Session = Depends(get_db),
) -> JobGradeOut:
    grade = get_job_grade(db, grade_id, principal)
    updated = update_job_grade(
        db, grade=grade, payload=payload, principal=principal, ip=client_ip(request)
    )
    return JobGradeOut.model_validate(updated)


@router.delete("/{grade_id}", status_code=204)
def remove(
    grade_id: int,
    request: Request,
    principal: Principal = Depends(require_permission("job_grade.delete")),
    db: Session = Depends(get_db),
) -> Response:
    grade = get_job_grade(db, grade_id, principal)
    delete_job_grade(db, grade=grade, principal=principal, ip=client_ip(request))
    return Response(status_code=204)
