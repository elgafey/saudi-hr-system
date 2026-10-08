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
from app.roles.schemas import (
    PermissionOut,
    RoleCreate,
    RoleOut,
    RolePermissionOut,
    RolePermissionUpdate,
    RoleUpdate,
)
from app.roles.service import (
    create_role,
    get_role,
    get_role_permission_codes,
    list_permissions,
    list_roles,
    set_role_permissions,
    update_role,
)

router = APIRouter(tags=["roles"])


@router.get("/roles", response_model=list[RoleOut])
def list_all_roles(
    company_id: int | None = Query(default=None, ge=1),
    principal: Principal = Depends(require_permission("role.read")),
    scoped_company: int | None = Depends(optional_company_header),
    db: Session = Depends(get_db),
) -> list[RoleOut]:
    target = company_id if company_id is not None else scoped_company
    return [
        RoleOut.model_validate(r) for r in list_roles(db, principal, company_id=target)
    ]


@router.get("/roles/{role_id}", response_model=RolePermissionOut)
def read_role(
    role_id: int,
    principal: Principal = Depends(require_permission("role.read")),
    db: Session = Depends(get_db),
) -> RolePermissionOut:
    role = get_role(db, role_id, principal)
    return RolePermissionOut(
        role_id=role.id, permission_codes=get_role_permission_codes(db, role)
    )


@router.post("/roles", response_model=RoleOut, status_code=201)
def create(
    payload: RoleCreate,
    request: Request,
    principal: Principal = Depends(require_permission("role.create")),
    db: Session = Depends(get_db),
) -> RoleOut:
    role = create_role(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return RoleOut.model_validate(role)


@router.patch("/roles/{role_id}", response_model=RoleOut)
def update(
    role_id: int,
    payload: RoleUpdate,
    request: Request,
    principal: Principal = Depends(require_permission("role.update")),
    db: Session = Depends(get_db),
) -> RoleOut:
    role = get_role(db, role_id, principal)
    updated = update_role(
        db, role=role, payload=payload, principal=principal,
        ip=client_ip(request),
    )
    return RoleOut.model_validate(updated)


@router.put("/roles/{role_id}/permissions", response_model=RolePermissionOut)
def replace_permissions(
    role_id: int,
    payload: RolePermissionUpdate,
    request: Request,
    principal: Principal = Depends(require_permission("role.update")),
    db: Session = Depends(get_db),
) -> RolePermissionOut:
    role = get_role(db, role_id, principal)
    codes = set_role_permissions(
        db, role=role, payload=payload, principal=principal,
        ip=client_ip(request),
    )
    return RolePermissionOut(role_id=role.id, permission_codes=codes)


@router.get("/permissions", response_model=list[PermissionOut])
def permissions(
    principal: Principal = Depends(require_permission("permission.read")),
    db: Session = Depends(get_db),
) -> list[PermissionOut]:
    return [PermissionOut.model_validate(p) for p in list_permissions(db)]
