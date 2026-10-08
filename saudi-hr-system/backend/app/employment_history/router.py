from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import Principal, client_ip, require_permission
from app.core.pagination import Page, PageParams, pagination_params
from app.employment_history.schemas import (
    HistoryCreate,
    HistoryOut,
    HistoryPage,
)
from app.employment_history.service import create_history, list_history

router = APIRouter(
    prefix="/employees/{employee_id}/employment-history",
    tags=["employee-history"],
)


@router.get("", response_model=HistoryPage)
def list_all(
    employee_id: int,
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(require_permission("employee_history.view")),
    db: Session = Depends(get_db),
) -> HistoryPage:
    items, total = list_history(
        db, principal, employee_id=employee_id, page=page_params
    )
    return HistoryPage(
        items=[HistoryOut.model_validate(i) for i in items],
        page=Page(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ),
    )


@router.post("", response_model=HistoryOut, status_code=201)
def create(
    employee_id: int,
    payload: HistoryCreate,
    request: Request,
    principal: Principal = Depends(require_permission("employee_history.create")),
    db: Session = Depends(get_db),
) -> HistoryOut:
    row = create_history(
        db,
        employee_id=employee_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return HistoryOut.model_validate(row)
