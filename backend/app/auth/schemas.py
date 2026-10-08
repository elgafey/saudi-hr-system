from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserSummary(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    is_platform_admin: bool
    company_id: int | None
    employee_id: int | None

    model_config = {"from_attributes": True}


class MeResponse(BaseModel):
    user: UserSummary
    company_ids: list[int]
    permissions: list[str]


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
