from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import (
    Principal,
    client_ip,
    optional_company_header,
    require_permission,
)
from app.users.schemas import (
    RoleAssignment,
    UserCreate,
    UserDetailOut,
    UserOut,
    UserRoleOut,
    UserUpdate,
)
from app.users.service import (
    _roles_for_user,
    create_user,
    get_user,
    list_users,
    set_roles,
    update_user,
)

router = APIRouter(prefix="/users", tags=["users"])


def _detail(db: Session, user) -> UserDetailOut:
    roles = [
        UserRoleOut(
            role_id=link.role_id,
            company_id=link.company_id,
            code=role.code,
            name=role.name,
        )
        for link, role in _roles_for_user(db, user.id)
    ]
    return UserDetailOut(**UserOut.model_validate(user).model_dump(), roles=roles)


@router.get("", response_model=list[UserOut])
def list_all(
    company_id: int | None = Query(default=None, ge=1),
    search: str | None = Query(default=None, max_length=100),
    limit: int | None = Query(default=None, ge=1, le=100),
    principal: Principal = Depends(require_permission("user.read")),
    scoped_company: int | None = Depends(optional_company_header),
    db: Session = Depends(get_db),
) -> list[UserOut]:
    target = company_id if company_id is not None else scoped_company
    return [
        UserOut.model_validate(u)
        for u in list_users(
            db, principal, company_id=target, search=search, limit=limit
        )
    ]


@router.get("/{user_id}", response_model=UserDetailOut)
def read(
    user_id: int,
    principal: Principal = Depends(require_permission("user.read")),
    db: Session = Depends(get_db),
) -> UserDetailOut:
    user = get_user(db, user_id, principal)
    return _detail(db, user)


@router.post("", response_model=UserDetailOut, status_code=201)
def create(
    payload: UserCreate,
    request: Request,
    principal: Principal = Depends(require_permission("user.create")),
    db: Session = Depends(get_db),
) -> UserDetailOut:
    user = create_user(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return _detail(db, user)


@router.patch("/{user_id}", response_model=UserDetailOut)
def update(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    principal: Principal = Depends(require_permission("user.update")),
    db: Session = Depends(get_db),
) -> UserDetailOut:
    user = get_user(db, user_id, principal)
    updated = update_user(
        db, user=user, payload=payload, principal=principal,
        ip=client_ip(request),
    )
    detail = _detail(db, updated)
    # Commit here so a deactivation and its refresh-token revocation are
    # durable before the response is produced (M4).
    db.commit()
    return detail


@router.put("/{user_id}/roles", response_model=UserDetailOut)
def replace_roles(
    user_id: int,
    payload: RoleAssignment,
    request: Request,
    principal: Principal = Depends(require_permission("user.manage_roles")),
    db: Session = Depends(get_db),
) -> UserDetailOut:
    user = get_user(db, user_id, principal)
    set_roles(
        db, user=user, payload=payload, principal=principal,
        ip=client_ip(request),
    )
    return _detail(db, user)
