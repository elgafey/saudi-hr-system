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
from app.shifts.schemas import ShiftCreate, ShiftOut, ShiftPage, ShiftUpdate
from app.shifts.service import (
    create_shift,
    delete_shift,
    get_shift,
    list_shifts,
    shift_break_map,
    update_shift,
)
from app.work_schedules.schemas import BreakOut

router = APIRouter(prefix="/shifts", tags=["shifts"])


def _shift_out(shift, breaks) -> ShiftOut:
    return ShiftOut(
        id=shift.id,
        company_id=shift.company_id,
        code=shift.code,
        name_ar=shift.name_ar,
        name_en=shift.name_en,
        start_time=shift.start_time,
        end_time=shift.end_time,
        crosses_midnight=shift.crosses_midnight,
        status=shift.status,
        notes=shift.notes,
        created_by=shift.created_by,
        created_at=shift.created_at,
        updated_at=shift.updated_at,
        breaks=[BreakOut.model_validate(b) for b in breaks],
    )


@router.get("", response_model=ShiftPage)
def list_all(
    company_id: int | None = Query(default=None, ge=1),
    status: str | None = Query(default=None, pattern="^(active|archived)$"),
    search: str | None = Query(default=None, max_length=100),
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(require_permission("shift.view")),
    scoped_company: int | None = Depends(optional_company_header),
    db: Session = Depends(get_db),
) -> ShiftPage:
    target = company_id if company_id is not None else scoped_company
    items, total = list_shifts(
        db,
        principal,
        company_id=target,
        status=status,
        search=search,
        page=page_params,
    )
    breaks = shift_break_map(db, items)
    return ShiftPage(
        items=[_shift_out(s, breaks.get(s.id, [])) for s in items],
        page=Page(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ),
    )


@router.post("", response_model=ShiftOut, status_code=201)
def create(
    payload: ShiftCreate,
    request: Request,
    principal: Principal = Depends(require_permission("shift.create")),
    db: Session = Depends(get_db),
) -> ShiftOut:
    shift = create_shift(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return _shift_out(shift, shift_break_map(db, [shift]).get(shift.id, []))


@router.get("/{shift_id}", response_model=ShiftOut)
def read(
    shift_id: int,
    principal: Principal = Depends(require_permission("shift.view")),
    db: Session = Depends(get_db),
) -> ShiftOut:
    shift = get_shift(db, shift_id, principal)
    return _shift_out(shift, shift_break_map(db, [shift]).get(shift.id, []))


@router.patch("/{shift_id}", response_model=ShiftOut)
def update(
    shift_id: int,
    payload: ShiftUpdate,
    request: Request,
    principal: Principal = Depends(require_permission("shift.update")),
    db: Session = Depends(get_db),
) -> ShiftOut:
    shift = update_shift(
        db,
        shift_id=shift_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return _shift_out(shift, shift_break_map(db, [shift]).get(shift.id, []))


@router.delete("/{shift_id}", status_code=204)
def remove(
    shift_id: int,
    request: Request,
    principal: Principal = Depends(require_permission("shift.delete")),
    db: Session = Depends(get_db),
) -> Response:
    delete_shift(
        db, shift_id=shift_id, principal=principal, ip=client_ip(request)
    )
    return Response(status_code=204)
