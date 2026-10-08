"""Phase 8 salary advance core: self-scope helpers + workflow machine.

Authorization model (no hardcoded role names anywhere - permission codes
only, always company-scoped):

- owner verbs (create/update/submit/cancel): the code alone allows acting
  on your OWN advance; acting for another employee additionally requires
  ``salary_advance.view`` (cross-employee marker, Phase 5/7 pattern).
- decisions (approve/reject): ``(approver_employee_id == self AND the
  verb code)`` OR ``salary_advance.manage`` (HR override; also the only
  path when no manager is assigned at submit time).
- finance (disburse/settle): plain company-scoped verb checks - the grant
  matrix keeps decisions and payments separated (SoD).
- reads: ``view`` OR own-with-``create`` OR assigned-approver OR manage.

State machine: draft -> submitted -> approved -> disbursed -> settled;
submitted may also be rejected, draft/submitted cancelled (never after
approval). Approver is snapshotted from ``employees.manager_id`` at
submit; reject requires a reason.

Disbursement consumes the frozen ``create_payroll_deduction`` service
(real principal - no permission bypass); repayment happens inside the
frozen payroll-approve consumption; early settlement cancels the rule
through the frozen ``update_payroll_deduction`` service. A read-path
reconcile auto-settles advances whose linked rule already completed or
was cancelled (system-attributed event + NULL-actor audit).
"""

from __future__ import annotations

from datetime import date, datetime
from datetime import timezone as dt_timezone
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.advance.schemas import (
    AdvanceCreate,
    AdvanceDecision,
    AdvanceDisburse,
    AdvanceSettle,
    AdvanceUpdate,
)
from app.audit.service import record_audit
from app.core.deps import Principal
from app.core.exceptions import (
    EssNotLinkedError,
    ForbiddenError,
    SalaryAdvanceAmountError,
    SalaryAdvanceForbiddenError,
    SalaryAdvanceInstallmentError,
    SalaryAdvanceNotFoundError,
    SalaryAdvanceReasonRequiredError,
    SalaryAdvanceRuleMissingError,
    SalaryAdvanceStateError,
)
from app.core.pagination import PageParams
from app.ess.service import self_employee_id
from app.payroll.schemas import PayrollDeductionCreate, PayrollDeductionUpdate
from app.payroll.service import (
    create_payroll_deduction,
    update_payroll_deduction,
)
from app.shared.models import (
    Employee,
    PayrollDeductionRule,
    SalaryAdvance,
    SalaryAdvanceEvent,
    User,
)


def _now() -> datetime:
    return datetime.now(dt_timezone.utc)


def _today() -> date:
    return _now().date()


def _require(principal: Principal, code: str, company_id: int | None) -> None:
    """Company-scoped permission check (H1)."""
    if not principal.has_permission(code, company_id):
        raise ForbiddenError(f"Missing permission: {code}")


def _require_advance_verb(
    db: Session,
    principal: Principal,
    company_id: int,
    owner_employee_id: int,
    verb: str,
) -> None:
    _require(principal, verb, company_id)
    self_id = self_employee_id(db, principal)
    if owner_employee_id != self_id:
        _require(principal, "salary_advance.view", company_id)


def _can_read_advance(
    db: Session, principal: Principal, row: SalaryAdvance
) -> bool:
    if principal.has_permission("salary_advance.manage", row.company_id):
        return True
    if principal.has_permission("salary_advance.view", row.company_id):
        return True
    self_id = self_employee_id(db, principal)
    if self_id is None:
        return False
    if row.employee_id == self_id and principal.has_permission(
        "salary_advance.create", row.company_id
    ):
        return True
    return row.approver_employee_id == self_id and (
        principal.has_permission("salary_advance.approve", row.company_id)
        or principal.has_permission("salary_advance.reject", row.company_id)
    )


def _require_decision(
    db: Session, principal: Principal, row: SalaryAdvance, verb: str
) -> None:
    if principal.has_permission("salary_advance.manage", row.company_id):
        return
    self_id = self_employee_id(db, principal)
    if (
        self_id is not None
        and row.approver_employee_id == self_id
        and principal.has_permission(verb, row.company_id)
    ):
        return
    raise SalaryAdvanceForbiddenError(
        "You are not authorized to decide this advance"
    )


def _fetch_advance(
    db: Session, advance_id: int, principal: Principal, *, lock: bool = False
) -> SalaryAdvance:
    stmt = select(SalaryAdvance).where(SalaryAdvance.id == advance_id)
    if lock:
        stmt = stmt.with_for_update()
    row = db.execute(stmt).scalar_one_or_none()
    if row is None or not principal.can_access_company(row.company_id):
        raise SalaryAdvanceNotFoundError("Salary advance not found")
    return row


def _require_state(row: SalaryAdvance, allowed: set[str], action: str) -> None:
    if row.status not in allowed:
        raise SalaryAdvanceStateError(
            f"Cannot {action} an advance in status '{row.status}'"
        )


def _fetch_employee(
    db: Session, employee_id: int, principal: Principal
) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None or not principal.can_access_company(employee.company_id):
        raise SalaryAdvanceNotFoundError("Employee not found")
    return employee


def _require_active(employee: Employee) -> None:
    if employee.status != "active":
        raise ForbiddenError(
            "Salary advances are only available for active employees"
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
    row: SalaryAdvance,
    principal: Principal,
    event_type: str,
    note: str | None = None,
) -> None:
    db.add(
        SalaryAdvanceEvent(
            company_id=row.company_id,
            advance_id=row.id,
            event_type=event_type,
            actor_user_id=principal.user_id,
            actor_name=_actor_name(db, principal),
            note=(note[:500] if note else None),
        )
    )


def _add_system_event(
    db: Session, row: SalaryAdvance, note: str | None = None
) -> None:
    db.add(
        SalaryAdvanceEvent(
            company_id=row.company_id,
            advance_id=row.id,
            event_type="settled",
            actor_user_id=None,
            actor_name="system",
            note=(note[:500] if note else None),
        )
    )


def _snapshot(row: SalaryAdvance) -> dict:
    return {
        "employee_id": row.employee_id,
        "approver_employee_id": row.approver_employee_id,
        "status": row.status,
        "amount": str(row.amount),
        "installment_amount": (
            str(row.installment_amount) if row.installment_amount else None
        ),
        "requested_date": str(row.requested_date),
        "deduction_rule_id": row.deduction_rule_id,
    }


def _audit(
    db: Session,
    *,
    action: str,
    row: SalaryAdvance,
    principal: Principal,
    ip: str | None,
    old_value: dict | None = None,
    new_value: dict | None = None,
) -> None:
    record_audit(
        db,
        action=action,
        entity="salary_advance",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        old_value=old_value,
        new_value=new_value or _snapshot(row),
        ip_address=ip,
    )


# ---------------------------------------------------------------------------
# Read-path reconcile (auto-settlement)
# ---------------------------------------------------------------------------


def _reconcile_if_done(db: Session, row: SalaryAdvance) -> bool:
    """Close a disbursed advance whose linked deduction rule already
    finished (completed by payroll consumption, or cancelled)."""
    if row.status != "disbursed" or row.deduction_rule_id is None:
        return False
    rule = db.get(PayrollDeductionRule, row.deduction_rule_id)
    if rule is None or rule.status not in ("completed", "cancelled"):
        return False
    old = _snapshot(row)
    row.status = "settled"
    row.settled_by = None
    row.settled_at = _now()
    row.settle_note = f"auto: deduction rule {rule.status}"
    db.add(row)
    db.flush()
    _add_system_event(db, row, note=row.settle_note)
    record_audit(
        db,
        action="salary_advance.settle",
        entity="salary_advance",
        record_id=row.id,
        actor_user_id=None,
        company_id=row.company_id,
        old_value=old,
        new_value=_snapshot(row),
        ip_address=None,
    )
    db.flush()
    return True


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def list_advances(
    db: Session,
    principal: Principal,
    *,
    company_id: int | None = None,
    employee_id: int | None = None,
    status: str | None = None,
    assigned_to_me: bool = False,
    page: PageParams | None = None,
) -> tuple[list[SalaryAdvance], int]:
    """List with the Phase 5/7 self-scope fallback: ``view`` sees the
    company; create-only callers are forced to their own rows.
    ``assigned_to_me`` switches to the decision-inbox scoping (manage
    holders see their companies' rows, decide holders only their own
    assignments)."""
    if assigned_to_me:
        return _list_inbox(
            db,
            principal,
            company_id=company_id,
            status=status,
            page=page,
        )

    self_id = self_employee_id(db, principal)
    stmt = select(SalaryAdvance)
    count_stmt = select(func.count()).select_from(SalaryAdvance)
    forced_employee: int | None = None

    if company_id is not None:
        if not principal.can_access_company(company_id):
            raise ForbiddenError("You cannot access this company")
        if principal.has_permission("salary_advance.view", company_id):
            pass
        elif self_id is not None and principal.has_permission(
            "salary_advance.create", company_id
        ):
            if employee_id is not None and employee_id != self_id:
                raise ForbiddenError("Missing permission: salary_advance.view")
            forced_employee = self_id
        else:
            raise ForbiddenError("Missing permission: salary_advance.view")
        stmt = stmt.where(SalaryAdvance.company_id == company_id)
        count_stmt = count_stmt.where(SalaryAdvance.company_id == company_id)
    elif not principal.is_platform_admin:
        view_ids = principal.permitted_company_ids("salary_advance.view")
        if view_ids:
            stmt = stmt.where(SalaryAdvance.company_id.in_(view_ids))
            count_stmt = count_stmt.where(
                SalaryAdvance.company_id.in_(view_ids)
            )
        else:
            create_ids = principal.permitted_company_ids(
                "salary_advance.create"
            )
            if not create_ids or self_id is None:
                raise ForbiddenError("Missing permission: salary_advance.view")
            if employee_id is not None and employee_id != self_id:
                raise ForbiddenError("Missing permission: salary_advance.view")
            forced_employee = self_id
            stmt = stmt.where(SalaryAdvance.company_id.in_(create_ids))
            count_stmt = count_stmt.where(
                SalaryAdvance.company_id.in_(create_ids)
            )

    if forced_employee is not None:
        employee_id = forced_employee
    if employee_id is not None:
        stmt = stmt.where(SalaryAdvance.employee_id == employee_id)
        count_stmt = count_stmt.where(SalaryAdvance.employee_id == employee_id)
    if status is not None:
        stmt = stmt.where(SalaryAdvance.status == status)
        count_stmt = count_stmt.where(SalaryAdvance.status == status)

    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(SalaryAdvance.id.desc())
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    rows = list(db.execute(stmt).scalars())
    for row in rows:
        _reconcile_if_done(db, row)
    return rows, total


def _list_inbox(
    db: Session,
    principal: Principal,
    *,
    company_id: int | None,
    status: str | None,
    page: PageParams | None,
) -> tuple[list[SalaryAdvance], int]:
    """Decision inbox: manage holders see their companies' rows; decide
    holders see only rows assigned to them as approver."""
    self_id = self_employee_id(db, principal)
    manage_ids = principal.permitted_company_ids("salary_advance.manage")
    decide_ids = sorted(
        set(principal.permitted_company_ids("salary_advance.approve"))
        | set(principal.permitted_company_ids("salary_advance.reject"))
    )

    stmt = select(SalaryAdvance)
    count_stmt = select(func.count()).select_from(SalaryAdvance)

    if company_id is not None:
        if not principal.can_access_company(company_id):
            raise ForbiddenError("You cannot access this company")
        can_manage = principal.has_permission(
            "salary_advance.manage", company_id
        )
        can_decide = principal.has_permission(
            "salary_advance.approve", company_id
        ) or principal.has_permission("salary_advance.reject", company_id)
        if not can_manage and not can_decide:
            raise ForbiddenError(
                "Missing permission: salary_advance.approve"
            )
        stmt = stmt.where(SalaryAdvance.company_id == company_id)
        count_stmt = count_stmt.where(SalaryAdvance.company_id == company_id)
        if not can_manage:
            if self_id is None:
                return [], 0
            stmt = stmt.where(SalaryAdvance.approver_employee_id == self_id)
            count_stmt = count_stmt.where(
                SalaryAdvance.approver_employee_id == self_id
            )
    elif not principal.is_platform_admin:
        if not manage_ids and not decide_ids:
            raise ForbiddenError("Missing permission: salary_advance.approve")
        clauses = []
        if manage_ids:
            clauses.append(SalaryAdvance.company_id.in_(manage_ids))
        if decide_ids and self_id is not None:
            clauses.append(
                (SalaryAdvance.company_id.in_(decide_ids))
                & (SalaryAdvance.approver_employee_id == self_id)
            )
        if not clauses:
            return [], 0
        clause = or_(*clauses)
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)

    if status is not None:
        stmt = stmt.where(SalaryAdvance.status == status)
        count_stmt = count_stmt.where(SalaryAdvance.status == status)

    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(
        SalaryAdvance.submitted_at.asc().nulls_last(),
        SalaryAdvance.id.asc(),
    )
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    rows = list(db.execute(stmt).scalars())
    for row in rows:
        _reconcile_if_done(db, row)
    return rows, total


def get_advance(
    db: Session, advance_id: int, principal: Principal
) -> SalaryAdvance:
    row = _fetch_advance(db, advance_id, principal)
    if not _can_read_advance(db, principal, row):
        raise SalaryAdvanceForbiddenError("You cannot view this advance")
    _reconcile_if_done(db, row)
    return row


def get_advance_detail(
    db: Session, advance_id: int, principal: Principal
) -> tuple[SalaryAdvance, list[SalaryAdvanceEvent]]:
    row = get_advance(db, advance_id, principal)
    events = list(
        db.execute(
            select(SalaryAdvanceEvent)
            .where(SalaryAdvanceEvent.advance_id == row.id)
            .order_by(SalaryAdvanceEvent.id)
        ).scalars()
    )
    return row, events


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


def _validate_amount(amount: Decimal | None) -> None:
    if amount is not None and amount <= 0:
        raise SalaryAdvanceAmountError("amount must be greater than 0")


def _validate_reason(reason: str) -> str:
    cleaned = reason.strip()
    if not cleaned:
        raise SalaryAdvanceReasonRequiredError("reason is required")
    return cleaned


def create_advance(
    db: Session,
    *,
    payload: AdvanceCreate,
    principal: Principal,
    ip: str | None,
) -> SalaryAdvance:
    self_id = self_employee_id(db, principal)
    employee_id = (
        payload.employee_id if payload.employee_id is not None else self_id
    )
    if employee_id is None:
        raise EssNotLinkedError("Your account is not linked to an employee")
    employee = _fetch_employee(db, employee_id, principal)
    _require_advance_verb(
        db,
        principal,
        employee.company_id,
        employee.id,
        "salary_advance.create",
    )
    _require_active(employee)
    _validate_amount(payload.amount)
    reason = _validate_reason(payload.reason)

    row = SalaryAdvance(
        company_id=employee.company_id,
        employee_id=employee.id,
        amount=payload.amount,
        reason=reason,
        requested_date=payload.requested_date,
        status="draft",
        created_by=principal.user_id,
    )
    db.add(row)
    db.flush()
    _add_event(db, row, principal, "created")
    _audit(
        db, action="salary_advance.create", row=row, principal=principal, ip=ip
    )
    db.flush()
    return row


def update_advance(
    db: Session,
    *,
    advance_id: int,
    payload: AdvanceUpdate,
    principal: Principal,
    ip: str | None,
) -> SalaryAdvance:
    row = _fetch_advance(db, advance_id, principal, lock=True)
    _require_state(row, {"draft"}, "update")
    _require_advance_verb(
        db, principal, row.company_id, row.employee_id, "salary_advance.update"
    )
    old = _snapshot(row)

    if payload.amount is not None:
        _validate_amount(payload.amount)
        row.amount = payload.amount
    if payload.reason is not None:
        row.reason = _validate_reason(payload.reason)
    if payload.requested_date is not None:
        row.requested_date = payload.requested_date

    db.add(row)
    db.flush()
    _audit(
        db,
        action="salary_advance.update",
        row=row,
        principal=principal,
        ip=ip,
        old_value=old,
    )
    db.flush()
    return row


def submit_advance(
    db: Session,
    *,
    advance_id: int,
    principal: Principal,
    ip: str | None,
) -> SalaryAdvance:
    row = _fetch_advance(db, advance_id, principal, lock=True)
    _require_state(row, {"draft"}, "submit")
    _require_advance_verb(
        db,
        principal,
        row.company_id,
        row.employee_id,
        "salary_advance.submit",
    )
    employee = _fetch_employee(db, row.employee_id, principal)
    _require_active(employee)

    old = _snapshot(row)
    row.status = "submitted"
    row.submitted_by = principal.user_id
    row.submitted_at = _now()
    # Approver snapshot at submit; never self-assigned.
    manager_id = employee.manager_id
    row.approver_employee_id = (
        manager_id if manager_id is not None and manager_id != employee.id
        else None
    )
    db.add(row)
    db.flush()
    _add_event(db, row, principal, "submitted")
    _audit(
        db,
        action="salary_advance.submit",
        row=row,
        principal=principal,
        ip=ip,
        old_value=old,
    )
    db.flush()
    return row


def cancel_advance(
    db: Session,
    *,
    advance_id: int,
    payload: AdvanceDecision | None,
    principal: Principal,
    ip: str | None,
) -> SalaryAdvance:
    row = _fetch_advance(db, advance_id, principal, lock=True)
    _require_state(row, {"draft", "submitted"}, "cancel")
    _require_advance_verb(
        db, principal, row.company_id, row.employee_id, "salary_advance.cancel"
    )
    old = _snapshot(row)
    reason = payload.reason.strip() if payload and payload.reason else None
    row.status = "cancelled"
    db.add(row)
    db.flush()
    _add_event(db, row, principal, "cancelled", note=reason)
    _audit(
        db,
        action="salary_advance.cancel",
        row=row,
        principal=principal,
        ip=ip,
        old_value=old,
        new_value={**_snapshot(row), "cancel_reason": reason},
    )
    db.flush()
    return row


def approve_advance(
    db: Session,
    *,
    advance_id: int,
    payload: AdvanceDecision | None,
    principal: Principal,
    ip: str | None,
) -> SalaryAdvance:
    row = _fetch_advance(db, advance_id, principal, lock=True)
    _require_state(row, {"submitted"}, "approve")
    _require_decision(db, principal, row, "salary_advance.approve")
    old = _snapshot(row)
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
        action="salary_advance.approve",
        row=row,
        principal=principal,
        ip=ip,
        old_value=old,
    )
    db.flush()
    return row


def reject_advance(
    db: Session,
    *,
    advance_id: int,
    payload: AdvanceDecision | None,
    principal: Principal,
    ip: str | None,
) -> SalaryAdvance:
    row = _fetch_advance(db, advance_id, principal, lock=True)
    _require_state(row, {"submitted"}, "reject")
    _require_decision(db, principal, row, "salary_advance.reject")
    reason = payload.reason if payload else None
    if not reason or not reason.strip():
        raise SalaryAdvanceReasonRequiredError(
            "A reason is required to reject an advance"
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
        action="salary_advance.reject",
        row=row,
        principal=principal,
        ip=ip,
        old_value=old,
    )
    db.flush()
    return row


def disburse_advance(
    db: Session,
    *,
    advance_id: int,
    payload: AdvanceDisburse,
    principal: Principal,
    ip: str | None,
) -> SalaryAdvance:
    row = _fetch_advance(db, advance_id, principal, lock=True)
    _require_state(row, {"approved"}, "disburse")
    _require(principal, "salary_advance.disburse", row.company_id)

    installment = (
        payload.installment_amount
        if payload.installment_amount is not None
        else row.amount
    )
    if installment <= 0 or installment > row.amount:
        raise SalaryAdvanceInstallmentError(
            "installment_amount must be greater than 0 and at most amount"
        )
    _validate_amount(row.amount)

    # Frozen Phase 6 service: re-enforces payroll_deduction.create + company
    # access with the caller's real principal (no permission bypass) and
    # writes the payroll_deduction.create audit entry.
    rule = create_payroll_deduction(
        db,
        payload=PayrollDeductionCreate(
            company_id=row.company_id,
            employee_id=row.employee_id,
            name=f"Salary advance #{row.id}"[:100],
            amount=installment,
            total_amount=row.amount,
            effective_from=_today(),
            reason=row.reason[:500],
        ),
        principal=principal,
        ip=ip,
    )

    old = _snapshot(row)
    row.installment_amount = installment
    row.deduction_rule_id = rule.id
    row.status = "disbursed"
    row.disbursed_by = principal.user_id
    row.disbursed_at = _now()
    db.add(row)
    db.flush()
    _add_event(db, row, principal, "disbursed", note=payload.note)
    _audit(
        db,
        action="salary_advance.disburse",
        row=row,
        principal=principal,
        ip=ip,
        old_value=old,
    )
    db.flush()
    return row


def settle_advance(
    db: Session,
    *,
    advance_id: int,
    payload: AdvanceSettle | None,
    principal: Principal,
    ip: str | None,
) -> SalaryAdvance:
    row = _fetch_advance(db, advance_id, principal, lock=True)
    _require_state(row, {"disbursed"}, "settle")
    _require(principal, "salary_advance.settle", row.company_id)
    if row.deduction_rule_id is None:
        raise SalaryAdvanceRuleMissingError(
            "The linked payroll deduction rule is missing"
        )
    rule = db.get(PayrollDeductionRule, row.deduction_rule_id)
    if rule is None or rule.company_id != row.company_id:
        raise SalaryAdvanceRuleMissingError(
            "The linked payroll deduction rule is missing"
        )

    reason = payload.reason.strip() if payload and payload.reason else None
    if rule.status == "active":
        # Early settlement: the remainder stops being collected.
        if not reason:
            raise SalaryAdvanceReasonRequiredError(
                "A reason is required to settle an active deduction rule"
            )
        update_payroll_deduction(
            db,
            deduction_id=rule.id,
            payload=PayrollDeductionUpdate(
                status="cancelled",
                reason=reason[:500],
            ),
            principal=principal,
            ip=ip,
        )
    elif rule.status not in ("completed", "cancelled"):
        raise SalaryAdvanceRuleMissingError(
            "The linked payroll deduction rule is missing"
        )

    old = _snapshot(row)
    row.status = "settled"
    row.settled_by = principal.user_id
    row.settled_at = _now()
    row.settle_note = reason[:500] if reason else None
    db.add(row)
    db.flush()
    _add_event(db, row, principal, "settled", note=row.settle_note)
    _audit(
        db,
        action="salary_advance.settle",
        row=row,
        principal=principal,
        ip=ip,
        old_value=old,
    )
    db.flush()
    return row
