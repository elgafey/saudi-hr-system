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
from app.job_positions.schemas import (
    JobPositionCreate,
    JobPositionOut,
    JobPositionPage,
    JobPositionUpdate,
)
from app.job_positions.service import (
    create_job_position,
    delete_job_position,
    get_job_position,
    list_job_positions,
    update_job_position,
)

router = APIRouter(prefix="/job-positions", tags=["job_positions"])


@router.get("", response_model=JobPositionPage)
def list_all(
    company_id: int | None = Query(default=None, ge=1),
    search: str | None = Query(default=None, max_length=100),
    status: str | None = Query(default=None, pattern="^(active|inactive)$"),
    department_id: int | None = Query(default=None, ge=1),
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(require_permission("job_position.read")),
    scoped_company: int | None = Depends(optional_company_header),
    db: Session = Depends(get_db),
) -> JobPositionPage:
    target = company_id if company_id is not None else scoped_company
    items, total = list_job_positions(
        db,
        principal,
        company_id=target,
        search=search,
        status=status,
        department_id=department_id,
        page=page_params,
    )
    return JobPositionPage(
        items=[JobPositionOut.model_validate(i) for i in items],
        page=Page(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ),
    )


@router.get("/{position_id}", response_model=JobPositionOut)
def read(
    position_id: int,
    principal: Principal = Depends(require_permission("job_position.read")),
    db: Session = Depends(get_db),
) -> JobPositionOut:
    return JobPositionOut.model_validate(
        get_job_position(db, position_id, principal)
    )


@router.post("", response_model=JobPositionOut, status_code=201)
def create(
    payload: JobPositionCreate,
    request: Request,
    principal: Principal = Depends(require_permission("job_position.create")),
    db: Session = Depends(get_db),
) -> JobPositionOut:
    position = create_job_position(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return JobPositionOut.model_validate(position)


@router.patch("/{position_id}", response_model=JobPositionOut)
def update(
    position_id: int,
    payload: JobPositionUpdate,
    request: Request,
    principal: Principal = Depends(require_permission("job_position.update")),
    db: Session = Depends(get_db),
) -> JobPositionOut:
    position = get_job_position(db, position_id, principal)
    updated = update_job_position(
        db,
        position=position,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return JobPositionOut.model_validate(updated)


@router.delete("/{position_id}", status_code=204)
def remove(
    position_id: int,
    request: Request,
    principal: Principal = Depends(require_permission("job_position.delete")),
    db: Session = Depends(get_db),
) -> Response:
    position = get_job_position(db, position_id, principal)
    delete_job_position(
        db, position=position, principal=principal, ip=client_ip(request)
    )
    return Response(status_code=204)
