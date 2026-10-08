from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.audit.model import AuditLog
from app.audit.schemas import AuditLogOut, AuditPage
from app.core.database import get_db
from app.core.deps import Principal, require_permission
from app.core.exceptions import ForbiddenError
from app.core.pagination import Page, PageParams, pagination_params

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("", response_model=AuditPage)
def list_audit_logs(
    company_id: int | None = Query(default=None, ge=1),
    entity: str | None = Query(default=None, max_length=100),
    action: str | None = Query(default=None, max_length=100),
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(require_permission("audit.read")),
    db: Session = Depends(get_db),
) -> AuditPage:
    if company_id is not None and not principal.can_access_company(company_id):
        raise ForbiddenError("You cannot access this company")
    if company_id is not None and not principal.has_permission(
        "audit.read", company_id
    ):
        raise ForbiddenError("Missing permission: audit.read")

    stmt = select(AuditLog)
    count_stmt = select(func.count()).select_from(AuditLog)
    if company_id is not None:
        stmt = stmt.where(AuditLog.company_id == company_id)
        count_stmt = count_stmt.where(AuditLog.company_id == company_id)
    elif not principal.is_platform_admin:
        # Company-scoped permissions (H1): only surface audit rows for
        # companies where audit.read is actually granted; own actor rows
        # (e.g. own failed logins) remain visible.
        allowed = principal.permitted_company_ids("audit.read")
        scope = or_(
            AuditLog.company_id.in_(allowed),
            AuditLog.actor_user_id == principal.user_id,
        )
        stmt = stmt.where(scope)
        count_stmt = count_stmt.where(scope)
    if entity is not None:
        stmt = stmt.where(AuditLog.entity == entity)
        count_stmt = count_stmt.where(AuditLog.entity == entity)
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
        count_stmt = count_stmt.where(AuditLog.action == action)

    total = int(db.execute(count_stmt).scalar_one())
    rows = (
        db.execute(
            stmt.order_by(AuditLog.id.desc())
            .limit(page_params.limit)
            .offset(page_params.offset)
        )
        .scalars()
        .all()
    )
    return AuditPage(
        items=[AuditLogOut.model_validate(r) for r in rows],
        page=Page(
            page=page_params.page, page_size=page_params.page_size, total=total
        ),
    )
