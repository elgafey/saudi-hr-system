"""Attendance-correction business handler (Phase 7 request approval).

Runs inside ``approve_request`` with the request row locked: writes or
updates exactly one ``attendance_records`` row for the requested day,
stamps the frozen Phase 4 correction columns (``correction_reason``,
``corrected_by``, ``corrected_at``), recomputes schedule metrics through
the public Phase 4/5 helpers and audits ``attendance.correct``. Reuses
frozen calculation/resolution logic read-only; never invents times or
legal values.
"""

from __future__ import annotations

from datetime import datetime
from datetime import timezone as dt_timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.attendance.calculation import compute_metrics
from app.audit.service import record_audit
from app.core.deps import Principal
from app.core.exceptions import (
    AttendanceCorrectionError,
    AttendanceCorrectionStaleError,
    AttendanceOverlapError,
    EmployeeRequestRecordMismatchError,
)
from app.ess.payloads import validate_payload
from app.shared.models import AttendanceRecord, Employee, EmployeeRequest
from app.work_schedules.resolution import resolve_employee_schedule
from app.work_schedules.timeutils import validate_timezone


def _now() -> datetime:
    return datetime.now(dt_timezone.utc)


def _localize(
    db: Session, employee: Employee, value: datetime, work_date
) -> datetime:
    """Attach/convert to the employee's schedule timezone for ``work_date``
    (naive input interpreted in that timezone; aware input converted)."""
    resolved = resolve_employee_schedule(db, employee, work_date)
    tz = validate_timezone(resolved.timezone)
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)


def _assert_no_overlap(
    db: Session,
    employee: Employee,
    check_in: datetime,
    check_out: datetime,
    exclude_id: int | None,
) -> None:
    """Half-open [check_in, check_out) overlap guard against the employee's
    other records (mirrors the Phase 4 EXCLUDE-constraint semantics)."""
    stmt = select(AttendanceRecord).where(
        AttendanceRecord.employee_id == employee.id
    )
    if exclude_id is not None:
        stmt = stmt.where(AttendanceRecord.id != exclude_id)
    for other in db.execute(stmt).scalars():
        if other.status == "missing_checkout":
            continue
        if other.status == "open":
            if other.check_in < check_out:
                raise AttendanceOverlapError(
                    "Attendance window overlaps another record"
                )
        elif other.check_out is not None and (
            other.check_in < check_out and other.check_out > check_in
        ):
            raise AttendanceOverlapError(
                "Attendance window overlaps another record"
            )


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


def _snapshot(record: AttendanceRecord) -> dict:
    return {
        "employee_id": record.employee_id,
        "work_date": str(record.work_date),
        "check_in": record.check_in.isoformat(),
        "check_out": record.check_out.isoformat() if record.check_out else None,
        "status": record.status,
        "worked_minutes": record.worked_minutes,
        "late_minutes": record.late_minutes,
    }


def apply_attendance_correction(
    db: Session,
    *,
    row: EmployeeRequest,
    employee: Employee,
    principal: Principal,
    ip: str | None,
) -> AttendanceRecord:
    """Materialize an approved ``attendance_correction`` request.

    - payload must agree with the request record (RECORD_MISMATCH);
    - a record modified after submit invalidates the request (STALE);
    - the new window must not overlap the employee's other records;
    - an existing record for the day is updated, otherwise a completed
      manual record is created.
    """
    normalized, work_date = validate_payload(row.request_type, row.payload)
    if work_date is None or row.work_date is None or work_date != row.work_date:
        raise EmployeeRequestRecordMismatchError(
            "payload.work_date does not match the request record"
        )
    check_in = _localize(
        db, employee, datetime.fromisoformat(normalized["check_in"]), work_date
    )
    check_out = _localize(
        db, employee, datetime.fromisoformat(normalized["check_out"]), work_date
    )
    if check_out <= check_in:
        raise AttendanceCorrectionError("check_out must be after check_in")

    records = list(
        db.execute(
            select(AttendanceRecord)
            .where(
                AttendanceRecord.employee_id == employee.id,
                AttendanceRecord.work_date == work_date,
            )
            .order_by(AttendanceRecord.id)
        ).scalars()
    )
    if len(records) > 1:
        raise AttendanceCorrectionError(
            "Multiple attendance records exist for this date; contact HR"
        )
    record = records[0] if records else None

    if record is not None and row.submitted_at is not None:
        if record.updated_at is not None and record.updated_at > row.submitted_at:
            raise AttendanceCorrectionStaleError(
                "The attendance record changed after this request was "
                "submitted; please review and resubmit"
            )

    _assert_no_overlap(
        db,
        employee,
        check_in,
        check_out,
        exclude_id=record.id if record is not None else None,
    )

    reason = (row.reason or f"Employee request #{row.id}").strip()[:500]
    resolved = resolve_employee_schedule(db, employee, work_date)
    metrics = compute_metrics(resolved, work_date, check_in, check_out)
    old_snapshot = _snapshot(record) if record is not None else None

    if record is None:
        record = AttendanceRecord(
            company_id=employee.company_id,
            employee_id=employee.id,
            work_date=work_date,
            schedule_id=resolved.schedule.id if resolved.schedule else None,
            shift_id=resolved.shift.id if resolved.shift else None,
            check_in=check_in,
            check_out=check_out,
            status="completed",
            source="manual",
            correction_reason=reason,
            corrected_by=principal.user_id,
            corrected_at=_now(),
            created_by=principal.user_id,
        )
        _apply_metrics(record, metrics)
        db.add(record)
    else:
        record.check_in = check_in
        record.check_out = check_out
        record.status = "completed"
        record.schedule_id = resolved.schedule.id if resolved.schedule else None
        record.shift_id = resolved.shift.id if resolved.shift else None
        _apply_metrics(record, metrics)
        record.correction_reason = reason
        record.corrected_by = principal.user_id
        record.corrected_at = _now()
        db.add(record)

    try:
        db.flush()
    except IntegrityError as exc:
        raise AttendanceOverlapError(
            "Attendance window overlaps another record"
        ) from exc

    row.attendance_record_id = record.id
    record_audit(
        db,
        action="attendance.correct",
        entity="attendance_record",
        record_id=record.id,
        actor_user_id=principal.user_id,
        company_id=employee.company_id,
        old_value=old_snapshot,
        new_value={
            "employee_id": employee.id,
            "work_date": str(work_date),
            "check_in": check_in.isoformat(),
            "check_out": check_out.isoformat(),
            "status": "completed",
            "reason": reason,
            "request_id": row.id,
        },
        ip_address=ip,
    )
    db.flush()
    return record
