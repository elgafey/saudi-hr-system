from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CompanyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    name_ar: str | None = Field(default=None, max_length=255)
    name_en: str | None = Field(default=None, max_length=255)
    commercial_registration_number: str | None = Field(default=None, max_length=64)
    tax_number: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, max_length=128)
    country: str = Field(default="SA", min_length=2, max_length=2)
    default_currency: str = Field(default="SAR", min_length=3, max_length=3)
    timezone: str = Field(default="Asia/Riyadh", max_length=64)
    working_week: str = Field(default="sun-thu", max_length=64)


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    name_ar: str | None = Field(default=None, max_length=255)
    name_en: str | None = Field(default=None, max_length=255)
    commercial_registration_number: str | None = Field(default=None, max_length=64)
    tax_number: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, max_length=128)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    default_currency: str | None = Field(default=None, min_length=3, max_length=3)
    timezone: str | None = Field(default=None, max_length=64)
    working_week: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default=None, pattern="^(active|suspended)$")


class CompanyOut(BaseModel):
    id: int
    name: str
    name_ar: str | None
    name_en: str | None
    commercial_registration_number: str | None
    tax_number: str | None
    address: str | None
    city: str | None
    country: str
    default_currency: str
    timezone: str
    working_week: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
