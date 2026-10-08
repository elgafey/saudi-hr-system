"""Phase 8 router: /salary-advances (apply, decide, disburse, settle).

Routes authenticate only; every self-scope, cross-employee, decision and
finance rule is enforced in the service layer (Phase 7 pattern - no
hardcoded role names, permission codes only).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.advance.schemas import (
    AdvanceCreate,
    AdvanceDecision,
    AdvanceDisburse,
    AdvanceEventOut,
    AdvanceOut,
    AdvancePage,
    AdvanceSettle,
    AdvanceUpdate,
)
from app.advance.service import (
    approve_advance,
    cancel_advance,
    create_advance,
    disburse_advance,
    get_advance_detail,
    list_advances,
    reject_advance,
    settle_advance,
    submit_advance,
    update_advance,
)
from app.core.database import get_db
from app.core.deps import Principal, client_ip, get_current_principal
from app.core.pagination import Page, PageParams, pagination_params

salary_advances_router = APIRouter(
    prefix="/salary-advances", tags=["salary-advances"]
)

STATUS_PATTERN = (
    "^(|draft|submitted|approved|rejected|cancelled|disbursed|settled)$"
)


def _page(page_params: PageParams, total: int) -> Page:
    return Page(
        page=page_params.page, page_size=page_params.page_size, total=total
    )


def _advance_out(row, events: list | None = None) -> AdvanceOut:
    out = AdvanceOut.model_validate(row)
    if events is not None:
        out.events = [AdvanceEventOut.model_validate(event) for event in events]
    return out


@salary_advances_router.post("", response_model=AdvanceOut, status_code=201)
def create(
    payload: AdvanceCreate,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> AdvanceOut:
    row = create_advance(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return _advance_out(row)


@salary_advances_router.get("", response_model=AdvancePage)
def list_(
    company_id: int | None = Query(default=None, ge=1),
    employee_id: int | None = Query(default=None, ge=1),
    status: str | None = Query(default=None, pattern=STATUS_PATTERN),
    assigned_to_me: bool = Query(default=False),
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> AdvancePage:
    items, total = list_advances(
        db,
        principal,
        company_id=company_id,
        employee_id=employee_id,
        status=status or None,
        assigned_to_me=assigned_to_me,
        page=page_params,
    )
    return AdvancePage(
        items=[_advance_out(row) for row in items],
        page=_page(page_params, total),
    )


@salary_advances_router.get("/{advance_id}", response_model=AdvanceOut)
def read(
    advance_id: int,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> AdvanceOut:
    row, events = get_advance_detail(db, advance_id, principal)
    return _advance_out(row, events)


@salary_advances_router.patch("/{advance_id}", response_model=AdvanceOut)
def update(
    advance_id: int,
    payload: AdvanceUpdate,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> AdvanceOut:
    row = update_advance(
        db,
        advance_id=advance_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return _advance_out(row)


@salary_advances_router.post("/{advance_id}/submit", response_model=AdvanceOut)
def submit(
    advance_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> AdvanceOut:
    row = submit_advance(
        db, advance_id=advance_id, principal=principal, ip=client_ip(request)
    )
    return _advance_out(row)


@salary_advances_router.post("/{advance_id}/cancel", response_model=AdvanceOut)
def cancel(
    advance_id: int,
    request: Request,
    payload: AdvanceDecision | None = None,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> AdvanceOut:
    row = cancel_advance(
        db,
        advance_id=advance_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return _advance_out(row)


@salary_advances_router.post(
    "/{advance_id}/approve", response_model=AdvanceOut
)
def approve(
    advance_id: int,
    request: Request,
    payload: AdvanceDecision | None = None,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> AdvanceOut:
    row = approve_advance(
        db,
        advance_id=advance_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return _advance_out(row)


@salary_advances_router.post("/{advance_id}/reject", response_model=AdvanceOut)
def reject(
    advance_id: int,
    request: Request,
    payload: AdvanceDecision | None = None,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> AdvanceOut:
    row = reject_advance(
        db,
        advance_id=advance_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return _advance_out(row)


@salary_advances_router.post(
    "/{advance_id}/disburse", response_model=AdvanceOut
)
def disburse(
    advance_id: int,
    request: Request,
    payload: AdvanceDisburse | None = None,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> AdvanceOut:
    row = disburse_advance(
        db,
        advance_id=advance_id,
        payload=payload or AdvanceDisburse(),
        principal=principal,
        ip=client_ip(request),
    )
    return _advance_out(row)


@salary_advances_router.post("/{advance_id}/settle", response_model=AdvanceOut)
def settle(
    advance_id: int,
    request: Request,
    payload: AdvanceSettle | None = None,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> AdvanceOut:
    row = settle_advance(
        db,
        advance_id=advance_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return _advance_out(row)
