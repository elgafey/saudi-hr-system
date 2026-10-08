from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.attendance.schemas import (
    AttendanceCheckIn,
    AttendanceCheckOut,
    AttendanceCreate,
    AttendanceOut,
    AttendancePage,
    AttendanceUpdate,
)
from app.attendance.service import (
    check_in,
    check_out,
    create_attendance,
    delete_attendance,
    get_attendance,
    list_attendance,
    update_attendance,
)
from app.core.database import get_db
from app.core.deps import (
    Principal,
    client_ip,
    optional_company_header,
    require_permission,
)
from app.core.pagination import Page, PageParams, pagination_params

router = APIRouter(prefix="/attendance", tags=["attendance"])


@router.get("", response_model=AttendancePage)
def list_all(
    company_id: int | None = Query(default=None, ge=1),
    employee_id: int | None = Query(default=None, ge=1),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    status: str | None = Query(
        default=None, pattern="^(open|completed|missing_checkout)$"
    ),
    department_id: int | None = Query(default=None, ge=1),
    branch_id: int | None = Query(default=None, ge=1),
    schedule_id: int | None = Query(default=None, ge=1),
    shift_id: int | None = Query(default=None, ge=1),
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(require_permission("attendance.view")),
    scoped_company: int | None = Depends(optional_company_header),
    db: Session = Depends(get_db),
) -> AttendancePage:
    target = company_id if company_id is not None else scoped_company
    items, total = list_attendance(
        db,
        principal,
        company_id=target,
        employee_id=employee_id,
        date_from=date_from,
        date_to=date_to,
        status=status,
        department_id=department_id,
        branch_id=branch_id,
        schedule_id=schedule_id,
        shift_id=shift_id,
        page=page_params,
    )
    return AttendancePage(
        items=[AttendanceOut.model_validate(r) for r in items],
        page=Page(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ),
    )


@router.post("", response_model=AttendanceOut, status_code=201)
def create(
    payload: AttendanceCreate,
    request: Request,
    principal: Principal = Depends(require_permission("attendance.create")),
    db: Session = Depends(get_db),
) -> AttendanceOut:
    record = create_attendance(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return AttendanceOut.model_validate(record)


@router.post("/check-in", response_model=AttendanceOut, status_code=201)
def open_record(
    payload: AttendanceCheckIn,
    request: Request,
    principal: Principal = Depends(require_permission("attendance.create")),
    db: Session = Depends(get_db),
) -> AttendanceOut:
    record = check_in(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return AttendanceOut.model_validate(record)


@router.post("/check-out", response_model=AttendanceOut)
def close_record(
    payload: AttendanceCheckOut,
    request: Request,
    principal: Principal = Depends(require_permission("attendance.update")),
    db: Session = Depends(get_db),
) -> AttendanceOut:
    record = check_out(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return AttendanceOut.model_validate(record)


@router.get("/{attendance_id}", response_model=AttendanceOut)
def read(
    attendance_id: int,
    principal: Principal = Depends(require_permission("attendance.view")),
    db: Session = Depends(get_db),
) -> AttendanceOut:
    return AttendanceOut.model_validate(
        get_attendance(db, attendance_id, principal)
    )


@router.patch("/{attendance_id}", response_model=AttendanceOut)
def update(
    attendance_id: int,
    payload: AttendanceUpdate,
    request: Request,
    principal: Principal = Depends(require_permission("attendance.update")),
    db: Session = Depends(get_db),
) -> AttendanceOut:
    record = update_attendance(
        db,
        attendance_id=attendance_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return AttendanceOut.model_validate(record)


@router.delete("/{attendance_id}", status_code=204)
def remove(
    attendance_id: int,
    request: Request,
    reason: str | None = Query(default=None, max_length=500),
    principal: Principal = Depends(require_permission("attendance.delete")),
    db: Session = Depends(get_db),
) -> Response:
    delete_attendance(
        db,
        attendance_id=attendance_id,
        reason=reason,
        principal=principal,
        ip=client_ip(request),
    )
    return Response(status_code=204)
