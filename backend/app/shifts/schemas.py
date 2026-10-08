from __future__ import annotations

from datetime import datetime, time

from pydantic import BaseModel, Field

from app.core.pagination import Page
from app.work_schedules.schemas import BreakIn, BreakOut


class ShiftCreate(BaseModel):
    company_id: int = Field(ge=1)
    code: str = Field(min_length=1, max_length=50)
    name_ar: str = Field(min_length=1, max_length=255)
    name_en: str = Field(min_length=1, max_length=255)
    start_time: time
    end_time: time
    status: str = Field(default="active", pattern="^(active|archived)$")
    notes: str | None = Field(default=None, max_length=500)
    breaks: list[BreakIn] = Field(default_factory=list)


class ShiftUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50)
    name_ar: str | None = Field(default=None, min_length=1, max_length=255)
    name_en: str | None = Field(default=None, min_length=1, max_length=255)
    start_time: time | None = None
    end_time: time | None = None
    status: str | None = Field(default=None, pattern="^(active|archived)$")
    notes: str | None = Field(default=None, max_length=500)
    breaks: list[BreakIn] | None = None


class ShiftOut(BaseModel):
    id: int
    company_id: int
    code: str
    name_ar: str
    name_en: str
    start_time: time
    end_time: time
    crosses_midnight: bool
    status: str
    notes: str | None
    created_by: int | None
    created_at: datetime
    updated_at: datetime
    breaks: list[BreakOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ShiftPage(BaseModel):
    items: list[ShiftOut]
    page: Page
