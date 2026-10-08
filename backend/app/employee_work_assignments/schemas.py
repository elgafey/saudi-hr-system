from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.core.pagination import Page


class AssignmentCreate(BaseModel):
    schedule_id: int = Field(ge=1)
    shift_id: int | None = Field(default=None, ge=1)
    effective_from: date
    effective_to: date | None = None
    notes: str | None = Field(default=None, max_length=500)


class AssignmentUpdate(BaseModel):
    schedule_id: int | None = Field(default=None, ge=1)
    shift_id: int | None = Field(default=None, ge=1)
    effective_from: date | None = None
    effective_to: date | None = None
    notes: str | None = Field(default=None, max_length=500)


class AssignmentOut(BaseModel):
    id: int
    company_id: int
    employee_id: int
    schedule_id: int
    shift_id: int | None
    effective_from: date
    effective_to: date | None
    notes: str | None
    created_by: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AssignmentPage(BaseModel):
    items: list[AssignmentOut]
    page: Page
