from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.core.pagination import Page

ATTENDANCE_STATUS = "^(open|completed|missing_checkout)$"
ATTENDANCE_SOURCE = "^(manual|device|import|api)$"


class AttendanceCreate(BaseModel):
    employee_id: int = Field(ge=1)
    check_in: datetime
    check_out: datetime | None = None
    status: str | None = Field(default=None, pattern=ATTENDANCE_STATUS)
    source: str = Field(default="manual", pattern=ATTENDANCE_SOURCE)
    notes: str | None = Field(default=None, max_length=500)


class AttendanceCheckIn(BaseModel):
    employee_id: int = Field(ge=1)
    at: datetime | None = None
    source: str = Field(default="api", pattern=ATTENDANCE_SOURCE)
    notes: str | None = Field(default=None, max_length=500)


class AttendanceCheckOut(BaseModel):
    employee_id: int = Field(ge=1)
    at: datetime | None = None


class AttendanceUpdate(BaseModel):
    check_in: datetime | None = None
    check_out: datetime | None = None
    status: str | None = Field(default=None, pattern=ATTENDANCE_STATUS)
    source: str | None = Field(default=None, pattern=ATTENDANCE_SOURCE)
    notes: str | None = Field(default=None, max_length=500)
    reason: str | None = Field(default=None, max_length=500)


class AttendanceOut(BaseModel):
    id: int
    company_id: int
    employee_id: int
    work_date: date
    schedule_id: int | None
    shift_id: int | None
    check_in: datetime
    check_out: datetime | None
    status: str
    source: str
    scheduled_minutes: int | None
    worked_minutes: int | None
    break_minutes: int | None
    late_minutes: int | None
    early_leave_minutes: int | None
    overtime_candidate_minutes: int | None
    notes: str | None
    correction_reason: str | None
    corrected_by: int | None
    corrected_at: datetime | None
    closed_by: int | None
    created_by: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AttendancePage(BaseModel):
    items: list[AttendanceOut]
    page: Page
