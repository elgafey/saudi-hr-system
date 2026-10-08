from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    company_id: int
    is_active: bool = True
    role_ids: list[int] = Field(default_factory=list)


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=255)
    is_active: bool | None = None
    company_id: int | None = None
    is_platform_admin: bool | None = None


class RoleAssignment(BaseModel):
    role_ids: list[int] = Field(default_factory=list)


class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    is_active: bool
    is_platform_admin: bool
    company_id: int | None
    employee_id: int | None
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserRoleOut(BaseModel):
    role_id: int
    company_id: int
    code: str
    name: str


class UserDetailOut(UserOut):
    roles: list[UserRoleOut] = Field(default_factory=list)
