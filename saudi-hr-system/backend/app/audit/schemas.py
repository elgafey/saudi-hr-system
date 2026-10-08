from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.core.pagination import Page


class AuditLogOut(BaseModel):
    id: int
    company_id: int | None
    actor_user_id: int | None
    action: str
    entity: str
    record_id: str
    old_value: str | None
    new_value: str | None
    ip_address: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditPage(BaseModel):
    items: list[AuditLogOut]
    page: Page
