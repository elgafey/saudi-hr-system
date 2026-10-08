"""Phase 8 salary advance schemas (closed payloads - no formula engine)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.core.pagination import Page


class AdvanceCreate(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    reason: str = Field(min_length=1, max_length=4000)
    requested_date: date
    # Defaults to the caller's own employee; acting for another employee
    # additionally requires salary_advance.view (cross-employee marker).
    employee_id: int | None = Field(default=None, ge=1)


class AdvanceUpdate(BaseModel):
    amount: Decimal | None = Field(
        default=None, gt=0, max_digits=12, decimal_places=2
    )
    reason: str | None = Field(default=None, min_length=1, max_length=4000)
    requested_date: date | None = None


class AdvanceDecision(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class AdvanceDisburse(BaseModel):
    # Per-payroll-period installment; NULL = the full amount is collected
    # in a single drawdown. Clamped by the service to (0, amount].
    installment_amount: Decimal | None = Field(
        default=None, gt=0, max_digits=12, decimal_places=2
    )
    note: str | None = Field(default=None, max_length=500)


class AdvanceSettle(BaseModel):
    # Required only for early settlement (linked rule still active);
    # optional confirmation note when the rule already completed/cancelled.
    reason: str | None = Field(default=None, max_length=500)


class AdvanceEventOut(BaseModel):
    id: int
    event_type: str
    actor_name: str
    note: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AdvanceOut(BaseModel):
    id: int
    company_id: int
    employee_id: int
    approver_employee_id: int | None
    amount: Decimal
    reason: str
    requested_date: date
    installment_amount: Decimal | None
    status: str
    submitted_by: int | None
    submitted_at: datetime | None
    decided_by: int | None
    decided_at: datetime | None
    decision_reason: str | None
    disbursed_by: int | None
    disbursed_at: datetime | None
    settled_by: int | None
    settled_at: datetime | None
    settle_note: str | None
    deduction_rule_id: int | None
    created_by: int | None
    created_at: datetime
    updated_at: datetime
    events: list[AdvanceEventOut] = []

    model_config = {"from_attributes": True}


class AdvancePage(BaseModel):
    items: list[AdvanceOut]
    page: Page
