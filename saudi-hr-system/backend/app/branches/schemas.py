from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class BranchCreate(BaseModel):
    company_id: int
    name: str = Field(min_length=2, max_length=255)
    name_ar: str | None = Field(default=None, max_length=255)
    code: str = Field(min_length=1, max_length=50)
    address: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, max_length=128)
    status: str = Field(default="active", pattern="^(active|inactive)$")


class BranchUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    name_ar: str | None = Field(default=None, max_length=255)
    code: str | None = Field(default=None, min_length=1, max_length=50)
    address: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, max_length=128)
    status: str | None = Field(default=None, pattern="^(active|inactive)$")


class BranchOut(BaseModel):
    id: int
    company_id: int
    name: str
    name_ar: str | None
    code: str
    address: str | None
    city: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
