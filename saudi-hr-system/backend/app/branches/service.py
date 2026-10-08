from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.branches.schemas import BranchCreate, BranchUpdate
from app.core.deps import Principal
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.shared.models import Branch


def _require(principal: Principal, code: str, company_id: int | None) -> None:
    """Company-scoped permission check (H1)."""
    if not principal.has_permission(code, company_id):
        raise ForbiddenError(f"Missing permission: {code}")


def list_branches(
    db: Session, principal: Principal, company_id: int | None = None
) -> list[Branch]:
    stmt = select(Branch).order_by(Branch.id)
    if company_id is not None:
        if not principal.can_access_company(company_id):
            raise ForbiddenError("You cannot access this company")
        _require(principal, "branch.read", company_id)
        stmt = stmt.where(Branch.company_id == company_id)
    elif not principal.is_platform_admin:
        allowed = principal.permitted_company_ids("branch.read")
        if not allowed:
            return []
        stmt = stmt.where(Branch.company_id.in_(allowed))
    return list(db.execute(stmt).scalars())


def get_branch(db: Session, branch_id: int, principal: Principal) -> Branch:
    branch = db.get(Branch, branch_id)
    if branch is None or not principal.can_access_company(branch.company_id):
        raise NotFoundError("Branch not found")
    _require(principal, "branch.read", branch.company_id)
    return branch


def create_branch(
    db: Session, *, payload: BranchCreate, principal: Principal, ip: str | None
) -> Branch:
    if not principal.can_access_company(payload.company_id):
        raise ForbiddenError("You cannot create branches in this company")
    _require(principal, "branch.create", payload.company_id)
    exists = db.execute(
        select(Branch).where(
            Branch.company_id == payload.company_id, Branch.code == payload.code
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise ConflictError("Branch code already exists in this company")
    branch = Branch(**payload.model_dump())
    db.add(branch)
    db.flush()
    record_audit(
        db,
        action="branch.create",
        entity="branch",
        record_id=branch.id,
        actor_user_id=principal.user_id,
        company_id=payload.company_id,
        new_value=payload.model_dump(),
        ip_address=ip,
    )
    db.flush()
    return branch


def update_branch(
    db: Session,
    *,
    branch: Branch,
    payload: BranchUpdate,
    principal: Principal,
    ip: str | None,
) -> Branch:
    if not principal.can_access_company(branch.company_id):
        raise ForbiddenError("You cannot modify this branch")
    _require(principal, "branch.update", branch.company_id)
    changes = payload.model_dump(exclude_unset=True)
    if "code" in changes and changes["code"] != branch.code:
        exists = db.execute(
            select(Branch).where(
                Branch.company_id == branch.company_id,
                Branch.code == changes["code"],
            )
        ).scalar_one_or_none()
        if exists is not None:
            raise ConflictError("Branch code already exists in this company")
    old = {k: getattr(branch, k) for k in changes}
    for key, value in changes.items():
        setattr(branch, key, value)
    db.add(branch)
    record_audit(
        db,
        action="branch.update",
        entity="branch",
        record_id=branch.id,
        actor_user_id=principal.user_id,
        company_id=branch.company_id,
        old_value=old,
        new_value=changes,
        ip_address=ip,
    )
    db.flush()
    return branch
