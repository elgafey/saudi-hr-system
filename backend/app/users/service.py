from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.auth.models import RefreshToken
from app.core.deps import Principal
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.security import hash_password
from app.shared.models import Role, User, UserRole
from app.users.schemas import RoleAssignment, UserCreate, UserUpdate


def _require(principal: Principal, code: str, company_id: int | None) -> None:
    """Company-scoped permission check (H1): the code must be granted in the
    target company, not merely somewhere in the user's memberships."""
    if not principal.has_permission(code, company_id):
        raise ForbiddenError(f"Missing permission: {code}")


def _roles_for_user(db: Session, user_id: int) -> list[UserRole]:
    stmt = (
        select(UserRole, Role)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id == user_id)
        .order_by(UserRole.id)
    )
    return [(row[0], row[1]) for row in db.execute(stmt).all()]


def list_users(
    db: Session,
    principal: Principal,
    company_id: int | None = None,
    *,
    search: str | None = None,
    limit: int | None = None,
) -> list[User]:
    stmt = select(User).order_by(User.id)
    if company_id is not None:
        if not principal.can_access_company(company_id):
            raise ForbiddenError("You cannot access this company")
        _require(principal, "user.read", company_id)
        stmt = stmt.where(User.company_id == company_id)
    elif not principal.is_platform_admin:
        allowed = principal.permitted_company_ids("user.read")
        if not allowed:
            return []
        stmt = stmt.where(User.company_id.in_(allowed))
    # Server-side autocomplete search (Phase 3): match on email or name.
    if search and search.strip():
        like = f"%{search.strip()}%"
        stmt = stmt.where(or_(User.email.ilike(like), User.full_name.ilike(like)))
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(db.execute(stmt).scalars())


def get_user(db: Session, user_id: int, principal: Principal) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    in_scope = principal.is_platform_admin or (
        user.company_id is not None and user.company_id in principal.company_ids
    )
    if not in_scope:
        raise NotFoundError("User not found")
    _require(principal, "user.read", user.company_id)
    return user


def create_user(
    db: Session, *, payload: UserCreate, principal: Principal, ip: str | None
) -> User:
    if not principal.can_access_company(payload.company_id):
        raise ForbiddenError("You cannot create users in this company")
    _require(principal, "user.create", payload.company_id)
    email = payload.email.strip().lower()
    existing = db.execute(
        select(User).where(User.email == email)
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("A user with this email already exists")

    user = User(
        email=email,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        is_active=payload.is_active,
        is_platform_admin=False,
        company_id=payload.company_id,
    )
    db.add(user)
    db.flush()

    if payload.role_ids:
        _assign_roles(db, user=user, role_ids=payload.role_ids, principal=principal)

    record_audit(
        db,
        action="user.create",
        entity="user",
        record_id=user.id,
        actor_user_id=principal.user_id,
        company_id=payload.company_id,
        new_value={
            "email": email,
            "full_name": payload.full_name,
            "role_ids": payload.role_ids,
        },
        ip_address=ip,
    )
    db.flush()
    return user


def _assign_roles(
    db: Session, *, user: User, role_ids: list[int], principal: Principal
) -> list[UserRole]:
    assigned: list[UserRole] = []
    for role_id in dict.fromkeys(role_ids):
        role = db.get(Role, role_id)
        if role is None or not principal.can_access_company(role.company_id):
            raise NotFoundError(f"Role {role_id} not found")
        existing = db.execute(
            select(UserRole).where(
                UserRole.user_id == user.id,
                UserRole.role_id == role.id,
                UserRole.company_id == role.company_id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        link = UserRole(
            user_id=user.id, role_id=role.id, company_id=role.company_id
        )
        db.add(link)
        db.flush()
        assigned.append(link)
    return assigned


def update_user(
    db: Session,
    *,
    user: User,
    payload: UserUpdate,
    principal: Principal,
    ip: str | None,
) -> User:
    _require(principal, "user.update", user.company_id)
    changes = payload.model_dump(exclude_unset=True)
    if "is_platform_admin" in changes:
        if not principal.is_platform_admin:
            raise ForbiddenError(
                "Only platform administrators may change platform admin flag"
            )
        if changes["is_platform_admin"] and not principal.is_platform_admin:
            raise ForbiddenError("Cannot grant platform admin access")
    if "is_active" in changes and changes["is_active"] is False:
        if user.id == principal.user_id:
            raise ForbiddenError("You cannot deactivate your own account")
    if "company_id" in changes and changes["company_id"] is not None:
        if not principal.is_platform_admin:
            raise ForbiddenError(
                "Only platform administrators may move users between companies"
            )
        if not principal.can_access_company(changes["company_id"]):
            raise ForbiddenError("You cannot move users into this company")
    old = {k: getattr(user, k) for k in changes}
    for key, value in changes.items():
        setattr(user, key, value)
    db.add(user)
    if changes.get("is_active") is False:
        # M4: revoke every active refresh session in the same transaction as
        # the deactivation, so both commit (or roll back) atomically.
        db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user.id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(timezone.utc))
        )
    record_audit(
        db,
        action="user.update",
        entity="user",
        record_id=user.id,
        actor_user_id=principal.user_id,
        company_id=user.company_id,
        old_value=old,
        new_value=changes,
        ip_address=ip,
    )
    db.flush()
    return user


def set_roles(
    db: Session,
    *,
    user: User,
    payload: RoleAssignment,
    principal: Principal,
    ip: str | None,
) -> list[UserRole]:
    if user.company_id is None or not principal.can_access_company(user.company_id):
        raise ForbiddenError("You cannot manage roles for this user")
    _require(principal, "user.manage_roles", user.company_id)

    existing_links = db.execute(
        select(UserRole).where(UserRole.user_id == user.id)
    ).scalars().all()
    requested = set(payload.role_ids)
    for link in existing_links:
        if link.role_id not in requested:
            db.delete(link)

    _assign_roles(db, user=user, role_ids=payload.role_ids, principal=principal)

    record_audit(
        db,
        action="user.set_roles",
        entity="user",
        record_id=user.id,
        actor_user_id=principal.user_id,
        company_id=user.company_id,
        old_value={"role_ids": [link.role_id for link in existing_links]},
        new_value={"role_ids": sorted(requested)},
        ip_address=ip,
    )
    db.flush()
    return [
        row[0]
        for row in db.execute(
            select(UserRole).where(UserRole.user_id == user.id)
        ).all()
    ]
