from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.core.pagination import Page

CONTRACT_TYPE_PATTERN = "^[a-z][a-z0-9_]{1,29}$"
CONTRACT_STATUS_PATTERN = "^(draft|active|expired|terminated|cancelled)$"


class ContractCreate(BaseModel):
    company_id: int = Field(ge=1)
    contract_type: str = Field(min_length=2, max_length=30, pattern=CONTRACT_TYPE_PATTERN)
    status: str = Field(default="draft", pattern=CONTRACT_STATUS_PATTERN)
    contract_number: str | None = Field(default=None, min_length=1, max_length=50)
    start_date: date
    end_date: date | None = None
    signed_date: date | None = None
    termination_date: date | None = None
    termination_reason: str | None = Field(default=None, max_length=500)
    notes: str | None = None
    basic_salary: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="SAR", pattern="^[A-Z]{3}$")


class ContractUpdate(BaseModel):
    contract_type: str | None = Field(
        default=None, min_length=2, max_length=30, pattern=CONTRACT_TYPE_PATTERN
    )
    status: str | None = Field(default=None, pattern=CONTRACT_STATUS_PATTERN)
    contract_number: str | None = Field(default=None, min_length=1, max_length=50)
    start_date: date | None = None
    end_date: date | None = None
    signed_date: date | None = None
    termination_date: date | None = None
    termination_reason: str | None = Field(default=None, max_length=500)
    notes: str | None = None
    basic_salary: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, pattern="^[A-Z]{3}$")


class ContractOut(BaseModel):
    id: int
    company_id: int
    employee_id: int
    contract_type: str
    status: str
    contract_number: str | None
    start_date: date
    end_date: date | None
    signed_date: date | None
    termination_date: date | None
    termination_reason: str | None
    notes: str | None
    basic_salary: Decimal | None
    currency: str
    created_by: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ContractPage(BaseModel):
    items: list[ContractOut]
    page: Page
