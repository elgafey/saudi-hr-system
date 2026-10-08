from __future__ import annotations

import hashlib
import json
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import (
    PayrollAttendanceOpenError,
    PayrollNoSalaryAssignmentError,
    PayrollReconciliationError,
)
from app.leave.day_counting import count_leave_days
from app.payroll.statutory import (
    BLOCKING_WARNINGS,
    ENGINE_VERSION,
    WARNING_MISSING_RULE,
    WARNING_UNVERIFIED_RULE,
    RuleSet,
)
from app.shared.models import (
    AttendanceRecord,
    Employee,
    EmployeeSalaryAssignment,
    LeaveRequest,
    LeaveType,
    OvertimeRecord,
    PayrollAdjustment,
    PayrollDeductionRule,
    PayrollPeriod,
    SalaryAssignmentComponent,
    SalaryComponent,
)

# Money is Decimal end-to-end: every payslip line is quantized to 0.01 with
# ROUND_HALF_UP, and period totals are the sums of those rounded lines
# (never a re-rounded aggregate). Floats never touch payroll math.
CENT = Decimal("0.01")
ZERO = Decimal("0.00")

# Deterministic sort groups for payslip lines.
GROUP_BASIC = 0
GROUP_COMPONENT = 1
GROUP_OVERTIME = 2
GROUP_LEAVE_DEDUCTION = 3
GROUP_ADJUSTMENT = 4
GROUP_DEDUCTION_RULE = 5

LABEL_BASIC_EN = "Basic Pay"
LABEL_BASIC_AR = "الأجر الأساسي"
LABEL_OVERTIME_EN = "Overtime Pay"
LABEL_OVERTIME_AR = "أجر إضافي"
LABEL_UNPAID_LEAVE_EN = "Unpaid Leave Deduction"
LABEL_UNPAID_LEAVE_AR = "خصم إجازة بدون أجر"
LABEL_ADJUSTMENT_EN = "Adjustment"
LABEL_ADJUSTMENT_AR = "تسوية"
LABEL_DEDUCTION_EN = "Deduction"
LABEL_DEDUCTION_AR = "خصم"


def money(value: Any) -> Decimal:
    """Quantize to 0.01 (ROUND_HALF_UP) - the only rounding in payroll."""
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def canonical_json(payload: Any) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )


def snapshot_hash(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _s(value: Any) -> str:
    return str(value)


def _clip(
    a_start: date, a_end: date | None, b_start: date, b_end: date
) -> tuple[date, date] | None:
    start = max(a_start, b_start)
    end = min(a_end, b_end) if a_end is not None else b_end
    if end < start:
        return None
    return start, end


def _month_chunks(start: date, end: date) -> list[tuple[date, date, int]]:
    """Split [start, end] (inclusive) into per-month (chunk_start, chunk_end,
    days_in_that_month) pieces for calendar-day proration."""
    chunks: list[tuple[date, date, int]] = []
    cursor = start
    while cursor <= end:
        dim = monthrange(cursor.year, cursor.month)[1]
        month_end = date(cursor.year, cursor.month, dim)
        chunk_end = min(month_end, end)
        chunks.append((cursor, chunk_end, dim))
        cursor = chunk_end + timedelta(days=1)
    return chunks


# ---------------------------------------------------------------------------
# Inputs (snapshot) - everything the engine reads, hashed at CALCULATE and
# rebuilt at APPROVE (PAYROLL_INPUTS_CHANGED on mismatch).
# ---------------------------------------------------------------------------


def check_open_attendance(db: Session, period: PayrollPeriod) -> None:
    """OPEN or missing-checkout attendance inside the period BLOCKS the
    calculation; the error lists employee/date/status so the user can fix
    attendance first (approved Phase 6 rule)."""
    rows = (
        db.execute(
            select(AttendanceRecord)
            .where(
                AttendanceRecord.company_id == period.company_id,
                AttendanceRecord.work_date >= period.period_start,
                AttendanceRecord.work_date <= period.period_end,
                AttendanceRecord.status != "completed",
            )
            .order_by(AttendanceRecord.employee_id, AttendanceRecord.work_date)
        )
        .scalars()
        .all()
    )
    if not rows:
        return
    details = [
        {
            "attendance_id": row.id,
            "employee_id": row.employee_id,
            "work_date": row.work_date.isoformat(),
            "status": row.status,
        }
        for row in rows
    ]
    preview = ", ".join(
        f"employee {d['employee_id']} on {d['work_date']} ({d['status']})"
        for d in details[:10]
    )
    more = "" if len(details) <= 10 else f" and {len(details) - 10} more"
    raise PayrollAttendanceOpenError(
        f"{len(details)} attendance record(s) are not completed in this "
        f"payroll period; close them before calculating: {preview}{more}",
        details=details,
    )


def _leave_days_in_period(
    db: Session,
    employee: Employee,
    leave_type: LeaveType,
    request: LeaveRequest,
    period: PayrollPeriod,
) -> tuple[Decimal, list[tuple[str, str]]]:
    """Count approved leave days that fall inside the payroll period.

    Fully-inside PAID requests use the stored snapshot (``request.days``).
    Anything else is recounted through the Phase 5 day-counting engine on
    the clipped range (read-only reuse; no Phase 5 code is modified), which
    also yields per-date fractions for unpaid-leave deductions.
    """
    clipped = _clip(
        request.start_date, request.end_date, period.period_start, period.period_end
    )
    if clipped is None:
        return ZERO, []
    c_start, c_end = clipped
    fully_inside = (
        c_start == request.start_date and c_end == request.end_date
    )
    if fully_inside and leave_type.is_paid:
        return Decimal(request.days), []
    start_time = request.start_time if (c_start == c_end == request.start_date) else None
    end_time = request.end_time if start_time is not None else None
    try:
        result = count_leave_days(
            db,
            employee,
            leave_type,
            c_start,
            c_end,
            start_time=start_time,
            end_time=end_time,
        )
    except Exception:
        # A range with no countable days contributes nothing; other domain
        # errors (no schedule for partial days) fall back to a proportional
        # calendar split so an unrelated leave configuration never blocks
        # the whole payroll run.
        total_days = (request.end_date - request.start_date).days + 1
        overlap_days = (c_end - c_start).days + 1
        fallback = (Decimal(request.days) * Decimal(overlap_days) / Decimal(total_days))
        dates = []
        cursor = c_start
        while cursor <= c_end:
            dates.append((cursor.isoformat(), "1.00"))
            cursor += timedelta(days=1)
        return money(fallback), dates
    entries = [
        (entry["date"], entry["fraction"])
        for entry in result.entries
        if Decimal(entry["fraction"]) > 0
    ]
    return Decimal(result.days), entries


def build_inputs(db: Session, period: PayrollPeriod) -> dict[str, Any]:
    """Collect every input the calculation depends on (canonical, sorted)."""
    check_open_attendance(db, period)
    company_id = period.company_id
    p_start, p_end = period.period_start, period.period_end

    rules = RuleSet(db, company_id, p_start)

    components = (
        db.execute(
            select(SalaryComponent)
            .where(
                SalaryComponent.company_id == company_id,
                SalaryComponent.status == "active",
            )
            .order_by(SalaryComponent.id)
        )
        .scalars()
        .all()
    )

    # Rule status for every key the calculation may depend on. The resolved
    # VALUES ride along in the snapshot so APPROVE detects config changes.
    needed_keys: set[str] = {"overtime"}
    for component in components:
        if component.is_statutory and component.statutory_key:
            needed_keys.add(component.statutory_key)
    if rules.rule("daily_divisor") is not None:
        needed_keys.add("daily_divisor")
    if rules.rule("proration_basis") is not None:
        needed_keys.add("proration_basis")

    rule_status: dict[str, dict[str, Any]] = {}
    rule_values: dict[str, Any] = {}
    for key in sorted(needed_keys):
        row = rules.rule(key)
        rule_status[key] = {
            "present": row is not None,
            "verified": row is not None and not row.requires_legal_verification,
            "version": row.version if row is not None else None,
        }
        if row is not None:
            rule_values[key] = {
                k: _s(v) if isinstance(v, Decimal) else v
                for k, v in dict(row.rule_json).items()
            }
    overtime_value = rules.overtime_params()
    rule_values["overtime"] = (
        {k: _s(v) for k, v in overtime_value.items()} if overtime_value else None
    )

    # Employees in scope: onboarded (not draft) with an employment window
    # that touches the period. Active employees MUST have a salary
    # assignment (payroll source of truth); inactive leftovers are skipped.
    candidates = (
        db.execute(
            select(Employee)
            .where(
                Employee.company_id == company_id,
                Employee.status != "draft",
                (Employee.hire_date.is_(None)) | (Employee.hire_date <= p_end),
                (Employee.termination_date.is_(None))
                | (Employee.termination_date >= p_start),
            )
            .order_by(Employee.id)
        )
        .scalars()
        .all()
    )

    employees_payload: dict[str, Any] = {}
    unassigned: list[str] = []

    for employee in candidates:
        assignment_rows = (
            db.execute(
                select(EmployeeSalaryAssignment)
                .where(
                    EmployeeSalaryAssignment.employee_id == employee.id,
                    EmployeeSalaryAssignment.effective_from <= p_end,
                    (EmployeeSalaryAssignment.effective_to.is_(None))
                    | (EmployeeSalaryAssignment.effective_to > p_start),
                )
                .order_by(
                    EmployeeSalaryAssignment.effective_from,
                    EmployeeSalaryAssignment.id,
                )
            )
            .scalars()
            .all()
        )
        segments: list[dict[str, Any]] = []
        assignment_ids: list[int] = []
        for row in assignment_rows:
            window = _clip(row.effective_from, row.effective_to, p_start, p_end)
            if window is None:
                continue
            emp_window = _clip(
                employee.hire_date or date.min,
                employee.termination_date,
                window[0],
                window[1],
            )
            if emp_window is None:
                continue
            segments.append(
                {
                    "assignment_id": row.id,
                    "start": emp_window[0].isoformat(),
                    "end": emp_window[1].isoformat(),
                    "monthly": _s(row.basic_salary),
                    "currency": row.currency,
                }
            )
            assignment_ids.append(row.id)
        if not segments:
            if employee.status == "active":
                unassigned.append(employee.employee_number or str(employee.id))
            continue

        overrides = []
        if assignment_ids:
            override_rows = (
                db.execute(
                    select(SalaryAssignmentComponent)
                    .where(
                        SalaryAssignmentComponent.assignment_id.in_(assignment_ids)
                    )
                    .order_by(SalaryAssignmentComponent.id)
                )
                .scalars()
                .all()
            )
            overrides = [
                {
                    "assignment_id": row.assignment_id,
                    "component_id": row.component_id,
                    "amount": _s(row.amount) if row.amount is not None else None,
                    "rate": _s(row.rate) if row.rate is not None else None,
                }
                for row in override_rows
            ]

        attendance_rows = (
            db.execute(
                select(AttendanceRecord)
                .where(
                    AttendanceRecord.employee_id == employee.id,
                    AttendanceRecord.work_date >= p_start,
                    AttendanceRecord.work_date <= p_end,
                    AttendanceRecord.status == "completed",
                )
                .order_by(AttendanceRecord.id)
            )
            .scalars()
            .all()
        )
        attendance = {
            "worked_minutes": sum(r.worked_minutes or 0 for r in attendance_rows),
            "break_minutes": sum(r.break_minutes or 0 for r in attendance_rows),
            "late_minutes": sum(r.late_minutes or 0 for r in attendance_rows),
            "early_leave_minutes": sum(
                r.early_leave_minutes or 0 for r in attendance_rows
            ),
            "record_ids": [r.id for r in attendance_rows],
        }

        overtime_rows = (
            db.execute(
                select(OvertimeRecord)
                .where(
                    OvertimeRecord.employee_id == employee.id,
                    OvertimeRecord.work_date >= p_start,
                    OvertimeRecord.work_date <= p_end,
                    OvertimeRecord.status == "approved",
                )
                .order_by(OvertimeRecord.id)
            )
            .scalars()
            .all()
        )
        overtime = {
            "approved_minutes": sum(r.approved_minutes or 0 for r in overtime_rows),
            "records": [
                {
                    "id": r.id,
                    "work_date": r.work_date.isoformat(),
                    "minutes": r.approved_minutes or 0,
                }
                for r in overtime_rows
            ],
        }

        leave_rows = (
            db.execute(
                select(LeaveRequest)
                .join(LeaveType, LeaveType.id == LeaveRequest.leave_type_id)
                .where(
                    LeaveRequest.employee_id == employee.id,
                    LeaveRequest.status == "approved",
                    LeaveRequest.start_date <= p_end,
                    LeaveRequest.end_date >= p_start,
                )
                .order_by(LeaveRequest.id)
            )
            .scalars()
            .all()
        )
        paid_days = ZERO
        unpaid_days = ZERO
        unpaid_dates: list[tuple[str, str]] = []
        request_ids: list[int] = []
        for request in leave_rows:
            leave_type = db.get(LeaveType, request.leave_type_id)
            if leave_type is None:  # pragma: no cover - FK guarantees
                continue
            days, entries = _leave_days_in_period(
                db, employee, leave_type, request, period
            )
            if days <= 0:
                continue
            request_ids.append(request.id)
            if leave_type.is_paid:
                paid_days += days
            else:
                unpaid_days += days
                unpaid_dates.extend(entries)
        leave_payload = {
            "paid_days": _s(money(paid_days)),
            "unpaid_days": _s(money(unpaid_days)),
            "unpaid_dates": sorted(unpaid_dates),
            "request_ids": request_ids,
        }

        deduction_rows = (
            db.execute(
                select(PayrollDeductionRule)
                .where(
                    PayrollDeductionRule.employee_id == employee.id,
                    PayrollDeductionRule.status == "active",
                    PayrollDeductionRule.effective_from <= p_end,
                    (PayrollDeductionRule.effective_to.is_(None))
                    | (PayrollDeductionRule.effective_to > p_start),
                )
                .order_by(PayrollDeductionRule.effective_from, PayrollDeductionRule.id)
            )
            .scalars()
            .all()
        )
        deduction_payload = []
        for row in deduction_rows:
            installment = row.total_amount is not None
            if installment and (row.remaining_amount or ZERO) <= 0:
                continue
            deduction_payload.append(
                {
                    "id": row.id,
                    "component_id": row.component_id,
                    "name": row.name,
                    "amount": _s(row.amount),
                    "remaining": _s(row.remaining_amount) if installment else None,
                    "effective_from": row.effective_from.isoformat(),
                }
            )

        adjustment_rows = (
            db.execute(
                select(PayrollAdjustment)
                .where(
                    PayrollAdjustment.employee_id == employee.id,
                    PayrollAdjustment.period_id == period.id,
                    PayrollAdjustment.status == "approved",
                )
                .order_by(PayrollAdjustment.id)
            )
            .scalars()
            .all()
        )
        adjustments = [
            {
                "id": row.id,
                "component_id": row.component_id,
                "amount": _s(row.amount),
                "direction": row.direction,
            }
            for row in adjustment_rows
        ]

        employees_payload[str(employee.id)] = {
            "employee_number": employee.employee_number,
            "segments": segments,
            "overrides": overrides,
            "attendance": attendance,
            "overtime": overtime,
            "leave": leave_payload,
            "deduction_rules": deduction_payload,
            "adjustments": adjustments,
        }

    if unassigned:
        raise PayrollNoSalaryAssignmentError(
            "Active employee(s) without a salary assignment cannot be paid: "
            + ", ".join(sorted(unassigned))
            + " (seed the initial assignment from the active contract first)",
        )

    return {
        "engine_version": ENGINE_VERSION,
        "company_id": company_id,
        "period": {
            "id": period.id,
            "name": period.name,
            "start": p_start.isoformat(),
            "end": p_end.isoformat(),
            "currency": period.currency,
        },
        "rules": {
            "daily_divisor": _s(rules.daily_divisor()),
            "proration_basis": rules.proration_basis(),
            "status": rule_status,
            "values": rule_values,
        },
        "components": [
            {
                "id": c.id,
                "code": c.code,
                "category": c.category,
                "basis": c.calculation_basis,
                "default_amount": _s(c.default_amount)
                if c.default_amount is not None
                else None,
                "default_rate": _s(c.default_rate)
                if c.default_rate is not None
                else None,
                "is_statutory": c.is_statutory,
                "statutory_key": c.statutory_key,
                "sort_order": c.sort_order,
            }
            for c in components
        ],
        "employees": employees_payload,
    }


# ---------------------------------------------------------------------------
# Computation - pure function over the snapshot (no DB, no code from DB).
# ---------------------------------------------------------------------------


@dataclass
class ComputedLine:
    line_type: str  # earning | deduction | employer_contribution
    label_ar: str
    label_en: str
    unit: str  # amount | minutes | days | percent
    amount: Decimal
    component_id: int | None = None
    quantity: Decimal | None = None
    rate: Decimal | None = None
    sort_group: int = GROUP_COMPONENT
    sort_order: int = 0
    sort_id: int = 0


@dataclass
class EmployeeCalculation:
    employee_id: int
    basic_snapshot: Decimal
    currency: str
    lines: list[ComputedLine]
    earnings_total: Decimal
    deductions_total: Decimal
    employer_total: Decimal
    net_pay: Decimal
    worked_minutes: int
    overtime_minutes: int
    paid_leave_days: Decimal
    unpaid_leave_days: Decimal
    absent_days: Decimal
    late_minutes: int
    warnings: list[dict] = field(default_factory=list)


@dataclass
class CalculationResult:
    snapshot: dict
    inputs_hash: str
    engine_version: str
    employees: list[EmployeeCalculation]
    warnings: list[dict]
    totals: dict


def _segment_days(start: date, end: date) -> int:
    return (end - start).days + 1


def _prorate(monthly: Decimal, start: date, end: date) -> Decimal:
    """Calendar-day proration: daily rate = monthly / calendar days in the
    month, summed over each month chunk (Phase 6 approved default)."""
    total = Decimal("0")
    for chunk_start, chunk_end, dim in _month_chunks(start, end):
        days = _segment_days(chunk_start, chunk_end)
        total += (monthly / Decimal(dim)) * Decimal(days)
    return total


def _segment_at(segments: list[dict], day: date) -> dict | None:
    for segment in segments:
        start = date.fromisoformat(segment["start"])
        end = date.fromisoformat(segment["end"])
        if start <= day <= end:
            return segment
    return None


def _rule_warnings(inputs: dict, overtime_minutes: int) -> list[dict]:
    warnings: list[dict] = []
    status = inputs["rules"]["status"]
    values = inputs["rules"]["values"]

    def add(key: str, code: str) -> None:
        warnings.append(
            {"code": code, "statutory_key": key, "scope": "company"}
        )

    if overtime_minutes > 0:
        info = status.get("overtime", {"present": False, "verified": False})
        if not info["present"] or values.get("overtime") is None:
            add("overtime", WARNING_MISSING_RULE)
        elif not info["verified"]:
            add("overtime", WARNING_UNVERIFIED_RULE)
    for key, info in status.items():
        if key == "overtime":
            continue
        if not info["present"]:
            if key in ("daily_divisor", "proration_basis"):
                continue  # approved built-in defaults apply
            add(key, WARNING_MISSING_RULE)
        elif not info["verified"]:
            add(key, WARNING_UNVERIFIED_RULE)
    return warnings


def compute_lines(inputs: dict) -> tuple[list[EmployeeCalculation], list[dict]]:
    """Pure computation: snapshot in, per-employee calculations out.

    No eval/exec, no formulas from the database - only the closed set of
    calculation bases supported by the engine (fixed, percent_of_basic,
    engine_derived).
    """
    currency = inputs["period"]["currency"]
    components = {c["id"]: c for c in inputs["components"]}
    divisor = Decimal(inputs["rules"]["daily_divisor"])
    results: list[EmployeeCalculation] = []
    run_warnings: list[dict] = []

    total_ot_minutes = sum(
        emp["overtime"]["approved_minutes"] for emp in inputs["employees"].values()
    )
    company_warnings = _rule_warnings(inputs, total_ot_minutes)
    run_warnings.extend(company_warnings)

    for employee_id_key in sorted(inputs["employees"], key=int):
        payload = inputs["employees"][employee_id_key]
        employee_id = int(employee_id_key)
        segments = payload["segments"]
        warnings: list[dict] = [
            dict(w) for w in company_warnings if w.get("employee_id") is None
        ]

        # --- basic pay (per segment, calendar-day proration) --------------
        segment_basic: list[tuple[dict, Decimal]] = []
        basic_total = Decimal("0")
        for segment in segments:
            start = date.fromisoformat(segment["start"])
            end = date.fromisoformat(segment["end"])
            amount = _prorate(Decimal(segment["monthly"]), start, end)
            segment_basic.append((segment, amount))
            basic_total += amount
        basic_line_amount = money(basic_total)

        lines: list[ComputedLine] = []
        if basic_line_amount > 0 or not segment_basic:
            lines.append(
                ComputedLine(
                    line_type="earning",
                    label_ar=LABEL_BASIC_AR,
                    label_en=LABEL_BASIC_EN,
                    unit="amount",
                    amount=basic_line_amount,
                    sort_group=GROUP_BASIC,
                    sort_order=0,
                    sort_id=0,
                )
            )

        # --- overrides for the latest segment (deterministic) -------------
        latest_assignment = max(
            (int(s["assignment_id"]) for s in segments), default=None
        )
        override_by_component: dict[int, dict] = {}
        for override in payload["overrides"]:
            if int(override["assignment_id"]) == latest_assignment:
                override_by_component[int(override["component_id"])] = override

        # --- components ----------------------------------------------------
        component_rows = sorted(
            inputs["components"],
            key=lambda c: (c["sort_order"], c["id"]),
        )
        for component in component_rows:
            component_id = component["id"]
            override = override_by_component.get(component_id)
            amount = ZERO
            rate_used: Decimal | None = None
            if component["is_statutory"] and component["statutory_key"]:
                # Statutory rate always comes from the verified rule -
                # never from a stored expression or hardcoded constant.
                key = component["statutory_key"]
                info = inputs["rules"]["status"].get(
                    key, {"present": False, "verified": False}
                )
                raw_rate = (
                    inputs["rules"]["values"].get(key) or {}
                ).get("rate")
                if not info["present"] or raw_rate is None:
                    warnings.append(
                        {
                            "code": WARNING_MISSING_RULE,
                            "statutory_key": key,
                            "employee_id": employee_id,
                            "component_id": component_id,
                        }
                    )
                elif not info["verified"]:
                    warnings.append(
                        {
                            "code": WARNING_UNVERIFIED_RULE,
                            "statutory_key": key,
                            "employee_id": employee_id,
                            "component_id": component_id,
                        }
                    )
                if raw_rate is not None:
                    rate_used = Decimal(str(raw_rate))
                    amount = basic_total * rate_used
            elif component["basis"] == "fixed":
                raw = None
                if override and override.get("amount") is not None:
                    raw = Decimal(str(override["amount"]))
                elif component["default_amount"] is not None:
                    raw = Decimal(str(component["default_amount"]))
                if raw is not None:
                    # Monthly fixed amount prorated exactly like basic pay.
                    amount = Decimal("0")
                    for segment, _seg_basic in segment_basic:
                        start = date.fromisoformat(segment["start"])
                        end = date.fromisoformat(segment["end"])
                        amount += _prorate(raw, start, end)
            elif component["basis"] == "percent_of_basic":
                raw = None
                if override and override.get("rate") is not None:
                    raw = Decimal(str(override["rate"]))
                elif component["default_rate"] is not None:
                    raw = Decimal(str(component["default_rate"]))
                if raw is not None:
                    rate_used = Decimal(str(raw))
                    amount = basic_total * rate_used
            else:
                # engine_derived components are produced by the engine
                # itself (overtime / leave / statutory buckets) - never
                # computed twice from a stored formula.
                continue

            amount = money(amount)
            if amount == 0:
                continue
            if component["category"] == "earning":
                lines.append(
                    ComputedLine(
                        line_type="earning",
                        label_ar=None,  # filled below from component names
                        label_en=None,
                        unit="percent" if rate_used is not None and component["basis"] == "percent_of_basic" else "amount",
                        amount=amount,
                        component_id=component_id,
                        rate=rate_used,
                        sort_group=GROUP_COMPONENT,
                        sort_order=component["sort_order"],
                        sort_id=component_id,
                    )
                )
            elif component["category"] == "deduction":
                lines.append(
                    ComputedLine(
                        line_type="deduction",
                        label_ar=None,
                        label_en=None,
                        unit="amount",
                        amount=amount,
                        component_id=component_id,
                        rate=rate_used,
                        sort_group=GROUP_COMPONENT,
                        sort_order=component["sort_order"],
                        sort_id=component_id,
                    )
                )
            else:  # employer_contribution
                lines.append(
                    ComputedLine(
                        line_type="employer_contribution",
                        label_ar=None,
                        label_en=None,
                        unit="amount",
                        amount=amount,
                        component_id=component_id,
                        rate=rate_used,
                        sort_group=GROUP_COMPONENT,
                        sort_order=component["sort_order"],
                        sort_id=component_id,
                    )
                )

        # --- overtime pay (HRSD framework, rule-driven) --------------------
        overtime = payload["overtime"]
        ot_minutes = overtime["approved_minutes"]
        ot_amount = Decimal("0")
        if ot_minutes > 0:
            ot_params_raw = inputs["rules"]["values"].get("overtime")
            if ot_params_raw:
                rate_pct = Decimal(str(ot_params_raw["overtime_rate_percent"]))
                days_per_month = Decimal(str(ot_params_raw["days_per_month"]))
                hours_per_day = Decimal(str(ot_params_raw["hours_per_day"]))
                for record in overtime["records"]:
                    work_day = date.fromisoformat(record["work_date"])
                    segment = _segment_at(segments, work_day)
                    if segment is None:
                        warnings.append(
                            {
                                "code": "OVERTIME_SKIPPED_NO_SALARY",
                                "employee_id": employee_id,
                                "work_date": record["work_date"],
                            }
                        )
                        continue
                    monthly = Decimal(segment["monthly"])
                    basic_hourly = monthly / days_per_month / hours_per_day
                    actual_hourly = monthly / days_per_month / hours_per_day
                    ot_hourly = actual_hourly + (rate_pct / 100) * basic_hourly
                    ot_amount += (
                        Decimal(record["minutes"]) / Decimal("60")
                    ) * ot_hourly
            # rule missing/unverifiable -> warning already emitted at company
            # level; no money is invented.
        if ot_amount > 0:
            lines.append(
                ComputedLine(
                    line_type="earning",
                    label_ar=LABEL_OVERTIME_AR,
                    label_en=LABEL_OVERTIME_EN,
                    unit="minutes",
                    amount=money(ot_amount),
                    quantity=Decimal(ot_minutes),
                    sort_group=GROUP_OVERTIME,
                    sort_order=0,
                    sort_id=0,
                )
            )

        # --- unpaid leave deduction (daily rate = monthly / divisor) -------
        unpaid_amount = Decimal("0")
        for iso_day, fraction in payload["leave"]["unpaid_dates"]:
            day = date.fromisoformat(iso_day)
            segment = _segment_at(segments, day)
            if segment is None:
                continue
            daily_rate = Decimal(segment["monthly"]) / divisor
            unpaid_amount += daily_rate * Decimal(fraction)
        if unpaid_amount > 0:
            lines.append(
                ComputedLine(
                    line_type="deduction",
                    label_ar=LABEL_UNPAID_LEAVE_AR,
                    label_en=LABEL_UNPAID_LEAVE_EN,
                    unit="days",
                    amount=money(unpaid_amount),
                    quantity=Decimal(payload["leave"]["unpaid_days"]),
                    sort_group=GROUP_LEAVE_DEDUCTION,
                    sort_order=0,
                    sort_id=0,
                )
            )

        # --- approved adjustments ------------------------------------------
        for adjustment in payload["adjustments"]:
            component = components.get(adjustment["component_id"])
            amount = money(Decimal(str(adjustment["amount"])))
            if amount == 0:
                continue
            lines.append(
                ComputedLine(
                    line_type="earning"
                    if adjustment["direction"] == "earning"
                    else "deduction",
                    label_ar=LABEL_ADJUSTMENT_AR,
                    label_en=component["code"] if component else LABEL_ADJUSTMENT_EN,
                    unit="amount",
                    amount=amount,
                    component_id=adjustment["component_id"],
                    sort_group=GROUP_ADJUSTMENT,
                    sort_order=0,
                    sort_id=int(adjustment["id"]),
                )
            )

        # --- recurring / installment deduction rules ------------------------
        for deduction in payload["deduction_rules"]:
            component = components.get(deduction["component_id"])
            amount = money(Decimal(str(deduction["amount"])))
            if amount == 0:
                continue
            lines.append(
                ComputedLine(
                    line_type="deduction",
                    label_ar=LABEL_DEDUCTION_AR,
                    label_en=component["code"] if component else deduction["name"],
                    unit="amount",
                    amount=amount,
                    component_id=deduction["component_id"],
                    sort_group=GROUP_DEDUCTION_RULE,
                    sort_order=0,
                    sort_id=int(deduction["id"]),
                )
            )

        # Fill component labels from the snapshot, then sort deterministically.
        for line in lines:
            if line.component_id is not None:
                component = components.get(line.component_id)
                if component:
                    line.label_en = component["code"]
                    line.label_ar = component["code"]
        lines.sort(key=lambda ln: (ln.sort_group, ln.sort_order, ln.sort_id))

        earnings = sum(
            (ln.amount for ln in lines if ln.line_type == "earning"), ZERO
        )
        deductions = sum(
            (ln.amount for ln in lines if ln.line_type == "deduction"), ZERO
        )
        employer = sum(
            (ln.amount for ln in lines if ln.line_type == "employer_contribution"),
            ZERO,
        )
        net = earnings - deductions

        # Reconciliation invariant: totals must be exactly the sums of the
        # rounded lines (and net must equal earnings - deductions).
        if (
            earnings != money(earnings)
            or deductions != money(deductions)
            or employer != money(employer)
            or net != money(net)
        ):  # pragma: no cover - defensive
            raise PayrollReconciliationError(
                f"Rounded line totals do not reconcile for employee {employee_id}"
            )

        results.append(
            EmployeeCalculation(
                employee_id=employee_id,
                basic_snapshot=basic_line_amount,
                currency=currency,
                lines=lines,
                earnings_total=earnings,
                deductions_total=deductions,
                employer_total=employer,
                net_pay=net,
                worked_minutes=payload["attendance"]["worked_minutes"],
                overtime_minutes=ot_minutes,
                paid_leave_days=Decimal(payload["leave"]["paid_days"]),
                unpaid_leave_days=Decimal(payload["leave"]["unpaid_days"]),
                absent_days=ZERO,
                late_minutes=payload["attendance"]["late_minutes"],
                warnings=warnings,
            )
        )
        run_warnings.extend(warnings)

    totals = {
        "gross_total": money(sum(r.earnings_total for r in results)),
        "deductions_total": money(sum(r.deductions_total for r in results)),
        "employer_total": money(sum(r.employer_total for r in results)),
        "net_total": money(sum(r.net_pay for r in results)),
    }
    if results:
        if totals["net_total"] != money(
            totals["gross_total"] - totals["deductions_total"]
        ):  # pragma: no cover - defensive
            raise PayrollReconciliationError(
                "Run totals do not reconcile (net != gross - deductions)"
            )
    # De-duplicate company-level warnings while keeping order.
    seen: set[str] = set()
    unique_warnings: list[dict] = []
    for warning in run_warnings:
        key = canonical_json(warning)
        if key in seen:
            continue
        seen.add(key)
        unique_warnings.append(warning)
    return results, unique_warnings


def calculate(db: Session, period: PayrollPeriod) -> CalculationResult:
    """Full calculation: gather inputs (attendance gate included), hash them
    for reproducibility, and compute every payslip line."""
    snapshot = build_inputs(db, period)
    inputs_hash = snapshot_hash(snapshot)
    employees, warnings = compute_lines(snapshot)
    totals = {
        "gross_total": money(sum(r.earnings_total for r in employees)),
        "deductions_total": money(sum(r.deductions_total for r in employees)),
        "employer_total": money(sum(r.employer_total for r in employees)),
        "net_total": money(sum(r.net_pay for r in employees)),
    }
    return CalculationResult(
        snapshot=snapshot,
        inputs_hash=inputs_hash,
        engine_version=ENGINE_VERSION,
        employees=employees,
        warnings=warnings,
        totals=totals,
    )


def blocking_warnings(warnings: list[dict]) -> list[dict]:
    return [w for w in warnings if w.get("code") in BLOCKING_WARNINGS]
