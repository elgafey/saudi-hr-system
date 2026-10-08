from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.branches.schemas import BranchCreate, BranchOut, BranchUpdate
from app.branches.service import (
    create_branch,
    get_branch,
    list_branches,
    update_branch,
)
from app.core.database import get_db
from app.core.deps import (
    Principal,
    client_ip,
    optional_company_header,
    require_permission,
)

router = APIRouter(prefix="/branches", tags=["branches"])


@router.get("", response_model=list[BranchOut])
def list_all(
    company_id: int | None = Query(default=None, ge=1),
    principal: Principal = Depends(require_permission("branch.read")),
    scoped_company: int | None = Depends(optional_company_header),
    db: Session = Depends(get_db),
) -> list[BranchOut]:
    target = company_id if company_id is not None else scoped_company
    return [
        BranchOut.model_validate(b)
        for b in list_branches(db, principal, company_id=target)
    ]


@router.get("/{branch_id}", response_model=BranchOut)
def read(
    branch_id: int,
    principal: Principal = Depends(require_permission("branch.read")),
    db: Session = Depends(get_db),
) -> BranchOut:
    return BranchOut.model_validate(get_branch(db, branch_id, principal))


@router.post("", response_model=BranchOut, status_code=201)
def create(
    payload: BranchCreate,
    request: Request,
    principal: Principal = Depends(require_permission("branch.create")),
    db: Session = Depends(get_db),
) -> BranchOut:
    branch = create_branch(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return BranchOut.model_validate(branch)


@router.patch("/{branch_id}", response_model=BranchOut)
def update(
    branch_id: int,
    payload: BranchUpdate,
    request: Request,
    principal: Principal = Depends(require_permission("branch.update")),
    db: Session = Depends(get_db),
) -> BranchOut:
    branch = get_branch(db, branch_id, principal)
    updated = update_branch(
        db, branch=branch, payload=payload, principal=principal,
        ip=client_ip(request),
    )
    return BranchOut.model_validate(updated)
