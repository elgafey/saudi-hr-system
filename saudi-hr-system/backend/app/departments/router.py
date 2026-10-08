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
from app.departments.schemas import (
    DepartmentCreate,
    DepartmentOut,
    DepartmentPage,
    DepartmentUpdate,
)
from app.departments.service import (
    create_department,
    delete_department,
    get_department,
    list_departments,
    update_department,
)

router = APIRouter(prefix="/departments", tags=["departments"])


@router.get("", response_model=DepartmentPage)
def list_all(
    company_id: int | None = Query(default=None, ge=1),
    search: str | None = Query(default=None, max_length=100),
    status: str | None = Query(default=None, pattern="^(active|inactive)$"),
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(require_permission("department.read")),
    scoped_company: int | None = Depends(optional_company_header),
    db: Session = Depends(get_db),
) -> DepartmentPage:
    target = company_id if company_id is not None else scoped_company
    items, total = list_departments(
        db,
        principal,
        company_id=target,
        search=search,
        status=status,
        page=page_params,
    )
    return DepartmentPage(
        items=[DepartmentOut.model_validate(i) for i in items],
        page=Page(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ),
    )


@router.get("/{department_id}", response_model=DepartmentOut)
def read(
    department_id: int,
    principal: Principal = Depends(require_permission("department.read")),
    db: Session = Depends(get_db),
) -> DepartmentOut:
    return DepartmentOut.model_validate(get_department(db, department_id, principal))


@router.post("", response_model=DepartmentOut, status_code=201)
def create(
    payload: DepartmentCreate,
    request: Request,
    principal: Principal = Depends(require_permission("department.create")),
    db: Session = Depends(get_db),
) -> DepartmentOut:
    department = create_department(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return DepartmentOut.model_validate(department)


@router.patch("/{department_id}", response_model=DepartmentOut)
def update(
    department_id: int,
    payload: DepartmentUpdate,
    request: Request,
    principal: Principal = Depends(require_permission("department.update")),
    db: Session = Depends(get_db),
) -> DepartmentOut:
    department = get_department(db, department_id, principal)
    updated = update_department(
        db,
        department=department,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return DepartmentOut.model_validate(updated)


@router.delete("/{department_id}", status_code=204)
def remove(
    department_id: int,
    request: Request,
    principal: Principal = Depends(require_permission("department.delete")),
    db: Session = Depends(get_db),
) -> Response:
    department = get_department(db, department_id, principal)
    delete_department(
        db, department=department, principal=principal, ip=client_ip(request)
    )
    return Response(status_code=204)
