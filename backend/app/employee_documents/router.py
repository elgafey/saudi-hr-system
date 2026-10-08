from __future__ import annotations

from datetime import date
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
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
    optional_company_header,
    require_permission,
)
from app.core.pagination import Page, PageParams, pagination_params
from app.employee_documents.schemas import (
    DocumentOut,
    DocumentPage,
    DocumentTypeCreate,
    DocumentTypeOut,
    DocumentUpdate,
)
from app.employee_documents.service import (
    create_document,
    create_document_type,
    delete_document,
    download_document,
    get_document,
    list_document_types,
    list_documents,
    update_document,
)

router = APIRouter(
    prefix="/employees/{employee_id}/documents", tags=["employee-documents"]
)
types_router = APIRouter(
    prefix="/employee-document-types", tags=["employee-document-types"]
)


def _content_disposition(filename: str) -> str:
    ascii_name = filename.encode("ascii", "ignore").decode() or "download"
    ascii_name = ascii_name.replace('"', "")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"


@router.get("", response_model=DocumentPage)
def list_all(
    employee_id: int,
    document_type_id: int | None = Query(default=None, ge=1),
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(require_permission("employee_document.view")),
    db: Session = Depends(get_db),
) -> DocumentPage:
    items, total = list_documents(
        db,
        principal,
        employee_id=employee_id,
        document_type_id=document_type_id,
        page=page_params,
    )
    return DocumentPage(
        items=[DocumentOut.model_validate(i) for i in items],
        page=Page(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ),
    )


@router.post("", response_model=DocumentOut, status_code=201)
def upload(
    employee_id: int,
    request: Request,
    document_type_id: int = Form(..., ge=1),
    document_number: str | None = Form(default=None, max_length=50),
    issue_date: date | None = Form(default=None),
    expiry_date: date | None = Form(default=None),
    notes: str | None = Form(default=None),
    file: UploadFile = File(...),
    principal: Principal = Depends(require_permission("employee_document.create")),
    db: Session = Depends(get_db),
) -> DocumentOut:
    data = file.file.read()
    doc = create_document(
        db,
        employee_id=employee_id,
        document_type_id=document_type_id,
        document_number=document_number,
        issue_date=issue_date,
        expiry_date=expiry_date,
        notes=notes,
        raw_filename=file.filename or "file",
        declared_mime=file.content_type,
        file_data=data,
        principal=principal,
        ip=client_ip(request),
    )
    return DocumentOut.model_validate(doc)


@router.get("/{document_id}", response_model=DocumentOut)
def read(
    employee_id: int,
    document_id: int,
    principal: Principal = Depends(require_permission("employee_document.view")),
    db: Session = Depends(get_db),
) -> DocumentOut:
    doc = get_document(
        db, principal, employee_id=employee_id, document_id=document_id
    )
    return DocumentOut.model_validate(doc)


@router.patch("/{document_id}", response_model=DocumentOut)
def update(
    employee_id: int,
    document_id: int,
    payload: DocumentUpdate,
    request: Request,
    principal: Principal = Depends(require_permission("employee_document.update")),
    db: Session = Depends(get_db),
) -> DocumentOut:
    doc = update_document(
        db,
        employee_id=employee_id,
        document_id=document_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return DocumentOut.model_validate(doc)


@router.delete("/{document_id}", status_code=204)
def remove(
    employee_id: int,
    document_id: int,
    request: Request,
    principal: Principal = Depends(require_permission("employee_document.delete")),
    db: Session = Depends(get_db),
) -> Response:
    delete_document(
        db,
        employee_id=employee_id,
        document_id=document_id,
        principal=principal,
        ip=client_ip(request),
    )
    return Response(status_code=204)


@router.get("/{document_id}/download")
def download(
    employee_id: int,
    document_id: int,
    request: Request,
    principal: Principal = Depends(require_permission("employee_document.download")),
    db: Session = Depends(get_db),
) -> Response:
    data, mime_type, file_name = download_document(
        db,
        employee_id=employee_id,
        document_id=document_id,
        principal=principal,
        ip=client_ip(request),
    )
    return Response(
        content=data,
        media_type=mime_type,
        headers={
            "Content-Disposition": _content_disposition(file_name),
            "X-Content-Type-Options": "nosniff",
        },
    )


@types_router.get("", response_model=list[DocumentTypeOut])
def list_types(
    company_id: int | None = Query(default=None, ge=1),
    principal: Principal = Depends(require_permission("employee_document.view")),
    scoped_company: int | None = Depends(optional_company_header),
    db: Session = Depends(get_db),
) -> list[DocumentTypeOut]:
    target = company_id if company_id is not None else scoped_company
    if target is not None:
        return [
            DocumentTypeOut.model_validate(t)
            for t in list_document_types(db, principal=principal, company_id=target)
        ]
    # No company scope: return types for every company the caller may read.
    # Platform admins (no implicit scope) must pass an explicit company.
    if principal.is_platform_admin:
        return []
    out: list[DocumentTypeOut] = []
    for cid in principal.permitted_company_ids("employee_document.view"):
        out.extend(
            DocumentTypeOut.model_validate(t)
            for t in list_document_types(db, principal=principal, company_id=cid)
        )
    return out


@types_router.post("", response_model=DocumentTypeOut, status_code=201)
def create_type(
    payload: DocumentTypeCreate,
    principal: Principal = Depends(require_permission("employee_document.create")),
    db: Session = Depends(get_db),
) -> DocumentTypeOut:
    doc_type = create_document_type(db, payload=payload, principal=principal)
    return DocumentTypeOut.model_validate(doc_type)
