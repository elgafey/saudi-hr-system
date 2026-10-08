from __future__ import annotations

from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.core.deps import Principal
from app.core.exceptions import (
    ForbiddenError,
    NotFoundError,
    PayrollAdjustmentNotFoundError,
    PayrollAdjustmentStateError,
    PayrollAdjustmentTargetError,
    PayrollDeductionNotFoundError,
    PayrollDeductionStateError,
    PayrollImmutableError,
    PayrollInputsChangedError,
    PayrollNotCalculatedError,
    PayrollPeriodExistsError,
    PayrollPeriodNotFoundError,
    PayrollPeriodStateError,
    PayrollRunNotFoundError,
    PayrollStatutoryRuleDateRangeError,
    PayrollStatutoryRuleError,
    PayrollStatutoryRuleNotFoundError,
    PayrollStatutoryRuleOverlapError,
    PayrollStatutoryRuleSourceRequiredError,
    PayrollStatutoryRuleValueError,
    SalaryAssignmentDateRangeError,
    SalaryAssignmentNotFoundError,
    SalaryAssignmentOverlapError,
    SalaryComponentCodeExistsError,
    SalaryComponentNotFoundError,
)
from app.core.pagination import PageParams
from app.payroll.engine import (
    blocking_warnings,
    build_inputs,
    calculate,
    snapshot_hash,
)
from app.payroll.schemas import (
    PayrollAdjustmentCreate,
    PayrollAdjustmentDecision,
    PayrollDeductionCreate,
    PayrollDeductionUpdate,
    PayrollPeriodCreate,
    PayrollPeriodUpdate,
    PayrollStatutoryRuleCreate,
    PayrollStatutoryRuleDeactivate,
    SalaryAssignmentCreate,
    SalaryAssignmentUpdate,
    SalaryComponentCreate,
    SalaryComponentUpdate,
)
from app.payroll.statutory import (
    KEY_DAILY_DIVISOR,
    KEY_OVERTIME,
    KEY_PRORATION_BASIS,
    PRORATION_BASES,
)
from app.shared.models import (
    Employee,
    EmployeeContract,
    EmployeeSalaryAssignment,
    PayrollAdjustment,
    PayrollDeductionRule,
    PayrollPeriod,
    PayrollRun,
    PayrollRunLine,
    PayrollStatutoryRule,
    PayslipLine,
    SalaryComponent,
)

# Periods whose payroll data may still change (adjustments allowed here).
OPEN_PERIOD_STATUSES = ("draft", "calculated", "reviewed")
# The single workflow machine (payroll_periods.status is authoritative).
PERIOD_TRANSITIONS = {
    "calculate": ("draft", "calculated", "reviewed"),
    "review": ("calculated",),
    "approve": ("reviewed",),
    "mark_paid": ("approved",),
    "lock": ("paid",),
}


def _now() -> datetime:
    return datetime.now(dt_timezone.utc)


def _require(principal: Principal, code: str, company_id: int | None) -> None:
    if not principal.has_permission(code, company_id):
        raise ForbiddenError(f"Missing permission: {code}")


def _scope_company(
    db: Session,
    principal: Principal,
    code: str,
    company_id: int | None,
) -> list[int] | None:
    """Return the company filter for a list query (None = no filter)."""
    if company_id is not None:
        if not principal.can_access_company(company_id):
            raise ForbiddenError("You cannot access this company")
        _require(principal, code, company_id)
        return [company_id]
    if principal.is_platform_admin:
        return None
    allowed = principal.permitted_company_ids(code)
    return allowed


# ---------------------------------------------------------------------------
# Salary components
# ---------------------------------------------------------------------------


def list_salary_components(
    db: Session,
    principal: Principal,
    *,
    company_id: int | None = None,
    category: str | None = None,
    status: str | None = None,
    page: PageParams | None = None,
) -> tuple[list[SalaryComponent], int]:
    stmt = select(SalaryComponent)
    count_stmt = select(func.count()).select_from(SalaryComponent)
    scope = _scope_company(db, principal, "salary_component.view", company_id)
    if scope is None:
        pass
    elif not scope:
        return [], 0
    else:
        stmt = stmt.where(SalaryComponent.company_id.in_(scope))
        count_stmt = count_stmt.where(SalaryComponent.company_id.in_(scope))
    if category is not None:
        stmt = stmt.where(SalaryComponent.category == category)
        count_stmt = count_stmt.where(SalaryComponent.category == category)
    if status is not None:
        stmt = stmt.where(SalaryComponent.status == status)
        count_stmt = count_stmt.where(SalaryComponent.status == status)
    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(SalaryComponent.sort_order, SalaryComponent.id)
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


def get_salary_component(
    db: Session, component_id: int, principal: Principal
) -> SalaryComponent:
    row = db.get(SalaryComponent, component_id)
    if row is None or not principal.can_access_company(row.company_id):
        raise SalaryComponentNotFoundError("Salary component not found")
    _require(principal, "salary_component.view", row.company_id)
    return row


def create_salary_component(
    db: Session, *, payload: SalaryComponentCreate, principal: Principal, ip: str | None
) -> SalaryComponent:
    if not principal.can_access_company(payload.company_id):
        raise ForbiddenError("You cannot create salary components in this company")
    _require(principal, "salary_component.create", payload.company_id)
    code = payload.code.strip()
    exists = db.execute(
        select(SalaryComponent.id).where(
            SalaryComponent.company_id == payload.company_id,
            SalaryComponent.code == code,
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise SalaryComponentCodeExistsError(
            "Salary component code already exists in this company"
        )
    row = SalaryComponent(
        company_id=payload.company_id,
        code=code,
        name_ar=payload.name_ar,
        name_en=payload.name_en,
        description=payload.description,
        category=payload.category,
        calculation_basis=payload.calculation_basis,
        default_amount=payload.default_amount,
        default_rate=payload.default_rate,
        is_statutory=payload.is_statutory,
        statutory_key=(payload.statutory_key or "").strip() or None,
        status=payload.status,
        sort_order=payload.sort_order,
        created_by=principal.user_id,
    )
    db.add(row)
    db.flush()
    record_audit(
        db,
        action="salary_component.create",
        entity="salary_component",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        new_value={"code": row.code, "category": row.category},
        ip_address=ip,
    )
    return row


def update_salary_component(
    db: Session,
    *,
    component_id: int,
    payload: SalaryComponentUpdate,
    principal: Principal,
    ip: str | None,
) -> SalaryComponent:
    row = get_salary_component(db, component_id, principal)
    _require(principal, "salary_component.update", row.company_id)
    data = payload.model_dump(exclude_unset=True)
    if "code" in data and data["code"] is not None:
        code = data["code"].strip()
        clash = db.execute(
            select(SalaryComponent.id).where(
                SalaryComponent.company_id == row.company_id,
                SalaryComponent.code == code,
                SalaryComponent.id != row.id,
            )
        ).scalar_one_or_none()
        if clash is not None:
            raise SalaryComponentCodeExistsError(
                "Salary component code already exists in this company"
            )
        data["code"] = code
    old_value = {"status": row.status, "default_amount": str(row.default_amount)}
    for key, value in data.items():
        setattr(row, key, value)
    db.flush()
    record_audit(
        db,
        action="salary_component.update",
        entity="salary_component",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        old_value=old_value,
        new_value={"status": row.status, "default_amount": str(row.default_amount)},
        ip_address=ip,
    )
    return row


def deactivate_salary_component(
    db: Session, *, component_id: int, principal: Principal, ip: str | None
) -> SalaryComponent:
    row = get_salary_component(db, component_id, principal)
    _require(principal, "salary_component.deactivate", row.company_id)
    # Deactivation never deletes history: payslip labels/amounts are
    # snapshots, so past payroll is untouched.
    row.status = "inactive"
    db.flush()
    record_audit(
        db,
        action="salary_component.deactivate",
        entity="salary_component",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        old_value={"status": "active"},
        new_value={"status": "inactive"},
        ip_address=ip,
    )
    return row


# ---------------------------------------------------------------------------
# Salary assignments (effective-dated, historical rows are immutable)
# ---------------------------------------------------------------------------


def list_salary_assignments(
    db: Session,
    principal: Principal,
    *,
    company_id: int | None = None,
    employee_id: int | None = None,
    as_of: date | None = None,
    page: PageParams | None = None,
) -> tuple[list[EmployeeSalaryAssignment], int]:
    stmt = select(EmployeeSalaryAssignment)
    count_stmt = select(func.count()).select_from(EmployeeSalaryAssignment)
    scope = _scope_company(db, principal, "salary_assignment.view", company_id)
    if scope is None:
        pass
    elif not scope:
        return [], 0
    else:
        stmt = stmt.where(EmployeeSalaryAssignment.company_id.in_(scope))
        count_stmt = count_stmt.where(
            EmployeeSalaryAssignment.company_id.in_(scope)
        )
    if employee_id is not None:
        stmt = stmt.where(EmployeeSalaryAssignment.employee_id == employee_id)
        count_stmt = count_stmt.where(
            EmployeeSalaryAssignment.employee_id == employee_id
        )
    if as_of is not None:
        stmt = stmt.where(
            EmployeeSalaryAssignment.effective_from <= as_of,
            (EmployeeSalaryAssignment.effective_to.is_(None))
            | (EmployeeSalaryAssignment.effective_to > as_of),
        )
        count_stmt = count_stmt.where(
            EmployeeSalaryAssignment.effective_from <= as_of,
            (EmployeeSalaryAssignment.effective_to.is_(None))
            | (EmployeeSalaryAssignment.effective_to > as_of),
        )
    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(
        EmployeeSalaryAssignment.employee_id,
        EmployeeSalaryAssignment.effective_from.desc(),
        EmployeeSalaryAssignment.id.desc(),
    )
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


def get_salary_assignment(
    db: Session, assignment_id: int, principal: Principal
) -> EmployeeSalaryAssignment:
    row = db.get(EmployeeSalaryAssignment, assignment_id)
    if row is None or not principal.can_access_company(row.company_id):
        raise SalaryAssignmentNotFoundError("Salary assignment not found")
    _require(principal, "salary_assignment.view", row.company_id)
    return row


def _check_assignment_overlap(
    db: Session,
    *,
    employee_id: int,
    effective_from: date,
    effective_to: date | None,
    exclude_id: int | None = None,
) -> None:
    stmt = select(EmployeeSalaryAssignment.id).where(
        EmployeeSalaryAssignment.employee_id == employee_id,
        EmployeeSalaryAssignment.effective_from
        < (effective_to + timedelta(days=1) if effective_to else date.max),
        (EmployeeSalaryAssignment.effective_to.is_(None))
        | (
            EmployeeSalaryAssignment.effective_to
            >= effective_from
        ),
    )
    if exclude_id is not None:
        stmt = stmt.where(EmployeeSalaryAssignment.id != exclude_id)
    if db.execute(stmt).scalar_one_or_none() is not None:
        raise SalaryAssignmentOverlapError(
            "Salary assignment windows may not overlap for the same employee"
        )


def create_salary_assignment(
    db: Session,
    *,
    payload: SalaryAssignmentCreate,
    principal: Principal,
    ip: str | None,
) -> EmployeeSalaryAssignment:
    if not principal.can_access_company(payload.company_id):
        raise ForbiddenError("You cannot create salary assignments in this company")
    _require(principal, "salary_assignment.create", payload.company_id)
    employee = db.get(Employee, payload.employee_id)
    if employee is None or employee.company_id != payload.company_id:
        raise SalaryAssignmentNotFoundError("Employee not found in this company")
    if payload.effective_to is not None and payload.effective_to < payload.effective_from:
        raise SalaryAssignmentDateRangeError(
            "effective_to must not be before effective_from"
        )
    # Creating a new window auto-closes the currently open row (history is
    # never overwritten - closing preserves the past values). The open row
    # is excluded from the overlap check because it gets closed to
    # effective_from - 1 day below, and the UPDATE is flushed BEFORE the
    # INSERT so the gist EXCLUDE constraint never sees the old open window.
    open_row = db.execute(
        select(EmployeeSalaryAssignment)
        .where(
            EmployeeSalaryAssignment.employee_id == payload.employee_id,
            EmployeeSalaryAssignment.effective_to.is_(None),
        )
        .with_for_update()
    ).scalar_one_or_none()
    if open_row is not None:
        close_on = payload.effective_from - timedelta(days=1)
        if close_on < open_row.effective_from:
            raise SalaryAssignmentOverlapError(
                "New assignment starts before the current open window"
            )
        open_row.effective_to = close_on
        db.flush()
    _check_assignment_overlap(
        db,
        employee_id=payload.employee_id,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        exclude_id=open_row.id if open_row is not None else None,
    )
    row = EmployeeSalaryAssignment(
        company_id=payload.company_id,
        employee_id=payload.employee_id,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        basic_salary=payload.basic_salary,
        currency=payload.currency,
        reason=payload.reason,
        created_by=principal.user_id,
    )
    db.add(row)
    db.flush()
    record_audit(
        db,
        action="salary_assignment.create",
        entity="salary_assignment",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        new_value={
            "employee_id": row.employee_id,
            "effective_from": row.effective_from.isoformat(),
            "basic_salary": str(row.basic_salary),
        },
        ip_address=ip,
    )
    return row


def update_salary_assignment(
    db: Session,
    *,
    assignment_id: int,
    payload: SalaryAssignmentUpdate,
    principal: Principal,
    ip: str | None,
) -> EmployeeSalaryAssignment:
    row = get_salary_assignment(db, assignment_id, principal)
    _require(principal, "salary_assignment.update", row.company_id)
    if row.effective_to is not None:
        # Historical assignments are never overwritten (approved rule).
        raise PayrollImmutableError(
            "Historical salary assignments are immutable; create a new "
            "effective-dated assignment instead"
        )
    data = payload.model_dump(exclude_unset=True)
    if "effective_to" in data:
        new_to = data["effective_to"]
        if new_to is not None and new_to <= row.effective_from:
            raise SalaryAssignmentDateRangeError(
                "effective_to must be after effective_from"
            )
        if new_to is not None:
            _check_assignment_overlap(
                db,
                employee_id=row.employee_id,
                effective_from=row.effective_from,
                effective_to=new_to,
                exclude_id=row.id,
            )
    old_value = {"basic_salary": str(row.basic_salary), "currency": row.currency}
    for key, value in data.items():
        setattr(row, key, value)
    db.flush()
    record_audit(
        db,
        action="salary_assignment.update",
        entity="salary_assignment",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        old_value=old_value,
        new_value={
            "basic_salary": str(row.basic_salary),
            "currency": row.currency,
        },
        ip_address=ip,
    )
    return row


def seed_salary_assignments(
    db: Session, *, company_id: int, principal: Principal, ip: str | None
) -> dict[str, int]:
    """Seed the INITIAL assignment from the active contract's basic salary.

    ``EmployeeContract.basic_salary`` is only ever read here - after Phase 6
    payroll calculations use salary assignments exclusively.
    """
    if not principal.can_access_company(company_id):
        raise ForbiddenError("You cannot seed salary assignments in this company")
    _require(principal, "salary_assignment.create", company_id)
    contracts = db.execute(
        select(EmployeeContract).where(
            EmployeeContract.company_id == company_id,
            EmployeeContract.status == "active",
            EmployeeContract.basic_salary.is_not(None),
        )
    ).scalars()
    created = 0
    skipped = 0
    for contract in contracts:
        has_assignment = db.execute(
            select(EmployeeSalaryAssignment.id).where(
                EmployeeSalaryAssignment.employee_id == contract.employee_id
            )
        ).scalar_one_or_none()
        if has_assignment is not None:
            skipped += 1
            continue
        employee = db.get(Employee, contract.employee_id)
        if employee is None:
            skipped += 1
            continue
        effective_from = (
            contract.start_date
            or employee.hire_date
            or date.today()
        )
        row = EmployeeSalaryAssignment(
            company_id=company_id,
            employee_id=contract.employee_id,
            effective_from=effective_from,
            effective_to=None,
            basic_salary=contract.basic_salary,
            currency=contract.currency,
            reason="Seeded from active contract",
            created_by=principal.user_id,
        )
        db.add(row)
        db.flush()
        created += 1
        record_audit(
            db,
            action="salary_assignment.seed",
            entity="salary_assignment",
            record_id=row.id,
            actor_user_id=principal.user_id,
            company_id=company_id,
            new_value={
                "employee_id": row.employee_id,
                "contract_id": contract.id,
                "basic_salary": str(row.basic_salary),
            },
            ip_address=ip,
        )
    return {"created": created, "skipped": skipped}


# ---------------------------------------------------------------------------
# Payroll periods - the single workflow state machine
# ---------------------------------------------------------------------------


def list_payroll_periods(
    db: Session,
    principal: Principal,
    *,
    company_id: int | None = None,
    status: str | None = None,
    page: PageParams | None = None,
) -> tuple[list[PayrollPeriod], int]:
    stmt = select(PayrollPeriod)
    count_stmt = select(func.count()).select_from(PayrollPeriod)
    scope = _scope_company(db, principal, "payroll_period.view", company_id)
    if scope is None:
        pass
    elif not scope:
        return [], 0
    else:
        stmt = stmt.where(PayrollPeriod.company_id.in_(scope))
        count_stmt = count_stmt.where(PayrollPeriod.company_id.in_(scope))
    if status is not None:
        stmt = stmt.where(PayrollPeriod.status == status)
        count_stmt = count_stmt.where(PayrollPeriod.status == status)
    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(
        PayrollPeriod.period_start.desc(), PayrollPeriod.id.desc()
    )
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


def _fetch_period(
    db: Session, period_id: int, principal: Principal, *, lock: bool = False
) -> PayrollPeriod:
    stmt = select(PayrollPeriod).where(PayrollPeriod.id == period_id)
    if lock:
        stmt = stmt.with_for_update()
    row = db.execute(stmt).scalar_one_or_none()
    if row is None or not principal.can_access_company(row.company_id):
        raise PayrollPeriodNotFoundError("Payroll period not found")
    return row


def get_payroll_period(
    db: Session, period_id: int, principal: Principal
) -> PayrollPeriod:
    row = _fetch_period(db, period_id, principal)
    _require(principal, "payroll_period.view", row.company_id)
    return row


def create_payroll_period(
    db: Session, *, payload: PayrollPeriodCreate, principal: Principal, ip: str | None
) -> PayrollPeriod:
    if not principal.can_access_company(payload.company_id):
        raise ForbiddenError("You cannot create payroll periods in this company")
    _require(principal, "payroll_period.create", payload.company_id)
    overlap = db.execute(
        select(PayrollPeriod.id).where(
            PayrollPeriod.company_id == payload.company_id,
            PayrollPeriod.period_start <= payload.period_end,
            PayrollPeriod.period_end >= payload.period_start,
        )
    ).scalar_one_or_none()
    if overlap is not None:
        raise PayrollPeriodExistsError(
            "A payroll period already covers part of this date range"
        )
    row = PayrollPeriod(
        company_id=payload.company_id,
        name=payload.name.strip(),
        period_start=payload.period_start,
        period_end=payload.period_end,
        currency=payload.currency,
        notes=payload.notes,
        created_by=principal.user_id,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise PayrollPeriodExistsError(
            "A payroll period already covers part of this date range"
        ) from exc
    record_audit(
        db,
        action="payroll_period.create",
        entity="payroll_period",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        new_value={
            "name": row.name,
            "period_start": row.period_start.isoformat(),
            "period_end": row.period_end.isoformat(),
        },
        ip_address=ip,
    )
    return row


def update_payroll_period(
    db: Session,
    *,
    period_id: int,
    payload: PayrollPeriodUpdate,
    principal: Principal,
    ip: str | None,
) -> PayrollPeriod:
    row = _fetch_period(db, period_id, principal, lock=True)
    _require(principal, "payroll_period.update", row.company_id)
    if row.status != "draft":
        raise PayrollImmutableError(
            "Only draft payroll periods can be edited (payroll is immutable "
            "once calculated)"
        )
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        data["name"] = data["name"].strip()
    old_value = {"name": row.name, "notes": row.notes}
    for key, value in data.items():
        setattr(row, key, value)
    db.flush()
    record_audit(
        db,
        action="payroll_period.update",
        entity="payroll_period",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        old_value=old_value,
        new_value={"name": row.name, "notes": row.notes},
        ip_address=ip,
    )
    return row


def _active_run(db: Session, period_id: int) -> PayrollRun | None:
    return db.execute(
        select(PayrollRun).where(
            PayrollRun.period_id == period_id, PayrollRun.status == "active"
        )
    ).scalar_one_or_none()


def _next_run_number(db: Session, company_id: int) -> int:
    current = db.execute(
        select(func.coalesce(func.max(PayrollRun.run_number), 0)).where(
            PayrollRun.company_id == company_id
        )
    ).scalar_one()
    return int(current) + 1


def _do_calculate(
    db: Session, period: PayrollPeriod, principal: Principal, ip: str | None
) -> tuple[PayrollPeriod, PayrollRun]:
    """Shared calculation path (initial calculate AND recalculate).

    Allowed only from DRAFT / CALCULATED / REVIEWED; recalculation always
    returns the period to CALCULATED (approved Phase 6 rule).
    """
    if period.status not in PERIOD_TRANSITIONS["calculate"]:
        raise PayrollPeriodStateError(
            "Payroll can only be calculated from draft, calculated or "
            f"reviewed (current: {period.status})"
        )
    result = calculate(db, period)
    run = _active_run(db, period.id)
    if run is None:
        run = PayrollRun(
            company_id=period.company_id,
            period_id=period.id,
            run_number=_next_run_number(db, period.company_id),
            status="active",
            created_by=principal.user_id,
        )
        db.add(run)
        db.flush()
    else:
        # Replace the artifact's lines - the workflow state stays on the
        # period (no second state machine).
        for line in db.execute(
            select(PayrollRunLine).where(PayrollRunLine.run_id == run.id)
        ).scalars():
            db.query(PayslipLine).filter(
                PayslipLine.run_line_id == line.id
            ).delete(synchronize_session=False)
        db.query(PayrollRunLine).filter(
            PayrollRunLine.run_id == run.id
        ).delete(synchronize_session=False)

    run.input_snapshot = result.snapshot
    run.inputs_hash = result.inputs_hash
    run.engine_version = result.engine_version
    run.employee_count = len(result.employees)
    run.gross_total = result.totals["gross_total"]
    run.deductions_total = result.totals["deductions_total"]
    run.employer_total = result.totals["employer_total"]
    run.net_total = result.totals["net_total"]
    run.warnings = result.warnings
    run.calculated_at = _now()
    run.calculated_by = principal.user_id
    run.void_reason = None
    run.voided_by = None
    run.voided_at = None

    for calc in result.employees:
        line = PayrollRunLine(
            company_id=period.company_id,
            run_id=run.id,
            employee_id=calc.employee_id,
            basic_snapshot=calc.basic_snapshot,
            currency=calc.currency,
            earnings_total=calc.earnings_total,
            deductions_total=calc.deductions_total,
            employer_total=calc.employer_total,
            net_pay=calc.net_pay,
            worked_minutes=calc.worked_minutes,
            overtime_minutes=calc.overtime_minutes,
            paid_leave_days=calc.paid_leave_days,
            unpaid_leave_days=calc.unpaid_leave_days,
            absent_days=calc.absent_days,
            late_minutes=calc.late_minutes,
            warnings=calc.warnings,
        )
        db.add(line)
        db.flush()
        for sort_order, computed in enumerate(calc.lines):
            db.add(
                PayslipLine(
                    company_id=period.company_id,
                    run_line_id=line.id,
                    component_id=computed.component_id,
                    line_type=computed.line_type,
                    label_ar=computed.label_ar,
                    label_en=computed.label_en,
                    unit=computed.unit,
                    quantity=computed.quantity,
                    rate=computed.rate,
                    amount=computed.amount,
                    sort_order=sort_order,
                )
            )
        db.flush()

    period.status = "calculated"
    period.calculated_at = _now()
    period.calculated_by = principal.user_id
    # A recalculation invalidates an earlier review.
    period.reviewed_at = None
    period.reviewed_by = None
    db.flush()
    record_audit(
        db,
        action="payroll_period.calculate",
        entity="payroll_period",
        record_id=period.id,
        actor_user_id=principal.user_id,
        company_id=period.company_id,
        new_value={
            "run_id": run.id,
            "inputs_hash": run.inputs_hash,
            "employee_count": run.employee_count,
            "net_total": str(run.net_total),
        },
        ip_address=ip,
    )
    return period, run


def calculate_payroll_period(
    db: Session, *, period_id: int, principal: Principal, ip: str | None
) -> tuple[PayrollPeriod, PayrollRun]:
    period = _fetch_period(db, period_id, principal, lock=True)
    _require(principal, "payroll_run.calculate", period.company_id)
    return _do_calculate(db, period, principal, ip)


def recalculate_payroll_run(
    db: Session, *, run_id: int, principal: Principal, ip: str | None
) -> tuple[PayrollPeriod, PayrollRun]:
    run = db.get(PayrollRun, run_id)
    if run is None or not principal.can_access_company(run.company_id):
        raise PayrollRunNotFoundError("Payroll run not found")
    _require(principal, "payroll_run.calculate", run.company_id)
    period = _fetch_period(db, run.period_id, principal, lock=True)
    return _do_calculate(db, period, principal, ip)


def review_payroll_period(
    db: Session, *, period_id: int, principal: Principal, ip: str | None
) -> PayrollPeriod:
    period = _fetch_period(db, period_id, principal, lock=True)
    _require(principal, "payroll_run.review", period.company_id)
    if period.status != "calculated":
        raise PayrollPeriodStateError(
            "Only calculated payroll periods can be reviewed "
            f"(current: {period.status})"
        )
    if _active_run(db, period.id) is None:
        raise PayrollNotCalculatedError("The payroll period has not been calculated")
    period.status = "reviewed"
    period.reviewed_at = _now()
    period.reviewed_by = principal.user_id
    db.flush()
    record_audit(
        db,
        action="payroll_period.review",
        entity="payroll_period",
        record_id=period.id,
        actor_user_id=principal.user_id,
        company_id=period.company_id,
        new_value={"status": "reviewed"},
        ip_address=ip,
    )
    return period


def approve_payroll_period(
    db: Session, *, period_id: int, principal: Principal, ip: str | None
) -> PayrollPeriod:
    period = _fetch_period(db, period_id, principal, lock=True)
    _require(principal, "payroll_run.approve", period.company_id)
    if period.status != "reviewed":
        raise PayrollPeriodStateError(
            "Only reviewed payroll periods can be approved "
            f"(current: {period.status})"
        )
    run = _active_run(db, period.id)
    if run is None or run.inputs_hash is None:
        raise PayrollNotCalculatedError("The payroll period has not been calculated")

    # Input integrity: rebuild the CURRENT inputs and compare with the hash
    # stored at calculate time (Phase 4/5 data or config changes detected).
    current_hash = snapshot_hash(build_inputs(db, period))
    if current_hash != run.inputs_hash:
        raise PayrollInputsChangedError(
            "Payroll inputs changed since calculation "
            "(attendance, overtime, leave, salaries, deductions, "
            "adjustments or statutory rules); recalculate before approval"
        )

    blockers = blocking_warnings(run.warnings or [])
    if blockers:
        keys = sorted({w.get("statutory_key", "?") for w in blockers})
        raise PayrollStatutoryRuleError(
            "Unverified or missing statutory rule(s) block approval: "
            + ", ".join(keys)
            + ". Configure and verify them, then recalculate."
        )

    _consume_deduction_rules(db, period, run)

    period.status = "approved"
    period.approved_at = _now()
    period.approved_by = principal.user_id
    db.flush()
    record_audit(
        db,
        action="payroll_period.approve",
        entity="payroll_period",
        record_id=period.id,
        actor_user_id=principal.user_id,
        company_id=period.company_id,
        new_value={
            "status": "approved",
            "run_id": run.id,
            "inputs_hash": run.inputs_hash,
            "net_total": str(run.net_total),
        },
        ip_address=ip,
    )
    return period


def _consume_deduction_rules(
    db: Session, period: PayrollPeriod, run: PayrollRun
) -> None:
    """Draw down installment deductions at APPROVE time only.

    Rows are locked and consumed in deterministic (effective_from, id)
    order so concurrent/consecutive approvals can never double-spend, and
    recalculation (which happens before approval) never mutates remaining
    amounts.
    """
    snapshot = run.input_snapshot or {}
    entries: list[tuple[str, int, Decimal, Decimal]] = []
    for employee_payload in (snapshot.get("employees") or {}).values():
        for rule in employee_payload.get("deduction_rules", []):
            if rule.get("remaining") is None:
                continue  # non-installment: never consumed
            entries.append(
                (
                    str(rule.get("effective_from")),
                    int(rule["id"]),
                    Decimal(str(rule["amount"])),
                    Decimal(str(rule["remaining"])),
                )
            )
    for _eff, rule_id, amount, _remaining in sorted(entries):
        row = db.execute(
            select(PayrollDeductionRule)
            .where(PayrollDeductionRule.id == rule_id)
            .with_for_update()
        ).scalar_one_or_none()
        if row is None or row.status != "active":
            continue
        remaining = row.remaining_amount or Decimal("0")
        charge = min(amount, remaining)
        remaining -= charge
        row.remaining_amount = max(remaining, Decimal("0"))
        if row.remaining_amount <= 0:
            row.status = "completed"
            row.remaining_amount = Decimal("0.00")
    db.flush()


def mark_payroll_period_paid(
    db: Session, *, period_id: int, principal: Principal, ip: str | None
) -> PayrollPeriod:
    period = _fetch_period(db, period_id, principal, lock=True)
    _require(principal, "payroll_run.mark_paid", period.company_id)
    if period.status != "approved":
        raise PayrollPeriodStateError(
            "Only approved payroll periods can be marked paid "
            f"(current: {period.status})"
        )
    period.status = "paid"
    period.paid_at = _now()
    period.paid_by = principal.user_id
    db.flush()
    record_audit(
        db,
        action="payroll_period.mark_paid",
        entity="payroll_period",
        record_id=period.id,
        actor_user_id=principal.user_id,
        company_id=period.company_id,
        new_value={"status": "paid"},
        ip_address=ip,
    )
    return period


def lock_payroll_period(
    db: Session, *, period_id: int, principal: Principal, ip: str | None
) -> PayrollPeriod:
    period = _fetch_period(db, period_id, principal, lock=True)
    _require(principal, "payroll_run.lock", period.company_id)
    if period.status != "paid":
        raise PayrollPeriodStateError(
            "Only paid payroll periods can be locked (current: "
            f"{period.status})"
        )
    period.status = "locked"
    period.locked_at = _now()
    period.locked_by = principal.user_id
    db.flush()
    record_audit(
        db,
        action="payroll_period.lock",
        entity="payroll_period",
        record_id=period.id,
        actor_user_id=principal.user_id,
        company_id=period.company_id,
        new_value={"status": "locked"},
        ip_address=ip,
    )
    return period


# ---------------------------------------------------------------------------
# Runs, payslips, accounting export
# ---------------------------------------------------------------------------


def list_payroll_runs(
    db: Session,
    principal: Principal,
    *,
    company_id: int | None = None,
    period_id: int | None = None,
    page: PageParams | None = None,
) -> tuple[list[PayrollRun], int]:
    stmt = select(PayrollRun)
    count_stmt = select(func.count()).select_from(PayrollRun)
    scope = _scope_company(db, principal, "payroll_run.view", company_id)
    if scope is None:
        pass
    elif not scope:
        return [], 0
    else:
        stmt = stmt.where(PayrollRun.company_id.in_(scope))
        count_stmt = count_stmt.where(PayrollRun.company_id.in_(scope))
    if period_id is not None:
        stmt = stmt.where(PayrollRun.period_id == period_id)
        count_stmt = count_stmt.where(PayrollRun.period_id == period_id)
    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(PayrollRun.id.desc())
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


def get_payroll_run(db: Session, run_id: int, principal: Principal) -> PayrollRun:
    row = db.get(PayrollRun, run_id)
    if row is None or not principal.can_access_company(row.company_id):
        raise PayrollRunNotFoundError("Payroll run not found")
    _require(principal, "payroll_run.view", row.company_id)
    return row


def list_run_lines(
    db: Session,
    principal: Principal,
    *,
    run_id: int,
    employee_id: int | None = None,
    page: PageParams | None = None,
) -> tuple[list[PayrollRunLine], int]:
    run = get_payroll_run(db, run_id, principal)
    stmt = select(PayrollRunLine).where(PayrollRunLine.run_id == run.id)
    count_stmt = (
        select(func.count())
        .select_from(PayrollRunLine)
        .where(PayrollRunLine.run_id == run.id)
    )
    if employee_id is not None:
        stmt = stmt.where(PayrollRunLine.employee_id == employee_id)
        count_stmt = count_stmt.where(PayrollRunLine.employee_id == employee_id)
    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(PayrollRunLine.id)
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


def get_payslip(db: Session, run_line_id: int, principal: Principal) -> PayrollRunLine:
    row = db.get(PayrollRunLine, run_line_id)
    if row is None or not principal.can_access_company(row.company_id):
        raise NotFoundError("Payslip not found")
    _require(principal, "payroll_run.view", row.company_id)
    return row


def build_accounting_export(
    db: Session, *, run_id: int, principal: Principal
) -> dict[str, Any]:
    """Deterministic accounting EXPORT CONTRACT (Phase 6: JSON only - no
    journal entries, no postings)."""
    run = get_payroll_run(db, run_id, principal)
    _require(principal, "payroll_export.execute", run.company_id)
    period = db.get(PayrollPeriod, run.period_id)
    if period is None:  # pragma: no cover - FK guarantees
        raise PayrollPeriodNotFoundError("Payroll period not found")
    lines: list[dict[str, Any]] = []
    run_lines = db.execute(
        select(PayrollRunLine)
        .where(PayrollRunLine.run_id == run.id)
        .order_by(PayrollRunLine.id)
    ).scalars()
    for run_line in run_lines:
        employee = db.get(Employee, run_line.employee_id)
        payslip_lines = db.execute(
            select(PayslipLine)
            .where(PayslipLine.run_line_id == run_line.id)
            .order_by(PayslipLine.sort_order, PayslipLine.id)
        ).scalars()
        for payslip_line in payslip_lines:
            component = (
                db.get(SalaryComponent, payslip_line.component_id)
                if payslip_line.component_id is not None
                else None
            )
            lines.append(
                {
                    "employee_id": run_line.employee_id,
                    "employee_number": employee.employee_number
                    if employee
                    else None,
                    "component_code": component.code if component else None,
                    "line_type": payslip_line.line_type,
                    "label_en": payslip_line.label_en,
                    "amount": str(payslip_line.amount),
                }
            )
    return {
        "schema_name": "payroll.accounting_export.v1",
        "engine_version": run.engine_version,
        "inputs_hash": run.inputs_hash,
        "company_id": run.company_id,
        "period_id": period.id,
        "period_start": period.period_start.isoformat(),
        "period_end": period.period_end.isoformat(),
        "currency": period.currency,
        "status": period.status,
        "gross_total": str(run.gross_total),
        "deductions_total": str(run.deductions_total),
        "employer_total": str(run.employer_total),
        "net_total": str(run.net_total),
        "employee_count": run.employee_count,
        "lines": lines,
    }


# ---------------------------------------------------------------------------
# Adjustments
# ---------------------------------------------------------------------------


def list_payroll_adjustments(
    db: Session,
    principal: Principal,
    *,
    company_id: int | None = None,
    status: str | None = None,
    period_id: int | None = None,
    employee_id: int | None = None,
    page: PageParams | None = None,
) -> tuple[list[PayrollAdjustment], int]:
    stmt = select(PayrollAdjustment)
    count_stmt = select(func.count()).select_from(PayrollAdjustment)
    scope = _scope_company(db, principal, "payroll_adjustment.view", company_id)
    if scope is None:
        pass
    elif not scope:
        return [], 0
    else:
        stmt = stmt.where(PayrollAdjustment.company_id.in_(scope))
        count_stmt = count_stmt.where(PayrollAdjustment.company_id.in_(scope))
    for column, value in (
        (PayrollAdjustment.status, status),
        (PayrollAdjustment.period_id, period_id),
        (PayrollAdjustment.employee_id, employee_id),
    ):
        if value is not None:
            stmt = stmt.where(column == value)
            count_stmt = count_stmt.where(column == value)
    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(PayrollAdjustment.id.desc())
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


def _fetch_adjustment(
    db: Session, adjustment_id: int, principal: Principal, *, lock: bool = False
) -> PayrollAdjustment:
    stmt = select(PayrollAdjustment).where(PayrollAdjustment.id == adjustment_id)
    if lock:
        stmt = stmt.with_for_update()
    row = db.execute(stmt).scalar_one_or_none()
    if row is None or not principal.can_access_company(row.company_id):
        raise PayrollAdjustmentNotFoundError("Payroll adjustment not found")
    return row


def get_payroll_adjustment(
    db: Session, adjustment_id: int, principal: Principal
) -> PayrollAdjustment:
    row = _fetch_adjustment(db, adjustment_id, principal)
    _require(principal, "payroll_adjustment.view", row.company_id)
    return row


def create_payroll_adjustment(
    db: Session,
    *,
    payload: PayrollAdjustmentCreate,
    principal: Principal,
    ip: str | None,
) -> PayrollAdjustment:
    if not principal.can_access_company(payload.company_id):
        raise ForbiddenError("You cannot create adjustments in this company")
    _require(principal, "payroll_adjustment.create", payload.company_id)
    period = db.get(PayrollPeriod, payload.period_id)
    if period is None or period.company_id != payload.company_id:
        raise PayrollPeriodNotFoundError("Payroll period not found")
    if period.status not in OPEN_PERIOD_STATUSES:
        raise PayrollAdjustmentTargetError(
            "Adjustments may only target an open payroll period "
            "(draft, calculated or reviewed); corrections to approved "
            "payroll must be posted to the NEXT open period"
        )
    employee = db.get(Employee, payload.employee_id)
    if employee is None or employee.company_id != payload.company_id:
        raise PayrollAdjustmentTargetError("Employee not found in this company")
    if payload.original_run_id is not None:
        original = db.get(PayrollRun, payload.original_run_id)
        if original is None or original.company_id != payload.company_id:
            raise PayrollAdjustmentTargetError("Original payroll run not found")
        original_period = db.get(PayrollPeriod, original.period_id)
        if original_period is None or original_period.status not in (
            "approved",
            "paid",
            "locked",
        ):
            raise PayrollAdjustmentTargetError(
                "original_run_id must reference an approved, paid or locked "
                "payroll run"
            )
        if original_period.period_start >= period.period_start:
            raise PayrollAdjustmentTargetError(
                "Corrections must reference an earlier payroll period"
            )
    row = PayrollAdjustment(
        company_id=payload.company_id,
        employee_id=payload.employee_id,
        period_id=payload.period_id,
        original_run_id=payload.original_run_id,
        component_id=payload.component_id,
        amount=payload.amount,
        direction=payload.direction,
        reason=payload.reason.strip(),
        status="pending",
        requested_by=principal.user_id,
        created_by=principal.user_id,
    )
    db.add(row)
    db.flush()
    record_audit(
        db,
        action="payroll_adjustment.create",
        entity="payroll_adjustment",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        new_value={
            "employee_id": row.employee_id,
            "period_id": row.period_id,
            "amount": str(row.amount),
            "direction": row.direction,
        },
        ip_address=ip,
    )
    return row


def decide_payroll_adjustment(
    db: Session,
    *,
    adjustment_id: int,
    decision: str,
    payload: PayrollAdjustmentDecision,
    principal: Principal,
    ip: str | None,
) -> PayrollAdjustment:
    row = _fetch_adjustment(db, adjustment_id, principal, lock=True)
    if decision == "approve":
        _require(principal, "payroll_adjustment.approve", row.company_id)
        allowed = ("pending",)
        target_status = "approved"
        action = "payroll_adjustment.approve"
    elif decision == "reject":
        _require(principal, "payroll_adjustment.reject", row.company_id)
        allowed = ("pending",)
        target_status = "rejected"
        action = "payroll_adjustment.reject"
    else:  # void
        _require(principal, "payroll_adjustment.void", row.company_id)
        allowed = ("draft", "pending", "approved")
        target_status = "void"
        action = "payroll_adjustment.void"
    if row.status not in allowed:
        raise PayrollAdjustmentStateError(
            f"Adjustment cannot move from {row.status} to {target_status}"
        )
    old_status = row.status
    row.status = target_status
    if target_status in ("approved", "rejected"):
        row.decided_by = principal.user_id
        row.decided_at = _now()
        row.decision_reason = payload.decision_reason
    elif target_status == "void":
        row.voided_by = principal.user_id
        row.voided_at = _now()
    db.flush()
    record_audit(
        db,
        action=action,
        entity="payroll_adjustment",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        old_value={"status": old_status},
        new_value={"status": target_status},
        ip_address=ip,
    )
    return row


# ---------------------------------------------------------------------------
# Deduction rules
# ---------------------------------------------------------------------------


def list_payroll_deductions(
    db: Session,
    principal: Principal,
    *,
    company_id: int | None = None,
    status: str | None = None,
    employee_id: int | None = None,
    page: PageParams | None = None,
) -> tuple[list[PayrollDeductionRule], int]:
    stmt = select(PayrollDeductionRule)
    count_stmt = select(func.count()).select_from(PayrollDeductionRule)
    scope = _scope_company(db, principal, "payroll_deduction.view", company_id)
    if scope is None:
        pass
    elif not scope:
        return [], 0
    else:
        stmt = stmt.where(PayrollDeductionRule.company_id.in_(scope))
        count_stmt = count_stmt.where(PayrollDeductionRule.company_id.in_(scope))
    if status is not None:
        stmt = stmt.where(PayrollDeductionRule.status == status)
        count_stmt = count_stmt.where(PayrollDeductionRule.status == status)
    if employee_id is not None:
        stmt = stmt.where(PayrollDeductionRule.employee_id == employee_id)
        count_stmt = count_stmt.where(
            PayrollDeductionRule.employee_id == employee_id
        )
    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(
        PayrollDeductionRule.effective_from, PayrollDeductionRule.id
    )
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


def get_payroll_deduction(
    db: Session, deduction_id: int, principal: Principal
) -> PayrollDeductionRule:
    row = db.get(PayrollDeductionRule, deduction_id)
    if row is None or not principal.can_access_company(row.company_id):
        raise PayrollDeductionNotFoundError("Payroll deduction not found")
    _require(principal, "payroll_deduction.view", row.company_id)
    return row


def create_payroll_deduction(
    db: Session,
    *,
    payload: PayrollDeductionCreate,
    principal: Principal,
    ip: str | None,
) -> PayrollDeductionRule:
    if not principal.can_access_company(payload.company_id):
        raise ForbiddenError("You cannot create deductions in this company")
    _require(principal, "payroll_deduction.create", payload.company_id)
    employee = db.get(Employee, payload.employee_id)
    if employee is None or employee.company_id != payload.company_id:
        raise PayrollDeductionNotFoundError("Employee not found in this company")
    installment = payload.total_amount is not None
    row = PayrollDeductionRule(
        company_id=payload.company_id,
        employee_id=payload.employee_id,
        component_id=payload.component_id,
        name=payload.name.strip(),
        amount=payload.amount,
        total_amount=payload.total_amount,
        remaining_amount=payload.total_amount if installment else None,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        status="active",
        reason=payload.reason,
        created_by=principal.user_id,
    )
    db.add(row)
    db.flush()
    record_audit(
        db,
        action="payroll_deduction.create",
        entity="payroll_deduction",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        new_value={
            "employee_id": row.employee_id,
            "amount": str(row.amount),
            "total_amount": str(row.total_amount) if installment else None,
        },
        ip_address=ip,
    )
    return row


def update_payroll_deduction(
    db: Session,
    *,
    deduction_id: int,
    payload: PayrollDeductionUpdate,
    principal: Principal,
    ip: str | None,
) -> PayrollDeductionRule:
    row = get_payroll_deduction(db, deduction_id, principal)
    _require(principal, "payroll_deduction.update", row.company_id)
    if row.status != "active":
        raise PayrollDeductionStateError(
            "Only active deduction rules can be edited "
            f"(current: {row.status})"
        )
    data = payload.model_dump(exclude_unset=True)
    if "amount" in data and data["amount"] is not None:
        row.amount = data["amount"]
        if row.total_amount is not None and row.remaining_amount is not None:
            # Keep remaining consistent: an installment change re-derives
            # remaining from the total minus what was already consumed.
            consumed = row.total_amount - row.remaining_amount
            row.total_amount = row.amount * (
                (row.total_amount / row.amount).to_integral_value(rounding="ROUND_FLOOR")
                if row.amount
                else Decimal("1")
            )
            row.remaining_amount = max(row.total_amount - consumed, Decimal("0"))
    if "effective_to" in data:
        row.effective_to = data["effective_to"]
    if "reason" in data and data["reason"] is not None:
        row.reason = data["reason"]
    if "status" in data and data["status"] is not None:
        row.status = data["status"]
    db.flush()
    record_audit(
        db,
        action="payroll_deduction.update",
        entity="payroll_deduction",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        old_value={"amount": str(row.amount)},
        new_value={"amount": str(row.amount), "status": row.status},
        ip_address=ip,
    )
    return row


# ---------------------------------------------------------------------------
# Payroll statutory rules (framework - mandatory source + effective dates)
# ---------------------------------------------------------------------------


def _validate_rule_json(statutory_key: str, payload: dict[str, Any]) -> None:
    """Closed validation for the structured keys. NO legal values are
    invented or defaulted here - companies must cite their source."""

    def as_decimal(name: str) -> Decimal | None:
        raw = payload.get(name)
        if isinstance(raw, bool) or raw is None:
            return None
        try:
            value = Decimal(str(raw))
        except Exception:
            return None
        return value if value.is_finite() else None

    if "rate" in payload:
        rate = as_decimal("rate")
        if rate is None or rate <= 0 or rate > 1:
            raise PayrollStatutoryRuleValueError(
                "rule_json.rate must be a fraction greater than 0 and at "
                "most 1 (e.g. \"0.0975\")"
            )
    if statutory_key == KEY_OVERTIME:
        rate = as_decimal("overtime_rate_percent")
        days = as_decimal("days_per_month")
        hours = as_decimal("hours_per_day")
        if rate is None or rate < 0:
            raise PayrollStatutoryRuleValueError(
                "overtime rule requires overtime_rate_percent >= 0"
            )
        if days is None or days <= 0:
            raise PayrollStatutoryRuleValueError(
                "overtime rule requires days_per_month > 0"
            )
        if hours is None or hours <= 0:
            raise PayrollStatutoryRuleValueError(
                "overtime rule requires hours_per_day > 0"
            )
    elif statutory_key == KEY_DAILY_DIVISOR:
        divisor = as_decimal("divisor")
        if divisor is None or divisor <= 0:
            raise PayrollStatutoryRuleValueError(
                "daily_divisor rule requires divisor > 0"
            )
    elif statutory_key == KEY_PRORATION_BASIS:
        basis = payload.get("basis")
        if not isinstance(basis, str) or basis not in PRORATION_BASES:
            raise PayrollStatutoryRuleValueError(
                f"proration_basis rule requires basis in {PRORATION_BASES}"
            )


def list_payroll_statutory_rules(
    db: Session,
    principal: Principal,
    *,
    company_id: int | None = None,
    statutory_key: str | None = None,
    status: str | None = None,
    as_of: date | None = None,
    page: PageParams | None = None,
) -> tuple[list[PayrollStatutoryRule], int]:
    stmt = select(PayrollStatutoryRule)
    count_stmt = select(func.count()).select_from(PayrollStatutoryRule)
    scope = _scope_company(
        db, principal, "payroll_statutory_rule.view", company_id
    )
    if scope is None:
        pass
    elif not scope:
        return [], 0
    else:
        stmt = stmt.where(PayrollStatutoryRule.company_id.in_(scope))
        count_stmt = count_stmt.where(PayrollStatutoryRule.company_id.in_(scope))
    if statutory_key is not None:
        stmt = stmt.where(PayrollStatutoryRule.statutory_key == statutory_key)
        count_stmt = count_stmt.where(
            PayrollStatutoryRule.statutory_key == statutory_key
        )
    if status is not None:
        stmt = stmt.where(PayrollStatutoryRule.status == status)
        count_stmt = count_stmt.where(PayrollStatutoryRule.status == status)
    if as_of is not None:
        clause = (
            PayrollStatutoryRule.effective_from <= as_of,
            (PayrollStatutoryRule.effective_to.is_(None))
            | (PayrollStatutoryRule.effective_to > as_of),
        )
        stmt = stmt.where(*clause)
        count_stmt = count_stmt.where(*clause)
    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(
        PayrollStatutoryRule.statutory_key,
        PayrollStatutoryRule.effective_from.desc(),
        PayrollStatutoryRule.version.desc(),
    )
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


def get_payroll_statutory_rule(
    db: Session, rule_id: int, principal: Principal
) -> PayrollStatutoryRule:
    row = db.get(PayrollStatutoryRule, rule_id)
    if row is None or not principal.can_access_company(row.company_id):
        raise PayrollStatutoryRuleNotFoundError("Payroll statutory rule not found")
    _require(principal, "payroll_statutory_rule.view", row.company_id)
    return row


def create_payroll_statutory_rule(
    db: Session,
    *,
    payload: PayrollStatutoryRuleCreate,
    principal: Principal,
    ip: str | None,
) -> PayrollStatutoryRule:
    if not principal.can_access_company(payload.company_id):
        raise ForbiddenError("You cannot create statutory rules in this company")
    _require(principal, "payroll_statutory_rule.create", payload.company_id)
    if not payload.source_reference.strip():
        raise PayrollStatutoryRuleSourceRequiredError(
            "A source_reference (citation) is required for statutory rules"
        )
    if payload.effective_to is not None and payload.effective_to <= payload.effective_from:
        raise PayrollStatutoryRuleDateRangeError(
            "effective_to must be after effective_from"
        )
    key = payload.statutory_key.strip()
    _validate_rule_json(key, payload.rule_json)
    # Windows are [effective_from, effective_to) and may not overlap for
    # the same key - checked against ALL versions (mirrors the DB EXCLUDE).
    overlap = db.execute(
        select(PayrollStatutoryRule.id).where(
            PayrollStatutoryRule.company_id == payload.company_id,
            PayrollStatutoryRule.statutory_key == key,
            PayrollStatutoryRule.effective_from
            < (payload.effective_to or date.max),
            (PayrollStatutoryRule.effective_to.is_(None))
            | (PayrollStatutoryRule.effective_to > payload.effective_from),
        )
    ).scalar_one_or_none()
    if overlap is not None:
        raise PayrollStatutoryRuleOverlapError(
            "Rule versions may not overlap for the same statutory key"
        )
    next_version = (
        db.execute(
            select(func.coalesce(func.max(PayrollStatutoryRule.version), 0)).where(
                PayrollStatutoryRule.company_id == payload.company_id,
                PayrollStatutoryRule.statutory_key == key,
            )
        ).scalar_one()
        + 1
    )
    row = PayrollStatutoryRule(
        company_id=payload.company_id,
        statutory_key=key,
        version=int(next_version),
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
        db.rollback()
        raise PayrollStatutoryRuleOverlapError(
            "Rule versions may not overlap for the same statutory key"
        ) from exc
    record_audit(
        db,
        action="payroll_statutory_rule.create",
        entity="payroll_statutory_rule",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        new_value={
            "statutory_key": row.statutory_key,
            "version": row.version,
            "requires_legal_verification": row.requires_legal_verification,
        },
        ip_address=ip,
    )
    return row


def deactivate_payroll_statutory_rule(
    db: Session,
    *,
    rule_id: int,
    payload: PayrollStatutoryRuleDeactivate,
    principal: Principal,
    ip: str | None,
) -> PayrollStatutoryRule:
    row = get_payroll_statutory_rule(db, rule_id, principal)
    _require(principal, "payroll_statutory_rule.deactivate", row.company_id)
    old_status = row.status
    row.status = payload.status
    db.flush()
    record_audit(
        db,
        action="payroll_statutory_rule.deactivate",
        entity="payroll_statutory_rule",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        old_value={"status": old_status},
        new_value={"status": row.status},
        ip_address=ip,
    )
    return row
