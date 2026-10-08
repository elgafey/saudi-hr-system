from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.core.pagination import Page
from app.employees.numbering import EMPLOYEE_NUMBER_PATTERN


class EmployeeCreate(BaseModel):
    company_id: int = Field(ge=1)
    employee_number: str | None = Field(
        default=None, min_length=2, max_length=50,
        pattern=EMPLOYEE_NUMBER_PATTERN,
    )
    first_name_ar: str = Field(min_length=1, max_length=100)
    middle_name_ar: str | None = Field(default=None, max_length=100)
    last_name_ar: str = Field(min_length=1, max_length=100)
    first_name_en: str = Field(min_length=1, max_length=100)
    middle_name_en: str | None = Field(default=None, max_length=100)
    last_name_en: str = Field(min_length=1, max_length=100)
    date_of_birth: date | None = None
    gender: str | None = Field(default=None, pattern="^(male|female)$")
    nationality: str = Field(default="SA", pattern="^[A-Z]{2}$")
    personal_email: EmailStr | None = None
    work_email: EmailStr | None = None
    mobile_phone: str | None = Field(default=None, max_length=32)
    emergency_contact_name: str | None = Field(default=None, max_length=255)
    emergency_contact_phone: str | None = Field(default=None, max_length=32)
    identity_type: str | None = Field(
        default=None, pattern="^(national_id|iqama|passport)$"
    )
    identity_number: str | None = Field(default=None, max_length=50)
    identity_issue_date: date | None = None
    identity_expiry_date: date | None = None
    branch_id: int | None = Field(default=None, ge=1)
    department_id: int | None = Field(default=None, ge=1)
    job_position_id: int | None = Field(default=None, ge=1)
    job_grade_id: int | None = Field(default=None, ge=1)
    manager_id: int | None = Field(default=None, ge=1)
    status: str = Field(
        default="draft", pattern="^(draft|active|suspended|terminated)$"
    )
    employment_type: str = Field(
        default="full_time", pattern="^(full_time|part_time|temporary|intern)$"
    )
    hire_date: date | None = None
    probation_end_date: date | None = None
    termination_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _check_identity_and_dates(self) -> "EmployeeCreate":
        if self.identity_number and not self.identity_type:
            raise ValueError(
                "identity_type is required when identity_number is provided"
            )
        if (
            self.identity_issue_date
            and self.identity_expiry_date
            and self.identity_expiry_date < self.identity_issue_date
        ):
            raise ValueError(
                "identity_expiry_date must be on or after identity_issue_date"
            )
        return self


class EmployeeUpdate(BaseModel):
    employee_number: str | None = Field(
        default=None, min_length=2, max_length=50,
        pattern=EMPLOYEE_NUMBER_PATTERN,
    )
    first_name_ar: str | None = Field(default=None, min_length=1, max_length=100)
    middle_name_ar: str | None = Field(default=None, max_length=100)
    last_name_ar: str | None = Field(default=None, min_length=1, max_length=100)
    first_name_en: str | None = Field(default=None, min_length=1, max_length=100)
    middle_name_en: str | None = Field(default=None, max_length=100)
    last_name_en: str | None = Field(default=None, min_length=1, max_length=100)
    date_of_birth: date | None = None
    gender: str | None = Field(default=None, pattern="^(male|female)$")
    nationality: str | None = Field(default=None, pattern="^[A-Z]{2}$")
    personal_email: EmailStr | None = None
    work_email: EmailStr | None = None
    mobile_phone: str | None = Field(default=None, max_length=32)
    emergency_contact_name: str | None = Field(default=None, max_length=255)
    emergency_contact_phone: str | None = Field(default=None, max_length=32)
    identity_type: str | None = Field(
        default=None, pattern="^(national_id|iqama|passport)$"
    )
    identity_number: str | None = Field(default=None, max_length=50)
    identity_issue_date: date | None = None
    identity_expiry_date: date | None = None
    branch_id: int | None = Field(default=None, ge=1)
    department_id: int | None = Field(default=None, ge=1)
    job_position_id: int | None = Field(default=None, ge=1)
    job_grade_id: int | None = Field(default=None, ge=1)
    manager_id: int | None = Field(default=None, ge=1)
    status: str | None = Field(
        default=None, pattern="^(draft|active|suspended|terminated)$"
    )
    employment_type: str | None = Field(
        default=None, pattern="^(full_time|part_time|temporary|intern)$"
    )
    hire_date: date | None = None
    probation_end_date: date | None = None
    termination_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _check_dates(self) -> "EmployeeUpdate":
        # Identity pairing: sending a number requires sending the type in the
        # same request (the merged record is re-checked by the service).
        if (
            self.identity_number
            and "identity_type" not in self.model_fields_set
        ):
            raise ValueError(
                "identity_type is required when identity_number is provided"
            )
        if (
            self.identity_issue_date
            and self.identity_expiry_date
            and self.identity_expiry_date < self.identity_issue_date
        ):
            raise ValueError(
                "identity_expiry_date must be on or after identity_issue_date"
            )
        return self


class EmployeeOut(BaseModel):
    id: int
    company_id: int
    branch_id: int | None
    department_id: int | None
    job_position_id: int | None
    job_grade_id: int | None
    manager_id: int | None
    employee_number: str
    first_name_ar: str
    middle_name_ar: str | None
    last_name_ar: str
    first_name_en: str
    middle_name_en: str | None
    last_name_en: str
    date_of_birth: date | None
    gender: str | None
    nationality: str
    personal_email: str | None
    work_email: str | None
    mobile_phone: str | None
    emergency_contact_name: str | None
    emergency_contact_phone: str | None
    identity_type: str | None
    identity_number: str | None
    identity_issue_date: date | None
    identity_expiry_date: date | None
    status: str
    employment_type: str
    hire_date: date | None
    probation_end_date: date | None
    termination_date: date | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EmployeePage(BaseModel):
    items: list[EmployeeOut]
    page: Page


class UserLinkIn(BaseModel):
    user_id: int = Field(ge=1)


class LinkedUserOut(BaseModel):
    id: int
    email: str
    full_name: str
    is_active: bool

    model_config = {"from_attributes": True}


class EmployeeUserLinkOut(BaseModel):
    linked: bool
    user: LinkedUserOut | None
