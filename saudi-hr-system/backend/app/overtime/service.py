from __future__ import annotations

from datetime import date, datetime
from datetime import timezone as dt_timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.core.deps import Principal
from app.core.exceptions import (
    AttendanceNotFoundError,
    CorrectionReasonRequiredError,
    EmployeeNotFoundError,
    ForbiddenError,
    OvertimeAlreadyApprovedError,
    OvertimeApprovalRequiredError,
    OvertimeInvalidMinutesError,
    OvertimeInvalidTransitionError,
    OvertimeNotFoundError,
)
from app.core.pagination import PageParams
from app.overtime.schemas import (
    OvertimeApprove,
    OvertimeCorrect,
    OvertimeCreate,
    OvertimeDecision,
    OvertimeUpdate,
)
from app.shared.models import AttendanceRecord, Employee, OvertimeRecord


def _now() -> datetime:
    return datetime.now(dt_timezone.utc)


def _require(principal: Principal, code: str, company_id: int | None) -> None:
    """Company-scoped permission check (H1)."""
    if not principal.has_permission(code, company_id):
        raise ForbiddenError(f"Missing permission: {code}")


def _resolve_employee(db: Session, employee_id: int, principal: Principal) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None or not principal.can_access_company(employee.company_id):
        raise EmployeeNotFoundError("Employee not found")
    return employee


def _fetch(db: Session, overtime_id: int, principal: Principal) -> OvertimeRecord:
    row = db.get(OvertimeRecord, overtime_id)
    if row is None or not principal.can_access_company(row.company_id):
        raise OvertimeNotFoundError("Overtime request not found")
    return row


def _check_attendance(
    db: Session, employee: Employee, attendance_id: int | None
) -> None:
    if attendance_id is None:
        return
    row = db.get(AttendanceRecord, attendance_id)
    if row is None or row.company_id != employee.company_id or (
        row.employee_id != employee.id
    ):
        raise AttendanceNotFoundError("Attendance record not found")


def _check_minutes(requested: int | None, approved: int | None = None) -> None:
    if requested is not None and not 1 <= requested <= 1440:
        raise OvertimeInvalidMinutesError(
            "requested_minutes must be between 1 and 1440"
        )
    if approved is not None and not 1 <= approved <= 1440:
        raise OvertimeInvalidMinutesError(
            "approved_minutes must be between 1 and 1440"
        )


def _snapshot(row: OvertimeRecord) -> dict:
    return {
        "employee_id": row.employee_id,
        "work_date": str(row.work_date),
        "status": row.status,
        "requested_minutes": row.requested_minutes,
        "approved_minutes": row.approved_minutes,
    }


def _transition_guard(row: OvertimeRecord, allowed: set[str]) -> None:
    """Raise the stable Phase 4 codes for illegal workflow jumps."""
    if row.status in allowed:
        return
    if row.status == "approved":
        raise OvertimeAlreadyApprovedError(
            "Overtime request is already approved"
        )
    if row.status == "draft" and allowed <= {"submitted"}:
        raise OvertimeApprovalRequiredError(
            "Overtime request must be submitted before this action"
        )
    raise OvertimeInvalidTransitionError(
        f"Cannot perform this action while status is '{row.status}'"
    )


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def list_overtime(
    db: Session,
    principal: Principal,
    *,
    company_id: int | None = None,
    employee_id: int | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: PageParams | None = None,
) -> tuple[list[OvertimeRecord], int]:
    stmt = select(OvertimeRecord)
    count_stmt = select(func.count()).select_from(OvertimeRecord)
    if company_id is not None:
        if not principal.can_access_company(company_id):
            raise ForbiddenError("You cannot access this company")
        _require(principal, "overtime.view", company_id)
        stmt = stmt.where(OvertimeRecord.company_id == company_id)
        count_stmt = count_stmt.where(OvertimeRecord.company_id == company_id)
    elif not principal.is_platform_admin:
        allowed = principal.permitted_company_ids("overtime.view")
        if not allowed:
            return [], 0
        stmt = stmt.where(OvertimeRecord.company_id.in_(allowed))
        count_stmt = count_stmt.where(OvertimeRecord.company_id.in_(allowed))
    if employee_id is not None:
        stmt = stmt.where(OvertimeRecord.employee_id == employee_id)
        count_stmt = count_stmt.where(
            OvertimeRecord.employee_id == employee_id
        )
    if status is not None:
        stmt = stmt.where(OvertimeRecord.status == status)
        count_stmt = count_stmt.where(OvertimeRecord.status == status)
    if date_from is not None:
        stmt = stmt.where(OvertimeRecord.work_date >= date_from)
        count_stmt = count_stmt.where(OvertimeRecord.work_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(OvertimeRecord.work_date <= date_to)
        count_stmt = count_stmt.where(OvertimeRecord.work_date <= date_to)
    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(
        OvertimeRecord.work_date.desc(), OvertimeRecord.id.desc()
    )
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


def get_overtime(
    db: Session, overtime_id: int, principal: Principal
) -> OvertimeRecord:
    row = _fetch(db, overtime_id, principal)
    _require(principal, "overtime.view", row.company_id)
    return row


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


def create_overtime(
    db: Session, *, payload: OvertimeCreate, principal: Principal, ip: str | None
) -> OvertimeRecord:
    employee = _resolve_employee(db, payload.employee_id, principal)
    _require(principal, "overtime.create", employee.company_id)
    _check_minutes(payload.requested_minutes)
    _check_attendance(db, employee, payload.attendance_id)
    row = OvertimeRecord(
        company_id=employee.company_id,
        employee_id=employee.id,
        attendance_id=payload.attendance_id,
        work_date=payload.work_date,
        requested_minutes=payload.requested_minutes,
        status="draft",
        reason=payload.reason,
        notes=payload.notes,
        created_by=principal.user_id,
    )
    db.add(row)
    db.flush()
    record_audit(
        db,
        action="overtime.create",
        entity="overtime_record",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=employee.company_id,
        new_value=_snapshot(row),
        ip_address=ip,
    )
    db.flush()
    return row


def update_overtime(
    db: Session,
    *,
    overtime_id: int,
    payload: OvertimeUpdate,
    principal: Principal,
    ip: str | None,
) -> OvertimeRecord:
    row = _fetch(db, overtime_id, principal)
    _require(principal, "overtime.update", row.company_id)
    # Only drafts may be edited; approved requests are corrected instead.
    _transition_guard(row, allowed={"draft"})
    employee = db.get(Employee, row.employee_id)
    changes = payload.model_dump(exclude_unset=True)
    if "requested_minutes" in changes:
        _check_minutes(changes["requested_minutes"])
    if "attendance_id" in changes and employee is not None:
        _check_attendance(db, employee, changes["attendance_id"])
    for key, value in changes.items():
        setattr(row, key, value)
    db.add(row)
    db.flush()
    record_audit(
        db,
        action="overtime.update",
        entity="overtime_record",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        new_value={"fields": sorted(changes)},
        ip_address=ip,
    )
    db.flush()
    return row


def submit_overtime(
    db: Session, *, overtime_id: int, principal: Principal, ip: str | None
) -> OvertimeRecord:
    row = _fetch(db, overtime_id, principal)
    _require(principal, "overtime.submit", row.company_id)
    _transition_guard(row, allowed={"draft"})
    old = _snapshot(row)
    row.status = "submitted"
    row.submitted_by = principal.user_id
    row.submitted_at = _now()
    db.add(row)
    db.flush()
    record_audit(
        db,
        action="overtime.submit",
        entity="overtime_record",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        old_value=old,
        new_value=_snapshot(row),
        ip_address=ip,
    )
    db.flush()
    return row


def approve_overtime(
    db: Session,
    *,
    overtime_id: int,
    payload: OvertimeApprove,
    principal: Principal,
    ip: str | None,
) -> OvertimeRecord:
    row = _fetch(db, overtime_id, principal)
    _require(principal, "overtime.approve", row.company_id)
    _transition_guard(row, allowed={"submitted"})
    approved = (
        payload.approved_minutes
        if payload.approved_minutes is not None
        else row.requested_minutes
    )
    _check_minutes(row.requested_minutes, approved)
    if approved > row.requested_minutes:
        raise OvertimeInvalidMinutesError(
            "approved_minutes cannot exceed requested_minutes"
        )
    old = _snapshot(row)
    row.status = "approved"
    row.approved_minutes = approved
    row.decision_reason = payload.reason
    row.decided_by = principal.user_id
    row.decided_at = _now()
    db.add(row)
    db.flush()
    record_audit(
        db,
        action="overtime.approve",
        entity="overtime_record",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        old_value=old,
        new_value=_snapshot(row),
        ip_address=ip,
    )
    db.flush()
    return row


def reject_overtime(
    db: Session,
    *,
    overtime_id: int,
    payload: OvertimeDecision,
    principal: Principal,
    ip: str | None,
) -> OvertimeRecord:
    row = _fetch(db, overtime_id, principal)
    _require(principal, "overtime.reject", row.company_id)
    _transition_guard(row, allowed={"submitted"})
    old = _snapshot(row)
    row.status = "rejected"
    row.approved_minutes = None
    row.decision_reason = payload.reason
    row.decided_by = principal.user_id
    row.decided_at = _now()
    db.add(row)
    db.flush()
    record_audit(
        db,
        action="overtime.reject",
        entity="overtime_record",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        old_value=old,
        new_value=_snapshot(row),
        ip_address=ip,
    )
    db.flush()
    return row


def cancel_overtime(
    db: Session,
    *,
    overtime_id: int,
    payload: OvertimeDecision,
    principal: Principal,
    ip: str | None,
) -> OvertimeRecord:
    row = _fetch(db, overtime_id, principal)
    _require(principal, "overtime.cancel", row.company_id)
    _transition_guard(row, allowed={"draft", "submitted", "approved"})
    old = _snapshot(row)
    row.status = "cancelled"
    row.decision_reason = payload.reason
    row.decided_by = principal.user_id
    row.decided_at = _now()
    db.add(row)
    db.flush()
    record_audit(
        db,
        action="overtime.cancel",
        entity="overtime_record",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        old_value=old,
        new_value=_snapshot(row),
        ip_address=ip,
    )
    db.flush()
    return row


def correct_overtime(
    db: Session,
    *,
    overtime_id: int,
    payload: OvertimeCorrect,
    principal: Principal,
    ip: str | None,
) -> OvertimeRecord:
    """Controlled amendment of an APPROVED request (reason + audit)."""
    row = _fetch(db, overtime_id, principal)
    _require(principal, "overtime.approve", row.company_id)
    if row.status != "approved":
        raise OvertimeApprovalRequiredError(
            "Only approved overtime requests can be corrected"
        )
    if not payload.reason or not payload.reason.strip():
        raise CorrectionReasonRequiredError(
            "A reason is required to correct an approved overtime request"
        )
    if payload.approved_minutes > row.requested_minutes:
        raise OvertimeInvalidMinutesError(
            "approved_minutes cannot exceed requested_minutes"
        )
    old = _snapshot(row)
    row.approved_minutes = payload.approved_minutes
    row.correction_reason = payload.reason
    row.corrected_by = principal.user_id
    row.corrected_at = _now()
    db.add(row)
    db.flush()
    record_audit(
        db,
        action="overtime.correct",
        entity="overtime_record",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        old_value=old,
        new_value={**_snapshot(row), "reason": payload.reason},
        ip_address=ip,
    )
    db.flush()
    return row
