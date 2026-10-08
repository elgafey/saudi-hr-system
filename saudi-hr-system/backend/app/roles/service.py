from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.core.deps import Principal
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.roles.schemas import RoleCreate, RolePermissionUpdate, RoleUpdate
from app.shared.models import Permission, Role, RolePermission


def _require(principal: Principal, code: str, company_id: int | None) -> None:
    """Company-scoped permission check (H1)."""
    if not principal.has_permission(code, company_id):
        raise ForbiddenError(f"Missing permission: {code}")


def list_roles(
    db: Session, principal: Principal, company_id: int | None = None
) -> list[Role]:
    stmt = select(Role).order_by(Role.id)
    if company_id is not None:
        if not principal.can_access_company(company_id):
            raise ForbiddenError("You cannot access this company")
        _require(principal, "role.read", company_id)
        stmt = stmt.where(Role.company_id == company_id)
    elif not principal.is_platform_admin:
        allowed = principal.permitted_company_ids("role.read")
        if not allowed:
            return []
        stmt = stmt.where(Role.company_id.in_(allowed))
    return list(db.execute(stmt).scalars())


def get_role(db: Session, role_id: int, principal: Principal) -> Role:
    role = db.get(Role, role_id)
    if role is None or not principal.can_access_company(role.company_id):
        raise NotFoundError("Role not found")
    _require(principal, "role.read", role.company_id)
    return role


def create_role(
    db: Session, *, payload: RoleCreate, principal: Principal, ip: str | None
) -> Role:
    if not principal.can_access_company(payload.company_id):
        raise ForbiddenError("You cannot create roles in this company")
    _require(principal, "role.create", payload.company_id)
    existing = db.execute(
        select(Role).where(
            Role.company_id == payload.company_id, Role.code == payload.code
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("Role code already exists in this company")
    role = Role(**payload.model_dump())
    db.add(role)
    db.flush()
    record_audit(
        db,
        action="role.create",
        entity="role",
        record_id=role.id,
        actor_user_id=principal.user_id,
        company_id=payload.company_id,
        new_value=payload.model_dump(),
        ip_address=ip,
    )
    db.flush()
    return role


def update_role(
    db: Session,
    *,
    role: Role,
    payload: RoleUpdate,
    principal: Principal,
    ip: str | None,
) -> Role:
    _require(principal, "role.update", role.company_id)
    changes = payload.model_dump(exclude_unset=True)
    old = {k: getattr(role, k) for k in changes}
    for key, value in changes.items():
        setattr(role, key, value)
    db.add(role)
    record_audit(
        db,
        action="role.update",
        entity="role",
        record_id=role.id,
        actor_user_id=principal.user_id,
        company_id=role.company_id,
        old_value=old,
        new_value=changes,
        ip_address=ip,
    )
    db.flush()
    return role


def get_role_permission_codes(db: Session, role: Role) -> list[str]:
    rows = db.execute(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role.id)
        .order_by(Permission.code)
    ).scalars()
    return list(rows)


def set_role_permissions(
    db: Session,
    *,
    role: Role,
    payload: RolePermissionUpdate,
    principal: Principal,
    ip: str | None,
) -> list[str]:
    _require(principal, "role.update", role.company_id)
    valid = {
        code: pid
        for code, pid in db.execute(select(Permission.code, Permission.id)).all()
    }
    unknown = [c for c in payload.permission_codes if c not in valid]
    if unknown:
        raise NotFoundError(f"Unknown permissions: {', '.join(sorted(unknown))}")

    old_codes = get_role_permission_codes(db, role)
    links = db.execute(
        select(RolePermission).where(RolePermission.role_id == role.id)
    ).scalars().all()
    for link in links:
        db.delete(link)
    db.flush()
    for code in dict.fromkeys(payload.permission_codes):
        db.add(
            RolePermission(
                role_id=role.id,
                permission_id=valid[code],
                company_id=role.company_id,
            )
        )
    db.flush()
    new_codes = sorted(set(payload.permission_codes))
    record_audit(
        db,
        action="role.set_permissions",
        entity="role",
        record_id=role.id,
        actor_user_id=principal.user_id,
        company_id=role.company_id,
        old_value={"permission_codes": old_codes},
        new_value={"permission_codes": new_codes},
        ip_address=ip,
    )
    db.flush()
    return new_codes


def list_permissions(db: Session) -> list[Permission]:
    return list(
        db.execute(select(Permission).order_by(Permission.module, Permission.code)).scalars()
    )
