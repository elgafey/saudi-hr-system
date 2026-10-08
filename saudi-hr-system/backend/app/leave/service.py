from __future__ import annotations

from datetime import date, datetime
from datetime import timezone as dt_timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.core.deps import Principal
from app.core.exceptions import (
    CompanyHolidayExistsError,
    CompanyHolidayNotFoundError,
    ConflictError,
    ForbiddenError,
    LeaveAllocationInUseError,
    LeaveAllocationInvalidDaysError,
    LeaveAllocationNotFoundError,
    LeaveAllocationOverlapError,
    LeaveAllocationStateError,
    LeaveAttendanceOpenConflictError,
    LeaveAttendanceRecordExistsError,
    LeaveCarryForwardError,
    LeaveDecisionReasonRequiredError,
    LeaveEmployeeNotActiveError,
    LeaveOvertimeConflictError,
    LeaveRequestAttachmentRequiredError,
    LeaveRequestDaysError,
    LeaveRequestNotFoundError,
    LeaveRequestOverlapError,
    LeaveRequestRangeError,
    LeaveRequestReasonRequiredError,
    LeaveRequestStateError,
    LeaveRequestTimesError,
    LeaveTypeCodeExistsError,
    LeaveTypeInactiveError,
    LeaveTypeInUseError,
    LeaveTypeNotFoundError,
    LeaveTypeRangeError,
    NotFoundError,
    StatutoryRuleDateRangeError,
    StatutoryRuleNotFoundError,
    StatutoryRuleOverlapError,
    StatutoryRuleSourceRequiredError,
)
from app.core.pagination import PageParams
from app.core.storage import get_storage, validate_document_upload
from app.leave.balance import (
    BalanceLine,
    compute_balance,
    consume_fifo,
    ensure_balance,
    lock_allocations_for_request,
    release_consumptions,
)
from app.leave.day_counting import count_leave_days
from app.leave.schemas import (
    BalanceOut,
    CarryForward,
    HolidayCreate,
    HolidayUpdate,
    LeaveAllocationCreate,
    LeaveAllocationDecision,
    LeaveAllocationGenerate,
    LeaveAllocationUpdate,
    LeaveRequestCreate,
    LeaveRequestDecision,
    LeaveRequestPreview,
    LeaveRequestPreviewOut,
    LeaveRequestUpdate,
    LeaveTypeCreate,
    LeaveTypeUpdate,
    StatutoryRuleCreate,
    StatutoryRuleDeactivate,
)
from app.shared.models import (
    AttendanceRecord,
    CompanyHoliday,
    Employee,
    LeaveAllocation,
    LeaveConsumption,
    LeaveRequest,
    LeaveStatutoryRule,
    LeaveType,
    OvertimeRecord,
    User,
)

# Max rows a bulk carry-forward/generate pass may touch in one call.
BULK_LIMIT = 500


def _now() -> datetime:
    return datetime.now(dt_timezone.utc)


def _require(principal: Principal, code: str, company_id: int | None) -> None:
    """Company-scoped permission check (H1)."""
    if not principal.has_permission(code, company_id):
        raise ForbiddenError(f"Missing permission: {code}")


def _resolve_employee(db: Session, employee_id: int, principal: Principal) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None or not principal.can_access_company(employee.company_id):
        raise LeaveRequestNotFoundError("Employee not found")
    return employee


def _self_employee_id(db: Session, principal: Principal) -> int | None:
    user = db.get(User, principal.user_id)
    if user is None:
        return None
    return user.employee_id


def _require_active_employee(employee: Employee) -> None:
    if employee.status != "active":
        raise LeaveEmployeeNotActiveError(
            "Leave is only available for active employees"
        )


def _fetch_type(db: Session, leave_type_id: int, principal: Principal) -> LeaveType:
    row = db.get(LeaveType, leave_type_id)
    if row is None or not principal.can_access_company(row.company_id):
        raise LeaveTypeNotFoundError("Leave type not found")
    return row


def _fetch_allocation(
    db: Session, allocation_id: int, principal: Principal
) -> LeaveAllocation:
    row = db.get(LeaveAllocation, allocation_id)
    if row is None or not principal.can_access_company(row.company_id):
        raise LeaveAllocationNotFoundError("Leave allocation not found")
    return row


def _fetch_request(
    db: Session, request_id: int, principal: Principal, *, lock: bool = False
) -> LeaveRequest:
    stmt = select(LeaveRequest).where(LeaveRequest.id == request_id)
    if lock:
        stmt = stmt.with_for_update()
    row = db.execute(stmt).scalar_one_or_none()
    if row is None or not principal.can_access_company(row.company_id):
        raise LeaveRequestNotFoundError("Leave request not found")
    return row


def _require_request_verb(
    db: Session, principal: Principal, company_id: int, owner_employee_id: int, verb: str
) -> None:
    """Self-service scoping: the verb code alone allows acting on your OWN
    request; acting on another employee's request additionally requires
    leave_request.view (the cross-employee marker)."""
    _require(principal, verb, company_id)
    self_eid = _self_employee_id(db, principal)
    if owner_employee_id != self_eid:
        _require(principal, "leave_request.view", company_id)


def _can_read_request(db: Session, principal: Principal, row: LeaveRequest) -> bool:
    if principal.has_permission("leave_request.view", row.company_id):
        return True
    self_eid = _self_employee_id(db, principal)
    return (
        self_eid is not None
        and row.employee_id == self_eid
        and principal.has_permission("leave_request.create", row.company_id)
    )


# ---------------------------------------------------------------------------
# Leave types
# ---------------------------------------------------------------------------


def _validate_type_days(
    min_days: Decimal | None, max_days: Decimal | None
) -> None:
    if (
        min_days is not None
        and max_days is not None
        and Decimal(min_days) > Decimal(max_days)
    ):
        raise LeaveTypeRangeError(
            "min_request_days must not exceed max_request_days"
        )


def _norm_code(code: str) -> str:
    return code.strip()


def list_leave_types(
    db: Session,
    principal: Principal,
    *,
    company_id: int | None = None,
    status: str | None = None,
    statutory_key: str | None = None,
    q: str | None = None,
    page: PageParams | None = None,
) -> tuple[list[LeaveType], int]:
    stmt = select(LeaveType)
    count_stmt = select(func.count()).select_from(LeaveType)
    if company_id is not None:
        if not principal.can_access_company(company_id):
            raise ForbiddenError("You cannot access this company")
        _require(principal, "leave_type.view", company_id)
        stmt = stmt.where(LeaveType.company_id == company_id)
        count_stmt = count_stmt.where(LeaveType.company_id == company_id)
    elif not principal.is_platform_admin:
        allowed = principal.permitted_company_ids("leave_type.view")
        if not allowed:
            return [], 0
        stmt = stmt.where(LeaveType.company_id.in_(allowed))
        count_stmt = count_stmt.where(LeaveType.company_id.in_(allowed))
    if status is not None:
        stmt = stmt.where(LeaveType.status == status)
        count_stmt = count_stmt.where(LeaveType.status == status)
    if statutory_key is not None:
        stmt = stmt.where(LeaveType.statutory_key == statutory_key)
        count_stmt = count_stmt.where(LeaveType.statutory_key == statutory_key)
    if q is not None and q.strip():
        like = f"%{q.strip()}%"
        clause = or_(
            LeaveType.code.ilike(like),
            LeaveType.name_ar.ilike(like),
            LeaveType.name_en.ilike(like),
        )
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)
    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(LeaveType.sort_order, LeaveType.id)
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


def get_leave_type(
    db: Session, leave_type_id: int, principal: Principal
) -> LeaveType:
    row = _fetch_type(db, leave_type_id, principal)
    _require(principal, "leave_type.view", row.company_id)
    return row


def _check_type_code(db: Session, company_id: int, code: str, exclude_id: int | None = None) -> None:
    stmt = select(LeaveType.id).where(
        LeaveType.company_id == company_id, LeaveType.code == code
    )
    if exclude_id is not None:
        stmt = stmt.where(LeaveType.id != exclude_id)
    if db.execute(stmt).scalar_one_or_none() is not None:
        raise LeaveTypeCodeExistsError(
            "Leave type code already exists in this company"
        )


def _type_snapshot(row: LeaveType) -> dict:
    return {"code": row.code, "status": row.status, "is_paid": row.is_paid}


def create_leave_type(
    db: Session, *, payload: LeaveTypeCreate, principal: Principal, ip: str | None
) -> LeaveType:
    if not principal.can_access_company(payload.company_id):
        raise ForbiddenError("You cannot create leave types in this company")
    _require(principal, "leave_type.create", payload.company_id)
    code = _norm_code(payload.code)
    _check_type_code(db, payload.company_id, code)
    _validate_type_days(payload.min_request_days, payload.max_request_days)
    row = LeaveType(
        company_id=payload.company_id,
        code=code,
        name_ar=payload.name_ar,
        name_en=payload.name_en,
        description=payload.description,
        is_paid=payload.is_paid,
        requires_approval=payload.requires_approval,
        allocation_requires_approval=payload.allocation_requires_approval,
        day_counting_mode=payload.day_counting_mode,
        requires_attachment=payload.requires_attachment,
        attachment_threshold_days=payload.attachment_threshold_days,
        requires_reason=payload.requires_reason,
        negative_balance_allowed=payload.negative_balance_allowed,
        min_request_days=payload.min_request_days,
        max_request_days=payload.max_request_days,
        default_entitlement_days=payload.default_entitlement_days,
        carry_forward_enabled=payload.carry_forward_enabled,
        carry_forward_max_days=payload.carry_forward_max_days,
        carry_forward_expiry=payload.carry_forward_expiry,
        allowance_treatment=payload.allowance_treatment,
        is_statutory=payload.is_statutory,
        statutory_key=payload.statutory_key,
        status=payload.status,
        sort_order=payload.sort_order,
        created_by=principal.user_id,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        raise LeaveTypeCodeExistsError(
            "Leave type code already exists in this company"
        ) from exc
    record_audit(
        db,
        action="leave_type.create",
        entity="leave_type",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        new_value=_type_snapshot(row),
        ip_address=ip,
    )
    db.flush()
    return row


def update_leave_type(
    db: Session,
    *,
    leave_type_id: int,
    payload: LeaveTypeUpdate,
    principal: Principal,
    ip: str | None,
) -> LeaveType:
    row = _fetch_type(db, leave_type_id, principal)
    _require(principal, "leave_type.update", row.company_id)
    changes = payload.model_dump(exclude_unset=True)
    if "code" in changes:
        code = _norm_code(changes["code"])
        _check_type_code(db, row.company_id, code, exclude_id=row.id)
        changes["code"] = code
    merged_min = changes.get("min_request_days", row.min_request_days)
    merged_max = changes.get("max_request_days", row.max_request_days)
    _validate_type_days(merged_min, merged_max)
    for key, value in changes.items():
        setattr(row, key, value)
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        raise LeaveTypeCodeExistsError(
            "Leave type code already exists in this company"
        ) from exc
    record_audit(
        db,
        action="leave_type.update",
        entity="leave_type",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        new_value={"fields": sorted(changes)},
        ip_address=ip,
    )
    db.flush()
    return row


def delete_leave_type(
    db: Session, *, leave_type_id: int, principal: Principal, ip: str | None
) -> None:
    row = _fetch_type(db, leave_type_id, principal)
    _require(principal, "leave_type.delete", row.company_id)
    used = db.execute(
        select(func.count())
        .select_from(LeaveAllocation)
        .where(LeaveAllocation.leave_type_id == row.id)
    ).scalar_one()
    used += db.execute(
        select(func.count())
        .select_from(LeaveRequest)
        .where(LeaveRequest.leave_type_id == row.id)
    ).scalar_one()
    if used:
        raise LeaveTypeInUseError(
            "Leave type is referenced by allocations or requests; "
            "deactivate it instead"
        )
    old = _type_snapshot(row)
    db.delete(row)
    db.flush()
    record_audit(
        db,
        action="leave_type.delete",
        entity="leave_type",
        record_id=leave_type_id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        old_value=old,
        ip_address=ip,
    )
    db.flush()


# ---------------------------------------------------------------------------
# Statutory rules (versioned, source + effective date required)
# ---------------------------------------------------------------------------


def list_statutory_rules(
    db: Session,
    principal: Principal,
    *,
    company_id: int | None = None,
    statutory_key: str | None = None,
    as_of: date | None = None,
    status: str | None = None,
    page: PageParams | None = None,
) -> tuple[list[LeaveStatutoryRule], int]:
    stmt = select(LeaveStatutoryRule)
    count_stmt = select(func.count()).select_from(LeaveStatutoryRule)
    if company_id is not None:
        if not principal.can_access_company(company_id):
            raise ForbiddenError("You cannot access this company")
        _require(principal, "leave_type.view", company_id)
        stmt = stmt.where(LeaveStatutoryRule.company_id == company_id)
        count_stmt = count_stmt.where(LeaveStatutoryRule.company_id == company_id)
    elif not principal.is_platform_admin:
        allowed = principal.permitted_company_ids("leave_type.view")
        if not allowed:
            return [], 0
        stmt = stmt.where(LeaveStatutoryRule.company_id.in_(allowed))
        count_stmt = count_stmt.where(LeaveStatutoryRule.company_id.in_(allowed))
    if statutory_key is not None:
        stmt = stmt.where(LeaveStatutoryRule.statutory_key == statutory_key)
        count_stmt = count_stmt.where(
            LeaveStatutoryRule.statutory_key == statutory_key
        )
    if status is not None:
        stmt = stmt.where(LeaveStatutoryRule.status == status)
        count_stmt = count_stmt.where(LeaveStatutoryRule.status == status)
    if as_of is not None:
        stmt = stmt.where(
            LeaveStatutoryRule.effective_from <= as_of,
            (LeaveStatutoryRule.effective_to.is_(None))
            | (LeaveStatutoryRule.effective_to > as_of),
        )
        count_stmt = count_stmt.where(
            LeaveStatutoryRule.effective_from <= as_of,
            (LeaveStatutoryRule.effective_to.is_(None))
            | (LeaveStatutoryRule.effective_to > as_of),
        )
    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(
        LeaveStatutoryRule.statutory_key,
        LeaveStatutoryRule.effective_from.desc(),
        LeaveStatutoryRule.version.desc(),
    )
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


def resolve_statutory_rule(
    db: Session, company_id: int, statutory_key: str, as_of: date
) -> LeaveStatutoryRule | None:
    """Effective-dated resolution: the version in force on ``as_of``."""
    return db.execute(
        select(LeaveStatutoryRule)
        .where(
            LeaveStatutoryRule.company_id == company_id,
            LeaveStatutoryRule.statutory_key == statutory_key,
            LeaveStatutoryRule.status == "active",
            LeaveStatutoryRule.effective_from <= as_of,
            (LeaveStatutoryRule.effective_to.is_(None))
            | (LeaveStatutoryRule.effective_to > as_of),
        )
        .order_by(
            LeaveStatutoryRule.effective_from.desc(),
            LeaveStatutoryRule.version.desc(),
        )
        .limit(1)
    ).scalar_one_or_none()


def _fetch_rule(
    db: Session, rule_id: int, principal: Principal
) -> LeaveStatutoryRule:
    row = db.get(LeaveStatutoryRule, rule_id)
    if row is None or not principal.can_access_company(row.company_id):
        raise StatutoryRuleNotFoundError("Statutory rule not found")
    return row


def get_statutory_rule(
    db: Session, rule_id: int, principal: Principal
) -> LeaveStatutoryRule:
    row = _fetch_rule(db, rule_id, principal)
    _require(principal, "leave_type.view", row.company_id)
    return row


def _assert_rule_overlap(
    db: Session, company_id: int, key: str, start: date, end: date | None
) -> None:
    """Effective windows are [effective_from, effective_to) with NULL end =
    open-ended (mirrors the daterange '[)' EXCLUDE constraint). Adjacent
    versions are legal: v1 ending 2025-01-01 and v2 starting 2025-01-01
    do not overlap."""
    stmt = select(LeaveStatutoryRule).where(
        LeaveStatutoryRule.company_id == company_id,
        LeaveStatutoryRule.statutory_key == key,
    )
    for other in db.execute(stmt).scalars():
        if other.effective_to is not None and other.effective_to <= start:
            continue
        if end is not None and end <= other.effective_from:
            continue
        raise StatutoryRuleOverlapError(
            "Rule versions may not overlap for the same statutory key"
        )


def create_statutory_rule(
    db: Session, *, payload: StatutoryRuleCreate, principal: Principal, ip: str | None
) -> LeaveStatutoryRule:
    if not principal.can_access_company(payload.company_id):
        raise ForbiddenError("You cannot create statutory rules in this company")
    # Statutory rules are configuration of a leave type: same code family.
    _require(principal, "leave_type.create", payload.company_id)
    if not payload.source_reference or not payload.source_reference.strip():
        raise StatutoryRuleSourceRequiredError(
            "A source_reference (citation) is required for statutory rules"
        )
    if payload.effective_to is not None and payload.effective_to <= payload.effective_from:
        raise StatutoryRuleDateRangeError(
            "effective_to must be later than effective_from"
        )
    _assert_rule_overlap(
        db,
        payload.company_id,
        payload.statutory_key.strip(),
        payload.effective_from,
        payload.effective_to,
    )
    next_version = (
        db.execute(
            select(func.coalesce(func.max(LeaveStatutoryRule.version), 0)).where(
                LeaveStatutoryRule.company_id == payload.company_id,
                LeaveStatutoryRule.statutory_key == payload.statutory_key.strip(),
            )
        ).scalar_one()
        + 1
    )
    row = LeaveStatutoryRule(
        company_id=payload.company_id,
        statutory_key=payload.statutory_key.strip(),
        jurisdiction="SA",
        version=next_version,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        rule_json=payload.rule_json,
        source_reference=payload.source_reference.strip(),
        source_date=payload.source_date,
        requires_legal_verification=payload.requires_legal_verification,
        notes=payload.notes,
        status="active",
        created_by=principal.user_id,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        raise StatutoryRuleOverlapError(
            "Rule versions may not overlap for the same statutory key"
        ) from exc
    record_audit(
        db,
        action="leave_statutory_rule.create",
        entity="leave_statutory_rule",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        new_value={
            "statutory_key": row.statutory_key,
            "version": row.version,
            "effective_from": str(row.effective_from),
            "source_reference": row.source_reference,
        },
        ip_address=ip,
    )
    db.flush()
    return row


def deactivate_statutory_rule(
    db: Session,
    *,
    rule_id: int,
    payload: StatutoryRuleDeactivate,
    principal: Principal,
    ip: str | None,
) -> LeaveStatutoryRule:
    row = _fetch_rule(db, rule_id, principal)
    _require(principal, "leave_type.update", row.company_id)
    if row.status == "inactive":
        raise ConflictError("Statutory rule is already inactive")
    row.status = "inactive"
    db.add(row)
    db.flush()
    record_audit(
        db,
        action="leave_statutory_rule.deactivate",
        entity="leave_statutory_rule",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        old_value={"status": "active"},
        new_value={"status": "inactive", "reason": payload.reason},
        ip_address=ip,
    )
    db.flush()
    return row


# ---------------------------------------------------------------------------
# Allocations
# ---------------------------------------------------------------------------


def _assert_allocation_overlap(
    db: Session,
    employee: Employee,
    leave_type_id: int,
    start: date,
    end: date,
    exclude_id: int | None = None,
) -> None:
    stmt = select(LeaveAllocation.id).where(
        LeaveAllocation.employee_id == employee.id,
        LeaveAllocation.leave_type_id == leave_type_id,
        LeaveAllocation.period_start <= end,
        LeaveAllocation.period_end >= start,
    )
    if exclude_id is not None:
        stmt = stmt.where(LeaveAllocation.id != exclude_id)
    if db.execute(stmt).scalar_one_or_none() is not None:
        raise LeaveAllocationOverlapError(
            "An allocation already covers part of this period for the "
            "employee and leave type"
        )


def _allocation_snapshot(row: LeaveAllocation) -> dict:
    return {
        "employee_id": row.employee_id,
        "leave_type_id": row.leave_type_id,
        "period_start": str(row.period_start),
        "period_end": str(row.period_end),
        "allocated_days": str(row.allocated_days),
        "status": row.status,
    }


def list_leave_allocations(
    db: Session,
    principal: Principal,
    *,
    company_id: int | None = None,
    employee_id: int | None = None,
    leave_type_id: int | None = None,
    status: str | None = None,
    period_from: date | None = None,
    period_to: date | None = None,
    page: PageParams | None = None,
) -> tuple[list[LeaveAllocation], int]:
    stmt = select(LeaveAllocation)
    count_stmt = select(func.count()).select_from(LeaveAllocation)
    if company_id is not None:
        if not principal.can_access_company(company_id):
            raise ForbiddenError("You cannot access this company")
        _require(principal, "leave_allocation.view", company_id)
        stmt = stmt.where(LeaveAllocation.company_id == company_id)
        count_stmt = count_stmt.where(LeaveAllocation.company_id == company_id)
    elif not principal.is_platform_admin:
        allowed = principal.permitted_company_ids("leave_allocation.view")
        if not allowed:
            return [], 0
        stmt = stmt.where(LeaveAllocation.company_id.in_(allowed))
        count_stmt = count_stmt.where(LeaveAllocation.company_id.in_(allowed))
    if employee_id is not None:
        stmt = stmt.where(LeaveAllocation.employee_id == employee_id)
        count_stmt = count_stmt.where(LeaveAllocation.employee_id == employee_id)
    if leave_type_id is not None:
        stmt = stmt.where(LeaveAllocation.leave_type_id == leave_type_id)
        count_stmt = count_stmt.where(
            LeaveAllocation.leave_type_id == leave_type_id
        )
    if status is not None:
        stmt = stmt.where(LeaveAllocation.status == status)
        count_stmt = count_stmt.where(LeaveAllocation.status == status)
    if period_from is not None:
        stmt = stmt.where(LeaveAllocation.period_end >= period_from)
        count_stmt = count_stmt.where(
            LeaveAllocation.period_end >= period_from
        )
    if period_to is not None:
        stmt = stmt.where(LeaveAllocation.period_start <= period_to)
        count_stmt = count_stmt.where(
            LeaveAllocation.period_start <= period_to
        )
    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(
        LeaveAllocation.period_start.desc(), LeaveAllocation.id.desc()
    )
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


def get_leave_allocation(
    db: Session, allocation_id: int, principal: Principal
) -> LeaveAllocation:
    row = _fetch_allocation(db, allocation_id, principal)
    _require(principal, "leave_allocation.view", row.company_id)
    return row


def _resolve_allocation_target(
    db: Session, principal: Principal, employee_id: int, leave_type_id: int
) -> tuple[Employee, LeaveType]:
    employee = _resolve_employee(db, employee_id, principal)
    leave_type = db.get(LeaveType, leave_type_id)
    if leave_type is None or leave_type.company_id != employee.company_id:
        raise LeaveTypeNotFoundError("Leave type not found")
    if leave_type.status != "active":
        raise LeaveTypeInactiveError("Leave type is inactive")
    return employee, leave_type


def _validate_allocation_days(days: Decimal | None) -> Decimal:
    if days is None or Decimal(days) <= 0:
        raise LeaveAllocationInvalidDaysError(
            "allocated_days must be greater than zero"
        )
    return Decimal(days)


def _insert_allocation(
    db: Session,
    *,
    employee: Employee,
    leave_type: LeaveType,
    period_start: date,
    period_end: date,
    allocated_days: Decimal,
    source: str,
    principal: Principal,
    ip: str | None = None,
    reason: str | None = None,
    carried_from_id: int | None = None,
) -> LeaveAllocation:
    if period_end < period_start:
        raise LeaveAllocationInvalidDaysError(
            "period_end must not be before period_start"
        )
    _assert_allocation_overlap(
        db, employee, leave_type.id, period_start, period_end
    )
    status = "submitted" if leave_type.allocation_requires_approval else "approved"
    row = LeaveAllocation(
        company_id=employee.company_id,
        employee_id=employee.id,
        leave_type_id=leave_type.id,
        period_start=period_start,
        period_end=period_end,
        allocated_days=Decimal(allocated_days),
        used_days=Decimal("0.00"),
        source=source,
        carried_from_id=carried_from_id,
        status=status,
        reason=reason,
        created_by=principal.user_id,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        raise LeaveAllocationOverlapError(
            "An allocation already covers part of this period for the "
            "employee and leave type"
        ) from exc
    record_audit(
        db,
        action="leave_allocation.create",
        entity="leave_allocation",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        new_value=_allocation_snapshot(row),
        ip_address=ip,
    )
    db.flush()
    return row


def create_leave_allocation(
    db: Session,
    *,
    payload: LeaveAllocationCreate,
    principal: Principal,
    ip: str | None,
) -> LeaveAllocation:
    employee, leave_type = _resolve_allocation_target(
        db, principal, payload.employee_id, payload.leave_type_id
    )
    _require(principal, "leave_allocation.create", employee.company_id)
    days = _validate_allocation_days(payload.allocated_days)
    row = _insert_allocation(
        db,
        employee=employee,
        leave_type=leave_type,
        period_start=payload.period_start,
        period_end=payload.period_end,
        allocated_days=days,
        source=payload.source if payload.source in {
            "manual", "generate", "carry_forward", "statutory"
        } else "manual",
        principal=principal,
        ip=ip,
        reason=payload.reason,
    )
    return row


def generate_leave_allocations(
    db: Session,
    *,
    payload: LeaveAllocationGenerate,
    principal: Principal,
    ip: str | None,
) -> list[LeaveAllocation]:
    leave_type = db.get(LeaveType, payload.leave_type_id)
    if leave_type is None or not principal.can_access_company(
        leave_type.company_id
    ):
        raise LeaveTypeNotFoundError("Leave type not found")
    _require(principal, "leave_allocation.create", leave_type.company_id)
    if payload.period_end < payload.period_start:
        raise LeaveAllocationInvalidDaysError(
            "period_end must not be before period_start"
        )
    if payload.employee_ids is None:
        employees = list(
            db.execute(
                select(Employee).where(
                    Employee.company_id == leave_type.company_id,
                    Employee.status == "active",
                )
            ).scalars()
        )
    else:
        employees = []
        for eid in payload.employee_ids:
            emp = _resolve_employee(db, eid, principal)
            if emp.company_id != leave_type.company_id:
                raise LeaveTypeNotFoundError("Employee not in the same company")
            employees.append(emp)
    if len(employees) > BULK_LIMIT:
        raise LeaveAllocationInvalidDaysError(
            f"Bulk generation is limited to {BULK_LIMIT} employees"
        )
    default_days = payload.allocated_days or leave_type.default_entitlement_days
    days = _validate_allocation_days(default_days)
    created: list[LeaveAllocation] = []
    for employee in employees:
        row = _insert_allocation(
            db,
            employee=employee,
            leave_type=leave_type,
            period_start=payload.period_start,
            period_end=payload.period_end,
            allocated_days=days,
            source="generate",
            principal=principal,
            ip=ip,
        )
        created.append(row)
    record_audit(
        db,
        action="leave_allocation.create",
        entity="leave_allocation",
        record_id=0,
        actor_user_id=principal.user_id,
        company_id=leave_type.company_id,
        new_value={
            "generated": len(created),
            "leave_type_id": leave_type.id,
            "period_start": str(payload.period_start),
            "period_end": str(payload.period_end),
            "allocated_days": str(days),
        },
        ip_address=ip,
    )
    db.flush()
    return created


def update_leave_allocation(
    db: Session,
    *,
    allocation_id: int,
    payload: LeaveAllocationUpdate,
    principal: Principal,
    ip: str | None,
) -> LeaveAllocation:
    row = _fetch_allocation(db, allocation_id, principal)
    _require(principal, "leave_allocation.update", row.company_id)
    if row.status != "approved":
        raise LeaveAllocationStateError(
            "Only approved allocations with no usage can be edited"
        )
    if Decimal(row.used_days) > 0:
        raise LeaveAllocationInUseError(
            "Allocation already has consumed days"
        )
    changes = payload.model_dump(exclude_unset=True)
    merged_start = changes.get("period_start", row.period_start)
    merged_end = changes.get("period_end", row.period_end)
    if merged_end < merged_start:
        raise LeaveAllocationInvalidDaysError(
            "period_end must not be before period_start"
        )
    if "allocated_days" in changes:
        changes["allocated_days"] = _validate_allocation_days(
            changes["allocated_days"]
        )
    if "period_start" in changes or "period_end" in changes:
        employee = db.get(Employee, row.employee_id)
        if employee is not None:
            _assert_allocation_overlap(
                db,
                employee,
                row.leave_type_id,
                merged_start,
                merged_end,
                exclude_id=row.id,
            )
    for key, value in changes.items():
        setattr(row, key, value)
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        raise LeaveAllocationOverlapError(
            "An allocation already covers part of this period for the "
            "employee and leave type"
        ) from exc
    record_audit(
        db,
        action="leave_allocation.update",
        entity="leave_allocation",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        new_value={"fields": sorted(changes)},
        ip_address=ip,
    )
    db.flush()
    return row


def delete_leave_allocation(
    db: Session, *, allocation_id: int, principal: Principal, ip: str | None
) -> None:
    row = _fetch_allocation(db, allocation_id, principal)
    _require(principal, "leave_allocation.delete", row.company_id)
    consumed = db.execute(
        select(func.count()).select_from(LeaveConsumption).where(
            LeaveConsumption.leave_allocation_id == row.id
        )
    ).scalar_one()
    if consumed or Decimal(row.used_days) > 0:
        raise LeaveAllocationInUseError(
            "Allocation has consumed days; cancel the requests first, "
            "then revoke it"
        )
    old = _allocation_snapshot(row)
    db.delete(row)
    db.flush()
    record_audit(
        db,
        action="leave_allocation.delete",
        entity="leave_allocation",
        record_id=allocation_id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        old_value=old,
        ip_address=ip,
    )
    db.flush()


def submit_leave_allocation(
    db: Session, *, allocation_id: int, principal: Principal, ip: str | None
) -> LeaveAllocation:
    """Idempotent submit: allocations that require approval enter
    ``submitted`` directly at creation (approved design state machine), so
    submitting an already-submitted allocation is a no-op."""
    row = _fetch_allocation(db, allocation_id, principal)
    _require(principal, "leave_allocation.submit", row.company_id)
    if row.status == "submitted":
        return row
    raise LeaveAllocationStateError(
        f"Cannot submit an allocation while status is '{row.status}'"
    )


def approve_leave_allocation(
    db: Session,
    *,
    allocation_id: int,
    payload: LeaveAllocationDecision,
    principal: Principal,
    ip: str | None,
) -> LeaveAllocation:
    row = _fetch_allocation(db, allocation_id, principal)
    _require(principal, "leave_allocation.approve", row.company_id)
    if row.status != "submitted":
        raise LeaveAllocationStateError(
            "Only submitted allocations can be approved"
        )
    row.status = "approved"
    row.approved_by = principal.user_id
    row.approved_at = _now()
    row.decision_reason = payload.reason
    db.add(row)
    db.flush()
    record_audit(
        db,
        action="leave_allocation.approve",
        entity="leave_allocation",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        old_value={"status": "submitted"},
        new_value={"status": "approved"},
        ip_address=ip,
    )
    db.flush()
    return row


def reject_leave_allocation(
    db: Session,
    *,
    allocation_id: int,
    payload: LeaveAllocationDecision,
    principal: Principal,
    ip: str | None,
) -> LeaveAllocation:
    row = _fetch_allocation(db, allocation_id, principal)
    _require(principal, "leave_allocation.reject", row.company_id)
    if row.status != "submitted":
        raise LeaveAllocationStateError(
            "Only submitted allocations can be rejected"
        )
    if not payload.reason or not payload.reason.strip():
        raise LeaveDecisionReasonRequiredError(
            "A reason is required to reject an allocation"
        )
    row.status = "rejected"
    row.rejected_by = principal.user_id
    row.rejected_at = _now()
    row.decision_reason = payload.reason
    db.add(row)
    db.flush()
    record_audit(
        db,
        action="leave_allocation.reject",
        entity="leave_allocation",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        old_value={"status": "submitted"},
        new_value={"status": "rejected", "reason": payload.reason},
        ip_address=ip,
    )
    db.flush()
    return row


def _carry_source_allows(leave_type: LeaveType, source: LeaveAllocation, target_start: date) -> bool:
    """Carry-forward expiry rules (configuration, not law):
    - none: any prior period may carry;
    - end_of_year: only the immediately preceding calendar year carries;
    - end_of_next_year: the source period must end within ~1 year before
      the target starts (older entitlements expire)."""
    rule = leave_type.carry_forward_expiry
    if rule == "none":
        return source.period_end < target_start
    if rule == "end_of_year":
        return (
            source.period_end < target_start
            and source.period_end.year == target_start.year - 1
        )
    # end_of_next_year
    return (
        source.period_end < target_start
        and (target_start - source.period_end).days <= 366
    )


def carry_forward_allocations(
    db: Session,
    *,
    payload: CarryForward,
    principal: Principal,
    ip: str | None,
) -> list[LeaveAllocation]:
    if payload.period_end < payload.period_start:
        raise LeaveCarryForwardError("period_end must not be before period_start")
    if payload.company_id is None:
        raise LeaveCarryForwardError("company_id is required")
    if not principal.can_access_company(payload.company_id):
        raise ForbiddenError("You cannot access this company")
    _require(principal, "leave_allocation.carry_forward", payload.company_id)
    types = list(
        db.execute(
            select(LeaveType).where(
                LeaveType.company_id == payload.company_id,
                LeaveType.status == "active",
                LeaveType.carry_forward_enabled.is_(True),
            )
        ).scalars()
    )
    created: list[LeaveAllocation] = []
    for leave_type in types:
        employees = db.execute(
            select(Employee).where(
                Employee.company_id == payload.company_id,
                Employee.status == "active",
            )
        ).scalars()
        for employee in employees:
            # Skip when ANY allocation already covers the target period
            # (the EXCLUDE constraint would reject it anyway).
            existing = db.execute(
                select(LeaveAllocation.id).where(
                    LeaveAllocation.employee_id == employee.id,
                    LeaveAllocation.leave_type_id == leave_type.id,
                    LeaveAllocation.period_start <= payload.period_end,
                    LeaveAllocation.period_end >= payload.period_start,
                )
            ).scalar_one_or_none()
            if existing is not None:
                continue
            # Latest approved source period entirely before the target.
            sources = list(
                db.execute(
                    select(LeaveAllocation)
                    .where(
                        LeaveAllocation.employee_id == employee.id,
                        LeaveAllocation.leave_type_id == leave_type.id,
                        LeaveAllocation.status == "approved",
                        LeaveAllocation.period_end < payload.period_start,
                    )
                    .order_by(LeaveAllocation.period_end.desc())
                    .limit(1)
                ).scalars()
            )
            if not sources:
                continue
            source = sources[0]
            if not _carry_source_allows(leave_type, source, payload.period_start):
                continue
            remaining = Decimal(source.allocated_days) - Decimal(source.used_days)
            if remaining <= 0:
                continue
            cap = leave_type.carry_forward_max_days
            carry_days = (
                min(remaining, Decimal(cap)) if cap is not None else remaining
            )
            if carry_days <= 0:
                continue
            row = LeaveAllocation(
                company_id=payload.company_id,
                employee_id=employee.id,
                leave_type_id=leave_type.id,
                period_start=payload.period_start,
                period_end=payload.period_end,
                allocated_days=carry_days,
                used_days=Decimal("0.00"),
                source="carry_forward",
                carried_from_id=source.id,
                status="approved",
                reason=(
                    f"Carried forward from allocation #{source.id} "
                    f"({source.period_start} - {source.period_end})"
                ),
                created_by=principal.user_id,
            )
            db.add(row)
            try:
                db.flush()
            except IntegrityError as exc:
                raise LeaveAllocationOverlapError(
                    "An allocation already covers part of this period"
                ) from exc
            created.append(row)
            record_audit(
                db,
                action="leave_allocation.create",
                entity="leave_allocation",
                record_id=row.id,
                actor_user_id=principal.user_id,
                company_id=payload.company_id,
                new_value=_allocation_snapshot(row),
                ip_address=ip,
            )
    record_audit(
        db,
        action="leave_allocation.carry_forward",
        entity="leave_allocation",
        record_id=0,
        actor_user_id=principal.user_id,
        company_id=payload.company_id,
        new_value={
            "created": len(created),
            "period_start": str(payload.period_start),
            "period_end": str(payload.period_end),
        },
        ip_address=ip,
    )
    db.flush()
    return created


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


def _request_snapshot(row: LeaveRequest) -> dict:
    return {
        "employee_id": row.employee_id,
        "leave_type_id": row.leave_type_id,
        "start_date": str(row.start_date),
        "end_date": str(row.end_date),
        "days": str(row.days),
        "status": row.status,
    }


def _transition_guard(row: LeaveRequest, allowed: set[str]) -> None:
    if row.status in allowed:
        return
    raise LeaveRequestStateError(
        f"Cannot perform this action while status is '{row.status}'"
    )


def _assert_no_request_overlap(
    db: Session, employee: Employee, start: date, end: date, exclude_id: int | None = None
) -> None:
    stmt = select(LeaveRequest.id).where(
        LeaveRequest.employee_id == employee.id,
        LeaveRequest.status.in_(("submitted", "approved")),
        LeaveRequest.start_date <= end,
        LeaveRequest.end_date >= start,
    )
    if exclude_id is not None:
        stmt = stmt.where(LeaveRequest.id != exclude_id)
    if db.execute(stmt).scalar_one_or_none() is not None:
        raise LeaveRequestOverlapError(
            "Another submitted or approved leave request already covers "
            "part of this range"
        )


def _validate_request_days(leave_type: LeaveType, days: Decimal) -> None:
    if leave_type.min_request_days is not None and days < Decimal(
        leave_type.min_request_days
    ):
        raise LeaveRequestDaysError(
            f"Request must be at least {leave_type.min_request_days} day(s)"
        )
    if leave_type.max_request_days is not None and days > Decimal(
        leave_type.max_request_days
    ):
        raise LeaveRequestDaysError(
            f"Request must be at most {leave_type.max_request_days} day(s)"
        )


def _validate_reason(leave_type: LeaveType, reason: str | None) -> None:
    if leave_type.requires_reason and not (reason and reason.strip()):
        raise LeaveRequestReasonRequiredError(
            "A reason is required for this leave type"
        )


def _validate_attachment(leave_type: LeaveType, row: LeaveRequest) -> None:
    if not leave_type.requires_attachment:
        return
    threshold = leave_type.attachment_threshold_days
    if threshold is not None and Decimal(row.days) < Decimal(threshold):
        return
    if not row.attachment_path:
        raise LeaveRequestAttachmentRequiredError(
            "An attachment is required for this leave type "
            "(upload before submitting)"
        )


def _count_for(db: Session, employee: Employee, leave_type: LeaveType, row: LeaveRequest) -> None:
    result = count_leave_days(
        db,
        employee,
        leave_type,
        row.start_date,
        row.end_date,
        row.start_time,
        row.end_time,
    )
    row.days = result.days
    row.count_details = result.to_details()


def _open_attendance_conflict(db: Session, employee: Employee, row: LeaveRequest) -> bool:
    return (
        db.execute(
            select(func.count())
            .select_from(AttendanceRecord)
            .where(
                AttendanceRecord.employee_id == employee.id,
                AttendanceRecord.status == "open",
                AttendanceRecord.work_date >= row.start_date,
                AttendanceRecord.work_date <= row.end_date,
            )
        ).scalar_one()
        > 0
    )


def _attendance_exists(db: Session, employee: Employee, row: LeaveRequest) -> bool:
    return (
        db.execute(
            select(func.count())
            .select_from(AttendanceRecord)
            .where(
                AttendanceRecord.employee_id == employee.id,
                AttendanceRecord.work_date >= row.start_date,
                AttendanceRecord.work_date <= row.end_date,
            )
        ).scalar_one()
        > 0
    )


def _full_covered_dates(row: LeaveRequest) -> list[date]:
    """Dates the request covers for a FULL working day (fraction == 1.00) -
    partial-day dates never conflict with approved overtime."""
    details = row.count_details or {}
    entries = details.get("entries") or []
    return [
        date.fromisoformat(entry["date"])
        for entry in entries
        if Decimal(entry["fraction"]) >= 1
    ]


def _overtime_conflict(db: Session, employee: Employee, row: LeaveRequest) -> bool:
    full_dates = _full_covered_dates(row)
    if not full_dates:
        return False
    return (
        db.execute(
            select(func.count())
            .select_from(OvertimeRecord)
            .where(
                OvertimeRecord.employee_id == employee.id,
                OvertimeRecord.status == "approved",
                OvertimeRecord.work_date.in_(full_dates),
            )
        ).scalar_one()
        > 0
    )


def list_leave_requests(
    db: Session,
    principal: Principal,
    *,
    company_id: int | None = None,
    employee_id: int | None = None,
    leave_type_id: int | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = None,
    page: PageParams | None = None,
) -> tuple[list[LeaveRequest], int]:
    self_eid = _self_employee_id(db, principal)
    stmt = select(LeaveRequest)
    count_stmt = select(func.count()).select_from(LeaveRequest)
    forced_employee: int | None = None

    if company_id is not None:
        if not principal.can_access_company(company_id):
            raise ForbiddenError("You cannot access this company")
        if principal.has_permission("leave_request.view", company_id):
            pass
        elif self_eid is not None and principal.has_permission(
            "leave_request.create", company_id
        ):
            if employee_id is not None and employee_id != self_eid:
                raise ForbiddenError("Missing permission: leave_request.view")
            forced_employee = self_eid
        else:
            raise ForbiddenError("Missing permission: leave_request.view")
        stmt = stmt.where(LeaveRequest.company_id == company_id)
        count_stmt = count_stmt.where(LeaveRequest.company_id == company_id)
    elif not principal.is_platform_admin:
        view_ids = principal.permitted_company_ids("leave_request.view")
        if view_ids:
            stmt = stmt.where(LeaveRequest.company_id.in_(view_ids))
            count_stmt = count_stmt.where(LeaveRequest.company_id.in_(view_ids))
        else:
            create_ids = principal.permitted_company_ids("leave_request.create")
            if not create_ids or self_eid is None:
                raise ForbiddenError("Missing permission: leave_request.view")
            if employee_id is not None and employee_id != self_eid:
                raise ForbiddenError("Missing permission: leave_request.view")
            forced_employee = self_eid
            stmt = stmt.where(LeaveRequest.company_id.in_(create_ids))
            count_stmt = count_stmt.where(
                LeaveRequest.company_id.in_(create_ids)
            )

    if forced_employee is not None:
        employee_id = forced_employee
    if employee_id is not None:
        stmt = stmt.where(LeaveRequest.employee_id == employee_id)
        count_stmt = count_stmt.where(LeaveRequest.employee_id == employee_id)
    if leave_type_id is not None:
        stmt = stmt.where(LeaveRequest.leave_type_id == leave_type_id)
        count_stmt = count_stmt.where(LeaveRequest.leave_type_id == leave_type_id)
    if status is not None:
        stmt = stmt.where(LeaveRequest.status == status)
        count_stmt = count_stmt.where(LeaveRequest.status == status)
    if date_from is not None:
        stmt = stmt.where(LeaveRequest.end_date >= date_from)
        count_stmt = count_stmt.where(LeaveRequest.end_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(LeaveRequest.start_date <= date_to)
        count_stmt = count_stmt.where(LeaveRequest.start_date <= date_to)
    if q is not None and q.strip():
        clause = LeaveRequest.reason.ilike(f"%{q.strip()}%")
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)
    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(
        LeaveRequest.start_date.desc(), LeaveRequest.id.desc()
    )
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


def get_leave_request(
    db: Session, request_id: int, principal: Principal
) -> LeaveRequest:
    row = _fetch_request(db, request_id, principal)
    if not _can_read_request(db, principal, row):
        raise ForbiddenError("Missing permission: leave_request.view")
    return row


def create_leave_request(
    db: Session, *, payload: LeaveRequestCreate, principal: Principal, ip: str | None
) -> LeaveRequest:
    employee = _resolve_employee(db, payload.employee_id, principal)
    _require_request_verb(
        db, principal, employee.company_id, employee.id, "leave_request.create"
    )
    _require_active_employee(employee)
    leave_type = db.get(LeaveType, payload.leave_type_id)
    if leave_type is None or leave_type.company_id != employee.company_id:
        raise LeaveTypeNotFoundError("Leave type not found")
    if leave_type.status != "active":
        raise LeaveTypeInactiveError("Leave type is inactive")
    if payload.end_date < payload.start_date:
        raise LeaveRequestRangeError("end_date must not be before start_date")
    if (payload.start_time is None) != (payload.end_time is None):
        raise LeaveRequestTimesError(
            "start_time and end_time must be provided together"
        )
    _validate_reason(leave_type, payload.reason)
    _assert_no_request_overlap(
        db, employee, payload.start_date, payload.end_date
    )
    row = LeaveRequest(
        company_id=employee.company_id,
        employee_id=employee.id,
        leave_type_id=leave_type.id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        reason=payload.reason,
        status="draft",
        created_by=principal.user_id,
    )
    _count_for(db, employee, leave_type, row)
    _validate_request_days(leave_type, row.days)
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        raise LeaveRequestOverlapError(
            "Another submitted or approved leave request already covers "
            "part of this range"
        ) from exc
    record_audit(
        db,
        action="leave_request.create",
        entity="leave_request",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        new_value=_request_snapshot(row),
        ip_address=ip,
    )
    db.flush()
    return row


def update_leave_request(
    db: Session,
    *,
    request_id: int,
    payload: LeaveRequestUpdate,
    principal: Principal,
    ip: str | None,
) -> LeaveRequest:
    row = _fetch_request(db, request_id, principal)
    _require_request_verb(
        db, principal, row.company_id, row.employee_id, "leave_request.update"
    )
    _transition_guard(row, allowed={"draft"})
    changes = payload.model_dump(exclude_unset=True)
    if "leave_type_id" in changes:
        leave_type = db.get(LeaveType, changes["leave_type_id"])
        if leave_type is None or leave_type.company_id != row.company_id:
            raise LeaveTypeNotFoundError("Leave type not found")
        if leave_type.status != "active":
            raise LeaveTypeInactiveError("Leave type is inactive")
    else:
        leave_type = db.get(LeaveType, row.leave_type_id)
        assert leave_type is not None
    for key, value in changes.items():
        setattr(row, key, value)
    if row.end_date < row.start_date:
        raise LeaveRequestRangeError("end_date must not be before start_date")
    if (row.start_time is None) != (row.end_time is None):
        raise LeaveRequestTimesError(
            "start_time and end_time must be provided together"
        )
    employee = db.get(Employee, row.employee_id)
    assert employee is not None
    _validate_reason(leave_type, row.reason)
    _assert_no_request_overlap(
        db, employee, row.start_date, row.end_date, exclude_id=row.id
    )
    _count_for(db, employee, leave_type, row)
    _validate_request_days(leave_type, row.days)
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        raise LeaveRequestOverlapError(
            "Another submitted or approved leave request already covers "
            "part of this range"
        ) from exc
    record_audit(
        db,
        action="leave_request.update",
        entity="leave_request",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        new_value={"fields": sorted(changes)},
        ip_address=ip,
    )
    db.flush()
    return row


def delete_leave_request(
    db: Session, *, request_id: int, principal: Principal, ip: str | None
) -> None:
    row = _fetch_request(db, request_id, principal)
    _require(principal, "leave_request.delete", row.company_id)
    _transition_guard(row, allowed={"draft"})
    old = _request_snapshot(row)
    db.delete(row)
    db.flush()
    record_audit(
        db,
        action="leave_request.delete",
        entity="leave_request",
        record_id=request_id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        old_value=old,
        ip_address=ip,
    )
    db.flush()


def preview_leave_request(
    db: Session, *, payload: LeaveRequestPreview, principal: Principal
) -> LeaveRequestPreviewOut:
    employee = _resolve_employee(db, payload.employee_id, principal)
    _require_request_verb(
        db, principal, employee.company_id, employee.id, "leave_request.create"
    )
    leave_type = db.get(LeaveType, payload.leave_type_id)
    if leave_type is None or leave_type.company_id != employee.company_id:
        raise LeaveTypeNotFoundError("Leave type not found")
    result = count_leave_days(
        db,
        employee,
        leave_type,
        payload.start_date,
        payload.end_date,
        payload.start_time,
        payload.end_time,
    )
    balance = compute_balance(
        db,
        employee,
        leave_type,
        period=(payload.start_date, payload.end_date),
        exclude_request_id=payload.exclude_request_id,
    )
    would_be_negative = balance.remaining_days - result.days < 0
    probe = LeaveRequest(
        company_id=employee.company_id,
        employee_id=employee.id,
        leave_type_id=leave_type.id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        days=result.days,
        status="submitted",
        count_details=result.to_details(),
    )
    return LeaveRequestPreviewOut(
        days=result.days,
        day_counting_mode=result.mode,
        count_details=probe.count_details,
        balance=BalanceOut(**_balance_line_out(balance)),
        would_be_negative=would_be_negative,
        has_open_attendance_conflict=_open_attendance_conflict(
            db, employee, probe
        ),
        has_approved_overtime_conflict=_overtime_conflict(db, employee, probe),
    )


def _approve_core(
    db: Session,
    *,
    request: LeaveRequest,
    employee: Employee,
    leave_type: LeaveType,
    principal: Principal,
    reason: str | None,
    auto: bool,
    ip: str | None,
) -> LeaveRequest:
    """Shared approval path (submit auto-approve + explicit approve).

    Lock order (deterministic, deadlock-free):
    1. the request row (already locked by the caller when explicit),
    2. covering allocations ordered by (period_start, id).
    """
    if _open_attendance_conflict(db, employee, request):
        raise LeaveAttendanceOpenConflictError(
            "An open attendance record exists within the leave dates"
        )
    if _overtime_conflict(db, employee, request):
        raise LeaveOvertimeConflictError(
            "Approved overtime exists on a full leave day"
        )
    locked = lock_allocations_for_request(
        db, employee, leave_type.id, (request.start_date, request.end_date)
    )
    ensure_balance(
        db,
        employee,
        leave_type,
        period=(request.start_date, request.end_date),
        days_needed=Decimal(request.days),
        exclude_request_id=request.id,
    )
    consume_fifo(db, request, leave_type, locked)
    request.status = "approved"
    request.decided_by = principal.user_id
    request.decided_at = _now()
    request.decision_reason = reason
    db.add(request)
    db.flush()
    record_audit(
        db,
        action="leave_request.approve",
        entity="leave_request",
        record_id=request.id,
        actor_user_id=principal.user_id,
        company_id=request.company_id,
        old_value={"status": "submitted"},
        new_value={
            **_request_snapshot(request),
            "mode": "auto" if auto else "manual",
            "reason": reason,
        },
        ip_address=ip,
    )
    db.flush()
    return request


def submit_leave_request(
    db: Session, *, request_id: int, principal: Principal, ip: str | None
) -> LeaveRequest:
    row = _fetch_request(db, request_id, principal)
    _require_request_verb(
        db, principal, row.company_id, row.employee_id, "leave_request.submit"
    )
    _transition_guard(row, allowed={"draft"})
    employee = db.get(Employee, row.employee_id)
    assert employee is not None
    _require_active_employee(employee)
    leave_type = db.get(LeaveType, row.leave_type_id)
    assert leave_type is not None
    if leave_type.status != "active":
        raise LeaveTypeInactiveError("Leave type is inactive")
    _validate_reason(leave_type, row.reason)
    _count_for(db, employee, leave_type, row)
    _validate_request_days(leave_type, row.days)
    _validate_attachment(leave_type, row)
    _assert_no_request_overlap(
        db, employee, row.start_date, row.end_date, exclude_id=row.id
    )
    ensure_balance(
        db,
        employee,
        leave_type,
        period=(row.start_date, row.end_date),
        days_needed=Decimal(row.days),
        exclude_request_id=row.id,
    )
    row.status = "submitted"
    row.submitted_by = principal.user_id
    row.submitted_at = _now()
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        raise LeaveRequestOverlapError(
            "Another submitted or approved leave request already covers "
            "part of this range"
        ) from exc
    record_audit(
        db,
        action="leave_request.submit",
        entity="leave_request",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        old_value={"status": "draft"},
        new_value=_request_snapshot(row),
        ip_address=ip,
    )
    db.flush()
    if not leave_type.requires_approval:
        return _approve_core(
            db,
            request=row,
            employee=employee,
            leave_type=leave_type,
            principal=principal,
            reason="auto",
            auto=True,
            ip=ip,
        )
    return row


def approve_leave_request(
    db: Session,
    *,
    request_id: int,
    payload: LeaveRequestDecision,
    principal: Principal,
    ip: str | None,
) -> LeaveRequest:
    row = _fetch_request(db, request_id, principal, lock=True)
    _require(principal, "leave_request.approve", row.company_id)
    _transition_guard(row, allowed={"submitted"})
    employee = db.get(Employee, row.employee_id)
    assert employee is not None
    _require_active_employee(employee)
    leave_type = db.get(LeaveType, row.leave_type_id)
    assert leave_type is not None
    return _approve_core(
        db,
        request=row,
        employee=employee,
        leave_type=leave_type,
        principal=principal,
        reason=payload.reason,
        auto=False,
        ip=ip,
    )


def reject_leave_request(
    db: Session,
    *,
    request_id: int,
    payload: LeaveRequestDecision,
    principal: Principal,
    ip: str | None,
) -> LeaveRequest:
    row = _fetch_request(db, request_id, principal, lock=True)
    _require(principal, "leave_request.reject", row.company_id)
    _transition_guard(row, allowed={"submitted"})
    if not payload.reason or not payload.reason.strip():
        raise LeaveDecisionReasonRequiredError(
            "A reason is required to reject a leave request"
        )
    old = _request_snapshot(row)
    row.status = "rejected"
    row.decision_reason = payload.reason
    row.decided_by = principal.user_id
    row.decided_at = _now()
    db.add(row)
    db.flush()
    record_audit(
        db,
        action="leave_request.reject",
        entity="leave_request",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        old_value=old,
        new_value={**_request_snapshot(row), "reason": payload.reason},
        ip_address=ip,
    )
    db.flush()
    return row


def cancel_leave_request(
    db: Session,
    *,
    request_id: int,
    payload: LeaveRequestDecision,
    principal: Principal,
    ip: str | None,
) -> LeaveRequest:
    row = _fetch_request(db, request_id, principal, lock=True)
    _require_request_verb(
        db, principal, row.company_id, row.employee_id, "leave_request.cancel"
    )
    _transition_guard(row, allowed={"draft", "submitted", "approved"})
    employee = db.get(Employee, row.employee_id)
    assert employee is not None
    old = _request_snapshot(row)
    released = 0
    if row.status == "approved":
        if _attendance_exists(db, employee, row):
            raise LeaveAttendanceRecordExistsError(
                "Attendance records exist on the leave dates; correct "
                "them before cancelling approved leave"
            )
        leave_type = db.get(LeaveType, row.leave_type_id)
        assert leave_type is not None
        locked = lock_allocations_for_request(
            db, employee, leave_type.id, (row.start_date, row.end_date)
        )
        released = release_consumptions(db, row, locked)
    row.status = "cancelled"
    row.cancel_reason = payload.reason
    row.cancelled_by = principal.user_id
    row.cancelled_at = _now()
    db.add(row)
    db.flush()
    record_audit(
        db,
        action="leave_request.cancel",
        entity="leave_request",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        old_value=old,
        new_value={**_request_snapshot(row), "released_days": released},
        ip_address=ip,
    )
    db.flush()
    return row


# ---------------------------------------------------------------------------
# Attachments (single optional file per request, existing FileStorage)
# ---------------------------------------------------------------------------


def upload_request_attachment(
    db: Session,
    *,
    request_id: int,
    raw_filename: str,
    declared_mime: str | None,
    file_data: bytes,
    principal: Principal,
    ip: str | None,
) -> LeaveRequest:
    row = _fetch_request(db, request_id, principal)
    _require_request_verb(
        db, principal, row.company_id, row.employee_id, "leave_request.update"
    )
    _transition_guard(row, allowed={"draft", "submitted"})
    file_name, mime_type = validate_document_upload(
        filename=raw_filename, declared_mime=declared_mime, data=file_data
    )
    employee = db.get(Employee, row.employee_id)
    assert employee is not None
    storage = get_storage()
    if row.attachment_path:
        storage.delete(row.attachment_path)
    storage_key = storage.save(
        company_id=row.company_id,
        employee_id=employee.id,
        data=file_data,
        mime_type=mime_type,
    )
    row.attachment_path = storage_key
    row.attachment_name = file_name
    row.attachment_mime = mime_type
    row.attachment_size = len(file_data)
    row.attachment_uploaded_by = principal.user_id
    db.add(row)
    db.flush()
    record_audit(
        db,
        action="leave_request.update",
        entity="leave_request",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        new_value={"fields": ["attachment"]},
        ip_address=ip,
    )
    db.flush()
    return row


def download_request_attachment(
    db: Session, *, request_id: int, principal: Principal
) -> tuple[bytes, str, str]:
    row = _fetch_request(db, request_id, principal)
    if not _can_read_request(db, principal, row):
        raise ForbiddenError("Missing permission: leave_request.view")
    if not row.attachment_path:
        raise NotFoundError("Leave request has no attachment")
    storage = get_storage()
    data = storage.load(row.attachment_path)
    return (
        data,
        row.attachment_mime or "application/octet-stream",
        row.attachment_name or "attachment",
    )


def delete_request_attachment(
    db: Session, *, request_id: int, principal: Principal, ip: str | None
) -> None:
    row = _fetch_request(db, request_id, principal)
    _require_request_verb(
        db, principal, row.company_id, row.employee_id, "leave_request.update"
    )
    _transition_guard(row, allowed={"draft", "submitted"})
    if not row.attachment_path:
        raise NotFoundError("Leave request has no attachment")
    storage = get_storage()
    storage.delete(row.attachment_path)
    row.attachment_path = None
    row.attachment_name = None
    row.attachment_mime = None
    row.attachment_size = None
    row.attachment_uploaded_by = None
    db.add(row)
    db.flush()
    record_audit(
        db,
        action="leave_request.update",
        entity="leave_request",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        new_value={"fields": ["attachment_removed"]},
        ip_address=ip,
    )
    db.flush()


# ---------------------------------------------------------------------------
# Balances
# ---------------------------------------------------------------------------


def _balance_line_out(line: BalanceLine) -> dict[str, Any]:
    return {
        "leave_type_id": line.leave_type_id,
        "code": line.code,
        "name_ar": line.name_ar,
        "name_en": line.name_en,
        "is_paid": line.is_paid,
        "allocated_days": line.allocated_days,
        "used_days": line.used_days,
        "pending_days": line.pending_days,
        "remaining_days": line.remaining_days,
        "negative_balance_allowed": line.negative_balance_allowed,
    }


def list_leave_balances(
    db: Session,
    principal: Principal,
    *,
    company_id: int | None = None,
    employee_id: int | None = None,
    leave_type_id: int | None = None,
    as_of: date | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
) -> list[dict[str, Any]]:
    if employee_id is None:
        raise LeaveRequestNotFoundError("employee_id is required")
    employee = _resolve_employee(db, employee_id, principal)
    _require(principal, "leave_balance.view", employee.company_id)
    stmt = select(LeaveType).where(
        LeaveType.company_id == employee.company_id,
        LeaveType.status == "active",
    )
    if leave_type_id is not None:
        stmt = stmt.where(LeaveType.id == leave_type_id)
    stmt = stmt.order_by(LeaveType.sort_order, LeaveType.id)
    period = None
    if period_start is not None and period_end is not None:
        period = (period_start, period_end)
    lines = []
    for leave_type in db.execute(stmt).scalars():
        line = compute_balance(
            db, employee, leave_type, as_of=as_of, period=period
        )
        lines.append(_balance_line_out(line))
    return lines


def my_leave_balances(
    db: Session,
    principal: Principal,
    *,
    as_of: date | None = None,
) -> list[dict[str, Any]]:
    """Self balance: authenticated + linked employee, no extra code."""
    self_eid = _self_employee_id(db, principal)
    if self_eid is None:
        raise ForbiddenError("Your account is not linked to an employee")
    employee = db.get(Employee, self_eid)
    if employee is None or not principal.can_access_company(employee.company_id):
        raise ForbiddenError("Your account is not linked to an employee")
    stmt = (
        select(LeaveType)
        .where(
            LeaveType.company_id == employee.company_id,
            LeaveType.status == "active",
        )
        .order_by(LeaveType.sort_order, LeaveType.id)
    )
    lines = []
    for leave_type in db.execute(stmt).scalars():
        line = compute_balance(db, employee, leave_type, as_of=as_of)
        lines.append(_balance_line_out(line))
    return lines


# ---------------------------------------------------------------------------
# Company holidays (dedicated company-scoped table, D1)
# ---------------------------------------------------------------------------


def list_holidays(
    db: Session,
    principal: Principal,
    *,
    company_id: int | None = None,
    year: int | None = None,
    status: str | None = None,
    page: PageParams | None = None,
) -> tuple[list[CompanyHoliday], int]:
    stmt = select(CompanyHoliday)
    count_stmt = select(func.count()).select_from(CompanyHoliday)
    if company_id is not None:
        if not principal.can_access_company(company_id):
            raise ForbiddenError("You cannot access this company")
        _require(principal, "leave_holiday.view", company_id)
        stmt = stmt.where(CompanyHoliday.company_id == company_id)
        count_stmt = count_stmt.where(CompanyHoliday.company_id == company_id)
    elif not principal.is_platform_admin:
        allowed = principal.permitted_company_ids("leave_holiday.view")
        if not allowed:
            return [], 0
        stmt = stmt.where(CompanyHoliday.company_id.in_(allowed))
        count_stmt = count_stmt.where(CompanyHoliday.company_id.in_(allowed))
    if year is not None:
        stmt = stmt.where(
            func.extract("year", CompanyHoliday.date) == year
        )
        count_stmt = count_stmt.where(
            func.extract("year", CompanyHoliday.date) == year
        )
    if status is not None:
        stmt = stmt.where(CompanyHoliday.status == status)
        count_stmt = count_stmt.where(CompanyHoliday.status == status)
    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(CompanyHoliday.date)
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


def _fetch_holiday(
    db: Session, holiday_id: int, principal: Principal
) -> CompanyHoliday:
    row = db.get(CompanyHoliday, holiday_id)
    if row is None or not principal.can_access_company(row.company_id):
        raise CompanyHolidayNotFoundError("Holiday not found")
    return row


def get_holiday(
    db: Session, holiday_id: int, principal: Principal
) -> CompanyHoliday:
    row = _fetch_holiday(db, holiday_id, principal)
    _require(principal, "leave_holiday.view", row.company_id)
    return row


def create_holiday(
    db: Session, *, payload: HolidayCreate, principal: Principal, ip: str | None
) -> CompanyHoliday:
    if not principal.can_access_company(payload.company_id):
        raise ForbiddenError("You cannot create holidays in this company")
    _require(principal, "leave_holiday.create", payload.company_id)
    existing = db.execute(
        select(CompanyHoliday.id).where(
            CompanyHoliday.company_id == payload.company_id,
            CompanyHoliday.date == payload.date,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise CompanyHolidayExistsError(
            "A holiday already exists on this date in this company"
        )
    row = CompanyHoliday(
        company_id=payload.company_id,
        name_ar=payload.name_ar,
        name_en=payload.name_en,
        date=payload.date,
        status=payload.status,
        notes=payload.notes,
        created_by=principal.user_id,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        raise CompanyHolidayExistsError(
            "A holiday already exists on this date in this company"
        ) from exc
    record_audit(
        db,
        action="leave_holiday.create",
        entity="company_holiday",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        new_value={"date": str(row.date), "name_en": row.name_en},
        ip_address=ip,
    )
    db.flush()
    return row


def update_holiday(
    db: Session,
    *,
    holiday_id: int,
    payload: HolidayUpdate,
    principal: Principal,
    ip: str | None,
) -> CompanyHoliday:
    row = _fetch_holiday(db, holiday_id, principal)
    _require(principal, "leave_holiday.update", row.company_id)
    changes = payload.model_dump(exclude_unset=True)
    if "date" in changes and changes["date"] != row.date:
        existing = db.execute(
            select(CompanyHoliday.id).where(
                CompanyHoliday.company_id == row.company_id,
                CompanyHoliday.date == changes["date"],
                CompanyHoliday.id != row.id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise CompanyHolidayExistsError(
                "A holiday already exists on this date in this company"
            )
    for key, value in changes.items():
        setattr(row, key, value)
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        raise CompanyHolidayExistsError(
            "A holiday already exists on this date in this company"
        ) from exc
    record_audit(
        db,
        action="leave_holiday.update",
        entity="company_holiday",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        new_value={"fields": sorted(changes)},
        ip_address=ip,
    )
    db.flush()
    return row


def delete_holiday(
    db: Session, *, holiday_id: int, principal: Principal, ip: str | None
) -> None:
    row = _fetch_holiday(db, holiday_id, principal)
    _require(principal, "leave_holiday.delete", row.company_id)
    old = {"date": str(row.date), "name_en": row.name_en}
    db.delete(row)
    db.flush()
    record_audit(
        db,
        action="leave_holiday.delete",
        entity="company_holiday",
        record_id=holiday_id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        old_value=old,
        ip_address=ip,
    )
    db.flush()
