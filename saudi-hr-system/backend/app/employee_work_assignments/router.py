from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import Principal, client_ip, require_permission
from app.core.pagination import Page, PageParams, pagination_params
from app.employee_work_assignments.schemas import (
    AssignmentCreate,
    AssignmentOut,
    AssignmentPage,
    AssignmentUpdate,
)
from app.employee_work_assignments.service import (
    create_assignment,
    delete_assignment,
    get_assignment,
    list_assignments,
    update_assignment,
)

router = APIRouter(
    prefix="/employees/{employee_id}/work-assignments",
    tags=["employee-work-assignments"],
)


@router.get("", response_model=AssignmentPage)
def list_all(
    employee_id: int,
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(
        require_permission("employee_work_assignment.view")
    ),
    db: Session = Depends(get_db),
) -> AssignmentPage:
    items, total = list_assignments(
        db, employee_id, principal, page=page_params
    )
    return AssignmentPage(
        items=[AssignmentOut.model_validate(a) for a in items],
        page=Page(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ),
    )


@router.post("", response_model=AssignmentOut, status_code=201)
def create(
    employee_id: int,
    payload: AssignmentCreate,
    request: Request,
    principal: Principal = Depends(
        require_permission("employee_work_assignment.create")
    ),
    db: Session = Depends(get_db),
) -> AssignmentOut:
    row = create_assignment(
        db,
        employee_id=employee_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return AssignmentOut.model_validate(row)


@router.get("/{assignment_id}", response_model=AssignmentOut)
def read(
    employee_id: int,
    assignment_id: int,
    principal: Principal = Depends(
        require_permission("employee_work_assignment.view")
    ),
    db: Session = Depends(get_db),
) -> AssignmentOut:
    row = get_assignment(db, employee_id, assignment_id, principal)
    return AssignmentOut.model_validate(row)


@router.patch("/{assignment_id}", response_model=AssignmentOut)
def update(
    employee_id: int,
    assignment_id: int,
    payload: AssignmentUpdate,
    request: Request,
    principal: Principal = Depends(
        require_permission("employee_work_assignment.update")
    ),
    db: Session = Depends(get_db),
) -> AssignmentOut:
    row = update_assignment(
        db,
        employee_id=employee_id,
        assignment_id=assignment_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return AssignmentOut.model_validate(row)


@router.delete("/{assignment_id}", status_code=204)
def remove(
    employee_id: int,
    assignment_id: int,
    request: Request,
    principal: Principal = Depends(
        require_permission("employee_work_assignment.delete")
    ),
    db: Session = Depends(get_db),
) -> Response:
    delete_assignment(
        db,
        employee_id=employee_id,
        assignment_id=assignment_id,
        principal=principal,
        ip=client_ip(request),
    )
    return Response(status_code=204)
