"""Phase 7 /me (employee self-service) reads.

Every function resolves the caller's OWN linked employee first (no IDOR:
there is no employee_id parameter anywhere), enforces the matching
``ess.*`` code against that employee's company, and returns only data the
design allows the employee to see:

- profile: own employee record, org names and active contract (own basic
  pay included - open Q3 default);
- documents: only rows whose sidecar flag is ``employee_visible``
  (default-deny on the frozen ``employee_documents`` table);
- attendance: own rows only;
- payslips: own run lines whose PERIOD status is approved/paid/locked,
  read-only over frozen Phase 6 tables, audited ``payslip.view``.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.core.deps import Principal
from app.core.exceptions import (
    DocumentNotFoundError,
    EssDocumentNotSharedError,
    ForbiddenError,
    NotFoundError,
    PayslipNotOwnError,
)
from app.core.pagination import PageParams
from app.core.storage import get_storage
from app.ess.schemas import (
    PayslipSummaryOut,
    ProfileContractOut,
    ProfileNameOut,
    ProfileOut,
)
from app.ess.service import self_employee
from app.payroll.schemas import PayrollRunLineOut, PayslipLineOut, PayslipOut
from app.shared.models import (
    AttendanceRecord,
    Branch,
    Company,
    Department,
    Employee,
    EmployeeContract,
    EmployeeDocument,
    EmployeeDocumentVisibility,
    JobPosition,
    PayrollPeriod,
    PayrollRun,
    PayrollRunLine,
    PayslipLine,
)

# Employees only ever see payslips of finalized periods (design: no draft
# or in-review payroll data reaches the employee portal).
VISIBLE_PERIOD_STATUSES = ("approved", "paid", "locked")


def _require(principal: Principal, code: str, company_id: int) -> None:
    if not principal.has_permission(code, company_id):
        raise ForbiddenError(f"Missing permission: {code}")


def _self_context(db: Session, principal: Principal, code: str) -> Employee:
    employee = self_employee(db, principal)
    _require(principal, code, employee.company_id)
    return employee


def _name_out(
    row_id: int, name_ar: str, name_en: str
) -> ProfileNameOut:
    return ProfileNameOut(id=row_id, name_ar=name_ar, name_en=name_en)


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


def my_profile(db: Session, principal: Principal) -> ProfileOut:
    employee = _self_context(db, principal, "ess.profile.view")

    company = db.get(Company, employee.company_id) if employee.company_id else None
    department = db.get(Department, employee.department_id) if employee.department_id else None
    branch = db.get(Branch, employee.branch_id) if employee.branch_id else None
    position = (
        db.get(JobPosition, employee.job_position_id)
        if employee.job_position_id
        else None
    )
    manager = db.get(Employee, employee.manager_id) if employee.manager_id else None
    contract = db.execute(
        select(EmployeeContract).where(
            EmployeeContract.employee_id == employee.id,
            EmployeeContract.status == "active",
        )
    ).scalar_one_or_none()

    def _full_ar(row: Employee) -> str:
        return " ".join(
            part
            for part in (row.first_name_ar, row.middle_name_ar, row.last_name_ar)
            if part
        )

    def _full_en(row: Employee) -> str:
        return " ".join(
            part
            for part in (row.first_name_en, row.middle_name_en, row.last_name_en)
            if part
        )

    return ProfileOut(
        id=employee.id,
        company_id=employee.company_id,
        employee_number=employee.employee_number,
        first_name_ar=employee.first_name_ar,
        middle_name_ar=employee.middle_name_ar,
        last_name_ar=employee.last_name_ar,
        first_name_en=employee.first_name_en,
        middle_name_en=employee.middle_name_en,
        last_name_en=employee.last_name_en,
        status=employee.status,
        employment_type=employee.employment_type,
        hire_date=employee.hire_date,
        nationality=employee.nationality,
        gender=employee.gender,
        work_email=employee.work_email,
        mobile_phone=employee.mobile_phone,
        company=(
            _name_out(company.id, company.name_ar, company.name_en)
            if company is not None
            else None
        ),
        department=(
            _name_out(department.id, department.name_ar, department.name_en)
            if department is not None
            else None
        ),
        branch=(
            _name_out(branch.id, branch.name_ar, branch.name_en)
            if branch is not None
            else None
        ),
        job_position=(
            _name_out(position.id, position.name_ar, position.name_en)
            if position is not None
            else None
        ),
        manager=(
            _name_out(manager.id, _full_ar(manager), _full_en(manager))
            if manager is not None
            else None
        ),
        contract=(
            ProfileContractOut(
                id=contract.id,
                contract_number=contract.contract_number,
                contract_type=contract.contract_type,
                start_date=contract.start_date,
                end_date=contract.end_date,
                basic_salary=contract.basic_salary,
                currency=contract.currency,
            )
            if contract is not None
            else None
        ),
    )


# ---------------------------------------------------------------------------
# Documents (sidecar visibility flag, default-deny)
# ---------------------------------------------------------------------------


def _visible_documents(db: Session, employee: Employee):
    return (
        select(EmployeeDocument)
        .join(
            EmployeeDocumentVisibility,
            (
                EmployeeDocumentVisibility.document_id == EmployeeDocument.id
            )
            & (EmployeeDocumentVisibility.employee_visible.is_(True)),
        )
        .where(EmployeeDocument.employee_id == employee.id)
    )


def my_documents(
    db: Session, principal: Principal, *, page: PageParams | None = None
) -> tuple[list[EmployeeDocument], int]:
    employee = _self_context(db, principal, "ess.document.view")
    stmt = _visible_documents(db, employee)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(EmployeeDocument.id.desc())
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


def my_document_download(
    db: Session,
    *,
    document_id: int,
    principal: Principal,
    ip: str | None,
) -> tuple[bytes, str, str]:
    employee = _self_context(db, principal, "ess.document.view")
    doc = db.get(EmployeeDocument, document_id)
    if doc is None or doc.employee_id != employee.id:
        raise EssDocumentNotSharedError("Document is not available to you")
    visibility = db.execute(
        select(EmployeeDocumentVisibility).where(
            EmployeeDocumentVisibility.document_id == doc.id
        )
    ).scalar_one_or_none()
    if visibility is None or not visibility.employee_visible:
        raise EssDocumentNotSharedError("Document is not available to you")

    data = get_storage().load(doc.storage_key)
    record_audit(
        db,
        action="document.download",
        entity="employee_document",
        record_id=doc.id,
        actor_user_id=principal.user_id,
        company_id=employee.company_id,
        new_value={
            "employee_id": employee.id,
            "file_name": doc.file_name,
            "via": "ess",
        },
        ip_address=ip,
    )
    db.flush()
    return data, doc.mime_type, doc.file_name


def set_document_visibility(
    db: Session,
    *,
    document_id: int,
    employee_visible: bool,
    principal: Principal,
    ip: str | None,
) -> EmployeeDocument:
    """HR-side toggle of the Phase 7 sidecar flag (company-scoped
    ``employee_document.update``; the frozen ``employee_documents`` rows
    themselves are never modified)."""
    doc = db.get(EmployeeDocument, document_id)
    if doc is None or not principal.can_access_company(doc.company_id):
        raise DocumentNotFoundError("Document not found")
    _require(principal, "employee_document.update", doc.company_id)

    visibility = db.execute(
        select(EmployeeDocumentVisibility).where(
            EmployeeDocumentVisibility.document_id == doc.id
        )
    ).scalar_one_or_none()
    if visibility is None:
        visibility = EmployeeDocumentVisibility(
            company_id=doc.company_id,
            document_id=doc.id,
            employee_visible=employee_visible,
            updated_by=principal.user_id,
        )
        db.add(visibility)
    else:
        visibility.employee_visible = employee_visible
        visibility.updated_by = principal.user_id
        db.add(visibility)
    db.flush()
    record_audit(
        db,
        action="document.visibility",
        entity="employee_document",
        record_id=doc.id,
        actor_user_id=principal.user_id,
        company_id=doc.company_id,
        new_value={
            "employee_id": doc.employee_id,
            "employee_visible": employee_visible,
        },
        ip_address=ip,
    )
    db.flush()
    return doc


def get_document_visibility(
    db: Session,
    *,
    document_id: int,
    principal: Principal,
) -> tuple[bool, int | None]:
    """HR-side read of the Phase 7 sidecar flag (default-deny: a missing
    row reads as ``employee_visible = False``)."""
    doc = db.get(EmployeeDocument, document_id)
    if doc is None or not principal.can_access_company(doc.company_id):
        raise DocumentNotFoundError("Document not found")
    _require(principal, "employee_document.view", doc.company_id)
    visibility = db.execute(
        select(EmployeeDocumentVisibility).where(
            EmployeeDocumentVisibility.document_id == doc.id
        )
    ).scalar_one_or_none()
    if visibility is None:
        return False, None
    return bool(visibility.employee_visible), visibility.updated_by


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------


def my_attendance(
    db: Session,
    principal: Principal,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    page: PageParams | None = None,
) -> tuple[list[AttendanceRecord], int]:
    employee = _self_context(db, principal, "ess.attendance.view")
    stmt = select(AttendanceRecord).where(
        AttendanceRecord.employee_id == employee.id
    )
    count_stmt = select(func.count()).select_from(AttendanceRecord).where(
        AttendanceRecord.employee_id == employee.id
    )
    if date_from is not None:
        stmt = stmt.where(AttendanceRecord.work_date >= date_from)
        count_stmt = count_stmt.where(AttendanceRecord.work_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(AttendanceRecord.work_date <= date_to)
        count_stmt = count_stmt.where(AttendanceRecord.work_date <= date_to)
    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(
        AttendanceRecord.work_date.desc(), AttendanceRecord.id.desc()
    )
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


# ---------------------------------------------------------------------------
# Payslips (own, finalized periods only)
# ---------------------------------------------------------------------------


def _visible_lines(db: Session, employee: Employee):
    return (
        select(PayrollRunLine, PayrollRun, PayrollPeriod)
        .join(PayrollRun, PayrollRunLine.run_id == PayrollRun.id)
        .join(PayrollPeriod, PayrollRun.period_id == PayrollPeriod.id)
        .where(
            PayrollRunLine.employee_id == employee.id,
            PayrollPeriod.status.in_(VISIBLE_PERIOD_STATUSES),
        )
    )


def my_payslips(
    db: Session,
    principal: Principal,
    *,
    page: PageParams | None = None,
    ip: str | None = None,
) -> tuple[list[PayslipSummaryOut], int]:
    employee = _self_context(db, principal, "ess.payslip.view")
    base = _visible_lines(db, employee)
    total = int(
        db.execute(
            select(func.count()).select_from(base.subquery())
        ).scalar_one()
    )
    stmt = base.order_by(
        PayrollPeriod.period_end.desc(), PayrollRunLine.id.desc()
    )
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    rows = db.execute(stmt).all()
    items = [
        PayslipSummaryOut(
            id=line.id,
            run_id=line.run_id,
            employee_id=line.employee_id,
            basic_snapshot=line.basic_snapshot,
            currency=line.currency,
            earnings_total=line.earnings_total,
            deductions_total=line.deductions_total,
            net_pay=line.net_pay,
            run_number=run.run_number,
            period_id=period.id,
            period_name=period.name,
            period_start=period.period_start,
            period_end=period.period_end,
            period_status=period.status,
        )
        for line, run, period in rows
    ]
    record_audit(
        db,
        action="payslip.view",
        entity="employee",
        record_id=employee.id,
        actor_user_id=principal.user_id,
        company_id=employee.company_id,
        new_value={"scope": "list", "count": len(items)},
        ip_address=ip,
    )
    db.flush()
    return items, total


def _line_out(db: Session, line: PayrollRunLine) -> PayrollRunLineOut:
    out = PayrollRunLineOut.model_validate(line)
    payslip_lines = db.execute(
        select(PayslipLine)
        .where(PayslipLine.run_line_id == line.id)
        .order_by(PayslipLine.sort_order, PayslipLine.id)
    ).scalars()
    out.lines = [PayslipLineOut.model_validate(r) for r in payslip_lines]
    return out


def my_payslip(
    db: Session,
    *,
    run_line_id: int,
    principal: Principal,
    ip: str | None = None,
) -> PayslipOut:
    employee = _self_context(db, principal, "ess.payslip.view")
    line = db.get(PayrollRunLine, run_line_id)
    if line is None:
        raise NotFoundError("Payslip not found")
    if line.employee_id != employee.id:
        raise PayslipNotOwnError("This payslip does not belong to you")
    run = db.get(PayrollRun, line.run_id)
    if run is None or run.company_id != employee.company_id:
        raise NotFoundError("Payslip not found")
    period = db.get(PayrollPeriod, run.period_id)
    if period is None or period.status not in VISIBLE_PERIOD_STATUSES:
        raise NotFoundError("Payslip is not available yet")

    out = PayslipOut.model_validate(_line_out(db, line))
    out.run_status = run.status
    out.run_number = run.run_number
    out.inputs_hash = run.inputs_hash
    out.period_status = period.status
    out.period_start = period.period_start
    out.period_end = period.period_end

    record_audit(
        db,
        action="payslip.view",
        entity="payroll_run_line",
        record_id=line.id,
        actor_user_id=principal.user_id,
        company_id=employee.company_id,
        new_value={"period_status": period.status},
        ip_address=ip,
    )
    db.flush()
    return out
