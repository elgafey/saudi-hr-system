from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.core.pagination import Page


class JobGradeCreate(BaseModel):
    company_id: int = Field(ge=1)
    code: str = Field(min_length=1, max_length=50)
    name_ar: str = Field(min_length=1, max_length=255)
    name_en: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    level: int = Field(ge=1, le=999)
    status: str = Field(default="active", pattern="^(active|inactive)$")


class JobGradeUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50)
    name_ar: str | None = Field(default=None, min_length=1, max_length=255)
    name_en: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    level: int | None = Field(default=None, ge=1, le=999)
    status: str | None = Field(default=None, pattern="^(active|inactive)$")


class JobGradeOut(BaseModel):
    id: int
    company_id: int
    code: str
    name_ar: str
    name_en: str
    description: str | None
    level: int
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobGradePage(BaseModel):
    items: list[JobGradeOut]
    page: Page
