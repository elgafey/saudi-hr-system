from __future__ import annotations

from datetime import date, datetime
from datetime import timezone as dt_timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.attendance.calculation import compute_metrics
from app.attendance.schemas import (
    AttendanceCheckIn,
    AttendanceCheckOut,
    AttendanceCreate,
    AttendanceUpdate,
)
from app.audit.service import record_audit
from app.core.deps import Principal
from app.core.exceptions import (
    AttendanceAlreadyOpenError,
    AttendanceMissingCheckoutError,
    AttendanceNotFoundError,
    AttendanceOverlapError,
    AttendanceTimeRangeError,
    CorrectionReasonRequiredError,
    EmployeeNotFoundError,
    ForbiddenError,
)
from app.core.pagination import PageParams
from app.shared.models import AttendanceRecord, Employee
from app.work_schedules.resolution import resolve_employee_schedule
from app.work_schedules.timeutils import validate_timezone


# Naive timestamps are interpreted in the schedule timezone (fallback: the
# company timezone, default Asia/Riyadh) - see docs/PHASE4.md.
def _company_timezone(db: Session, company_id: int) -> str:
    from app.shared.models import Company

    company = db.get(Company, company_id)
    if company is not None and company.timezone:
        return company.timezone
    return "Asia/Riyadh"


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


def _fetch(db: Session, attendance_id: int, principal: Principal) -> AttendanceRecord:
    record = db.get(AttendanceRecord, attendance_id)
    if record is None or not principal.can_access_company(record.company_id):
        raise AttendanceNotFoundError("Attendance record not found")
    return record


def _localize(
    db: Session, employee: Employee, value: datetime, fallback_date: date | None = None
) -> datetime:
    """Attach/convert a timestamp to the employee's schedule timezone.

    Naive input is interpreted in the schedule timezone; aware input is
    converted into it. The provisional resolution date comes from the
    timestamp itself (or ``fallback_date`` for explicit overrides)."""
    target = fallback_date or value.date()
    resolved = resolve_employee_schedule(db, employee, target)
    tz = validate_timezone(resolved.timezone)
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)


def _context(
    db: Session, employee: Employee, check_in: datetime
) -> tuple[datetime, date, object]:
    """Resolve (aware check_in, work_date, ResolvedDay) for a check-in.

    The resolution date comes from the company timezone (so the right
    day's schedule is found), then a NAIVE timestamp is interpreted in
    that schedule's timezone (an aware one is converted into it)."""
    if check_in.tzinfo is None:
        tz = validate_timezone(_company_timezone(db, employee.company_id))
        target = check_in.replace(tzinfo=tz).date()
    else:
        target = check_in.date()
    resolved = resolve_employee_schedule(db, employee, target)
    tz = validate_timezone(resolved.timezone)
    if check_in.tzinfo is None:
        check_in = check_in.replace(tzinfo=tz)
    else:
        check_in = check_in.astimezone(tz)
    if check_in.date() != target:
        # Crossing midnight in the schedule timezone: re-anchor.
        resolved = resolve_employee_schedule(db, employee, check_in.date())
        tz = validate_timezone(resolved.timezone)
        if check_in.tzinfo is not None:
            check_in = check_in.astimezone(tz)
    return check_in, check_in.date(), resolved


def _normalize(
    check_out: datetime | None,
    status: str | None,
    default_status: str | None = None,
) -> tuple[datetime | None, str]:
    """Normalize (check_out, status) into a consistent pair.

    - explicit open/missing_checkout clears check_out;
    - completed without check_out raises ATTENDANCE_MISSING_CHECKOUT;
    - check_out present implies completed.
    """
    if status in ("open", "missing_checkout"):
        check_out = None
    if check_out is None:
        if status == "completed":
            raise AttendanceMissingCheckoutError(
                "A completed record needs a check_out timestamp"
            )
        status = status or default_status or "open"
        if status not in ("open", "missing_checkout"):
            status = "open"
    else:
        status = "completed"
    return check_out, status


def _assert_no_open(
    db: Session, employee: Employee, exclude_id: int | None = None
) -> None:
    stmt = select(AttendanceRecord.id).where(
        AttendanceRecord.employee_id == employee.id,
        AttendanceRecord.status == "open",
    )
    if exclude_id is not None:
        stmt = stmt.where(AttendanceRecord.id != exclude_id)
    if db.execute(stmt.limit(1)).scalar_one_or_none() is not None:
        raise AttendanceAlreadyOpenError(
            "Employee already has an open attendance record"
        )


def _assert_no_overlap(
    db: Session,
    employee: Employee,
    check_in: datetime,
    check_out: datetime | None,
    status: str,
    exclude_id: int | None = None,
) -> None:
    """Reject windows that intersect another record for the same employee.

    - missing_checkout rows are inert (no known end) - they never block;
    - an OPEN row conflicts with any record that would intersect it once
      closed (one open record per employee is checked separately);
    - closed rows are checked with half-open [check_in, check_out)
      semantics, matching the database EXCLUDE constraint.
    """
    if status == "missing_checkout":
        return
    stmt = select(AttendanceRecord).where(
        AttendanceRecord.employee_id == employee.id
    )
    if exclude_id is not None:
        stmt = stmt.where(AttendanceRecord.id != exclude_id)
    for other in db.execute(stmt).scalars():
        if other.status == "missing_checkout":
            continue
        if check_out is None:  # ours open
            if other.status == "open":
                continue  # covered by _assert_no_open
            if other.check_out is not None and other.check_out > check_in:
                raise AttendanceOverlapError(
                    "Attendance window overlaps another record"
                )
        else:  # ours closed
            if other.status == "open":
                if other.check_in < check_out:
                    raise AttendanceOverlapError(
                        "Attendance window overlaps another record"
                    )
            elif (
                other.check_in < check_out and other.check_out > check_in
            ):
                raise AttendanceOverlapError(
                    "Attendance window overlaps another record"
                )


def _validate_range(check_in: datetime, check_out: datetime | None) -> None:
    if check_out is not None and check_out <= check_in:
        raise AttendanceTimeRangeError("check_out must be after check_in")


def _apply_metrics(
    record: AttendanceRecord, metrics: dict[str, int] | None
) -> None:
    if metrics is None:
        record.scheduled_minutes = None
        record.worked_minutes = None
        record.break_minutes = None
        record.late_minutes = None
        record.early_leave_minutes = None
        record.overtime_candidate_minutes = None
        return
    for key, value in metrics.items():
        setattr(record, key, value)


def _refresh_resolution(
    db: Session, employee: Employee, record: AttendanceRecord
) -> object:
    resolved = resolve_employee_schedule(db, employee, record.work_date)
    record.schedule_id = resolved.schedule.id if resolved.schedule else None
    record.shift_id = resolved.shift.id if resolved.shift else None
    metrics = compute_metrics(
        resolved, record.work_date, record.check_in, record.check_out
    )
    _apply_metrics(record, metrics)
    return resolved


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def list_attendance(
    db: Session,
    principal: Principal,
    *,
    company_id: int | None = None,
    employee_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    status: str | None = None,
    department_id: int | None = None,
    branch_id: int | None = None,
    schedule_id: int | None = None,
    shift_id: int | None = None,
    page: PageParams | None = None,
) -> tuple[list[AttendanceRecord], int]:
    stmt = select(AttendanceRecord)
    count_stmt = select(func.count()).select_from(AttendanceRecord)
    if department_id is not None or branch_id is not None:
        stmt = stmt.join(Employee, AttendanceRecord.employee_id == Employee.id)
        count_stmt = count_stmt.join(
            Employee, AttendanceRecord.employee_id == Employee.id
        )
    if company_id is not None:
        if not principal.can_access_company(company_id):
            raise ForbiddenError("You cannot access this company")
        _require(principal, "attendance.view", company_id)
        stmt = stmt.where(AttendanceRecord.company_id == company_id)
        count_stmt = count_stmt.where(
            AttendanceRecord.company_id == company_id
        )
    elif not principal.is_platform_admin:
        allowed = principal.permitted_company_ids("attendance.view")
        if not allowed:
            return [], 0
        stmt = stmt.where(AttendanceRecord.company_id.in_(allowed))
        count_stmt = count_stmt.where(
            AttendanceRecord.company_id.in_(allowed)
        )
    if employee_id is not None:
        stmt = stmt.where(AttendanceRecord.employee_id == employee_id)
        count_stmt = count_stmt.where(
            AttendanceRecord.employee_id == employee_id
        )
    if date_from is not None:
        stmt = stmt.where(AttendanceRecord.work_date >= date_from)
        count_stmt = count_stmt.where(AttendanceRecord.work_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(AttendanceRecord.work_date <= date_to)
        count_stmt = count_stmt.where(AttendanceRecord.work_date <= date_to)
    if status is not None:
        stmt = stmt.where(AttendanceRecord.status == status)
        count_stmt = count_stmt.where(AttendanceRecord.status == status)
    if schedule_id is not None:
        stmt = stmt.where(AttendanceRecord.schedule_id == schedule_id)
        count_stmt = count_stmt.where(
            AttendanceRecord.schedule_id == schedule_id
        )
    if shift_id is not None:
        stmt = stmt.where(AttendanceRecord.shift_id == shift_id)
        count_stmt = count_stmt.where(AttendanceRecord.shift_id == shift_id)
    if department_id is not None:
        clause = Employee.department_id == department_id
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)
    if branch_id is not None:
        clause = Employee.branch_id == branch_id
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)
    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(
        AttendanceRecord.work_date.desc(), AttendanceRecord.id.desc()
    )
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


def get_attendance(
    db: Session, attendance_id: int, principal: Principal
) -> AttendanceRecord:
    record = _fetch(db, attendance_id, principal)
    _require(principal, "attendance.view", record.company_id)
    return record


# ---------------------------------------------------------------------------
# Capture (create / check-in / check-out)
# ---------------------------------------------------------------------------


def create_attendance(
    db: Session, *, payload: AttendanceCreate, principal: Principal, ip: str | None
) -> AttendanceRecord:
    employee = _resolve_employee(db, payload.employee_id, principal)
    _require(principal, "attendance.create", employee.company_id)
    check_in, work_date, resolved = _context(db, employee, payload.check_in)
    check_out, status = _normalize(payload.check_out, payload.status)
    if check_out is not None:
        check_out = _localize(db, employee, check_out, work_date)
    _validate_range(check_in, check_out)
    if status == "open":
        _assert_no_open(db, employee)
    _assert_no_overlap(db, employee, check_in, check_out, status)

    record = AttendanceRecord(
        company_id=employee.company_id,
        employee_id=employee.id,
        work_date=work_date,
        schedule_id=resolved.schedule.id if resolved.schedule else None,
        shift_id=resolved.shift.id if resolved.shift else None,
        check_in=check_in,
        check_out=check_out,
        status=status,
        source=payload.source,
        notes=payload.notes,
        created_by=principal.user_id,
    )
    if status == "completed":
        _apply_metrics(
            record,
            compute_metrics(resolved, work_date, check_in, check_out),
        )
    db.add(record)
    db.flush()
    record_audit(
        db,
        action="attendance.create",
        entity="attendance_record",
        record_id=record.id,
        actor_user_id=principal.user_id,
        company_id=employee.company_id,
        new_value={
            "employee_id": employee.id,
            "work_date": str(work_date),
            "status": status,
            "check_in": check_in.isoformat(),
            "check_out": check_out.isoformat() if check_out else None,
        },
        ip_address=ip,
    )
    db.flush()
    return record


def check_in(
    db: Session, *, payload: AttendanceCheckIn, principal: Principal, ip: str | None
) -> AttendanceRecord:
    employee = _resolve_employee(db, payload.employee_id, principal)
    _require(principal, "attendance.create", employee.company_id)
    at = payload.at if payload.at is not None else _now()
    check_in, work_date, resolved = _context(db, employee, at)
    _assert_no_open(db, employee)
    record = AttendanceRecord(
        company_id=employee.company_id,
        employee_id=employee.id,
        work_date=work_date,
        schedule_id=resolved.schedule.id if resolved.schedule else None,
        shift_id=resolved.shift.id if resolved.shift else None,
        check_in=check_in,
        check_out=None,
        status="open",
        source=payload.source,
        notes=payload.notes,
        created_by=principal.user_id,
    )
    db.add(record)
    db.flush()
    record_audit(
        db,
        action="attendance.check_in",
        entity="attendance_record",
        record_id=record.id,
        actor_user_id=principal.user_id,
        company_id=employee.company_id,
        new_value={
            "employee_id": employee.id,
            "work_date": str(work_date),
            "check_in": check_in.isoformat(),
            "source": payload.source,
        },
        ip_address=ip,
    )
    db.flush()
    return record


def check_out(
    db: Session, *, payload: AttendanceCheckOut, principal: Principal, ip: str | None
) -> AttendanceRecord:
    employee = _resolve_employee(db, payload.employee_id, principal)
    _require(principal, "attendance.update", employee.company_id)
    open_row = db.execute(
        select(AttendanceRecord).where(
            AttendanceRecord.employee_id == employee.id,
            AttendanceRecord.status == "open",
        )
    ).scalar_one_or_none()
    if open_row is None:
        raise AttendanceNotFoundError("No open attendance record for employee")
    at = payload.at if payload.at is not None else _now()
    schedule_tz = None
    if open_row.schedule_id is not None:
        from app.shared.models import WorkSchedule

        schedule = db.get(WorkSchedule, open_row.schedule_id)
        if schedule is not None:
            schedule_tz = schedule.timezone
    if at.tzinfo is None:
        tz = validate_timezone(
            schedule_tz or _company_timezone(db, employee.company_id)
        )
        at = at.replace(tzinfo=tz)
    else:
        at = at.astimezone(validate_timezone(schedule_tz or _company_timezone(db, employee.company_id)))
    _validate_range(open_row.check_in, at)
    _assert_no_overlap(
        db, employee, open_row.check_in, at, "completed", exclude_id=open_row.id
    )
    open_row.check_out = at
    open_row.status = "completed"
    open_row.closed_by = principal.user_id
    _refresh_resolution(db, employee, open_row)
    record_audit(
        db,
        action="attendance.check_out",
        entity="attendance_record",
        record_id=open_row.id,
        actor_user_id=principal.user_id,
        company_id=employee.company_id,
        new_value={
            "check_out": at.isoformat(),
            "status": "completed",
            "worked_minutes": open_row.worked_minutes,
            "overtime_candidate_minutes": open_row.overtime_candidate_minutes,
        },
        ip_address=ip,
    )
    db.flush()
    return open_row


# ---------------------------------------------------------------------------
# Corrections (update / delete)
# ---------------------------------------------------------------------------


def _snapshot(record: AttendanceRecord) -> dict:
    return {
        "employee_id": record.employee_id,
        "work_date": str(record.work_date),
        "check_in": record.check_in.isoformat(),
        "check_out": record.check_out.isoformat() if record.check_out else None,
        "status": record.status,
        "scheduled_minutes": record.scheduled_minutes,
        "worked_minutes": record.worked_minutes,
        "late_minutes": record.late_minutes,
        "overtime_candidate_minutes": record.overtime_candidate_minutes,
    }


def update_attendance(
    db: Session,
    *,
    attendance_id: int,
    payload: AttendanceUpdate,
    principal: Principal,
    ip: str | None,
) -> AttendanceRecord:
    record = _fetch(db, attendance_id, principal)
    _require(principal, "attendance.update", record.company_id)
    employee = db.get(Employee, record.employee_id)
    if employee is None:
        raise AttendanceNotFoundError("Attendance record not found")
    was_closed = record.status != "open"
    changes = payload.model_dump(exclude_unset=True)
    if was_closed:
        # Editing a closed record is a controlled correction.
        _require(principal, "attendance.correct", record.company_id)
        reason = changes.get("reason")
        if not reason or not str(reason).strip():
            raise CorrectionReasonRequiredError(
                "A reason is required to correct a closed attendance record"
            )

    old_snapshot = _snapshot(record) if was_closed else None

    check_in = changes.get("check_in", record.check_in)
    if "check_in" in changes:
        check_in = _localize(db, employee, check_in)
    check_out = changes.get("check_out", record.check_out)
    if check_out is not None:
        check_out = _localize(db, employee, check_out, check_in.date())
    status = changes.get("status")
    check_out, status = _normalize(
        check_out, status, default_status=record.status
    )
    _validate_range(check_in, check_out)
    if status == "open":
        _assert_no_open(db, employee, exclude_id=record.id)
    _assert_no_overlap(
        db, employee, check_in, check_out, status, exclude_id=record.id
    )

    record.check_in = check_in
    record.check_out = check_out
    record.status = status
    if "source" in changes:
        record.source = changes["source"]
    if "notes" in changes:
        record.notes = changes["notes"]
    record.work_date = check_in.date()
    if status == "completed":
        resolved = _refresh_resolution(db, employee, record)
    else:
        _apply_metrics(record, None)
        resolved = resolve_employee_schedule(db, employee, record.work_date)
        record.schedule_id = resolved.schedule.id if resolved.schedule else None
        record.shift_id = resolved.shift.id if resolved.shift else None
    if was_closed:
        record.correction_reason = changes.get("reason")
        record.corrected_by = principal.user_id
        record.corrected_at = _now()
    db.add(record)
    db.flush()
    record_audit(
        db,
        action="attendance.correct" if was_closed else "attendance.update",
        entity="attendance_record",
        record_id=record.id,
        actor_user_id=principal.user_id,
        company_id=record.company_id,
        old_value=old_snapshot,
        new_value=(
            {"reason": record.correction_reason, **_snapshot(record)}
            if was_closed
            else {"fields": sorted(changes)}
        ),
        ip_address=ip,
    )
    db.flush()
    return record


def delete_attendance(
    db: Session,
    *,
    attendance_id: int,
    reason: str | None,
    principal: Principal,
    ip: str | None,
) -> None:
    record = _fetch(db, attendance_id, principal)
    _require(principal, "attendance.delete", record.company_id)
    was_closed = record.status != "open"
    if was_closed:
        if not reason or not reason.strip():
            raise CorrectionReasonRequiredError(
                "A reason is required to delete a closed attendance record"
            )
    old_snapshot = _snapshot(record)
    record_audit(
        db,
        action="attendance.delete",
        entity="attendance_record",
        record_id=record.id,
        actor_user_id=principal.user_id,
        company_id=record.company_id,
        old_value=old_snapshot,
        new_value={"reason": reason} if was_closed else None,
        ip_address=ip,
    )
    db.delete(record)
    db.flush()
