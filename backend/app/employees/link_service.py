"""Employee <-> user account linking (Phase 3).

Links are strictly explicit: this module never creates users. The link is a
unique FK (``users.employee_id``), so each employee has at most one account
and each account belongs to at most one employee. Target users must sit in
the employee's company (via ``users.company_id`` or a role membership);
anything else raises the stable ``CROSS_COMPANY_RELATION`` code.
"""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.core.deps import Principal
from app.core.exceptions import (
    CrossCompanyRelationError,
    EmployeeAlreadyLinkedError,
    ForbiddenError,
    UserAlreadyLinkedError,
    UserNotFoundError,
)
from app.shared.models import Employee, User, UserRole


def _require(principal: Principal, code: str, company_id: int | None) -> None:
    """Company-scoped permission check (H1)."""
    if not principal.has_permission(code, company_id):
        raise ForbiddenError(f"Missing permission: {code}")


def _resolve_employee(db: Session, employee_id: int, principal: Principal) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None or not principal.can_access_company(employee.company_id):
        from app.core.exceptions import EmployeeNotFoundError

        raise EmployeeNotFoundError("Employee not found")
    return employee


def _linked_user(db: Session, employee_id: int) -> User | None:
    stmt = select(User).where(User.employee_id == employee_id)
    return db.execute(stmt).scalars().first()


def _set_employee_link(db: Session, user: User, employee_id: int | None) -> None:
    """Write ``users.employee_id`` under the 0002 security trigger.

    ``guard_users_security`` (frozen migration 0002) treats ``employee_id``
    as a security-sensitive column: direct updates require platform-admin
    context. Linking is a deliberate, permission-checked system operation,
    so the platform-admin GUC is raised transaction-locally for exactly this
    flush and restored immediately afterwards (the GUC is transaction-local;
    an exception rolls the whole transaction back, so no window survives the
    request). No other statement runs in between.
    """
    was_admin = db.execute(
        text("SELECT app.is_platform_admin()")
    ).scalar_one()
    db.execute(text("SELECT set_config('app.is_platform_admin','true',true)"))
    try:
        user.employee_id = employee_id
        db.add(user)
        db.flush()
    finally:
        db.execute(
            text("SELECT set_config('app.is_platform_admin', :v, true)"),
            {"v": "true" if was_admin else "false"},
        )


def get_linked_user(
    db: Session, *, employee_id: int, principal: Principal
) -> User | None:
    employee = _resolve_employee(db, employee_id, principal)
    _require(principal, "employee_user_link.view", employee.company_id)
    return _linked_user(db, employee.id)


def link_user(
    db: Session,
    *,
    employee_id: int,
    user_id: int,
    principal: Principal,
    ip: str | None,
) -> User:
    employee = _resolve_employee(db, employee_id, principal)
    _require(principal, "employee_user_link.manage", employee.company_id)

    user = db.get(User, user_id)
    if user is None:
        raise UserNotFoundError("User not found")

    same_company = (
        user.company_id is not None and user.company_id == employee.company_id
    )
    has_membership = (
        db.execute(
            select(UserRole.id).where(
                UserRole.user_id == user.id,
                UserRole.company_id == employee.company_id,
            )
        ).first()
        is not None
    )
    if not same_company and not has_membership:
        raise CrossCompanyRelationError(
            "User does not belong to this employee's company"
        )

    if user.employee_id is not None:
        if user.employee_id == employee.id:
            raise EmployeeAlreadyLinkedError(
                "Employee already has a linked user account"
            )
        raise UserAlreadyLinkedError("User is already linked to another employee")
    if _linked_user(db, employee.id) is not None:
        raise EmployeeAlreadyLinkedError("Employee already has a linked user account")

    _set_employee_link(db, user, employee.id)
    record_audit(
        db,
        action="employee_user_link.link",
        entity="user",
        record_id=user.id,
        actor_user_id=principal.user_id,
        company_id=employee.company_id,
        new_value={"user_id": user.id, "employee_id": employee.id},
        ip_address=ip,
    )
    db.flush()
    return user


def unlink_user(
    db: Session, *, employee_id: int, principal: Principal, ip: str | None
) -> User:
    employee = _resolve_employee(db, employee_id, principal)
    _require(principal, "employee_user_link.manage", employee.company_id)
    user = _linked_user(db, employee.id)
    if user is None:
        raise UserNotFoundError("No user is linked to this employee")
    _set_employee_link(db, user, None)
    record_audit(
        db,
        action="employee_user_link.unlink",
        entity="user",
        record_id=user.id,
        actor_user_id=principal.user_id,
        company_id=employee.company_id,
        old_value={"user_id": user.id, "employee_id": employee.id},
        ip_address=ip,
    )
    db.flush()
    return user
