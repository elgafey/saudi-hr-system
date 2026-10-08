from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.companies.schemas import CompanyCreate, CompanyOut, CompanyUpdate
from app.companies.service import (
    create_company,
    get_company,
    list_companies,
    update_company,
)
from app.core.database import get_db
from app.core.deps import Principal, client_ip, get_current_principal
from app.core.exceptions import ForbiddenError

router = APIRouter(prefix="/companies", tags=["companies"])


@router.post("", response_model=CompanyOut, status_code=201)
def create(
    payload: CompanyCreate,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> CompanyOut:
    if not principal.is_platform_admin:
        raise ForbiddenError("Platform administrator access required")
    company = create_company(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return CompanyOut.model_validate(company)


@router.get("", response_model=list[CompanyOut])
def list_all(
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> list[CompanyOut]:
    return [CompanyOut.model_validate(c) for c in list_companies(db, principal)]


@router.get("/{company_id}", response_model=CompanyOut)
def read(
    company_id: int,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> CompanyOut:
    return CompanyOut.model_validate(get_company(db, company_id, principal))


@router.patch("/{company_id}", response_model=CompanyOut)
def update(
    company_id: int,
    payload: CompanyUpdate,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> CompanyOut:
    company = get_company(db, company_id, principal)
    updated = update_company(
        db,
        company=company,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return CompanyOut.model_validate(updated)
