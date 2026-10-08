"""Phase 7 request/approval core: self-scope helpers + workflow machine.

Authorization model (no hardcoded role names anywhere - permission codes
only, always company-scoped):

- owner verbs (create/update/submit/cancel): the code alone allows acting
  on your OWN request; acting for another employee additionally requires
  ``employee_request.view`` (cross-employee marker, Phase 5 pattern).
- decisions (approve/reject): ``(approver_employee_id == self AND the
  verb code)`` OR ``employee_request.manage`` (HR override; also the only
  path when no manager is assigned at submit time).
- reads: ``view`` OR own-with-``create`` OR assigned-approver OR manage.

State machine: draft -> submitted -> approved/rejected; draft/submitted
may be cancelled (approved never). Approver is snapshotted from
``employees.manager_id`` at submit; reject requires a reason.
"""

from __future__ import annotations

from datetime import datetime
from datetime import timezone as dt_timezone

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.core.deps import Principal
from app.core.exceptions import (
    EmployeeRequestDecisionReasonError,
    EmployeeRequestForbiddenError,
    EmployeeRequestNotFoundError,
    EmployeeRequestPayloadError,
    EmployeeRequestRecordMismatchError,
    EmployeeRequestStateError,
    EssNotLinkedError,
    ForbiddenError,
)
from app.core.pagination import PageParams
from app.ess.attendance import apply_attendance_correction
from app.ess.payloads import validate_payload
from app.ess.schemas import RequestCreate, RequestDecision, RequestUpdate
from app.shared.models import Employee, EmployeeRequest, EmployeeRequestEvent, User


def _now() -> datetime:
    return datetime.now(dt_timezone.utc)


def _require(principal: Principal, code: str, company_id: int | None) -> None:
    """Company-scoped permission check (H1)."""
    if not principal.has_permission(code, company_id):
        raise ForbiddenError(f"Missing permission: {code}")


# ---------------------------------------------------------------------------
# Self-scope helpers (shared with app.ess.me_service)
# ---------------------------------------------------------------------------


def self_employee_id(db: Session, principal: Principal) -> int | None:
    user = db.get(User, principal.user_id)
    if user is None:
        return None
    return user.employee_id


def self_employee(db: Session, principal: Principal) -> Employee:
    """The caller's linked employee or ESS_NOT_LINKED (403)."""
    employee_id = self_employee_id(db, principal)
    if employee_id is None:
        raise EssNotLinkedError("Your account is not linked to an employee")
    employee = db.get(Employee, employee_id)
    if employee is None or not principal.can_access_company(employee.company_id):
        raise EssNotLinkedError("Your account is not linked to an employee")
    return employee


def _require_request_verb(
    db: Session,
    principal: Principal,
    company_id: int,
    owner_employee_id: int,
    verb: str,
) -> None:
    _require(principal, verb, company_id)
    self_id = self_employee_id(db, principal)
    if owner_employee_id != self_id:
        _require(principal, "employee_request.view", company_id)


def _can_read_request(
    db: Session, principal: Principal, row: EmployeeRequest
) -> bool:
    if principal.has_permission("employee_request.manage", row.company_id):
        return True
    if principal.has_permission("employee_request.view", row.company_id):
        return True
    self_id = self_employee_id(db, principal)
    if self_id is None:
        return False
    if row.employee_id == self_id and principal.has_permission(
        "employee_request.create", row.company_id
    ):
        return True
    return row.approver_employee_id == self_id and (
        principal.has_permission("employee_request.approve", row.company_id)
        or principal.has_permission("employee_request.reject", row.company_id)
    )


def _require_decision(
    db: Session, principal: Principal, row: EmployeeRequest, verb: str
) -> None:
    if principal.has_permission("employee_request.manage", row.company_id):
        return
    self_id = self_employee_id(db, principal)
    if (
        self_id is not None
        and row.approver_employee_id == self_id
        and principal.has_permission(verb, row.company_id)
    ):
        return
    raise EmployeeRequestForbiddenError(
        "You are not authorized to decide this request"
    )


# ---------------------------------------------------------------------------
# Fetch / state helpers
# ---------------------------------------------------------------------------


def _fetch_request(
    db: Session, request_id: int, principal: Principal, *, lock: bool = False
) -> EmployeeRequest:
    stmt = select(EmployeeRequest).where(EmployeeRequest.id == request_id)
    if lock:
        stmt = stmt.with_for_update()
    row = db.execute(stmt).scalar_one_or_none()
    if row is None or not principal.can_access_company(row.company_id):
        raise EmployeeRequestNotFoundError("Employee request not found")
    return row


def _require_state(row: EmployeeRequest, allowed: set[str], action: str) -> None:
    if row.status not in allowed:
        raise EmployeeRequestStateError(
            f"Cannot {action} a request in status '{row.status}'"
        )


def _fetch_employee(
    db: Session, employee_id: int, principal: Principal
) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None or not principal.can_access_company(employee.company_id):
        raise EmployeeRequestNotFoundError("Employee not found")
    return employee


def _require_active(employee: Employee) -> None:
    if employee.status != "active":
        raise ForbiddenError("Requests are only available for active employees")


def _assert_no_open_correction(
    db: Session,
    *,
    company_id: int,
    employee_id: int,
    work_date,
    exclude_id: int | None = None,
) -> None:
    stmt = select(EmployeeRequest.id).where(
        EmployeeRequest.company_id == company_id,
        EmployeeRequest.employee_id == employee_id,
        EmployeeRequest.request_type == "attendance_correction",
        EmployeeRequest.work_date == work_date,
        EmployeeRequest.status.in_(("draft", "submitted")),
    )
    if exclude_id is not None:
        stmt = stmt.where(EmployeeRequest.id != exclude_id)
    if db.execute(stmt.limit(1)).scalar_one_or_none() is not None:
        raise EmployeeRequestStateError(
            "An attendance correction for this date is already open"
        )


# ---------------------------------------------------------------------------
# Events / audit
# ---------------------------------------------------------------------------


def _actor_name(db: Session, principal: Principal) -> str:
    user = db.get(User, principal.user_id)
    if user is not None and user.full_name:
        return user.full_name
    return principal.email


def _add_event(
    db: Session,
    row: EmployeeRequest,
    principal: Principal,
    event_type: str,
    note: str | None = None,
) -> None:
    db.add(
        EmployeeRequestEvent(
            company_id=row.company_id,
            request_id=row.id,
            event_type=event_type,
            actor_user_id=principal.user_id,
            actor_name=_actor_name(db, principal),
            note=(note[:500] if note else None),
        )
    )


def _snapshot(row: EmployeeRequest) -> dict:
    return {
        "employee_id": row.employee_id,
        "approver_employee_id": row.approver_employee_id,
        "request_type": row.request_type,
        "status": row.status,
        "subject": row.subject,
        "work_date": str(row.work_date) if row.work_date else None,
    }


def _audit(
    db: Session,
    *,
    action: str,
    row: EmployeeRequest,
    principal: Principal,
    ip: str | None,
    old_value: dict | None = None,
    new_value: dict | None = None,
) -> None:
    record_audit(
        db,
        action=action,
        entity="employee_request",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        old_value=old_value,
        new_value=new_value or _snapshot(row),
        ip_address=ip,
    )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def list_requests(
    db: Session,
    principal: Principal,
    *,
    company_id: int | None = None,
    employee_id: int | None = None,
    request_type: str | None = None,
    status: str | None = None,
    page: PageParams | None = None,
) -> tuple[list[EmployeeRequest], int]:
    """List with Phase 5 self-scope fallback: ``view`` sees the company;
    create-only callers are forced to their own rows."""
    self_id = self_employee_id(db, principal)
    stmt = select(EmployeeRequest)
    count_stmt = select(func.count()).select_from(EmployeeRequest)
    forced_employee: int | None = None

    if company_id is not None:
        if not principal.can_access_company(company_id):
            raise ForbiddenError("You cannot access this company")
        if principal.has_permission("employee_request.view", company_id):
            pass
        elif self_id is not None and principal.has_permission(
            "employee_request.create", company_id
        ):
            if employee_id is not None and employee_id != self_id:
                raise ForbiddenError("Missing permission: employee_request.view")
            forced_employee = self_id
        else:
            raise ForbiddenError("Missing permission: employee_request.view")
        stmt = stmt.where(EmployeeRequest.company_id == company_id)
        count_stmt = count_stmt.where(EmployeeRequest.company_id == company_id)
    elif not principal.is_platform_admin:
        view_ids = principal.permitted_company_ids("employee_request.view")
        if view_ids:
            stmt = stmt.where(EmployeeRequest.company_id.in_(view_ids))
            count_stmt = count_stmt.where(
                EmployeeRequest.company_id.in_(view_ids)
            )
        else:
            create_ids = principal.permitted_company_ids(
                "employee_request.create"
            )
            if not create_ids or self_id is None:
                raise ForbiddenError("Missing permission: employee_request.view")
            if employee_id is not None and employee_id != self_id:
                raise ForbiddenError("Missing permission: employee_request.view")
            forced_employee = self_id
            stmt = stmt.where(EmployeeRequest.company_id.in_(create_ids))
            count_stmt = count_stmt.where(
                EmployeeRequest.company_id.in_(create_ids)
            )

    if forced_employee is not None:
        employee_id = forced_employee
    if employee_id is not None:
        stmt = stmt.where(EmployeeRequest.employee_id == employee_id)
        count_stmt = count_stmt.where(EmployeeRequest.employee_id == employee_id)
    if request_type is not None:
        stmt = stmt.where(EmployeeRequest.request_type == request_type)
        count_stmt = count_stmt.where(
            EmployeeRequest.request_type == request_type
        )
    if status is not None:
        stmt = stmt.where(EmployeeRequest.status == status)
        count_stmt = count_stmt.where(EmployeeRequest.status == status)

    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(EmployeeRequest.id.desc())
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


def get_request(
    db: Session, request_id: int, principal: Principal
) -> EmployeeRequest:
    row = _fetch_request(db, request_id, principal)
    if not _can_read_request(db, principal, row):
        raise EmployeeRequestForbiddenError("You cannot view this request")
    return row


def get_request_detail(
    db: Session, request_id: int, principal: Principal
) -> tuple[EmployeeRequest, list[EmployeeRequestEvent]]:
    row = get_request(db, request_id, principal)
    events = list(
        db.execute(
            select(EmployeeRequestEvent)
            .where(EmployeeRequestEvent.request_id == row.id)
            .order_by(EmployeeRequestEvent.id)
        ).scalars()
    )
    return row, events


def list_approvals(
    db: Session,
    principal: Principal,
    *,
    company_id: int | None = None,
    status: str | None = "submitted",
    page: PageParams | None = None,
) -> tuple[list[EmployeeRequest], int]:
    """Decision inbox: manage holders see their companies' rows; decide
    holders see only rows assigned to them as approver."""
    self_id = self_employee_id(db, principal)
    manage_ids = principal.permitted_company_ids("employee_request.manage")
    decide_ids = sorted(
        set(principal.permitted_company_ids("employee_request.approve"))
        | set(principal.permitted_company_ids("employee_request.reject"))
    )

    stmt = select(EmployeeRequest)
    count_stmt = select(func.count()).select_from(EmployeeRequest)

    if company_id is not None:
        if not principal.can_access_company(company_id):
            raise ForbiddenError("You cannot access this company")
        can_manage = principal.has_permission(
            "employee_request.manage", company_id
        )
        can_decide = principal.has_permission(
            "employee_request.approve", company_id
        ) or principal.has_permission("employee_request.reject", company_id)
        if not can_manage and not can_decide:
            raise ForbiddenError("Missing permission: employee_request.approve")
        stmt = stmt.where(EmployeeRequest.company_id == company_id)
        count_stmt = count_stmt.where(EmployeeRequest.company_id == company_id)
        if not can_manage:
            if self_id is None:
                return [], 0
            stmt = stmt.where(EmployeeRequest.approver_employee_id == self_id)
            count_stmt = count_stmt.where(
                EmployeeRequest.approver_employee_id == self_id
            )
    elif not principal.is_platform_admin:
        if not manage_ids and not decide_ids:
            raise ForbiddenError("Missing permission: employee_request.approve")
        clauses = []
        if manage_ids:
            clauses.append(EmployeeRequest.company_id.in_(manage_ids))
        if decide_ids and self_id is not None:
            clauses.append(
                (EmployeeRequest.company_id.in_(decide_ids))
                & (EmployeeRequest.approver_employee_id == self_id)
            )
        if not clauses:
            return [], 0
        clause = or_(*clauses)
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)

    if status:
        stmt = stmt.where(EmployeeRequest.status == status)
        count_stmt = count_stmt.where(EmployeeRequest.status == status)

    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(
        EmployeeRequest.submitted_at.asc().nulls_last(),
        EmployeeRequest.id.asc(),
    )
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


def create_request(
    db: Session,
    *,
    payload: RequestCreate,
    principal: Principal,
    ip: str | None,
) -> EmployeeRequest:
    self_id = self_employee_id(db, principal)
    employee_id = (
        payload.employee_id if payload.employee_id is not None else self_id
    )
    if employee_id is None:
        raise EssNotLinkedError("Your account is not linked to an employee")
    employee = _fetch_employee(db, employee_id, principal)
    _require_request_verb(
        db, principal, employee.company_id, employee.id, "employee_request.create"
    )
    _require_active(employee)

    subject = payload.subject.strip()
    if not subject:
        raise EmployeeRequestPayloadError("subject is required")
    normalized, work_date = validate_payload(
        payload.request_type, payload.payload
    )
    if work_date is not None:
        _assert_no_open_correction(
            db,
            company_id=employee.company_id,
            employee_id=employee.id,
            work_date=work_date,
        )

    row = EmployeeRequest(
        company_id=employee.company_id,
        employee_id=employee.id,
        request_type=payload.request_type,
        status="draft",
        subject=subject,
        reason=(payload.reason.strip() if payload.reason else None) or None,
        payload=normalized,
        work_date=work_date,
        created_by=principal.user_id,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        raise EmployeeRequestStateError(
            "An attendance correction for this date is already open"
        ) from exc
    _add_event(db, row, principal, "created")
    _audit(db, action="employee_request.create", row=row, principal=principal, ip=ip)
    db.flush()
    return row


def update_request(
    db: Session,
    *,
    request_id: int,
    payload: RequestUpdate,
    principal: Principal,
    ip: str | None,
) -> EmployeeRequest:
    row = _fetch_request(db, request_id, principal, lock=True)
    _require_state(row, {"draft"}, "update")
    _require_request_verb(
        db, principal, row.company_id, row.employee_id, "employee_request.update"
    )
    old = _snapshot(row)

    if payload.subject is not None:
        subject = payload.subject.strip()
        if not subject:
            raise EmployeeRequestPayloadError("subject is required")
        row.subject = subject
    if payload.reason is not None:
        row.reason = payload.reason.strip() or None
    if payload.payload is not None:
        normalized, work_date = validate_payload(row.request_type, payload.payload)
        row.payload = normalized
        if row.request_type == "attendance_correction":
            assert work_date is not None
            if work_date != row.work_date:
                _assert_no_open_correction(
                    db,
                    company_id=row.company_id,
                    employee_id=row.employee_id,
                    work_date=work_date,
                    exclude_id=row.id,
                )
                row.work_date = work_date

    db.add(row)
    db.flush()
    _add_event(db, row, principal, "updated")
    _audit(
        db,
        action="employee_request.update",
        row=row,
        principal=principal,
        ip=ip,
        old_value=old,
    )
    db.flush()
    return row


def submit_request(
    db: Session,
    *,
    request_id: int,
    principal: Principal,
    ip: str | None,
) -> EmployeeRequest:
    row = _fetch_request(db, request_id, principal, lock=True)
    _require_state(row, {"draft"}, "submit")
    _require_request_verb(
        db, principal, row.company_id, row.employee_id, "employee_request.submit"
    )
    employee = _fetch_employee(db, row.employee_id, principal)
    _require_active(employee)

    _validate_payload_matches_record(row)
    if row.work_date is not None:
        _assert_no_open_correction(
            db,
            company_id=row.company_id,
            employee_id=row.employee_id,
            work_date=row.work_date,
            exclude_id=row.id,
        )

    old = _snapshot(row)
    row.status = "submitted"
    row.submitted_by = principal.user_id
    row.submitted_at = _now()
    # Approver snapshot at submit; never self-assigned.
    manager_id = employee.manager_id
    row.approver_employee_id = (
        manager_id if manager_id is not None and manager_id != employee.id else None
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        raise EmployeeRequestStateError(
            "An attendance correction for this date is already open"
        ) from exc
    _add_event(db, row, principal, "submitted")
    _audit(
        db,
        action="employee_request.submit",
        row=row,
        principal=principal,
        ip=ip,
        old_value=old,
    )
    db.flush()
    return row


def _validate_payload_matches_record(row: EmployeeRequest) -> None:
    """Re-validate the stored payload and require agreement with the
    denormalized work_date column (RECORD_MISMATCH guard)."""
    normalized, work_date = validate_payload(row.request_type, row.payload)
    row.payload = normalized
    if row.request_type == "attendance_correction" and work_date != row.work_date:
        raise EmployeeRequestRecordMismatchError(
            "payload.work_date does not match the request record"
        )


def cancel_request(
    db: Session,
    *,
    request_id: int,
    payload: RequestDecision | None,
    principal: Principal,
    ip: str | None,
) -> EmployeeRequest:
    row = _fetch_request(db, request_id, principal, lock=True)
    _require_state(row, {"draft", "submitted"}, "cancel")
    _require_request_verb(
        db, principal, row.company_id, row.employee_id, "employee_request.cancel"
    )
    old = _snapshot(row)
    reason = payload.reason.strip() if payload and payload.reason else None
    row.status = "cancelled"
    row.cancel_reason = reason or None
    row.cancelled_by = principal.user_id
    row.cancelled_at = _now()
    db.add(row)
    db.flush()
    _add_event(db, row, principal, "cancelled", note=reason)
    _audit(
        db,
        action="employee_request.cancel",
        row=row,
        principal=principal,
        ip=ip,
        old_value=old,
    )
    db.flush()
    return row


def approve_request(
    db: Session,
    *,
    request_id: int,
    payload: RequestDecision | None,
    principal: Principal,
    ip: str | None,
) -> EmployeeRequest:
    row = _fetch_request(db, request_id, principal, lock=True)
    _require_state(row, {"submitted"}, "approve")
    _require_decision(db, principal, row, "employee_request.approve")
    employee = _fetch_employee(db, row.employee_id, principal)
    old = _snapshot(row)

    if row.request_type == "attendance_correction":
        apply_attendance_correction(
            db, row=row, employee=employee, principal=principal, ip=ip
        )

    row.status = "approved"
    row.decision_reason = (
        payload.reason.strip() if payload and payload.reason else None
    )
    row.decided_by = principal.user_id
    row.decided_at = _now()
    db.add(row)
    db.flush()
    _add_event(db, row, principal, "approved", note=row.decision_reason)
    _audit(
        db,
        action="employee_request.approve",
        row=row,
        principal=principal,
        ip=ip,
        old_value=old,
    )
    db.flush()
    return row


def reject_request(
    db: Session,
    *,
    request_id: int,
    payload: RequestDecision | None,
    principal: Principal,
    ip: str | None,
) -> EmployeeRequest:
    row = _fetch_request(db, request_id, principal, lock=True)
    _require_state(row, {"submitted"}, "reject")
    _require_decision(db, principal, row, "employee_request.reject")
    reason = payload.reason if payload else None
    if not reason or not reason.strip():
        raise EmployeeRequestDecisionReasonError(
            "A reason is required to reject a request"
        )
    old = _snapshot(row)
    row.status = "rejected"
    row.decision_reason = reason.strip()
    row.decided_by = principal.user_id
    row.decided_at = _now()
    db.add(row)
    db.flush()
    _add_event(db, row, principal, "rejected", note=row.decision_reason)
    _audit(
        db,
        action="employee_request.reject",
        row=row,
        principal=principal,
        ip=ip,
        old_value=old,
    )
    db.flush()
    return row
