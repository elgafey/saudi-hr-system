from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import (
    Principal,
    client_ip,
    optional_company_header,
    require_permission,
)
from app.core.pagination import Page, PageParams, pagination_params
from app.payroll.schemas import (
    AccountingExportOut,
    PayrollAdjustmentCreate,
    PayrollAdjustmentDecision,
    PayrollAdjustmentOut,
    PayrollAdjustmentPage,
    PayrollDeductionCreate,
    PayrollDeductionOut,
    PayrollDeductionPage,
    PayrollDeductionUpdate,
    PayrollPeriodCreate,
    PayrollPeriodOut,
    PayrollPeriodPage,
    PayrollPeriodUpdate,
    PayrollRunLineOut,
    PayrollRunLinePage,
    PayrollRunOut,
    PayrollRunPage,
    PayrollStatutoryRuleCreate,
    PayrollStatutoryRuleDeactivate,
    PayrollStatutoryRuleOut,
    PayrollStatutoryRulePage,
    PayslipLineOut,
    PayslipOut,
    SalaryAssignmentCreate,
    SalaryAssignmentOut,
    SalaryAssignmentPage,
    SalaryAssignmentUpdate,
    SalaryComponentCreate,
    SalaryComponentOut,
    SalaryComponentPage,
    SalaryComponentUpdate,
    SeedAssignmentsOut,
)
from app.payroll.service import (
    approve_payroll_period,
    build_accounting_export,
    calculate_payroll_period,
    create_payroll_adjustment,
    create_payroll_deduction,
    create_payroll_period,
    create_payroll_statutory_rule,
    create_salary_assignment,
    create_salary_component,
    deactivate_payroll_statutory_rule,
    deactivate_salary_component,
    decide_payroll_adjustment,
    get_payroll_adjustment,
    get_payroll_deduction,
    get_payroll_period,
    get_payroll_run,
    get_payroll_statutory_rule,
    get_payslip,
    get_salary_assignment,
    get_salary_component,
    list_payroll_adjustments,
    list_payroll_deductions,
    list_payroll_periods,
    list_payroll_runs,
    list_payroll_statutory_rules,
    list_run_lines,
    list_salary_assignments,
    list_salary_components,
    lock_payroll_period,
    mark_payroll_period_paid,
    recalculate_payroll_run,
    review_payroll_period,
    seed_salary_assignments,
    update_payroll_deduction,
    update_payroll_period,
    update_salary_assignment,
    update_salary_component,
)
from app.shared.models import (
    PayrollPeriod,
    PayrollRun,
    PayrollRunLine,
    PayslipLine,
)

salary_components_router = APIRouter(
    prefix="/salary-components", tags=["salary-components"]
)
salary_assignments_router = APIRouter(
    prefix="/salary-assignments", tags=["salary-assignments"]
)
periods_router = APIRouter(prefix="/payroll-periods", tags=["payroll-periods"])
runs_router = APIRouter(prefix="/payroll-runs", tags=["payroll-runs"])
payslips_router = APIRouter(prefix="/payslips", tags=["payslips"])
adjustments_router = APIRouter(
    prefix="/payroll-adjustments", tags=["payroll-adjustments"]
)
deductions_router = APIRouter(
    prefix="/payroll-deductions", tags=["payroll-deductions"]
)
statutory_router = APIRouter(
    prefix="/payroll-statutory-rules", tags=["payroll-statutory-rules"]
)


def _period_of(db: Session, run: PayrollRun) -> PayrollPeriod | None:
    return db.get(PayrollPeriod, run.period_id)


def _run_out(db: Session, run: PayrollRun) -> PayrollRunOut:
    out = PayrollRunOut.model_validate(run)
    period = _period_of(db, run)
    if period is not None:
        out.period_status = period.status
        out.period_start = period.period_start
        out.period_end = period.period_end
    return out


def _run_line_out(
    db: Session, line: PayrollRunLine, *, with_lines: bool = True
) -> PayrollRunLineOut:
    out = PayrollRunLineOut.model_validate(line)
    if with_lines:
        payslip_lines = db.execute(
            select(PayslipLine)
            .where(PayslipLine.run_line_id == line.id)
            .order_by(PayslipLine.sort_order, PayslipLine.id)
        ).scalars()
        out.lines = [PayslipLineOut.model_validate(r) for r in payslip_lines]
    return out


def _payslip_out(
    db: Session, line: PayrollRunLine, run: PayrollRun
) -> PayslipOut:
    out = PayslipOut.model_validate(
        _run_line_out(db, line, with_lines=True)
    )
    out.run_status = run.status
    out.run_number = run.run_number
    out.inputs_hash = run.inputs_hash
    period = _period_of(db, run)
    if period is not None:
        out.period_status = period.status
        out.period_start = period.period_start
        out.period_end = period.period_end
    return out


# ---------------------------------------------------------------------------
# Salary components
# ---------------------------------------------------------------------------


@salary_components_router.get("", response_model=SalaryComponentPage)
def list_components(
    company_id: int | None = Query(default=None, ge=1),
    category: str | None = Query(default=None, pattern="^(earning|deduction|employer_contribution)$"),
    status: str | None = Query(default=None, pattern="^(active|inactive)$"),
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(require_permission("salary_component.view")),
    scoped_company: int | None = Depends(optional_company_header),
    db: Session = Depends(get_db),
) -> SalaryComponentPage:
    target = company_id if company_id is not None else scoped_company
    items, total = list_salary_components(
        db,
        principal,
        company_id=target,
        category=category,
        status=status,
        page=page_params,
    )
    return SalaryComponentPage(
        items=[SalaryComponentOut.model_validate(r) for r in items],
        page=Page(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ),
    )


@salary_components_router.post("", response_model=SalaryComponentOut, status_code=201)
def create_component(
    payload: SalaryComponentCreate,
    request: Request,
    principal: Principal = Depends(require_permission("salary_component.create")),
    db: Session = Depends(get_db),
) -> SalaryComponentOut:
    row = create_salary_component(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return SalaryComponentOut.model_validate(row)


@salary_components_router.get("/{component_id}", response_model=SalaryComponentOut)
def read_component(
    component_id: int,
    principal: Principal = Depends(require_permission("salary_component.view")),
    db: Session = Depends(get_db),
) -> SalaryComponentOut:
    return SalaryComponentOut.model_validate(
        get_salary_component(db, component_id, principal)
    )


@salary_components_router.patch("/{component_id}", response_model=SalaryComponentOut)
def update_component(
    component_id: int,
    payload: SalaryComponentUpdate,
    request: Request,
    principal: Principal = Depends(require_permission("salary_component.update")),
    db: Session = Depends(get_db),
) -> SalaryComponentOut:
    row = update_salary_component(
        db,
        component_id=component_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return SalaryComponentOut.model_validate(row)


@salary_components_router.post(
    "/{component_id}/deactivate", response_model=SalaryComponentOut
)
def deactivate_component(
    component_id: int,
    request: Request,
    principal: Principal = Depends(
        require_permission("salary_component.deactivate")
    ),
    db: Session = Depends(get_db),
) -> SalaryComponentOut:
    row = deactivate_salary_component(
        db, component_id=component_id, principal=principal, ip=client_ip(request)
    )
    return SalaryComponentOut.model_validate(row)


# ---------------------------------------------------------------------------
# Salary assignments (payroll source of truth)
# ---------------------------------------------------------------------------


@salary_assignments_router.get("", response_model=SalaryAssignmentPage)
def list_assignments(
    company_id: int | None = Query(default=None, ge=1),
    employee_id: int | None = Query(default=None, ge=1),
    as_of: date | None = Query(default=None),
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(require_permission("salary_assignment.view")),
    scoped_company: int | None = Depends(optional_company_header),
    db: Session = Depends(get_db),
) -> SalaryAssignmentPage:
    target = company_id if company_id is not None else scoped_company
    items, total = list_salary_assignments(
        db,
        principal,
        company_id=target,
        employee_id=employee_id,
        as_of=as_of,
        page=page_params,
    )
    return SalaryAssignmentPage(
        items=[SalaryAssignmentOut.model_validate(r) for r in items],
        page=Page(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ),
    )


@salary_assignments_router.post("", response_model=SalaryAssignmentOut, status_code=201)
def create_assignment(
    payload: SalaryAssignmentCreate,
    request: Request,
    principal: Principal = Depends(require_permission("salary_assignment.create")),
    db: Session = Depends(get_db),
) -> SalaryAssignmentOut:
    row = create_salary_assignment(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return SalaryAssignmentOut.model_validate(row)


@salary_assignments_router.post("/seed", response_model=SeedAssignmentsOut, status_code=201)
def seed_assignments(
    request: Request,
    company_id: int = Query(..., ge=1),
    principal: Principal = Depends(require_permission("salary_assignment.create")),
    db: Session = Depends(get_db),
) -> SeedAssignmentsOut:
    result = seed_salary_assignments(
        db, company_id=company_id, principal=principal, ip=client_ip(request)
    )
    return SeedAssignmentsOut(**result)


@salary_assignments_router.get("/{assignment_id}", response_model=SalaryAssignmentOut)
def read_assignment(
    assignment_id: int,
    principal: Principal = Depends(require_permission("salary_assignment.view")),
    db: Session = Depends(get_db),
) -> SalaryAssignmentOut:
    return SalaryAssignmentOut.model_validate(
        get_salary_assignment(db, assignment_id, principal)
    )


@salary_assignments_router.patch("/{assignment_id}", response_model=SalaryAssignmentOut)
def update_assignment(
    assignment_id: int,
    payload: SalaryAssignmentUpdate,
    request: Request,
    principal: Principal = Depends(require_permission("salary_assignment.update")),
    db: Session = Depends(get_db),
) -> SalaryAssignmentOut:
    row = update_salary_assignment(
        db,
        assignment_id=assignment_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return SalaryAssignmentOut.model_validate(row)


# ---------------------------------------------------------------------------
# Payroll periods (the single workflow state machine)
# ---------------------------------------------------------------------------


@periods_router.get("", response_model=PayrollPeriodPage)
def list_periods(
    company_id: int | None = Query(default=None, ge=1),
    status: str | None = Query(
        default=None,
        pattern="^(draft|calculated|reviewed|approved|paid|locked)$",
    ),
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(require_permission("payroll_period.view")),
    scoped_company: int | None = Depends(optional_company_header),
    db: Session = Depends(get_db),
) -> PayrollPeriodPage:
    target = company_id if company_id is not None else scoped_company
    items, total = list_payroll_periods(
        db, principal, company_id=target, status=status, page=page_params
    )
    return PayrollPeriodPage(
        items=[PayrollPeriodOut.model_validate(r) for r in items],
        page=Page(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ),
    )


@periods_router.post("", response_model=PayrollPeriodOut, status_code=201)
def create_period(
    payload: PayrollPeriodCreate,
    request: Request,
    principal: Principal = Depends(require_permission("payroll_period.create")),
    db: Session = Depends(get_db),
) -> PayrollPeriodOut:
    row = create_payroll_period(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return PayrollPeriodOut.model_validate(row)


@periods_router.get("/{period_id}", response_model=PayrollPeriodOut)
def read_period(
    period_id: int,
    principal: Principal = Depends(require_permission("payroll_period.view")),
    db: Session = Depends(get_db),
) -> PayrollPeriodOut:
    return PayrollPeriodOut.model_validate(
        get_payroll_period(db, period_id, principal)
    )


@periods_router.patch("/{period_id}", response_model=PayrollPeriodOut)
def update_period(
    period_id: int,
    payload: PayrollPeriodUpdate,
    request: Request,
    principal: Principal = Depends(require_permission("payroll_period.update")),
    db: Session = Depends(get_db),
) -> PayrollPeriodOut:
    row = update_payroll_period(
        db,
        period_id=period_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return PayrollPeriodOut.model_validate(row)


@periods_router.post("/{period_id}/calculate", response_model=PayrollRunOut)
def calculate_period(
    period_id: int,
    request: Request,
    principal: Principal = Depends(require_permission("payroll_run.calculate")),
    db: Session = Depends(get_db),
) -> PayrollRunOut:
    _period, run = calculate_payroll_period(
        db, period_id=period_id, principal=principal, ip=client_ip(request)
    )
    return _run_out(db, run)


@periods_router.post("/{period_id}/review", response_model=PayrollPeriodOut)
def review_period(
    period_id: int,
    request: Request,
    principal: Principal = Depends(require_permission("payroll_run.review")),
    db: Session = Depends(get_db),
) -> PayrollPeriodOut:
    row = review_payroll_period(
        db, period_id=period_id, principal=principal, ip=client_ip(request)
    )
    return PayrollPeriodOut.model_validate(row)


@periods_router.post("/{period_id}/approve", response_model=PayrollPeriodOut)
def approve_period(
    period_id: int,
    request: Request,
    principal: Principal = Depends(require_permission("payroll_run.approve")),
    db: Session = Depends(get_db),
) -> PayrollPeriodOut:
    row = approve_payroll_period(
        db, period_id=period_id, principal=principal, ip=client_ip(request)
    )
    return PayrollPeriodOut.model_validate(row)


@periods_router.post("/{period_id}/mark-paid", response_model=PayrollPeriodOut)
def mark_paid_period(
    period_id: int,
    request: Request,
    principal: Principal = Depends(require_permission("payroll_run.mark_paid")),
    db: Session = Depends(get_db),
) -> PayrollPeriodOut:
    row = mark_payroll_period_paid(
        db, period_id=period_id, principal=principal, ip=client_ip(request)
    )
    return PayrollPeriodOut.model_validate(row)


@periods_router.post("/{period_id}/lock", response_model=PayrollPeriodOut)
def lock_period(
    period_id: int,
    request: Request,
    principal: Principal = Depends(require_permission("payroll_run.lock")),
    db: Session = Depends(get_db),
) -> PayrollPeriodOut:
    row = lock_payroll_period(
        db, period_id=period_id, principal=principal, ip=client_ip(request)
    )
    return PayrollPeriodOut.model_validate(row)


# ---------------------------------------------------------------------------
# Payroll runs, lines, export
# ---------------------------------------------------------------------------


@runs_router.get("", response_model=PayrollRunPage)
def list_runs(
    company_id: int | None = Query(default=None, ge=1),
    period_id: int | None = Query(default=None, ge=1),
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(require_permission("payroll_run.view")),
    scoped_company: int | None = Depends(optional_company_header),
    db: Session = Depends(get_db),
) -> PayrollRunPage:
    target = company_id if company_id is not None else scoped_company
    items, total = list_payroll_runs(
        db,
        principal,
        company_id=target,
        period_id=period_id,
        page=page_params,
    )
    return PayrollRunPage(
        items=[_run_out(db, r) for r in items],
        page=Page(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ),
    )


@runs_router.get("/{run_id}", response_model=PayrollRunOut)
def read_run(
    run_id: int,
    principal: Principal = Depends(require_permission("payroll_run.view")),
    db: Session = Depends(get_db),
) -> PayrollRunOut:
    return _run_out(db, get_payroll_run(db, run_id, principal))


@runs_router.get("/{run_id}/lines", response_model=PayrollRunLinePage)
def read_run_lines(
    run_id: int,
    employee_id: int | None = Query(default=None, ge=1),
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(require_permission("payroll_run.view")),
    db: Session = Depends(get_db),
) -> PayrollRunLinePage:
    items, total = list_run_lines(
        db,
        principal,
        run_id=run_id,
        employee_id=employee_id,
        page=page_params,
    )
    return PayrollRunLinePage(
        items=[_run_line_out(db, r) for r in items],
        page=Page(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ),
    )


@runs_router.post("/{run_id}/recalculate", response_model=PayrollRunOut)
def recalculate_run(
    run_id: int,
    request: Request,
    principal: Principal = Depends(require_permission("payroll_run.calculate")),
    db: Session = Depends(get_db),
) -> PayrollRunOut:
    _period, run = recalculate_payroll_run(
        db, run_id=run_id, principal=principal, ip=client_ip(request)
    )
    return _run_out(db, run)


@runs_router.get("/{run_id}/export", response_model=AccountingExportOut)
def export_run(
    run_id: int,
    principal: Principal = Depends(require_permission("payroll_export.execute")),
    db: Session = Depends(get_db),
) -> AccountingExportOut:
    payload = build_accounting_export(db, run_id=run_id, principal=principal)
    return AccountingExportOut.model_validate(payload)


# ---------------------------------------------------------------------------
# Payslips (run lines ARE the payslips - no separate table)
# ---------------------------------------------------------------------------


@payslips_router.get("/{run_line_id}", response_model=PayslipOut)
def read_payslip(
    run_line_id: int,
    principal: Principal = Depends(require_permission("payroll_run.view")),
    db: Session = Depends(get_db),
) -> PayslipOut:
    line = get_payslip(db, run_line_id, principal)
    run = get_payroll_run(db, line.run_id, principal)
    return _payslip_out(db, line, run)


# ---------------------------------------------------------------------------
# Adjustments (corrections to approved/paid/locked payroll flow to the
# next OPEN period and must reference the original run)
# ---------------------------------------------------------------------------


@adjustments_router.get("", response_model=PayrollAdjustmentPage)
def list_adjustments(
    company_id: int | None = Query(default=None, ge=1),
    status: str | None = Query(
        default=None, pattern="^(draft|pending|approved|rejected|void)$"
    ),
    period_id: int | None = Query(default=None, ge=1),
    employee_id: int | None = Query(default=None, ge=1),
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(
        require_permission("payroll_adjustment.view")
    ),
    scoped_company: int | None = Depends(optional_company_header),
    db: Session = Depends(get_db),
) -> PayrollAdjustmentPage:
    target = company_id if company_id is not None else scoped_company
    items, total = list_payroll_adjustments(
        db,
        principal,
        company_id=target,
        status=status,
        period_id=period_id,
        employee_id=employee_id,
        page=page_params,
    )
    return PayrollAdjustmentPage(
        items=[PayrollAdjustmentOut.model_validate(r) for r in items],
        page=Page(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ),
    )


@adjustments_router.post("", response_model=PayrollAdjustmentOut, status_code=201)
def create_adjustment(
    payload: PayrollAdjustmentCreate,
    request: Request,
    principal: Principal = Depends(
        require_permission("payroll_adjustment.create")
    ),
    db: Session = Depends(get_db),
) -> PayrollAdjustmentOut:
    row = create_payroll_adjustment(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return PayrollAdjustmentOut.model_validate(row)


@adjustments_router.get("/{adjustment_id}", response_model=PayrollAdjustmentOut)
def read_adjustment(
    adjustment_id: int,
    principal: Principal = Depends(
        require_permission("payroll_adjustment.view")
    ),
    db: Session = Depends(get_db),
) -> PayrollAdjustmentOut:
    return PayrollAdjustmentOut.model_validate(
        get_payroll_adjustment(db, adjustment_id, principal)
    )


@adjustments_router.post("/{adjustment_id}/approve", response_model=PayrollAdjustmentOut)
def approve_adjustment(
    adjustment_id: int,
    payload: PayrollAdjustmentDecision,
    request: Request,
    principal: Principal = Depends(
        require_permission("payroll_adjustment.approve")
    ),
    db: Session = Depends(get_db),
) -> PayrollAdjustmentOut:
    row = decide_payroll_adjustment(
        db,
        adjustment_id=adjustment_id,
        decision="approve",
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return PayrollAdjustmentOut.model_validate(row)


@adjustments_router.post("/{adjustment_id}/reject", response_model=PayrollAdjustmentOut)
def reject_adjustment(
    adjustment_id: int,
    payload: PayrollAdjustmentDecision,
    request: Request,
    principal: Principal = Depends(
        require_permission("payroll_adjustment.reject")
    ),
    db: Session = Depends(get_db),
) -> PayrollAdjustmentOut:
    row = decide_payroll_adjustment(
        db,
        adjustment_id=adjustment_id,
        decision="reject",
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return PayrollAdjustmentOut.model_validate(row)


@adjustments_router.post("/{adjustment_id}/void", response_model=PayrollAdjustmentOut)
def void_adjustment(
    adjustment_id: int,
    payload: PayrollAdjustmentDecision,
    request: Request,
    principal: Principal = Depends(
        require_permission("payroll_adjustment.void")
    ),
    db: Session = Depends(get_db),
) -> PayrollAdjustmentOut:
    row = decide_payroll_adjustment(
        db,
        adjustment_id=adjustment_id,
        decision="void",
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return PayrollAdjustmentOut.model_validate(row)


# ---------------------------------------------------------------------------
# Deduction rules (recurring / installment, consumed at APPROVE only)
# ---------------------------------------------------------------------------


@deductions_router.get("", response_model=PayrollDeductionPage)
def list_deductions(
    company_id: int | None = Query(default=None, ge=1),
    status: str | None = Query(default=None, pattern="^(active|completed|cancelled)$"),
    employee_id: int | None = Query(default=None, ge=1),
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(
        require_permission("payroll_deduction.view")
    ),
    scoped_company: int | None = Depends(optional_company_header),
    db: Session = Depends(get_db),
) -> PayrollDeductionPage:
    target = company_id if company_id is not None else scoped_company
    items, total = list_payroll_deductions(
        db,
        principal,
        company_id=target,
        status=status,
        employee_id=employee_id,
        page=page_params,
    )
    return PayrollDeductionPage(
        items=[PayrollDeductionOut.model_validate(r) for r in items],
        page=Page(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ),
    )


@deductions_router.post("", response_model=PayrollDeductionOut, status_code=201)
def create_deduction(
    payload: PayrollDeductionCreate,
    request: Request,
    principal: Principal = Depends(
        require_permission("payroll_deduction.create")
    ),
    db: Session = Depends(get_db),
) -> PayrollDeductionOut:
    row = create_payroll_deduction(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return PayrollDeductionOut.model_validate(row)


@deductions_router.get("/{deduction_id}", response_model=PayrollDeductionOut)
def read_deduction(
    deduction_id: int,
    principal: Principal = Depends(
        require_permission("payroll_deduction.view")
    ),
    db: Session = Depends(get_db),
) -> PayrollDeductionOut:
    return PayrollDeductionOut.model_validate(
        get_payroll_deduction(db, deduction_id, principal)
    )


@deductions_router.patch("/{deduction_id}", response_model=PayrollDeductionOut)
def update_deduction(
    deduction_id: int,
    payload: PayrollDeductionUpdate,
    request: Request,
    principal: Principal = Depends(
        require_permission("payroll_deduction.update")
    ),
    db: Session = Depends(get_db),
) -> PayrollDeductionOut:
    row = update_payroll_deduction(
        db,
        deduction_id=deduction_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return PayrollDeductionOut.model_validate(row)


# ---------------------------------------------------------------------------
# Statutory rules (mandatory source_reference + effective dating)
# ---------------------------------------------------------------------------


@statutory_router.get("", response_model=PayrollStatutoryRulePage)
def list_rules(
    company_id: int | None = Query(default=None, ge=1),
    statutory_key: str | None = Query(default=None, max_length=50),
    status: str | None = Query(default=None, pattern="^(active|inactive)$"),
    as_of: date | None = Query(default=None),
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(
        require_permission("payroll_statutory_rule.view")
    ),
    scoped_company: int | None = Depends(optional_company_header),
    db: Session = Depends(get_db),
) -> PayrollStatutoryRulePage:
    target = company_id if company_id is not None else scoped_company
    items, total = list_payroll_statutory_rules(
        db,
        principal,
        company_id=target,
        statutory_key=statutory_key,
        status=status,
        as_of=as_of,
        page=page_params,
    )
    return PayrollStatutoryRulePage(
        items=[PayrollStatutoryRuleOut.model_validate(r) for r in items],
        page=Page(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ),
    )


@statutory_router.post("", response_model=PayrollStatutoryRuleOut, status_code=201)
def create_rule(
    payload: PayrollStatutoryRuleCreate,
    request: Request,
    principal: Principal = Depends(
        require_permission("payroll_statutory_rule.create")
    ),
    db: Session = Depends(get_db),
) -> PayrollStatutoryRuleOut:
    row = create_payroll_statutory_rule(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return PayrollStatutoryRuleOut.model_validate(row)


@statutory_router.get("/{rule_id}", response_model=PayrollStatutoryRuleOut)
def read_rule(
    rule_id: int,
    principal: Principal = Depends(
        require_permission("payroll_statutory_rule.view")
    ),
    db: Session = Depends(get_db),
) -> PayrollStatutoryRuleOut:
    return PayrollStatutoryRuleOut.model_validate(
        get_payroll_statutory_rule(db, rule_id, principal)
    )


@statutory_router.post(
    "/{rule_id}/deactivate", response_model=PayrollStatutoryRuleOut
)
def deactivate_rule(
    rule_id: int,
    payload: PayrollStatutoryRuleDeactivate,
    request: Request,
    principal: Principal = Depends(
        require_permission("payroll_statutory_rule.deactivate")
    ),
    db: Session = Depends(get_db),
) -> PayrollStatutoryRuleOut:
    row = deactivate_payroll_statutory_rule(
        db,
        rule_id=rule_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return PayrollStatutoryRuleOut.model_validate(row)
