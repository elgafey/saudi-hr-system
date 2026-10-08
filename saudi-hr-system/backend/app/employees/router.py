from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import (
    Principal,
    client_ip,
    optional_company_header,
    require_permission,
)
from app.core.pagination import Page, PageParams, pagination_params
from app.employees.link_service import (
    get_linked_user,
    link_user,
    unlink_user,
)
from app.employees.schemas import (
    EmployeeCreate,
    EmployeeOut,
    EmployeePage,
    EmployeeUpdate,
    EmployeeUserLinkOut,
    LinkedUserOut,
    UserLinkIn,
)
from app.employees.service import (
    create_employee,
    delete_employee,
    get_employee,
    list_employees,
    update_employee,
)

router = APIRouter(prefix="/employees", tags=["employees"])


@router.get("", response_model=EmployeePage)
def list_all(
    company_id: int | None = Query(default=None, ge=1),
    search: str | None = Query(default=None, max_length=100),
    status: str | None = Query(
        default=None, pattern="^(draft|active|suspended|terminated)$"
    ),
    department_id: int | None = Query(default=None, ge=1),
    branch_id: int | None = Query(default=None, ge=1),
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(require_permission("employee.read")),
    scoped_company: int | None = Depends(optional_company_header),
    db: Session = Depends(get_db),
) -> EmployeePage:
    target = company_id if company_id is not None else scoped_company
    items, total = list_employees(
        db,
        principal,
        company_id=target,
        search=search,
        status=status,
        department_id=department_id,
        branch_id=branch_id,
        page=page_params,
    )
    return EmployeePage(
        items=[EmployeeOut.model_validate(i) for i in items],
        page=Page(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ),
    )


@router.get("/{employee_id}", response_model=EmployeeOut)
def read(
    employee_id: int,
    principal: Principal = Depends(require_permission("employee.read")),
    db: Session = Depends(get_db),
) -> EmployeeOut:
    return EmployeeOut.model_validate(get_employee(db, employee_id, principal))


@router.post("", response_model=EmployeeOut, status_code=201)
def create(
    payload: EmployeeCreate,
    request: Request,
    principal: Principal = Depends(require_permission("employee.create")),
    db: Session = Depends(get_db),
) -> EmployeeOut:
    employee = create_employee(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return EmployeeOut.model_validate(employee)


@router.patch("/{employee_id}", response_model=EmployeeOut)
def update(
    employee_id: int,
    payload: EmployeeUpdate,
    request: Request,
    principal: Principal = Depends(require_permission("employee.update")),
    db: Session = Depends(get_db),
) -> EmployeeOut:
    employee = get_employee(db, employee_id, principal)
    updated = update_employee(
        db,
        employee=employee,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return EmployeeOut.model_validate(updated)


@router.delete("/{employee_id}", status_code=204)
def remove(
    employee_id: int,
    request: Request,
    principal: Principal = Depends(require_permission("employee.delete")),
    db: Session = Depends(get_db),
) -> Response:
    employee = get_employee(db, employee_id, principal)
    delete_employee(
        db, employee=employee, principal=principal, ip=client_ip(request)
    )
    return Response(status_code=204)


@router.get("/{employee_id}/user", response_model=EmployeeUserLinkOut)
def read_user_link(
    employee_id: int,
    principal: Principal = Depends(
        require_permission("employee_user_link.view")
    ),
    db: Session = Depends(get_db),
) -> EmployeeUserLinkOut:
    user = get_linked_user(db, employee_id=employee_id, principal=principal)
    return EmployeeUserLinkOut(
        linked=user is not None,
        user=LinkedUserOut.model_validate(user) if user is not None else None,
    )


@router.post("/{employee_id}/user", response_model=EmployeeUserLinkOut)
def link_user_route(
    employee_id: int,
    payload: UserLinkIn,
    request: Request,
    principal: Principal = Depends(
        require_permission("employee_user_link.manage")
    ),
    db: Session = Depends(get_db),
) -> EmployeeUserLinkOut:
    user = link_user(
        db,
        employee_id=employee_id,
        user_id=payload.user_id,
        principal=principal,
        ip=client_ip(request),
    )
    return EmployeeUserLinkOut(linked=True, user=LinkedUserOut.model_validate(user))


@router.delete("/{employee_id}/user", status_code=204)
def unlink_user_route(
    employee_id: int,
    request: Request,
    principal: Principal = Depends(
        require_permission("employee_user_link.manage")
    ),
    db: Session = Depends(get_db),
) -> Response:
    unlink_user(
        db, employee_id=employee_id, principal=principal, ip=client_ip(request)
    )
    return Response(status_code=204)
