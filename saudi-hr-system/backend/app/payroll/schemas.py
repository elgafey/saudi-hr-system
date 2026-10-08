from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.core.pagination import Page

COMPONENT_CATEGORY = "^(earning|deduction|employer_contribution)$"
COMPONENT_BASIS = "^(fixed|percent_of_basic|engine_derived)$"
ACTIVE_STATUS = "^(active|inactive)$"
PERIOD_STATUS = "^(draft|calculated|reviewed|approved|paid|locked)$"
ADJUSTMENT_STATUS = "^(draft|pending|approved|rejected|void)$"
ADJUSTMENT_DIRECTION = "^(earning|deduction)$"
DEDUCTION_STATUS = "^(active|completed|cancelled)$"
RULE_STATUS = "^(active|inactive)$"
CURRENCY = "^[A-Z]{3}$"


# ---------------------------------------------------------------------------
# Salary components
# ---------------------------------------------------------------------------


class SalaryComponentCreate(BaseModel):
    company_id: int = Field(ge=1)
    code: str = Field(min_length=1, max_length=50)
    name_ar: str = Field(min_length=1, max_length=255)
    name_en: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    category: str = Field(pattern=COMPONENT_CATEGORY)
    calculation_basis: str = Field(pattern=COMPONENT_BASIS)
    default_amount: Decimal | None = Field(default=None, ge=0)
    default_rate: Decimal | None = Field(default=None, gt=0, le=1)
    is_statutory: bool = False
    statutory_key: str | None = Field(default=None, max_length=50)
    status: str = Field(default="active", pattern=ACTIVE_STATUS)
    sort_order: int = 0

    @model_validator(mode="after")
    def _validate(self) -> SalaryComponentCreate:
        if self.is_statutory and not (self.statutory_key or "").strip():
            raise ValueError("statutory_key is required for statutory components")
        if self.calculation_basis == "fixed" and self.default_amount is None:
            raise ValueError("default_amount is required for fixed components")
        if (
            self.calculation_basis == "percent_of_basic"
            and self.default_rate is None
        ):
            raise ValueError("default_rate is required for percent_of_basic")
        return self


class SalaryComponentUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50)
    name_ar: str | None = Field(default=None, min_length=1, max_length=255)
    name_en: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    category: str | None = Field(default=None, pattern=COMPONENT_CATEGORY)
    calculation_basis: str | None = Field(default=None, pattern=COMPONENT_BASIS)
    default_amount: Decimal | None = Field(default=None, ge=0)
    default_rate: Decimal | None = Field(default=None, gt=0, le=1)
    is_statutory: bool | None = None
    statutory_key: str | None = Field(default=None, max_length=50)
    status: str | None = Field(default=None, pattern=ACTIVE_STATUS)
    sort_order: int | None = None


class SalaryComponentOut(BaseModel):
    id: int
    company_id: int
    code: str
    name_ar: str
    name_en: str
    description: str | None
    category: str
    calculation_basis: str
    default_amount: Decimal | None
    default_rate: Decimal | None
    is_statutory: bool
    statutory_key: str | None
    status: str
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SalaryComponentPage(BaseModel):
    items: list[SalaryComponentOut]
    page: Page


# ---------------------------------------------------------------------------
# Salary assignments (effective-dated history, payroll source of truth)
# ---------------------------------------------------------------------------


class SalaryAssignmentCreate(BaseModel):
    company_id: int = Field(ge=1)
    employee_id: int = Field(ge=1)
    effective_from: date
    effective_to: date | None = None
    basic_salary: Decimal = Field(ge=0)
    currency: str = Field(default="SAR", pattern=CURRENCY)
    reason: str | None = Field(default=None, max_length=500)


class SalaryAssignmentUpdate(BaseModel):
    basic_salary: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, pattern=CURRENCY)
    reason: str | None = Field(default=None, max_length=500)
    effective_to: date | None = None


class SalaryAssignmentOut(BaseModel):
    id: int
    company_id: int
    employee_id: int
    effective_from: date
    effective_to: date | None
    basic_salary: Decimal
    currency: str
    reason: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SalaryAssignmentPage(BaseModel):
    items: list[SalaryAssignmentOut]
    page: Page


class SeedAssignmentsOut(BaseModel):
    created: int
    skipped: int


# ---------------------------------------------------------------------------
# Payroll periods (single workflow source of truth)
# ---------------------------------------------------------------------------


class PayrollPeriodCreate(BaseModel):
    company_id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=100)
    period_start: date
    period_end: date
    currency: str = Field(default="SAR", pattern=CURRENCY)
    notes: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> PayrollPeriodCreate:
        if self.period_end < self.period_start:
            raise ValueError("period_end must not be before period_start")
        return self


class PayrollPeriodUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    notes: str | None = None


class PayrollPeriodOut(BaseModel):
    id: int
    company_id: int
    name: str
    period_start: date
    period_end: date
    currency: str
    status: str
    calculated_at: datetime | None
    calculated_by: int | None
    reviewed_at: datetime | None
    reviewed_by: int | None
    approved_at: datetime | None
    approved_by: int | None
    paid_at: datetime | None
    paid_by: int | None
    locked_at: datetime | None
    locked_by: int | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PayrollPeriodPage(BaseModel):
    items: list[PayrollPeriodOut]
    page: Page


# ---------------------------------------------------------------------------
# Payroll runs & payslips (run = calculation artifact)
# ---------------------------------------------------------------------------


class PayslipLineOut(BaseModel):
    id: int
    component_id: int | None
    line_type: str
    label_ar: str
    label_en: str
    unit: str
    quantity: Decimal | None
    rate: Decimal | None
    amount: Decimal
    sort_order: int

    model_config = {"from_attributes": True}


class PayrollRunLineOut(BaseModel):
    id: int
    run_id: int
    employee_id: int
    basic_snapshot: Decimal
    currency: str
    earnings_total: Decimal
    deductions_total: Decimal
    employer_total: Decimal
    net_pay: Decimal
    worked_minutes: int
    overtime_minutes: int
    paid_leave_days: Decimal
    unpaid_leave_days: Decimal
    absent_days: Decimal
    late_minutes: int
    warnings: list[dict[str, Any]] | None
    lines: list[PayslipLineOut] = []

    model_config = {"from_attributes": True}


class PayrollRunLinePage(BaseModel):
    items: list[PayrollRunLineOut]
    page: Page


class PayrollRunOut(BaseModel):
    id: int
    company_id: int
    period_id: int
    run_number: int
    status: str
    inputs_hash: str | None
    engine_version: str | None
    employee_count: int
    gross_total: Decimal
    deductions_total: Decimal
    employer_total: Decimal
    net_total: Decimal
    warnings: list[dict[str, Any]] | None
    calculated_at: datetime | None
    calculated_by: int | None
    created_at: datetime
    updated_at: datetime
    # Period workflow context lives on the period (single state machine).
    period_status: str | None = None
    period_start: date | None = None
    period_end: date | None = None

    model_config = {"from_attributes": True}


class PayrollRunPage(BaseModel):
    items: list[PayrollRunOut]
    page: Page


class PayslipOut(PayrollRunLineOut):
    run_status: str | None = None
    period_status: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    run_number: int | None = None
    inputs_hash: str | None = None


# ---------------------------------------------------------------------------
# Adjustments
# ---------------------------------------------------------------------------


class PayrollAdjustmentCreate(BaseModel):
    company_id: int = Field(ge=1)
    employee_id: int = Field(ge=1)
    period_id: int = Field(ge=1)
    original_run_id: int | None = Field(default=None, ge=1)
    component_id: int | None = Field(default=None, ge=1)
    amount: Decimal = Field(gt=0)
    direction: str = Field(pattern=ADJUSTMENT_DIRECTION)
    reason: str = Field(min_length=1)


class PayrollAdjustmentDecision(BaseModel):
    decision_reason: str | None = Field(default=None, max_length=500)


class PayrollAdjustmentOut(BaseModel):
    id: int
    company_id: int
    employee_id: int
    period_id: int
    original_run_id: int | None
    component_id: int | None
    amount: Decimal
    direction: str
    reason: str
    status: str
    requested_by: int | None
    decided_by: int | None
    decided_at: datetime | None
    decision_reason: str | None
    voided_by: int | None
    voided_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PayrollAdjustmentPage(BaseModel):
    items: list[PayrollAdjustmentOut]
    page: Page


# ---------------------------------------------------------------------------
# Deduction rules (recurring / installment)
# ---------------------------------------------------------------------------


class PayrollDeductionCreate(BaseModel):
    company_id: int = Field(ge=1)
    employee_id: int = Field(ge=1)
    component_id: int | None = Field(default=None, ge=1)
    name: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0)
    total_amount: Decimal | None = Field(default=None, gt=0)
    effective_from: date
    effective_to: date | None = None
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _validate(self) -> PayrollDeductionCreate:
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be after effective_from")
        if self.total_amount is not None and self.total_amount < self.amount:
            raise ValueError("total_amount must be >= amount")
        return self


class PayrollDeductionUpdate(BaseModel):
    amount: Decimal | None = Field(default=None, gt=0)
    effective_to: date | None = None
    status: str | None = Field(default=None, pattern=DEDUCTION_STATUS)
    reason: str | None = Field(default=None, max_length=500)


class PayrollDeductionOut(BaseModel):
    id: int
    company_id: int
    employee_id: int
    component_id: int | None
    name: str
    amount: Decimal
    total_amount: Decimal | None
    remaining_amount: Decimal | None
    effective_from: date
    effective_to: date | None
    status: str
    reason: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PayrollDeductionPage(BaseModel):
    items: list[PayrollDeductionOut]
    page: Page


# ---------------------------------------------------------------------------
# Statutory rules (framework - source_reference + effective dates mandatory)
# ---------------------------------------------------------------------------


class PayrollStatutoryRuleCreate(BaseModel):
    company_id: int = Field(ge=1)
    statutory_key: str = Field(min_length=1, max_length=50)
    effective_from: date
    effective_to: date | None = None
    rule_json: dict[str, Any] = Field(default_factory=dict)
    source_reference: str = Field(min_length=1, max_length=500)
    source_date: date | None = None
    requires_legal_verification: bool = True
    notes: str | None = Field(default=None, max_length=2000)


class PayrollStatutoryRuleOut(BaseModel):
    id: int
    company_id: int
    statutory_key: str
    jurisdiction: str
    version: int
    effective_from: date
    effective_to: date | None
    rule_json: dict[str, Any]
    source_reference: str
    source_date: date | None
    requires_legal_verification: bool
    notes: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PayrollStatutoryRulePage(BaseModel):
    items: list[PayrollStatutoryRuleOut]
    page: Page


class PayrollStatutoryRuleDeactivate(BaseModel):
    status: str = Field(default="inactive", pattern=RULE_STATUS)


# ---------------------------------------------------------------------------
# Accounting export contract (JSON only - no journal entries in Phase 6)
# ---------------------------------------------------------------------------


class AccountingExportLineOut(BaseModel):
    employee_id: int
    employee_number: str | None
    component_code: str | None
    line_type: str
    label_en: str
    amount: Decimal


class AccountingExportOut(BaseModel):
    schema_name: str
    engine_version: str | None
    inputs_hash: str | None
    company_id: int
    period_id: int
    period_start: date
    period_end: date
    currency: str
    status: str
    gross_total: Decimal
    deductions_total: Decimal
    employer_total: Decimal
    net_total: Decimal
    employee_count: int
    lines: list[AccountingExportLineOut]
