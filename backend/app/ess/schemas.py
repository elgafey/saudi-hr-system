"""Phase 7 request/approval and /me response schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.core.pagination import Page

# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class RequestCreate(BaseModel):
    request_type: str = Field(min_length=1, max_length=40)
    subject: str = Field(min_length=1, max_length=255)
    reason: str | None = Field(default=None, max_length=4000)
    payload: dict = Field(default_factory=dict)
    # Defaults to the caller's own employee; acting for another employee
    # additionally requires employee_request.view (cross-employee marker).
    employee_id: int | None = Field(default=None, ge=1)


class RequestUpdate(BaseModel):
    subject: str | None = Field(default=None, min_length=1, max_length=255)
    reason: str | None = Field(default=None, max_length=4000)
    payload: dict | None = None


class RequestDecision(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class RequestEventOut(BaseModel):
    id: int
    event_type: str
    actor_name: str
    note: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class RequestOut(BaseModel):
    id: int
    company_id: int
    employee_id: int
    approver_employee_id: int | None
    request_type: str
    status: str
    subject: str
    reason: str | None
    payload: dict
    work_date: date | None
    submitted_by: int | None
    submitted_at: datetime | None
    decided_by: int | None
    decided_at: datetime | None
    decision_reason: str | None
    cancelled_by: int | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    attendance_record_id: int | None
    created_by: int | None
    created_at: datetime
    updated_at: datetime
    events: list[RequestEventOut] = []

    model_config = {"from_attributes": True}


class RequestPage(BaseModel):
    items: list[RequestOut]
    page: Page


# ---------------------------------------------------------------------------
# /me profile
# ---------------------------------------------------------------------------


class ProfileNameOut(BaseModel):
    id: int
    name_ar: str
    name_en: str


class ProfileContractOut(BaseModel):
    id: int
    contract_number: str | None
    contract_type: str
    start_date: date
    end_date: date | None
    # Own contracted basic pay (open Q3 default: the employee may see it).
    basic_salary: Decimal | None
    currency: str


class ProfileOut(BaseModel):
    id: int
    company_id: int
    employee_number: str
    first_name_ar: str
    middle_name_ar: str | None
    last_name_ar: str
    first_name_en: str
    middle_name_en: str | None
    last_name_en: str
    status: str
    employment_type: str
    hire_date: date | None
    nationality: str
    gender: str | None
    work_email: str | None
    mobile_phone: str | None
    company: ProfileNameOut | None
    department: ProfileNameOut | None
    branch: ProfileNameOut | None
    job_position: ProfileNameOut | None
    manager: ProfileNameOut | None
    contract: ProfileContractOut | None


# ---------------------------------------------------------------------------
# /me payslips (period status gated to approved/paid/locked)
# ---------------------------------------------------------------------------


class PayslipSummaryOut(BaseModel):
    id: int
    run_id: int
    employee_id: int
    basic_snapshot: Decimal
    currency: str
    earnings_total: Decimal
    deductions_total: Decimal
    net_pay: Decimal
    run_number: int
    period_id: int
    period_name: str
    period_start: date
    period_end: date
    period_status: str


class PayslipSummaryPage(BaseModel):
    items: list[PayslipSummaryOut]
    page: Page


# ---------------------------------------------------------------------------
# HR-side document visibility toggle (sidecar, default-deny)
# ---------------------------------------------------------------------------


class DocumentVisibilityUpdate(BaseModel):
    employee_visible: bool


class DocumentVisibilityOut(BaseModel):
    document_id: int
    employee_visible: bool
    updated_by: int | None
