from __future__ import annotations

from pydantic import BaseModel, Field


class RoleCreate(BaseModel):
    company_id: int
    code: str = Field(min_length=2, max_length=50, pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=2, max_length=150)
    description: str | None = Field(default=None, max_length=500)


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    description: str | None = Field(default=None, max_length=500)


class RoleOut(BaseModel):
    id: int
    company_id: int
    code: str
    name: str
    description: str | None

    model_config = {"from_attributes": True}


class RolePermissionUpdate(BaseModel):
    permission_codes: list[str] = Field(default_factory=list)


class RolePermissionOut(BaseModel):
    role_id: int
    permission_codes: list[str]


class PermissionOut(BaseModel):
    id: int
    code: str
    name: str
    module: str

    model_config = {"from_attributes": True}
