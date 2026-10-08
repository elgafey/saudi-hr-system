from __future__ import annotations

from datetime import date
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    Query,
    Request,
    Response,
    UploadFile,
)
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import (
    Principal,
    client_ip,
    get_current_principal,
    optional_company_header,
    require_permission,
)
from app.core.pagination import Page, PageParams, pagination_params
from app.leave.schemas import (
    BalanceOut,
    CarryForward,
    HolidayCreate,
    HolidayOut,
    HolidayPage,
    HolidayUpdate,
    LeaveAllocationCreate,
    LeaveAllocationDecision,
    LeaveAllocationGenerate,
    LeaveAllocationOut,
    LeaveAllocationPage,
    LeaveAllocationUpdate,
    LeaveBalancesPage,
    LeaveRequestCreate,
    LeaveRequestDecision,
    LeaveRequestOut,
    LeaveRequestPage,
    LeaveRequestPreview,
    LeaveRequestPreviewOut,
    LeaveRequestUpdate,
    LeaveTypeCreate,
    LeaveTypeOut,
    LeaveTypePage,
    LeaveTypeUpdate,
    StatutoryRuleCreate,
    StatutoryRuleDeactivate,
    StatutoryRuleOut,
    StatutoryRulePage,
)
from app.leave.service import (
    approve_leave_allocation,
    approve_leave_request,
    cancel_leave_request,
    carry_forward_allocations,
    create_holiday,
    create_leave_allocation,
    create_leave_request,
    create_leave_type,
    create_statutory_rule,
    deactivate_statutory_rule,
    delete_holiday,
    delete_leave_allocation,
    delete_leave_request,
    delete_leave_type,
    delete_request_attachment,
    download_request_attachment,
    generate_leave_allocations,
    get_holiday,
    get_leave_allocation,
    get_leave_request,
    get_leave_type,
    get_statutory_rule,
    list_holidays,
    list_leave_allocations,
    list_leave_balances,
    list_leave_requests,
    list_leave_types,
    list_statutory_rules,
    my_leave_balances,
    preview_leave_request,
    reject_leave_allocation,
    reject_leave_request,
    submit_leave_allocation,
    submit_leave_request,
    update_holiday,
    update_leave_allocation,
    update_leave_request,
    update_leave_type,
    upload_request_attachment,
)

leave_types_router = APIRouter(prefix="/leave-types", tags=["leave-types"])
statutory_router = APIRouter(
    prefix="/leave-statutory-rules", tags=["leave-statutory-rules"]
)
allocations_router = APIRouter(
    prefix="/leave-allocations", tags=["leave-allocations"]
)
requests_router = APIRouter(prefix="/leave-requests", tags=["leave-requests"])
balances_router = APIRouter(prefix="/leave-balances", tags=["leave-balances"])
holidays_router = APIRouter(prefix="/company-holidays", tags=["company-holidays"])


def _content_disposition(filename: str) -> str:
    ascii_name = filename.encode("ascii", "ignore").decode() or "download"
    ascii_name = ascii_name.replace('"', "")
    return (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )


# ---------------------------------------------------------------------------
# Leave types
# ---------------------------------------------------------------------------


@leave_types_router.get("", response_model=LeaveTypePage)
def list_types(
    company_id: int | None = Query(default=None, ge=1),
    status: str | None = Query(default=None, pattern="^(active|inactive)$"),
    statutory_key: str | None = Query(default=None, max_length=50),
    q: str | None = Query(default=None, max_length=100),
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(require_permission("leave_type.view")),
    scoped_company: int | None = Depends(optional_company_header),
    db: Session = Depends(get_db),
) -> LeaveTypePage:
    target = company_id if company_id is not None else scoped_company
    items, total = list_leave_types(
        db,
        principal,
        company_id=target,
        status=status,
        statutory_key=statutory_key,
        q=q,
        page=page_params,
    )
    return LeaveTypePage(
        items=[LeaveTypeOut.model_validate(r) for r in items],
        page=Page(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ),
    )


@leave_types_router.post("", response_model=LeaveTypeOut, status_code=201)
def create_type(
    payload: LeaveTypeCreate,
    request: Request,
    principal: Principal = Depends(require_permission("leave_type.create")),
    db: Session = Depends(get_db),
) -> LeaveTypeOut:
    row = create_leave_type(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return LeaveTypeOut.model_validate(row)


@leave_types_router.get("/{leave_type_id}", response_model=LeaveTypeOut)
def read_type(
    leave_type_id: int,
    principal: Principal = Depends(require_permission("leave_type.view")),
    db: Session = Depends(get_db),
) -> LeaveTypeOut:
    return LeaveTypeOut.model_validate(
        get_leave_type(db, leave_type_id, principal)
    )


@leave_types_router.patch("/{leave_type_id}", response_model=LeaveTypeOut)
def update_type(
    leave_type_id: int,
    payload: LeaveTypeUpdate,
    request: Request,
    principal: Principal = Depends(require_permission("leave_type.update")),
    db: Session = Depends(get_db),
) -> LeaveTypeOut:
    row = update_leave_type(
        db,
        leave_type_id=leave_type_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return LeaveTypeOut.model_validate(row)


@leave_types_router.delete("/{leave_type_id}", status_code=204)
def remove_type(
    leave_type_id: int,
    request: Request,
    principal: Principal = Depends(require_permission("leave_type.delete")),
    db: Session = Depends(get_db),
) -> Response:
    delete_leave_type(
        db,
        leave_type_id=leave_type_id,
        principal=principal,
        ip=client_ip(request),
    )
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Statutory rules (reuses the leave_type.* code family)
# ---------------------------------------------------------------------------


@statutory_router.get("", response_model=StatutoryRulePage)
def list_rules(
    company_id: int | None = Query(default=None, ge=1),
    statutory_key: str | None = Query(default=None, max_length=50),
    as_of: date | None = Query(default=None),
    status: str | None = Query(default=None, pattern="^(active|inactive)$"),
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(require_permission("leave_type.view")),
    scoped_company: int | None = Depends(optional_company_header),
    db: Session = Depends(get_db),
) -> StatutoryRulePage:
    target = company_id if company_id is not None else scoped_company
    items, total = list_statutory_rules(
        db,
        principal,
        company_id=target,
        statutory_key=statutory_key,
        as_of=as_of,
        status=status,
        page=page_params,
    )
    return StatutoryRulePage(
        items=[StatutoryRuleOut.model_validate(r) for r in items],
        page=Page(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ),
    )


@statutory_router.post("", response_model=StatutoryRuleOut, status_code=201)
def create_rule(
    payload: StatutoryRuleCreate,
    request: Request,
    principal: Principal = Depends(require_permission("leave_type.create")),
    db: Session = Depends(get_db),
) -> StatutoryRuleOut:
    row = create_statutory_rule(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return StatutoryRuleOut.model_validate(row)


@statutory_router.get("/{rule_id}", response_model=StatutoryRuleOut)
def read_rule(
    rule_id: int,
    principal: Principal = Depends(require_permission("leave_type.view")),
    db: Session = Depends(get_db),
) -> StatutoryRuleOut:
    return StatutoryRuleOut.model_validate(
        get_statutory_rule(db, rule_id, principal)
    )


@statutory_router.post("/{rule_id}/deactivate", response_model=StatutoryRuleOut)
def deactivate_rule(
    rule_id: int,
    payload: StatutoryRuleDeactivate,
    request: Request,
    principal: Principal = Depends(require_permission("leave_type.update")),
    db: Session = Depends(get_db),
) -> StatutoryRuleOut:
    row = deactivate_statutory_rule(
        db,
        rule_id=rule_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return StatutoryRuleOut.model_validate(row)


# ---------------------------------------------------------------------------
# Allocations
# ---------------------------------------------------------------------------


@allocations_router.get("", response_model=LeaveAllocationPage)
def list_allocations(
    company_id: int | None = Query(default=None, ge=1),
    employee_id: int | None = Query(default=None, ge=1),
    leave_type_id: int | None = Query(default=None, ge=1),
    status: str | None = Query(
        default=None, pattern="^(submitted|approved|rejected|revoked)$"
    ),
    period_from: date | None = Query(default=None),
    period_to: date | None = Query(default=None),
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(
        require_permission("leave_allocation.view")
    ),
    scoped_company: int | None = Depends(optional_company_header),
    db: Session = Depends(get_db),
) -> LeaveAllocationPage:
    target = company_id if company_id is not None else scoped_company
    items, total = list_leave_allocations(
        db,
        principal,
        company_id=target,
        employee_id=employee_id,
        leave_type_id=leave_type_id,
        status=status,
        period_from=period_from,
        period_to=period_to,
        page=page_params,
    )
    return LeaveAllocationPage(
        items=[LeaveAllocationOut.model_validate(r) for r in items],
        page=Page(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ),
    )


@allocations_router.post("", response_model=LeaveAllocationOut, status_code=201)
def create_allocation(
    payload: LeaveAllocationCreate,
    request: Request,
    principal: Principal = Depends(
        require_permission("leave_allocation.create")
    ),
    db: Session = Depends(get_db),
) -> LeaveAllocationOut:
    row = create_leave_allocation(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return LeaveAllocationOut.model_validate(row)


@allocations_router.post(
    "/generate", response_model=list[LeaveAllocationOut], status_code=201
)
def generate_allocations(
    payload: LeaveAllocationGenerate,
    request: Request,
    principal: Principal = Depends(
        require_permission("leave_allocation.create")
    ),
    db: Session = Depends(get_db),
) -> list[LeaveAllocationOut]:
    rows = generate_leave_allocations(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return [LeaveAllocationOut.model_validate(r) for r in rows]


@allocations_router.post(
    "/carry-forward", response_model=list[LeaveAllocationOut], status_code=201
)
def carry_forward(
    payload: CarryForward,
    request: Request,
    principal: Principal = Depends(
        require_permission("leave_allocation.carry_forward")
    ),
    db: Session = Depends(get_db),
) -> list[LeaveAllocationOut]:
    rows = carry_forward_allocations(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return [LeaveAllocationOut.model_validate(r) for r in rows]


@allocations_router.get("/{allocation_id}", response_model=LeaveAllocationOut)
def read_allocation(
    allocation_id: int,
    principal: Principal = Depends(
        require_permission("leave_allocation.view")
    ),
    db: Session = Depends(get_db),
) -> LeaveAllocationOut:
    return LeaveAllocationOut.model_validate(
        get_leave_allocation(db, allocation_id, principal)
    )


@allocations_router.patch(
    "/{allocation_id}", response_model=LeaveAllocationOut
)
def update_allocation(
    allocation_id: int,
    payload: LeaveAllocationUpdate,
    request: Request,
    principal: Principal = Depends(
        require_permission("leave_allocation.update")
    ),
    db: Session = Depends(get_db),
) -> LeaveAllocationOut:
    row = update_leave_allocation(
        db,
        allocation_id=allocation_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return LeaveAllocationOut.model_validate(row)


@allocations_router.delete("/{allocation_id}", status_code=204)
def remove_allocation(
    allocation_id: int,
    request: Request,
    principal: Principal = Depends(
        require_permission("leave_allocation.delete")
    ),
    db: Session = Depends(get_db),
) -> Response:
    delete_leave_allocation(
        db,
        allocation_id=allocation_id,
        principal=principal,
        ip=client_ip(request),
    )
    return Response(status_code=204)


@allocations_router.post(
    "/{allocation_id}/submit", response_model=LeaveAllocationOut
)
def submit_allocation(
    allocation_id: int,
    request: Request,
    principal: Principal = Depends(
        require_permission("leave_allocation.submit")
    ),
    db: Session = Depends(get_db),
) -> LeaveAllocationOut:
    row = submit_leave_allocation(
        db, allocation_id=allocation_id, principal=principal, ip=client_ip(request)
    )
    return LeaveAllocationOut.model_validate(row)


@allocations_router.post(
    "/{allocation_id}/approve", response_model=LeaveAllocationOut
)
def approve_allocation(
    allocation_id: int,
    payload: LeaveAllocationDecision,
    request: Request,
    principal: Principal = Depends(
        require_permission("leave_allocation.approve")
    ),
    db: Session = Depends(get_db),
) -> LeaveAllocationOut:
    row = approve_leave_allocation(
        db,
        allocation_id=allocation_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return LeaveAllocationOut.model_validate(row)


@allocations_router.post(
    "/{allocation_id}/reject", response_model=LeaveAllocationOut
)
def reject_allocation(
    allocation_id: int,
    payload: LeaveAllocationDecision,
    request: Request,
    principal: Principal = Depends(
        require_permission("leave_allocation.reject")
    ),
    db: Session = Depends(get_db),
) -> LeaveAllocationOut:
    row = reject_leave_allocation(
        db,
        allocation_id=allocation_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return LeaveAllocationOut.model_validate(row)


# ---------------------------------------------------------------------------
# Requests (self-scoped: the router authenticates, the service authorizes)
# ---------------------------------------------------------------------------


@requests_router.get("", response_model=LeaveRequestPage)
def list_requests(
    company_id: int | None = Query(default=None, ge=1),
    employee_id: int | None = Query(default=None, ge=1),
    leave_type_id: int | None = Query(default=None, ge=1),
    status: str | None = Query(
        default=None, pattern="^(draft|submitted|approved|rejected|cancelled)$"
    ),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(get_current_principal),
    scoped_company: int | None = Depends(optional_company_header),
    db: Session = Depends(get_db),
) -> LeaveRequestPage:
    target = company_id if company_id is not None else scoped_company
    items, total = list_leave_requests(
        db,
        principal,
        company_id=target,
        employee_id=employee_id,
        leave_type_id=leave_type_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
        q=q,
        page=page_params,
    )
    return LeaveRequestPage(
        items=[LeaveRequestOut.model_validate(r) for r in items],
        page=Page(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ),
    )


@requests_router.post("", response_model=LeaveRequestOut, status_code=201)
def create_request(
    payload: LeaveRequestCreate,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> LeaveRequestOut:
    row = create_leave_request(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return LeaveRequestOut.model_validate(row)


@requests_router.post("/preview", response_model=LeaveRequestPreviewOut)
def preview_request(
    payload: LeaveRequestPreview,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> LeaveRequestPreviewOut:
    return preview_leave_request(db, payload=payload, principal=principal)


@requests_router.get("/{request_id}", response_model=LeaveRequestOut)
def read_request(
    request_id: int,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> LeaveRequestOut:
    return LeaveRequestOut.model_validate(
        get_leave_request(db, request_id, principal)
    )


@requests_router.patch("/{request_id}", response_model=LeaveRequestOut)
def update_request(
    request_id: int,
    payload: LeaveRequestUpdate,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> LeaveRequestOut:
    row = update_leave_request(
        db,
        request_id=request_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return LeaveRequestOut.model_validate(row)


@requests_router.delete("/{request_id}", status_code=204)
def remove_request(
    request_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> Response:
    delete_leave_request(
        db, request_id=request_id, principal=principal, ip=client_ip(request)
    )
    return Response(status_code=204)


@requests_router.post("/{request_id}/submit", response_model=LeaveRequestOut)
def submit_request(
    request_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> LeaveRequestOut:
    row = submit_leave_request(
        db, request_id=request_id, principal=principal, ip=client_ip(request)
    )
    return LeaveRequestOut.model_validate(row)


@requests_router.post("/{request_id}/approve", response_model=LeaveRequestOut)
def approve_request(
    request_id: int,
    payload: LeaveRequestDecision,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> LeaveRequestOut:
    row = approve_leave_request(
        db,
        request_id=request_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return LeaveRequestOut.model_validate(row)


@requests_router.post("/{request_id}/reject", response_model=LeaveRequestOut)
def reject_request(
    request_id: int,
    payload: LeaveRequestDecision,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> LeaveRequestOut:
    row = reject_leave_request(
        db,
        request_id=request_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return LeaveRequestOut.model_validate(row)


@requests_router.post("/{request_id}/cancel", response_model=LeaveRequestOut)
def cancel_request(
    request_id: int,
    payload: LeaveRequestDecision,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> LeaveRequestOut:
    row = cancel_leave_request(
        db,
        request_id=request_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return LeaveRequestOut.model_validate(row)


@requests_router.post(
    "/{request_id}/attachment", response_model=LeaveRequestOut
)
def upload_attachment(
    request_id: int,
    request: Request,
    file: UploadFile = File(...),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> LeaveRequestOut:
    data = file.file.read()
    row = upload_request_attachment(
        db,
        request_id=request_id,
        raw_filename=file.filename or "file",
        declared_mime=file.content_type,
        file_data=data,
        principal=principal,
        ip=client_ip(request),
    )
    return LeaveRequestOut.model_validate(row)


@requests_router.get("/{request_id}/attachment")
def download_attachment(
    request_id: int,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> Response:
    data, mime_type, file_name = download_request_attachment(
        db, request_id=request_id, principal=principal
    )
    return Response(
        content=data,
        media_type=mime_type,
        headers={
            "Content-Disposition": _content_disposition(file_name),
            "X-Content-Type-Options": "nosniff",
        },
    )


@requests_router.delete("/{request_id}/attachment", status_code=204)
def remove_attachment(
    request_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> Response:
    delete_request_attachment(
        db, request_id=request_id, principal=principal, ip=client_ip(request)
    )
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Balances
# ---------------------------------------------------------------------------


@balances_router.get("", response_model=LeaveBalancesPage)
def read_balances(
    employee_id: int = Query(..., ge=1),
    leave_type_id: int | None = Query(default=None, ge=1),
    as_of: date | None = Query(default=None),
    period_start: date | None = Query(default=None),
    period_end: date | None = Query(default=None),
    principal: Principal = Depends(require_permission("leave_balance.view")),
    db: Session = Depends(get_db),
) -> LeaveBalancesPage:
    lines = list_leave_balances(
        db,
        principal,
        employee_id=employee_id,
        leave_type_id=leave_type_id,
        as_of=as_of,
        period_start=period_start,
        period_end=period_end,
    )
    return LeaveBalancesPage(items=[BalanceOut(**line) for line in lines])


@balances_router.get("/me", response_model=LeaveBalancesPage)
def read_my_balances(
    as_of: date | None = Query(default=None),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> LeaveBalancesPage:
    lines = my_leave_balances(db, principal, as_of=as_of)
    return LeaveBalancesPage(items=[BalanceOut(**line) for line in lines])


# ---------------------------------------------------------------------------
# Company holidays (D1)
# ---------------------------------------------------------------------------


@holidays_router.get("", response_model=HolidayPage)
def list_all_holidays(
    company_id: int | None = Query(default=None, ge=1),
    year: int | None = Query(default=None, ge=1970, le=9999),
    status: str | None = Query(default=None, pattern="^(active|inactive)$"),
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(require_permission("leave_holiday.view")),
    scoped_company: int | None = Depends(optional_company_header),
    db: Session = Depends(get_db),
) -> HolidayPage:
    target = company_id if company_id is not None else scoped_company
    items, total = list_holidays(
        db,
        principal,
        company_id=target,
        year=year,
        status=status,
        page=page_params,
    )
    return HolidayPage(
        items=[HolidayOut.model_validate(r) for r in items],
        page=Page(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ),
    )


@holidays_router.post("", response_model=HolidayOut, status_code=201)
def create_holiday_route(
    payload: HolidayCreate,
    request: Request,
    principal: Principal = Depends(require_permission("leave_holiday.create")),
    db: Session = Depends(get_db),
) -> HolidayOut:
    row = create_holiday(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return HolidayOut.model_validate(row)


@holidays_router.get("/{holiday_id}", response_model=HolidayOut)
def read_holiday(
    holiday_id: int,
    principal: Principal = Depends(require_permission("leave_holiday.view")),
    db: Session = Depends(get_db),
) -> HolidayOut:
    return HolidayOut.model_validate(get_holiday(db, holiday_id, principal))


@holidays_router.patch("/{holiday_id}", response_model=HolidayOut)
def update_holiday_route(
    holiday_id: int,
    payload: HolidayUpdate,
    request: Request,
    principal: Principal = Depends(require_permission("leave_holiday.update")),
    db: Session = Depends(get_db),
) -> HolidayOut:
    row = update_holiday(
        db,
        holiday_id=holiday_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return HolidayOut.model_validate(row)


@holidays_router.delete("/{holiday_id}", status_code=204)
def remove_holiday(
    holiday_id: int,
    request: Request,
    principal: Principal = Depends(require_permission("leave_holiday.delete")),
    db: Session = Depends(get_db),
) -> Response:
    delete_holiday(
        db, holiday_id=holiday_id, principal=principal, ip=client_ip(request)
    )
    return Response(status_code=204)
