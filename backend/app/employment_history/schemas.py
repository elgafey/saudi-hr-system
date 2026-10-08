from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.core.pagination import Page


class HistoryCreate(BaseModel):
    company_id: int = Field(ge=1)
    effective_from: date
    effective_to: date | None = None
    branch_id: int | None = Field(default=None, ge=1)
    department_id: int | None = Field(default=None, ge=1)
    position_id: int | None = Field(default=None, ge=1)
    grade_id: int | None = Field(default=None, ge=1)
    manager_id: int | None = Field(default=None, ge=1)
    employment_status: str = Field(pattern="^(draft|active|suspended|terminated)$")
    employment_type: str = Field(
        pattern="^(full_time|part_time|temporary|intern)$"
    )
    change_reason: str | None = Field(default=None, max_length=100)
    notes: str | None = None
    apply_to_employee: bool = True


class HistoryOut(BaseModel):
    id: int
    company_id: int
    employee_id: int
    effective_from: date
    effective_to: date | None
    branch_id: int | None
    department_id: int | None
    position_id: int | None
    grade_id: int | None
    manager_id: int | None
    employment_status: str
    employment_type: str
    change_reason: str | None
    notes: str | None
    created_by: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class HistoryPage(BaseModel):
    items: list[HistoryOut]
    page: Page
