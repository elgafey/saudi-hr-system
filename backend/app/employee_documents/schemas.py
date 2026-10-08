from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.core.pagination import Page


class DocumentTypeCreate(BaseModel):
    company_id: int = Field(ge=1)
    code: str = Field(min_length=1, max_length=50)
    name_ar: str = Field(min_length=1, max_length=255)
    name_en: str = Field(min_length=1, max_length=255)


class DocumentTypeOut(BaseModel):
    id: int
    company_id: int
    code: str
    name_ar: str
    name_en: str
    is_default: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentUpdate(BaseModel):
    document_type_id: int | None = Field(default=None, ge=1)
    document_number: str | None = Field(default=None, max_length=50)
    issue_date: date | None = None
    expiry_date: date | None = None
    notes: str | None = None


class DocumentOut(BaseModel):
    id: int
    company_id: int
    employee_id: int
    document_type_id: int
    document_number: str | None
    issue_date: date | None
    expiry_date: date | None
    file_name: str
    mime_type: str
    file_size: int
    notes: str | None
    created_by: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentPage(BaseModel):
    items: list[DocumentOut]
    page: Page
