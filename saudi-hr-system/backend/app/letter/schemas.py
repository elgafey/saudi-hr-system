"""Phase 9 HR letter schemas (closed payloads - server-assembled content).

The client NEVER supplies or edits ``content``: letter bodies are assembled
server-side from frozen source records (employee, contract, salary
assignment, company) and validated against the closed per-type models below
(``extra="forbid"``). Four letter types: employment, salary, experience,
work_address; languages ar|en. Reference ``LTR-000123`` is derived from the
row id (no column).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.pagination import Page

LetterType = Literal["employment", "salary", "experience", "work_address"]
LetterLanguage = Literal["ar", "en"]
LetterStatus = Literal["draft", "issued", "void", "cancelled"]


# ---------------------------------------------------------------------------
# Closed content snapshots (server-assembled only)
# ---------------------------------------------------------------------------


class _LetterContentBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: str
    company_cr: str | None = None
    company_address: str | None = None
    company_city: str | None = None
    employee_name: str
    employee_number: str
    identity_number: str | None = None
    position: str | None = None
    department: str | None = None
    branch: str | None = None
    employment_type: str
    hire_date: date | None = None


class LetterContentEmployment(_LetterContentBase):
    employment_status: str
    contract_number: str | None = None
    contract_start_date: date | None = None
    contract_end_date: date | None = None


class LetterContentSalary(_LetterContentBase):
    basic_salary: Decimal = Field(max_digits=12, decimal_places=2)
    currency: str = Field(min_length=3, max_length=3)
    salary_effective_from: date


class LetterContentExperience(_LetterContentBase):
    employment_status: str
    contract_start_date: date | None = None


class LetterContentWorkAddress(_LetterContentBase):
    branch_address: str | None = None
    branch_city: str | None = None


CONTENT_MODELS: dict[str, type[_LetterContentBase]] = {
    "employment": LetterContentEmployment,
    "salary": LetterContentSalary,
    "experience": LetterContentExperience,
    "work_address": LetterContentWorkAddress,
}


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class LetterCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_id: int = Field(ge=1)
    letter_type: LetterType
    language: LetterLanguage = "ar"
    purpose: str | None = Field(default=None, max_length=500)
    # Optional Phase 7 approved hr_letter request this letter fulfils; at
    # most one ACTIVE (draft|issued) letter may reference a given request.
    source_request_id: int | None = Field(default=None, ge=1)


class LetterUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: str | None = Field(default=None, max_length=500)
    language: LetterLanguage | None = None


class LetterCancel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


class LetterVoid(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Optional here, REQUIRED in the service: voiding an issued letter is
    # audit-sensitive (HR_LETTER_REASON_REQUIRED, 400 - Phase 8 pattern:
    # closed optional payload field, service-level enforcement).
    reason: str | None = Field(default=None, max_length=500)


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class LetterEventOut(BaseModel):
    id: int
    action: str
    from_status: str | None
    to_status: str
    actor_name: str
    note: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class LetterListOut(BaseModel):
    """List projection: content and reason fields are intentionally absent
    (no salary leak through list responses)."""

    id: int
    reference: str
    company_id: int
    employee_id: int
    letter_type: str
    language: str
    purpose: str | None
    status: str
    source_request_id: int | None
    issued_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LetterOut(LetterListOut):
    """Detail projection: includes the frozen content snapshot."""

    content: dict
    issued_by: int | None
    cancelled_at: datetime | None
    cancelled_by: int | None
    cancel_reason: str | None
    voided_at: datetime | None
    voided_by: int | None
    void_reason: str | None
    created_by: int | None
    updated_by: int | None
    version: int
    events: list[LetterEventOut] = []

    model_config = {"from_attributes": True}


class LetterPage(BaseModel):
    items: list[LetterListOut]
    page: Page
