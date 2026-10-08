from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.core.pagination import Page

OVERTIME_STATUS = "^(draft|submitted|approved|rejected|cancelled)$"


class OvertimeCreate(BaseModel):
    employee_id: int = Field(ge=1)
    work_date: date
    # Range checks (1..1440) live in the service so callers receive the
    # stable OVERTIME_INVALID_MINUTES code instead of a 422.
    requested_minutes: int
    attendance_id: int | None = Field(default=None, ge=1)
    reason: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=500)


class OvertimeUpdate(BaseModel):
    work_date: date | None = None
    requested_minutes: int | None = None
    attendance_id: int | None = Field(default=None, ge=1)
    reason: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=500)


class OvertimeApprove(BaseModel):
    approved_minutes: int | None = None
    reason: str | None = Field(default=None, max_length=500)


class OvertimeDecision(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class OvertimeCorrect(BaseModel):
    approved_minutes: int
    reason: str | None = Field(default=None, max_length=500)


class OvertimeOut(BaseModel):
    id: int
    company_id: int
    employee_id: int
    attendance_id: int | None
    work_date: date
    requested_minutes: int
    approved_minutes: int | None
    status: str
    reason: str | None
    decision_reason: str | None
    decided_by: int | None
    decided_at: datetime | None
    submitted_by: int | None
    submitted_at: datetime | None
    correction_reason: str | None
    corrected_by: int | None
    corrected_at: datetime | None
    notes: str | None
    created_by: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OvertimePage(BaseModel):
    items: list[OvertimeOut]
    page: Page
