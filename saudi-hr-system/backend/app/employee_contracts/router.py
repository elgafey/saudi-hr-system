from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import Principal, client_ip, require_permission
from app.core.pagination import Page, PageParams, pagination_params
from app.employee_contracts.schemas import (
    ContractCreate,
    ContractOut,
    ContractPage,
    ContractUpdate,
)
from app.employee_contracts.service import (
    create_contract,
    delete_contract,
    get_contract,
    list_contracts,
    update_contract,
)

router = APIRouter(
    prefix="/employees/{employee_id}/contracts", tags=["employee-contracts"]
)


@router.get("", response_model=ContractPage)
def list_all(
    employee_id: int,
    status: str | None = Query(
        default=None, pattern="^(draft|active|expired|terminated|cancelled)$"
    ),
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(require_permission("employee_contract.view")),
    db: Session = Depends(get_db),
) -> ContractPage:
    items, total = list_contracts(
        db, principal, employee_id=employee_id, status=status, page=page_params
    )
    return ContractPage(
        items=[ContractOut.model_validate(i) for i in items],
        page=Page(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ),
    )


@router.post("", response_model=ContractOut, status_code=201)
def create(
    employee_id: int,
    payload: ContractCreate,
    request: Request,
    principal: Principal = Depends(require_permission("employee_contract.create")),
    db: Session = Depends(get_db),
) -> ContractOut:
    contract = create_contract(
        db,
        employee_id=employee_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return ContractOut.model_validate(contract)


@router.get("/{contract_id}", response_model=ContractOut)
def read(
    employee_id: int,
    contract_id: int,
    principal: Principal = Depends(require_permission("employee_contract.view")),
    db: Session = Depends(get_db),
) -> ContractOut:
    contract = get_contract(
        db, principal, employee_id=employee_id, contract_id=contract_id
    )
    return ContractOut.model_validate(contract)


@router.patch("/{contract_id}", response_model=ContractOut)
def update(
    employee_id: int,
    contract_id: int,
    payload: ContractUpdate,
    request: Request,
    principal: Principal = Depends(require_permission("employee_contract.update")),
    db: Session = Depends(get_db),
) -> ContractOut:
    contract = update_contract(
        db,
        employee_id=employee_id,
        contract_id=contract_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return ContractOut.model_validate(contract)


@router.delete("/{contract_id}", status_code=204)
def remove(
    employee_id: int,
    contract_id: int,
    request: Request,
    principal: Principal = Depends(require_permission("employee_contract.delete")),
    db: Session = Depends(get_db),
) -> Response:
    delete_contract(
        db,
        employee_id=employee_id,
        contract_id=contract_id,
        principal=principal,
        ip=client_ip(request),
    )
    return Response(status_code=204)
