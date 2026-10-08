from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.core.deps import Principal
from app.core.exceptions import (
    ConflictError,
    DocumentDateRangeError,
    DocumentNotFoundError,
    DocumentTypeNotFoundError,
    EmployeeNotFoundError,
    ForbiddenError,
)
from app.core.pagination import PageParams
from app.core.storage import get_storage, validate_document_upload
from app.employee_documents.schemas import DocumentTypeCreate, DocumentUpdate
from app.shared.models import Employee, EmployeeDocument, EmployeeDocumentType

# Seeded lazily (first list call per company) - not in migration 0004.
DEFAULT_DOCUMENT_TYPES: tuple[tuple[str, str, str], ...] = (
    ("national_id", "الهوية الوطنية", "National ID"),
    ("passport", "جواز السفر", "Passport"),
    ("iqama", "الإقامة", "Iqama"),
    ("driving_license", "رخصة القيادة", "Driving License"),
    ("qualification", "مؤهل علمي", "Qualification"),
    ("certificate", "شهادة", "Certificate"),
    ("medical", "مستند طبي", "Medical Document"),
    ("other", "أخرى", "Other"),
)


def _require(principal: Principal, code: str, company_id: int | None) -> None:
    """Company-scoped permission check (H1)."""
    if not principal.has_permission(code, company_id):
        raise ForbiddenError(f"Missing permission: {code}")


def _resolve_employee(db: Session, employee_id: int, principal: Principal) -> Employee:
    """Document routes are gated by their own permissions; employee.read is
    not required to resolve the target (404 never leaks existence)."""
    employee = db.get(Employee, employee_id)
    if employee is None or not principal.can_access_company(employee.company_id):
        raise EmployeeNotFoundError("Employee not found")
    return employee


def _fetch_document(db: Session, employee: Employee, document_id: int) -> EmployeeDocument:
    doc = db.get(EmployeeDocument, document_id)
    if (
        doc is None
        or doc.employee_id != employee.id
        or doc.company_id != employee.company_id
    ):
        raise DocumentNotFoundError("Document not found")
    return doc


def _check_dates(issue_date: date | None, expiry_date: date | None) -> None:
    if issue_date and expiry_date and expiry_date < issue_date:
        raise DocumentDateRangeError("expiry_date cannot be before issue_date")


def _check_type(db: Session, document_type_id: int, company_id: int) -> None:
    doc_type = db.get(EmployeeDocumentType, document_type_id)
    if doc_type is None or doc_type.company_id != company_id:
        raise DocumentTypeNotFoundError("Document type not found")


# ---------------------------------------------------------------------------
# Document types (company-scoped lookup; defaults are seeded lazily)
# ---------------------------------------------------------------------------


def list_document_types(
    db: Session, *, principal: Principal, company_id: int
) -> list[EmployeeDocumentType]:
    if not principal.can_access_company(company_id):
        raise ForbiddenError("You cannot access this company")
    _require(principal, "employee_document.view", company_id)
    stmt = (
        select(EmployeeDocumentType)
        .where(EmployeeDocumentType.company_id == company_id)
        .order_by(EmployeeDocumentType.id)
    )
    rows = list(db.execute(stmt).scalars())
    if rows:
        return rows
    # Lazy default seeding: system behavior behind employee_document.view so
    # every company has usable types without a migration-time bootstrap.
    for code, name_ar, name_en in DEFAULT_DOCUMENT_TYPES:
        db.add(
            EmployeeDocumentType(
                company_id=company_id,
                code=code,
                name_ar=name_ar,
                name_en=name_en,
                is_default=True,
            )
        )
    db.flush()
    return list(db.execute(stmt).scalars())


def create_document_type(
    db: Session, *, payload: DocumentTypeCreate, principal: Principal
) -> EmployeeDocumentType:
    if not principal.can_access_company(payload.company_id):
        raise ForbiddenError("You cannot create document types in this company")
    _require(principal, "employee_document.create", payload.company_id)
    existing = db.execute(
        select(EmployeeDocumentType.id).where(
            EmployeeDocumentType.company_id == payload.company_id,
            EmployeeDocumentType.code == payload.code,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("Document type code already exists in this company")
    doc_type = EmployeeDocumentType(**payload.model_dump())
    db.add(doc_type)
    db.flush()
    return doc_type


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


def list_documents(
    db: Session,
    principal: Principal,
    *,
    employee_id: int,
    document_type_id: int | None = None,
    page: PageParams | None = None,
) -> tuple[list[EmployeeDocument], int]:
    employee = _resolve_employee(db, employee_id, principal)
    _require(principal, "employee_document.view", employee.company_id)
    stmt = select(EmployeeDocument).where(
        EmployeeDocument.employee_id == employee.id,
        EmployeeDocument.company_id == employee.company_id,
    )
    count_stmt = select(func.count()).select_from(EmployeeDocument).where(
        EmployeeDocument.employee_id == employee.id,
        EmployeeDocument.company_id == employee.company_id,
    )
    if document_type_id is not None:
        stmt = stmt.where(EmployeeDocument.document_type_id == document_type_id)
        count_stmt = count_stmt.where(
            EmployeeDocument.document_type_id == document_type_id
        )
    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(EmployeeDocument.id.desc())
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


def get_document(
    db: Session,
    principal: Principal,
    *,
    employee_id: int,
    document_id: int,
) -> EmployeeDocument:
    employee = _resolve_employee(db, employee_id, principal)
    _require(principal, "employee_document.view", employee.company_id)
    return _fetch_document(db, employee, document_id)


def create_document(
    db: Session,
    *,
    employee_id: int,
    document_type_id: int,
    document_number: str | None,
    issue_date: date | None,
    expiry_date: date | None,
    notes: str | None,
    raw_filename: str,
    declared_mime: str | None,
    file_data: bytes,
    principal: Principal,
    ip: str | None,
) -> EmployeeDocument:
    employee = _resolve_employee(db, employee_id, principal)
    _require(principal, "employee_document.create", employee.company_id)
    file_name, mime_type = validate_document_upload(
        filename=raw_filename, declared_mime=declared_mime, data=file_data
    )
    _check_dates(issue_date, expiry_date)
    _check_type(db, document_type_id, employee.company_id)

    storage = get_storage()
    storage_key = storage.save(
        company_id=employee.company_id,
        employee_id=employee.id,
        data=file_data,
        mime_type=mime_type,
    )
    doc = EmployeeDocument(
        company_id=employee.company_id,
        employee_id=employee.id,
        document_type_id=document_type_id,
        document_number=document_number,
        issue_date=issue_date,
        expiry_date=expiry_date,
        file_name=file_name,
        mime_type=mime_type,
        file_size=len(file_data),
        storage_key=storage_key,
        notes=notes,
        created_by=principal.user_id,
    )
    db.add(doc)
    try:
        db.flush()
    except IntegrityError as exc:
        # The type can disappear (or the file land) only on a race with a
        # concurrent delete - never leave orphaned bytes behind.
        storage.delete(storage_key)
        raise ConflictError("Document type is no longer available") from exc
    record_audit(
        db,
        action="document.upload",
        entity="employee_document",
        record_id=doc.id,
        actor_user_id=principal.user_id,
        company_id=employee.company_id,
        new_value={
            "employee_id": employee.id,
            "document_type_id": document_type_id,
            "file_name": file_name,
            "file_size": doc.file_size,
            "mime_type": mime_type,
        },
        ip_address=ip,
    )
    db.flush()
    return doc


def update_document(
    db: Session,
    *,
    employee_id: int,
    document_id: int,
    payload: DocumentUpdate,
    principal: Principal,
    ip: str | None,
) -> EmployeeDocument:
    employee = _resolve_employee(db, employee_id, principal)
    _require(principal, "employee_document.update", employee.company_id)
    doc = _fetch_document(db, employee, document_id)
    changes = payload.model_dump(exclude_unset=True)
    if "document_type_id" in changes and changes["document_type_id"] is not None:
        _check_type(db, changes["document_type_id"], employee.company_id)
    merged_issue = changes.get("issue_date", doc.issue_date)
    merged_expiry = changes.get("expiry_date", doc.expiry_date)
    _check_dates(merged_issue, merged_expiry)
    for key, value in changes.items():
        setattr(doc, key, value)
    db.add(doc)
    record_audit(
        db,
        action="document.update",
        entity="employee_document",
        record_id=doc.id,
        actor_user_id=principal.user_id,
        company_id=employee.company_id,
        new_value={"employee_id": employee.id, "fields": sorted(changes)},
        ip_address=ip,
    )
    db.flush()
    return doc


def delete_document(
    db: Session,
    *,
    employee_id: int,
    document_id: int,
    principal: Principal,
    ip: str | None,
) -> None:
    employee = _resolve_employee(db, employee_id, principal)
    _require(principal, "employee_document.delete", employee.company_id)
    doc = _fetch_document(db, employee, document_id)
    storage_key = doc.storage_key
    record_id = doc.id
    record_audit(
        db,
        action="document.delete",
        entity="employee_document",
        record_id=record_id,
        actor_user_id=principal.user_id,
        company_id=employee.company_id,
        old_value={
            "employee_id": employee.id,
            "file_name": doc.file_name,
            "file_size": doc.file_size,
        },
        ip_address=ip,
    )
    db.delete(doc)
    db.flush()
    # Best effort: bytes are removed after the row; a failure here leaves an
    # orphan file (never a dangling row), which is the safe direction.
    try:
        get_storage().delete(storage_key)
    except OSError:
        pass


def download_document(
    db: Session,
    *,
    employee_id: int,
    document_id: int,
    principal: Principal,
    ip: str | None,
) -> tuple[bytes, str, str]:
    """Permission-checked, authenticated download. Returns
    ``(data, mime_type, file_name)``."""
    employee = _resolve_employee(db, employee_id, principal)
    _require(principal, "employee_document.download", employee.company_id)
    doc = _fetch_document(db, employee, document_id)
    data = get_storage().load(doc.storage_key)
    record_audit(
        db,
        action="document.download",
        entity="employee_document",
        record_id=doc.id,
        actor_user_id=principal.user_id,
        company_id=employee.company_id,
        new_value={"employee_id": employee.id, "file_name": doc.file_name},
        ip_address=ip,
    )
    db.flush()
    return data, doc.mime_type, doc.file_name
