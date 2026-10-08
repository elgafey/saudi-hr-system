from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.core.pagination import Page

_date_type = date

LEAVE_TYPE_STATUS = "^(active|inactive)$"
DAY_COUNTING_MODE = "^(working_days|calendar_days)$"
ALLOWANCE_TREATMENT = "^(continue|deduct|prorate)$"
CARRY_FORWARD_EXPIRY = "^(none|end_of_year|end_of_next_year)$"
ALLOCATION_STATUS = "^(submitted|approved|rejected|revoked)$"
ALLOCATION_SOURCE = "^(manual|generate|carry_forward|statutory)$"
REQUEST_STATUS = "^(draft|submitted|approved|rejected|cancelled)$"
HOLIDAY_STATUS = "^(active|inactive)$"
RULE_STATUS = "^(active|inactive)$"


# ---------------------------------------------------------------------------
# Leave types
# ---------------------------------------------------------------------------


class LeaveTypeCreate(BaseModel):
    company_id: int = Field(ge=1)
    code: str = Field(min_length=1, max_length=50)
    name_ar: str = Field(min_length=1, max_length=255)
    name_en: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    is_paid: bool = True
    requires_approval: bool = True
    allocation_requires_approval: bool = False
    day_counting_mode: str = Field(
        default="working_days", pattern=DAY_COUNTING_MODE
    )
    requires_attachment: bool = False
    attachment_threshold_days: Decimal | None = Field(default=None, gt=0)
    requires_reason: bool = False
    negative_balance_allowed: bool = False
    min_request_days: Decimal | None = Field(default=None, gt=0)
    max_request_days: Decimal | None = Field(default=None, gt=0)
    default_entitlement_days: Decimal | None = Field(default=None, ge=0)
    carry_forward_enabled: bool = False
    carry_forward_max_days: Decimal | None = Field(default=None, ge=0)
    carry_forward_expiry: str = Field(
        default="end_of_next_year", pattern=CARRY_FORWARD_EXPIRY
    )
    allowance_treatment: str = Field(
        default="continue", pattern=ALLOWANCE_TREATMENT
    )
    is_statutory: bool = False
    statutory_key: str | None = Field(default=None, max_length=50)
    status: str = Field(default="active", pattern=LEAVE_TYPE_STATUS)
    sort_order: int = 0


class LeaveTypeUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50)
    name_ar: str | None = Field(default=None, min_length=1, max_length=255)
    name_en: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    is_paid: bool | None = None
    requires_approval: bool | None = None
    allocation_requires_approval: bool | None = None
    day_counting_mode: str | None = Field(default=None, pattern=DAY_COUNTING_MODE)
    requires_attachment: bool | None = None
    attachment_threshold_days: Decimal | None = Field(default=None, gt=0)
    requires_reason: bool | None = None
    negative_balance_allowed: bool | None = None
    min_request_days: Decimal | None = Field(default=None, gt=0)
    max_request_days: Decimal | None = Field(default=None, gt=0)
    default_entitlement_days: Decimal | None = Field(default=None, ge=0)
    carry_forward_enabled: bool | None = None
    carry_forward_max_days: Decimal | None = Field(default=None, ge=0)
    carry_forward_expiry: str | None = Field(
        default=None, pattern=CARRY_FORWARD_EXPIRY
    )
    allowance_treatment: str | None = Field(
        default=None, pattern=ALLOWANCE_TREATMENT
    )
    is_statutory: bool | None = None
    statutory_key: str | None = Field(default=None, max_length=50)
    status: str | None = Field(default=None, pattern=LEAVE_TYPE_STATUS)
    sort_order: int | None = None


class LeaveTypeOut(BaseModel):
    id: int
    company_id: int
    code: str
    name_ar: str
    name_en: str
    description: str | None
    is_paid: bool
    requires_approval: bool
    allocation_requires_approval: bool
    day_counting_mode: str
    requires_attachment: bool
    attachment_threshold_days: Decimal | None
    requires_reason: bool
    negative_balance_allowed: bool
    min_request_days: Decimal | None
    max_request_days: Decimal | None
    default_entitlement_days: Decimal | None
    carry_forward_enabled: bool
    carry_forward_max_days: Decimal | None
    carry_forward_expiry: str
    allowance_treatment: str
    is_statutory: bool
    statutory_key: str | None
    status: str
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LeaveTypePage(BaseModel):
    items: list[LeaveTypeOut]
    page: Page


# ---------------------------------------------------------------------------
# Statutory rules (versioned, source + effective date REQUIRED)
# ---------------------------------------------------------------------------


class StatutoryRuleCreate(BaseModel):
    company_id: int = Field(ge=1)
    statutory_key: str = Field(min_length=1, max_length=50)
    effective_from: date
    effective_to: date | None = None
    rule_json: dict[str, Any] = Field(default_factory=dict)
    # DB CHECK also enforces non-empty: a citation/URL/internal policy ref.
    source_reference: str = Field(min_length=1, max_length=500)
    source_date: date | None = None
    requires_legal_verification: bool = True
    notes: str | None = Field(default=None, max_length=2000)


class StatutoryRuleOut(BaseModel):
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


class StatutoryRulePage(BaseModel):
    items: list[StatutoryRuleOut]
    page: Page


class StatutoryRuleDeactivate(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


# ---------------------------------------------------------------------------
# Allocations
# ---------------------------------------------------------------------------


class LeaveAllocationCreate(BaseModel):
    employee_id: int = Field(ge=1)
    leave_type_id: int = Field(ge=1)
    period_start: date
    period_end: date
    allocated_days: Decimal = Field(gt=0)
    source: str = Field(default="manual", pattern=ALLOCATION_SOURCE)
    reason: str | None = Field(default=None, max_length=2000)


class LeaveAllocationUpdate(BaseModel):
    period_start: date | None = None
    period_end: date | None = None
    allocated_days: Decimal | None = Field(default=None, gt=0)
    reason: str | None = Field(default=None, max_length=2000)


class LeaveAllocationGenerate(BaseModel):
    leave_type_id: int = Field(ge=1)
    period_start: date
    period_end: date
    allocated_days: Decimal | None = Field(default=None, gt=0)
    employee_ids: list[int] | None = None


class LeaveAllocationDecision(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class CarryForward(BaseModel):
    company_id: int = Field(ge=1)
    period_start: date
    period_end: date


class LeaveAllocationOut(BaseModel):
    id: int
    company_id: int
    employee_id: int
    leave_type_id: int
    period_start: date
    period_end: date
    allocated_days: Decimal
    used_days: Decimal
    source: str
    carried_from_id: int | None
    status: str
    reason: str | None
    decision_reason: str | None
    approved_by: int | None
    approved_at: datetime | None
    rejected_by: int | None
    rejected_at: datetime | None
    created_by: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LeaveAllocationPage(BaseModel):
    items: list[LeaveAllocationOut]
    page: Page


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class LeaveRequestCreate(BaseModel):
    employee_id: int = Field(ge=1)
    leave_type_id: int = Field(ge=1)
    start_date: date
    end_date: date
    start_time: time | None = None
    end_time: time | None = None
    reason: str | None = Field(default=None, max_length=2000)


class LeaveRequestUpdate(BaseModel):
    leave_type_id: int | None = Field(default=None, ge=1)
    start_date: date | None = None
    end_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    reason: str | None = Field(default=None, max_length=2000)


class LeaveRequestDecision(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class LeaveRequestPreview(BaseModel):
    employee_id: int = Field(ge=1)
    leave_type_id: int = Field(ge=1)
    start_date: date
    end_date: date
    start_time: time | None = None
    end_time: time | None = None
    exclude_request_id: int | None = Field(default=None, ge=1)


class BalanceOut(BaseModel):
    leave_type_id: int
    code: str
    name_ar: str
    name_en: str
    is_paid: bool
    allocated_days: Decimal
    used_days: Decimal
    pending_days: Decimal
    remaining_days: Decimal
    negative_balance_allowed: bool


class LeaveRequestPreviewOut(BaseModel):
    days: Decimal
    day_counting_mode: str
    count_details: dict[str, Any]
    balance: BalanceOut | None
    would_be_negative: bool
    has_open_attendance_conflict: bool
    has_approved_overtime_conflict: bool


class LeaveRequestOut(BaseModel):
    id: int
    company_id: int
    employee_id: int
    leave_type_id: int
    start_date: date
    end_date: date
    start_time: time | None
    end_time: time | None
    days: Decimal
    reason: str | None
    attachment_name: str | None
    attachment_mime: str | None
    attachment_size: int | None
    status: str
    count_details: dict[str, Any] | None
    submitted_by: int | None
    submitted_at: datetime | None
    decided_by: int | None
    decided_at: datetime | None
    decision_reason: str | None
    cancelled_by: int | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    created_by: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LeaveRequestPage(BaseModel):
    items: list[LeaveRequestOut]
    page: Page


# ---------------------------------------------------------------------------
# Balances
# ---------------------------------------------------------------------------


class LeaveBalancesPage(BaseModel):
    items: list[BalanceOut]


# ---------------------------------------------------------------------------
# Company holidays (D1: dedicated company-scoped table)
# ---------------------------------------------------------------------------


class HolidayCreate(BaseModel):
    company_id: int = Field(ge=1)
    date: date
    name_ar: str = Field(min_length=1, max_length=255)
    name_en: str = Field(min_length=1, max_length=255)
    status: str = Field(default="active", pattern=HOLIDAY_STATUS)
    notes: str | None = Field(default=None, max_length=1000)


class HolidayUpdate(BaseModel):
    date: _date_type | None = None
    name_ar: str | None = Field(default=None, min_length=1, max_length=255)
    name_en: str | None = Field(default=None, min_length=1, max_length=255)
    status: str | None = Field(default=None, pattern=HOLIDAY_STATUS)
    notes: str | None = Field(default=None, max_length=1000)


class HolidayOut(BaseModel):
    id: int
    company_id: int
    date: date
    name_ar: str
    name_en: str
    status: str
    notes: str | None
    created_by: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class HolidayPage(BaseModel):
    items: list[HolidayOut]
    page: Page
