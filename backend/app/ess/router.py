"""Phase 7 routers: /me (self-service), /employee-requests (workflow)
and /approvals (decision inbox).

Route gates: /me endpoints use coarse ``require_permission("ess.*")`` (the
service re-checks against the OWN employee's company); request/approval
endpoints authenticate only and let the service enforce every self-scope,
cross-employee marker and decision rule (no hardcoded role names).
"""

from __future__ import annotations

from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.attendance.schemas import AttendanceOut, AttendancePage
from app.core.database import get_db
from app.core.deps import (
    Principal,
    client_ip,
    get_current_principal,
    require_permission,
)
from app.core.pagination import Page, PageParams, pagination_params
from app.employee_documents.schemas import DocumentOut, DocumentPage
from app.ess.me_service import (
    get_document_visibility,
    my_attendance,
    my_document_download,
    my_documents,
    my_payslip,
    my_payslips,
    my_profile,
    set_document_visibility,
)
from app.ess.schemas import (
    DocumentVisibilityOut,
    DocumentVisibilityUpdate,
    PayslipSummaryPage,
    ProfileOut,
    RequestCreate,
    RequestDecision,
    RequestEventOut,
    RequestOut,
    RequestPage,
    RequestUpdate,
)
from app.ess.service import (
    approve_request,
    cancel_request,
    create_request,
    get_request_detail,
    list_approvals,
    list_requests,
    reject_request,
    submit_request,
    update_request,
)
from app.payroll.schemas import PayslipOut

me_router = APIRouter(prefix="/me", tags=["me"])
requests_router = APIRouter(prefix="/employee-requests", tags=["employee-requests"])
approvals_router = APIRouter(prefix="/approvals", tags=["approvals"])
visibility_router = APIRouter(
    prefix="/employee-documents", tags=["employee-document-visibility"]
)

REQUEST_STATUS_PATTERN = "^(draft|submitted|approved|rejected|cancelled)$"
REQUEST_TYPE_PATTERN = "^(attendance_correction|hr_letter|document_request|other)$"
INBOX_STATUS_PATTERN = (
    "^(|draft|submitted|approved|rejected|cancelled)$"
)


def _content_disposition(filename: str) -> str:
    ascii_name = filename.encode("ascii", "ignore").decode() or "download"
    ascii_name = ascii_name.replace('"', "")
    return (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )


def _page(page_params: PageParams, total: int) -> Page:
    return Page(
        page=page_params.page, page_size=page_params.page_size, total=total
    )


def _request_out(row, events: list | None = None) -> RequestOut:
    out = RequestOut.model_validate(row)
    if events is not None:
        out.events = [RequestEventOut.model_validate(event) for event in events]
    return out


# ---------------------------------------------------------------------------
# /me - employee self-service
# ---------------------------------------------------------------------------


@me_router.get("/profile", response_model=ProfileOut)
def read_profile(
    principal: Principal = Depends(require_permission("ess.profile.view")),
    db: Session = Depends(get_db),
) -> ProfileOut:
    return my_profile(db, principal)


@me_router.get("/documents", response_model=DocumentPage)
def list_documents(
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(require_permission("ess.document.view")),
    db: Session = Depends(get_db),
) -> DocumentPage:
    items, total = my_documents(db, principal, page=page_params)
    return DocumentPage(
        items=[DocumentOut.model_validate(row) for row in items],
        page=_page(page_params, total),
    )


@me_router.get("/documents/{document_id}/download")
def download_document(
    document_id: int,
    request: Request,
    principal: Principal = Depends(require_permission("ess.document.view")),
    db: Session = Depends(get_db),
) -> Response:
    data, mime_type, file_name = my_document_download(
        db,
        document_id=document_id,
        principal=principal,
        ip=client_ip(request),
    )
    return Response(
        content=data,
        media_type=mime_type,
        headers={"Content-Disposition": _content_disposition(file_name)},
    )


@me_router.get("/attendance", response_model=AttendancePage)
def list_my_attendance(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(require_permission("ess.attendance.view")),
    db: Session = Depends(get_db),
) -> AttendancePage:
    items, total = my_attendance(
        db, principal, date_from=date_from, date_to=date_to, page=page_params
    )
    return AttendancePage(
        items=[AttendanceOut.model_validate(row) for row in items],
        page=_page(page_params, total),
    )


@me_router.get("/payslips", response_model=PayslipSummaryPage)
def list_my_payslips(
    request: Request,
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(require_permission("ess.payslip.view")),
    db: Session = Depends(get_db),
) -> PayslipSummaryPage:
    items, total = my_payslips(
        db, principal, page=page_params, ip=client_ip(request)
    )
    return PayslipSummaryPage(items=items, page=_page(page_params, total))


@me_router.get("/payslips/{run_line_id}", response_model=PayslipOut)
def read_my_payslip(
    run_line_id: int,
    request: Request,
    principal: Principal = Depends(require_permission("ess.payslip.view")),
    db: Session = Depends(get_db),
) -> PayslipOut:
    return my_payslip(
        db, run_line_id=run_line_id, principal=principal, ip=client_ip(request)
    )


# ---------------------------------------------------------------------------
# /employee-requests - generic request workflow
# ---------------------------------------------------------------------------


@requests_router.post("", response_model=RequestOut, status_code=201)
def create(
    payload: RequestCreate,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> RequestOut:
    row = create_request(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return _request_out(row)


@requests_router.get("", response_model=RequestPage)
def list_(
    company_id: int | None = Query(default=None, ge=1),
    employee_id: int | None = Query(default=None, ge=1),
    request_type: str | None = Query(default=None, pattern=REQUEST_TYPE_PATTERN),
    status: str | None = Query(default=None, pattern=REQUEST_STATUS_PATTERN),
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> RequestPage:
    items, total = list_requests(
        db,
        principal,
        company_id=company_id,
        employee_id=employee_id,
        request_type=request_type,
        status=status,
        page=page_params,
    )
    return RequestPage(
        items=[_request_out(row) for row in items],
        page=_page(page_params, total),
    )


@requests_router.get("/{request_id}", response_model=RequestOut)
def read(
    request_id: int,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> RequestOut:
    row, events = get_request_detail(db, request_id, principal)
    return _request_out(row, events)


@requests_router.patch("/{request_id}", response_model=RequestOut)
def update(
    request_id: int,
    payload: RequestUpdate,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> RequestOut:
    row = update_request(
        db,
        request_id=request_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return _request_out(row)


@requests_router.post("/{request_id}/submit", response_model=RequestOut)
def submit(
    request_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> RequestOut:
    row = submit_request(
        db, request_id=request_id, principal=principal, ip=client_ip(request)
    )
    return _request_out(row)


@requests_router.post("/{request_id}/cancel", response_model=RequestOut)
def cancel(
    request_id: int,
    request: Request,
    payload: RequestDecision | None = None,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> RequestOut:
    row = cancel_request(
        db,
        request_id=request_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return _request_out(row)


@requests_router.post("/{request_id}/approve", response_model=RequestOut)
def approve(
    request_id: int,
    request: Request,
    payload: RequestDecision | None = None,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> RequestOut:
    row = approve_request(
        db,
        request_id=request_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return _request_out(row)


@requests_router.post("/{request_id}/reject", response_model=RequestOut)
def reject(
    request_id: int,
    request: Request,
    payload: RequestDecision | None = None,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> RequestOut:
    row = reject_request(
        db,
        request_id=request_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return _request_out(row)


# ---------------------------------------------------------------------------
# HR-side document visibility toggle (Phase 7 sidecar flag)
# ---------------------------------------------------------------------------


@visibility_router.get(
    "/{document_id}/visibility", response_model=DocumentVisibilityOut
)
def read_visibility(
    document_id: int,
    principal: Principal = Depends(require_permission("employee_document.view")),
    db: Session = Depends(get_db),
) -> DocumentVisibilityOut:
    visible, updated_by = get_document_visibility(
        db, document_id=document_id, principal=principal
    )
    return DocumentVisibilityOut(
        document_id=document_id,
        employee_visible=visible,
        updated_by=updated_by,
    )


@visibility_router.patch(
    "/{document_id}/visibility", response_model=DocumentVisibilityOut
)
def update_visibility(
    document_id: int,
    payload: DocumentVisibilityUpdate,
    request: Request,
    principal: Principal = Depends(require_permission("employee_document.update")),
    db: Session = Depends(get_db),
) -> DocumentVisibilityOut:
    doc = set_document_visibility(
        db,
        document_id=document_id,
        employee_visible=payload.employee_visible,
        principal=principal,
        ip=client_ip(request),
    )
    return DocumentVisibilityOut(
        document_id=doc.id,
        employee_visible=payload.employee_visible,
        updated_by=principal.user_id,
    )


# ---------------------------------------------------------------------------
# /approvals - decision inbox
# ---------------------------------------------------------------------------


@approvals_router.get("", response_model=RequestPage)
def inbox(
    company_id: int | None = Query(default=None, ge=1),
    status: str | None = Query(default="submitted", pattern=INBOX_STATUS_PATTERN),
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> RequestPage:
    items, total = list_approvals(
        db,
        principal,
        company_id=company_id,
        status=status or None,
        page=page_params,
    )
    return RequestPage(
        items=[_request_out(row) for row in items],
        page=_page(page_params, total),
    )
