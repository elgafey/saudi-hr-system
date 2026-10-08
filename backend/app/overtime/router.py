from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import (
    Principal,
    client_ip,
    optional_company_header,
    require_permission,
)
from app.core.pagination import Page, PageParams, pagination_params
from app.overtime.schemas import (
    OvertimeApprove,
    OvertimeCorrect,
    OvertimeCreate,
    OvertimeDecision,
    OvertimeOut,
    OvertimePage,
    OvertimeUpdate,
)
from app.overtime.service import (
    approve_overtime,
    cancel_overtime,
    correct_overtime,
    create_overtime,
    get_overtime,
    list_overtime,
    reject_overtime,
    submit_overtime,
    update_overtime,
)

router = APIRouter(prefix="/overtime", tags=["overtime"])


@router.get("", response_model=OvertimePage)
def list_all(
    company_id: int | None = Query(default=None, ge=1),
    employee_id: int | None = Query(default=None, ge=1),
    status: str | None = Query(
        default=None, pattern="^(draft|submitted|approved|rejected|cancelled)$"
    ),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(require_permission("overtime.view")),
    scoped_company: int | None = Depends(optional_company_header),
    db: Session = Depends(get_db),
) -> OvertimePage:
    target = company_id if company_id is not None else scoped_company
    items, total = list_overtime(
        db,
        principal,
        company_id=target,
        employee_id=employee_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
        page=page_params,
    )
    return OvertimePage(
        items=[OvertimeOut.model_validate(o) for o in items],
        page=Page(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ),
    )


@router.post("", response_model=OvertimeOut, status_code=201)
def create(
    payload: OvertimeCreate,
    request: Request,
    principal: Principal = Depends(require_permission("overtime.create")),
    db: Session = Depends(get_db),
) -> OvertimeOut:
    row = create_overtime(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return OvertimeOut.model_validate(row)


@router.get("/{overtime_id}", response_model=OvertimeOut)
def read(
    overtime_id: int,
    principal: Principal = Depends(require_permission("overtime.view")),
    db: Session = Depends(get_db),
) -> OvertimeOut:
    return OvertimeOut.model_validate(
        get_overtime(db, overtime_id, principal)
    )


@router.patch("/{overtime_id}", response_model=OvertimeOut)
def update(
    overtime_id: int,
    payload: OvertimeUpdate,
    request: Request,
    principal: Principal = Depends(require_permission("overtime.update")),
    db: Session = Depends(get_db),
) -> OvertimeOut:
    row = update_overtime(
        db,
        overtime_id=overtime_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return OvertimeOut.model_validate(row)


@router.post("/{overtime_id}/submit", response_model=OvertimeOut)
def submit(
    overtime_id: int,
    request: Request,
    principal: Principal = Depends(require_permission("overtime.submit")),
    db: Session = Depends(get_db),
) -> OvertimeOut:
    row = submit_overtime(
        db, overtime_id=overtime_id, principal=principal, ip=client_ip(request)
    )
    return OvertimeOut.model_validate(row)


@router.post("/{overtime_id}/approve", response_model=OvertimeOut)
def approve(
    overtime_id: int,
    payload: OvertimeApprove,
    request: Request,
    principal: Principal = Depends(require_permission("overtime.approve")),
    db: Session = Depends(get_db),
) -> OvertimeOut:
    row = approve_overtime(
        db,
        overtime_id=overtime_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return OvertimeOut.model_validate(row)


@router.post("/{overtime_id}/reject", response_model=OvertimeOut)
def reject(
    overtime_id: int,
    payload: OvertimeDecision,
    request: Request,
    principal: Principal = Depends(require_permission("overtime.reject")),
    db: Session = Depends(get_db),
) -> OvertimeOut:
    row = reject_overtime(
        db,
        overtime_id=overtime_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return OvertimeOut.model_validate(row)


@router.post("/{overtime_id}/cancel", response_model=OvertimeOut)
def cancel(
    overtime_id: int,
    payload: OvertimeDecision,
    request: Request,
    principal: Principal = Depends(require_permission("overtime.cancel")),
    db: Session = Depends(get_db),
) -> OvertimeOut:
    row = cancel_overtime(
        db,
        overtime_id=overtime_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return OvertimeOut.model_validate(row)


@router.post("/{overtime_id}/correct", response_model=OvertimeOut)
def correct(
    overtime_id: int,
    payload: OvertimeCorrect,
    request: Request,
    principal: Principal = Depends(require_permission("overtime.approve")),
    db: Session = Depends(get_db),
) -> OvertimeOut:
    row = correct_overtime(
        db,
        overtime_id=overtime_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return OvertimeOut.model_validate(row)
