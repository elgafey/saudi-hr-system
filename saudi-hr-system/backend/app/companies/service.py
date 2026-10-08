from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.companies.schemas import CompanyCreate, CompanyUpdate
from app.core.deps import Principal
from app.core.exceptions import ForbiddenError, NotFoundError
from app.permissions.catalog import DEFAULT_ROLES
from app.shared.models import Company, Permission, Role, RolePermission


def _permission_map(db: Session) -> dict[str, int]:
    rows = db.execute(select(Permission.code, Permission.id)).all()
    return {code: pid for code, pid in rows}


def seed_default_roles(db: Session, company: Company) -> list[Role]:
    """Create the default role set for a new company (elevated context)."""
    pmap = _permission_map(db)
    created: list[Role] = []
    for code, name, description, perm_codes in DEFAULT_ROLES:
        role = Role(
            company_id=company.id, code=code, name=name, description=description
        )
        db.add(role)
        db.flush()
        for perm_code in perm_codes:
            perm_id = pmap.get(perm_code)
            if perm_id is None:
                continue
            db.add(
                RolePermission(
                    role_id=role.id, permission_id=perm_id, company_id=company.id
                )
            )
        created.append(role)
    return created


def _require(principal: Principal, code: str, company_id: int | None = None) -> None:
    """Company-scoped permission check (H1/H2)."""
    if not principal.has_permission(code, company_id):
        raise ForbiddenError(f"Missing permission: {code}")


def create_company(
    db: Session, *, payload: CompanyCreate, principal: Principal, ip: str | None
) -> Company:
    # The router also requires platform admin; the catalog permission is
    # enforced here so company.create remains a real, checked permission.
    _require(principal, "company.create")
    company = Company(**payload.model_dump())
    db.add(company)
    db.flush()
    seed_default_roles(db, company)
    record_audit(
        db,
        action="company.create",
        entity="company",
        record_id=company.id,
        actor_user_id=principal.user_id,
        company_id=company.id,
        new_value=payload.model_dump(),
        ip_address=ip,
    )
    db.flush()
    return company


def get_company(db: Session, company_id: int, principal: Principal) -> Company:
    company = db.get(Company, company_id)
    if company is None or not principal.can_access_company(company.id):
        raise NotFoundError("Company not found")
    _require(principal, "company.read", company.id)
    return company


def list_companies(db: Session, principal: Principal) -> list[Company]:
    stmt = select(Company).order_by(Company.id)
    if not principal.is_platform_admin:
        allowed = principal.permitted_company_ids("company.read")
        if not allowed:
            return []
        stmt = stmt.where(Company.id.in_(allowed))
    return list(db.execute(stmt).scalars())


def update_company(
    db: Session,
    *,
    company: Company,
    payload: CompanyUpdate,
    principal: Principal,
    ip: str | None,
) -> Company:
    _require(principal, "company.update", company.id)
    changes = payload.model_dump(exclude_unset=True)
    if "status" in changes and not principal.is_platform_admin:
        raise ForbiddenError("Only platform administrators may change company status")
    old = {k: getattr(company, k) for k in changes}
    for key, value in changes.items():
        setattr(company, key, value)
    db.add(company)
    record_audit(
        db,
        action="company.update",
        entity="company",
        record_id=company.id,
        actor_user_id=principal.user_id,
        company_id=company.id,
        old_value=old,
        new_value=changes,
        ip_address=ip,
    )
    db.flush()
    return company
