from __future__ import annotations

from datetime import date, datetime, time

from pydantic import BaseModel, Field

from app.core.pagination import Page


class BreakIn(BaseModel):
    start_time: time
    end_time: time
    is_paid: bool = True


class BreakOut(BaseModel):
    id: int
    start_time: time
    end_time: time
    is_paid: bool

    model_config = {"from_attributes": True}


class ScheduleCreate(BaseModel):
    company_id: int = Field(ge=1)
    code: str = Field(min_length=1, max_length=50)
    name_ar: str = Field(min_length=1, max_length=255)
    name_en: str = Field(min_length=1, max_length=255)
    timezone: str = Field(default="Asia/Riyadh", min_length=1, max_length=64)
    effective_from: date
    effective_to: date | None = None
    status: str = Field(default="active", pattern="^(active|archived)$")
    notes: str | None = Field(default=None, max_length=500)


class ScheduleUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50)
    name_ar: str | None = Field(default=None, min_length=1, max_length=255)
    name_en: str | None = Field(default=None, min_length=1, max_length=255)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    effective_from: date | None = None
    effective_to: date | None = None
    status: str | None = Field(default=None, pattern="^(active|archived)$")
    notes: str | None = Field(default=None, max_length=500)


class ScheduleOut(BaseModel):
    id: int
    company_id: int
    code: str
    name_ar: str
    name_en: str
    timezone: str
    effective_from: date
    effective_to: date | None
    status: str
    notes: str | None
    created_by: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DayIn(BaseModel):
    weekday: int = Field(ge=0, le=6)
    is_working: bool = True
    start_time: time | None = None
    end_time: time | None = None
    shift_id: int | None = Field(default=None, ge=1)
    breaks: list[BreakIn] = Field(default_factory=list)


class DayOut(BaseModel):
    id: int
    schedule_id: int
    weekday: int
    is_working: bool
    start_time: time | None
    end_time: time | None
    shift_id: int | None
    breaks: list[BreakOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ScheduleDaysPut(BaseModel):
    days: list[DayIn] = Field(min_length=1, max_length=7)


class ScheduleDaysOut(BaseModel):
    items: list[DayOut]


class ResolvedScheduleOut(BaseModel):
    date: date
    weekday: int
    is_working: bool
    timezone: str
    crosses_midnight: bool
    assignment_id: int | None
    schedule_id: int | None
    schedule_code: str | None
    schedule_name_en: str | None
    schedule_name_ar: str | None
    shift_id: int | None
    shift_code: str | None
    shift_name_en: str | None
    start_time: time | None
    end_time: time | None
    breaks: list[BreakOut] = Field(default_factory=list)


class SchedulePage(BaseModel):
    items: list[ScheduleOut]
    page: Page
