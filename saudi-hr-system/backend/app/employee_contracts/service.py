from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.core.deps import Principal
from app.core.exceptions import (
    ConflictError,
    ContractActiveExistsError,
    ContractDateRangeError,
    ContractNotFoundError,
    EmployeeNotFoundError,
    ForbiddenError,
)
from app.core.pagination import PageParams
from app.employee_contracts.schemas import ContractCreate, ContractUpdate
from app.shared.models import Employee, EmployeeContract


def _require(principal: Principal, code: str, company_id: int | None) -> None:
    """Company-scoped permission check (H1)."""
    if not principal.has_permission(code, company_id):
        raise ForbiddenError(f"Missing permission: {code}")


def _resolve_employee(db: Session, employee_id: int, principal: Principal) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None or not principal.can_access_company(employee.company_id):
        raise EmployeeNotFoundError("Employee not found")
    return employee


def _fetch_contract(
    db: Session, employee: Employee, contract_id: int
) -> EmployeeContract:
    contract = db.get(EmployeeContract, contract_id)
    if (
        contract is None
        or contract.employee_id != employee.id
        or contract.company_id != employee.company_id
    ):
        raise ContractNotFoundError("Contract not found")
    return contract


def _validate_dates(
    start_date: date, end_date: date | None, termination_date: date | None
) -> None:
    """Service-layer mirror of the CHECK constraints (stable error code)."""
    if end_date is not None and end_date < start_date:
        raise ContractDateRangeError("end_date cannot be before start_date")
    if termination_date is not None and termination_date < start_date:
        raise ContractDateRangeError("termination_date cannot be before start_date")
    if (
        termination_date is not None
        and end_date is not None
        and termination_date > end_date
    ):
        raise ContractDateRangeError("termination_date cannot be after end_date")


def _has_active(
    db: Session, employee_id: int, *, exclude_id: int | None = None
) -> bool:
    stmt = select(EmployeeContract.id).where(
        EmployeeContract.employee_id == employee_id,
        EmployeeContract.status == "active",
    )
    if exclude_id is not None:
        stmt = stmt.where(EmployeeContract.id != exclude_id)
    return db.execute(stmt).scalars().first() is not None


def _ensure_number_unique(
    db: Session, company_id: int, number: str | None, *, exclude_id: int | None = None
) -> None:
    if number is None:
        return
    stmt = select(EmployeeContract.id).where(
        EmployeeContract.company_id == company_id,
        EmployeeContract.contract_number == number,
    )
    if exclude_id is not None:
        stmt = stmt.where(EmployeeContract.id != exclude_id)
    if db.execute(stmt).scalars().first() is not None:
        raise ConflictError("Contract number already exists in this company")


def list_contracts(
    db: Session,
    principal: Principal,
    *,
    employee_id: int,
    status: str | None = None,
    page: PageParams | None = None,
) -> tuple[list[EmployeeContract], int]:
    employee = _resolve_employee(db, employee_id, principal)
    _require(principal, "employee_contract.view", employee.company_id)
    stmt = select(EmployeeContract).where(
        EmployeeContract.employee_id == employee.id,
        EmployeeContract.company_id == employee.company_id,
    )
    count_stmt = select(func.count()).select_from(EmployeeContract).where(
        EmployeeContract.employee_id == employee.id,
        EmployeeContract.company_id == employee.company_id,
    )
    if status is not None:
        stmt = stmt.where(EmployeeContract.status == status)
        count_stmt = count_stmt.where(EmployeeContract.status == status)
    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(EmployeeContract.start_date.desc(), EmployeeContract.id.desc())
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


def get_contract(
    db: Session,
    principal: Principal,
    *,
    employee_id: int,
    contract_id: int,
) -> EmployeeContract:
    employee = _resolve_employee(db, employee_id, principal)
    _require(principal, "employee_contract.view", employee.company_id)
    return _fetch_contract(db, employee, contract_id)


def create_contract(
    db: Session,
    *,
    employee_id: int,
    payload: ContractCreate,
    principal: Principal,
    ip: str | None,
) -> EmployeeContract:
    employee = _resolve_employee(db, employee_id, principal)
    _require(principal, "employee_contract.create", employee.company_id)
    data = payload.model_dump()
    _validate_dates(data["start_date"], data["end_date"], data["termination_date"])
    _ensure_number_unique(db, employee.company_id, data["contract_number"])
    if data["status"] == "active" and _has_active(db, employee.id):
        raise ContractActiveExistsError("Employee already has an active contract")

    contract = EmployeeContract(
        **data, employee_id=employee.id, created_by=principal.user_id
    )
    db.add(contract)
    try:
        db.flush()
    except IntegrityError as exc:
        if "uq_employee_contract_active" in str(exc.orig):
            raise ContractActiveExistsError(
                "Employee already has an active contract"
            ) from exc
        raise ConflictError("Contract could not be created") from exc
    record_audit(
        db,
        action="contract.create",
        entity="employee_contract",
        record_id=contract.id,
        actor_user_id=principal.user_id,
        company_id=employee.company_id,
        new_value={
            "employee_id": employee.id,
            "contract_type": contract.contract_type,
            "status": contract.status,
            "contract_number": contract.contract_number,
            "start_date": contract.start_date.isoformat(),
            "end_date": (
                contract.end_date.isoformat() if contract.end_date else None
            ),
        },
        ip_address=ip,
    )
    db.flush()
    return contract


def update_contract(
    db: Session,
    *,
    employee_id: int,
    contract_id: int,
    payload: ContractUpdate,
    principal: Principal,
    ip: str | None,
) -> EmployeeContract:
    employee = _resolve_employee(db, employee_id, principal)
    _require(principal, "employee_contract.update", employee.company_id)
    contract = _fetch_contract(db, employee, contract_id)
    changes = payload.model_dump(exclude_unset=True)

    merged_start = changes.get("start_date", contract.start_date)
    merged_end = changes.get("end_date", contract.end_date)
    merged_termination = changes.get("termination_date", contract.termination_date)
    _validate_dates(merged_start, merged_end, merged_termination)

    merged_number = changes.get("contract_number", contract.contract_number)
    _ensure_number_unique(
        db, employee.company_id, merged_number, exclude_id=contract.id
    )

    merged_status = changes.get("status", contract.status)
    if (
        merged_status == "active"
        and contract.status != "active"
        and _has_active(db, employee.id, exclude_id=contract.id)
    ):
        raise ContractActiveExistsError("Employee already has an active contract")

    for key, value in changes.items():
        setattr(contract, key, value)
    db.add(contract)
    record_audit(
        db,
        action="contract.update",
        entity="employee_contract",
        record_id=contract.id,
        actor_user_id=principal.user_id,
        company_id=employee.company_id,
        new_value={"employee_id": employee.id, "fields": sorted(changes)},
        ip_address=ip,
    )
    db.flush()
    return contract


def delete_contract(
    db: Session,
    *,
    employee_id: int,
    contract_id: int,
    principal: Principal,
    ip: str | None,
) -> None:
    employee = _resolve_employee(db, employee_id, principal)
    _require(principal, "employee_contract.delete", employee.company_id)
    contract = _fetch_contract(db, employee, contract_id)
    old_value = {
        "employee_id": employee.id,
        "contract_type": contract.contract_type,
        "status": contract.status,
    }
    record_audit(
        db,
        action="contract.delete",
        entity="employee_contract",
        record_id=contract.id,
        actor_user_id=principal.user_id,
        company_id=employee.company_id,
        old_value=old_value,
        ip_address=ip,
    )
    db.delete(contract)
    db.flush()
