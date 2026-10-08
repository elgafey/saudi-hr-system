from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.rls import set_context
from app.core.security import TokenError, decode_access_token
from app.shared.models import Permission, RolePermission, User, UserRole

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    user_id: int
    email: str
    is_platform_admin: bool
    company_ids: list[int] = field(default_factory=list)
    # Union of permission codes across all memberships (display only, /me).
    permissions: set[str] = field(default_factory=set)
    # Authoritative authorization data: permission codes per company.
    permissions_by_company: dict[int, set[str]] = field(default_factory=dict)

    def has_permission(self, code: str, company_id: int | None = None) -> bool:
        """Check a permission code, optionally scoped to a target company.

        - Platform admins hold every permission in every company.
        - company_id=None means "any membership" (coarse gate used by route
          dependencies; services perform the strict per-company check).
        - company_id=<id> requires the code in that company's role set.
        """
        if self.is_platform_admin:
            return True
        if company_id is None:
            return any(code in perms for perms in self.permissions_by_company.values())
        return code in self.permissions_by_company.get(company_id, set())

    def permitted_company_ids(self, code: str) -> list[int]:
        """Membership companies where the code is granted (read scoping)."""
        if self.is_platform_admin:
            return list(self.company_ids)
        return sorted(
            cid
            for cid, perms in self.permissions_by_company.items()
            if code in perms
        )

    def can_access_company(self, company_id: int | None) -> bool:
        if self.is_platform_admin:
            return True
        if company_id is None:
            return False
        return company_id in self.company_ids


def _load_company_ids(db: Session, user_id: int) -> list[int]:
    rows = db.execute(
        select(UserRole.company_id).where(UserRole.user_id == user_id).distinct()
    ).scalars()
    return sorted({int(r) for r in rows})


def _load_permissions(
    db: Session, user: User, company_ids: list[int]
) -> tuple[set[str], dict[int, set[str]]]:
    """Return (union_display_codes, permissions_by_company)."""
    all_codes = set(db.execute(select(Permission.code)).scalars())
    if user.is_platform_admin:
        return all_codes, {cid: set(all_codes) for cid in company_ids}
    if not company_ids:
        return set(), {}
    rows = db.execute(
        select(UserRole.company_id, Permission.code)
        .join(RolePermission, RolePermission.role_id == UserRole.role_id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(
            UserRole.user_id == user.id,
            UserRole.company_id.in_(company_ids),
        )
    ).all()
    by_company: dict[int, set[str]] = {}
    union: set[str] = set()
    for company_id, code in rows:
        by_company.setdefault(int(company_id), set()).add(code)
        union.add(code)
    return union, by_company


def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Principal:
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("Authentication required")
    try:
        payload = decode_access_token(credentials.credentials)
    except TokenError as exc:
        raise UnauthorizedError(str(exc)) from exc

    user_id = int(payload["sub"])

    # Bootstrap context: self-read only (deny-by-default for companies).
    set_context(db, user_id=user_id, company_ids=[], is_platform_admin=False)

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("User is inactive or does not exist")

    company_ids = _load_company_ids(db, user_id)

    # Full request context for all subsequent queries (transaction-local).
    set_context(
        db,
        user_id=user_id,
        company_ids=company_ids,
        is_platform_admin=user.is_platform_admin,
    )

    permissions, permissions_by_company = _load_permissions(db, user, company_ids)
    return Principal(
        user_id=user.id,
        email=user.email,
        is_platform_admin=user.is_platform_admin,
        company_ids=company_ids,
        permissions=permissions,
        permissions_by_company=permissions_by_company,
    )


def require_permission(code: str):
    """Coarse route gate: the code must be held in at least one company.

    Services re-check the code against the operation's target company
    (company-scoped authorization); platform admins bypass both checks.
    """

    def checker(
        principal: Principal = Depends(get_current_principal),
    ) -> Principal:
        if not principal.has_permission(code):
            raise ForbiddenError(f"Missing permission: {code}")
        return principal

    return checker


def require_platform_admin(
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    if not principal.is_platform_admin:
        raise ForbiddenError("Platform administrator access required")
    return principal


def client_ip(request: Request) -> str | None:
    if request.client:
        return request.client.host
    return None


def optional_company_header(
    x_company_id: str | None = Header(default=None, alias="X-Company-Id"),
) -> int | None:
    if x_company_id is None or x_company_id == "":
        return None
    try:
        return int(x_company_id)
    except ValueError as exc:
        raise ForbiddenError("Invalid X-Company-Id header") from exc
