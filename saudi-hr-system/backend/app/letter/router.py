"""Phase 9 router: /hr-letters (HR lifecycle) + /me/letters (ESS portal).

HR routes authenticate only - state, permission and self-scope rules all
live in the service (Phase 7/8 pattern, permission codes only). ESS routes
additionally gate on ``ess.letter.view`` through a route dependency and
let the service scope reads to the caller's own employee. ESS responses
redact ``void_reason`` and the void event note (admin-only audit text).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import (
    Principal,
    client_ip,
    get_current_principal,
    require_permission,
)
from app.core.pagination import Page, PageParams, pagination_params
from app.letter.schemas import (
    LetterCancel,
    LetterCreate,
    LetterEventOut,
    LetterListOut,
    LetterOut,
    LetterPage,
    LetterUpdate,
    LetterVoid,
)
from app.letter.service import (
    cancel_letter,
    create_letter,
    get_letter_detail,
    get_own_letter_detail,
    issue_letter,
    list_letters,
    list_own_letters,
    update_letter,
    void_letter,
)

hr_letters_router = APIRouter(prefix="/hr-letters", tags=["hr-letters"])
ess_letters_router = APIRouter(prefix="/me/letters", tags=["ess-letters"])

STATUS_PATTERN = "^(|draft|issued|void|cancelled)$"
TYPE_PATTERN = "^(|employment|salary|experience|work_address)$"


def _page(page_params: PageParams, total: int) -> Page:
    return Page(
        page=page_params.page, page_size=page_params.page_size, total=total
    )


def _detail_out(
    row, events: list | None = None, *, ess: bool = False
) -> LetterOut:
    out = LetterOut.model_validate(row)
    if events is not None:
        rendered = []
        for event in events:
            event_out = LetterEventOut.model_validate(event)
            if ess and event.action == "voided":
                event_out.note = None
            rendered.append(event_out)
        out.events = rendered
    if ess:
        out.void_reason = None
    return out


# ---------------------------------------------------------------------------
# HR lifecycle
# ---------------------------------------------------------------------------


@hr_letters_router.post("", response_model=LetterOut, status_code=201)
def create(
    payload: LetterCreate,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> LetterOut:
    row = create_letter(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return _detail_out(row)


@hr_letters_router.get("", response_model=LetterPage)
def list_(
    company_id: int | None = Query(default=None, ge=1),
    employee_id: int | None = Query(default=None, ge=1),
    letter_type: str | None = Query(default=None, pattern=TYPE_PATTERN),
    status: str | None = Query(default=None, pattern=STATUS_PATTERN),
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> LetterPage:
    items, total = list_letters(
        db,
        principal,
        company_id=company_id,
        employee_id=employee_id,
        letter_type=letter_type or None,
        status=status or None,
        page=page_params,
    )
    return LetterPage(
        items=[LetterListOut.model_validate(row) for row in items],
        page=_page(page_params, total),
    )


@hr_letters_router.get("/{letter_id}", response_model=LetterOut)
def read(
    letter_id: int,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> LetterOut:
    row, events = get_letter_detail(db, letter_id, principal)
    return _detail_out(row, events)


@hr_letters_router.patch("/{letter_id}", response_model=LetterOut)
def update(
    letter_id: int,
    payload: LetterUpdate,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> LetterOut:
    row = update_letter(
        db,
        letter_id=letter_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return _detail_out(row)


@hr_letters_router.post("/{letter_id}/issue", response_model=LetterOut)
def issue(
    letter_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> LetterOut:
    row = issue_letter(
        db, letter_id=letter_id, principal=principal, ip=client_ip(request)
    )
    return _detail_out(row)


@hr_letters_router.post("/{letter_id}/cancel", response_model=LetterOut)
def cancel(
    letter_id: int,
    request: Request,
    payload: LetterCancel | None = None,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> LetterOut:
    row = cancel_letter(
        db,
        letter_id=letter_id,
        reason=payload.reason if payload else None,
        principal=principal,
        ip=client_ip(request),
    )
    return _detail_out(row)


@hr_letters_router.post("/{letter_id}/void", response_model=LetterOut)
def void(
    letter_id: int,
    request: Request,
    payload: LetterVoid,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> LetterOut:
    row = void_letter(
        db,
        letter_id=letter_id,
        reason=payload.reason,
        principal=principal,
        ip=client_ip(request),
    )
    return _detail_out(row)


# ---------------------------------------------------------------------------
# ESS portal (own letters only)
# ---------------------------------------------------------------------------


@ess_letters_router.get("", response_model=LetterPage)
def list_own(
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(require_permission("ess.letter.view")),
    db: Session = Depends(get_db),
) -> LetterPage:
    items, total = list_own_letters(db, principal, page=page_params)
    return LetterPage(
        items=[LetterListOut.model_validate(row) for row in items],
        page=_page(page_params, total),
    )


@ess_letters_router.get("/{letter_id}", response_model=LetterOut)
def read_own(
    letter_id: int,
    principal: Principal = Depends(require_permission("ess.letter.view")),
    db: Session = Depends(get_db),
) -> LetterOut:
    row, events = get_own_letter_detail(db, letter_id, principal)
    return _detail_out(row, events, ess=True)
