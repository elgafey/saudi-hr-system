from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.audit.model import AuditLog


def _serialize(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)


def record_audit(
    db: Session,
    *,
    action: str,
    entity: str,
    record_id: Any,
    actor_user_id: int | None = None,
    company_id: int | None = None,
    old_value: Any = None,
    new_value: Any = None,
    ip_address: str | None = None,
) -> AuditLog:
    """Append an audit entry. Never raises on serialization problems."""
    entry = AuditLog(
        company_id=company_id,
        actor_user_id=actor_user_id,
        action=action,
        entity=entity,
        record_id=str(record_id),
        old_value=_serialize(old_value),
        new_value=_serialize(new_value),
        ip_address=ip_address,
    )
    db.add(entry)
    db.flush()
    return entry
