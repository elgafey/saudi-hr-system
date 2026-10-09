"""Phase 9 HR letter core: content assembly + state machine + scoping.

Authorization model (permission codes only - no hardcoded role names,
always company-scoped):

- HR verbs: ``hr_letter.view`` (read), ``hr_letter.create`` (new drafts),
  ``hr_letter.update`` (edit/cancel drafts), ``hr_letter.issue``
  (draft -> issued), ``hr_letter.void`` (issued -> void, audit-sensitive).
- ESS: ``ess.letter.view`` gates the /me/letters routes; the service
  additionally scopes every read to the caller's own employee link.

State machine (Phase 9 design): draft -> issued -> void; draft ->
cancelled. State checks run BEFORE permission checks (Phase 8 pattern),
row fetches 404 for missing/cross-tenant rows. ``content`` is a closed
server-assembled snapshot (per-type schema, extra=forbid) built from
frozen sources at draft creation, rebuilt on language change, and
re-assembled + frozen at issue. Lists never return content. Audit
snapshots never include content (no salary values in the audit log).
"""

from __future__ import annotations

from datetime import datetime
from datetime import timezone as dt_timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.service import record_audit
from app.core.deps import Principal
from app.core.exceptions import (
    ConflictError,
    ForbiddenError,
    HrLetterEmployeeInvalidError,
    HrLetterForbiddenError,
    HrLetterNotFoundError,
    HrLetterReasonRequiredError,
    HrLetterRequestError,
    HrLetterRequestLinkedError,
    HrLetterSourceMissingError,
    HrLetterStateError,
)
from app.core.pagination import PageParams
from app.ess.service import self_employee
from app.letter.schemas import CONTENT_MODELS, LetterCreate, LetterUpdate
from app.shared.models import (
    Branch,
    Company,
    Department,
    Employee,
    EmployeeContract,
    EmployeeRequest,
    EmployeeSalaryAssignment,
    HrLetter,
    HrLetterEvent,
    JobPosition,
    User,
)


def _now() -> datetime:
    return datetime.now(dt_timezone.utc)


def _require(principal: Principal, code: str, company_id: int | None) -> None:
    """Company-scoped permission check (H1)."""
    if not principal.has_permission(code, company_id):
        raise HrLetterForbiddenError(f"Missing permission: {code}")


def _fetch_letter(
    db: Session, letter_id: int, principal: Principal, *, lock: bool = False
) -> HrLetter:
    stmt = select(HrLetter).where(HrLetter.id == letter_id)
    if lock:
        stmt = stmt.with_for_update()
    row = db.execute(stmt).scalar_one_or_none()
    if row is None or not principal.can_access_company(row.company_id):
        raise HrLetterNotFoundError("HR letter not found")
    return row


def _require_state(row: HrLetter, allowed: set[str], action: str) -> None:
    if row.status not in allowed:
        raise HrLetterStateError(
            f"Cannot {action} a letter in status '{row.status}'"
        )


# ---------------------------------------------------------------------------
# Content assembly (frozen sources -> closed per-type schema)
# ---------------------------------------------------------------------------


def _employee_name(employee: Employee, language: str) -> str:
    if language == "ar":
        parts = (
            employee.first_name_ar,
            employee.middle_name_ar,
            employee.last_name_ar,
        )
    else:
        parts = (
            employee.first_name_en,
            employee.middle_name_en,
            employee.last_name_en,
        )
    return " ".join(part for part in parts if part)


def _company_name(company: Company, language: str) -> str:
    localized = company.name_ar if language == "ar" else company.name_en
    return localized or company.name


def _dept_name(department: Department | None, language: str) -> str | None:
    if department is None:
        return None
    return department.name_ar if language == "ar" else department.name_en


def _position_name(position: JobPosition | None, language: str) -> str | None:
    if position is None:
        return None
    return position.name_ar if language == "ar" else position.name_en


def _branch_name(branch: Branch | None, language: str) -> str | None:
    if branch is None:
        return None
    if language == "ar":
        return branch.name_ar or branch.name
    return branch.name


def _active_contract(db: Session, employee_id: int) -> EmployeeContract | None:
    return db.execute(
        select(EmployeeContract).where(
            EmployeeContract.employee_id == employee_id,
            EmployeeContract.status == "active",
        )
    ).scalar_one_or_none()


def _active_assignment(
    db: Session, employee_id: int
) -> EmployeeSalaryAssignment | None:
    # One open row per employee is guaranteed by uq_salary_assignment_open.
    return db.execute(
        select(EmployeeSalaryAssignment).where(
            EmployeeSalaryAssignment.employee_id == employee_id,
            EmployeeSalaryAssignment.effective_to.is_(None),
        )
    ).scalar_one_or_none()


def _build_content(
    db: Session, *, letter_type: str, employee: Employee, language: str
) -> dict:
    """Assemble + validate the closed content snapshot for one letter type.

    Sources are read-only snapshots: companies, employees, contracts,
    departments, positions, branches, salary assignments. No calculations,
    no statutory values, no payroll writes. ``salary`` letters require an
    active salary assignment (HR_LETTER_SOURCE_MISSING otherwise).
    """
    company = db.get(Company, employee.company_id)
    if company is None:
        raise HrLetterSourceMissingError("The letter sources are unavailable")
    department = (
        db.get(Department, employee.department_id)
        if employee.department_id is not None
        else None
    )
    position = (
        db.get(JobPosition, employee.job_position_id)
        if employee.job_position_id is not None
        else None
    )
    branch = (
        db.get(Branch, employee.branch_id)
        if employee.branch_id is not None
        else None
    )
    contract = _active_contract(db, employee.id)

    data: dict = {
        "company_name": _company_name(company, language),
        "company_cr": company.commercial_registration_number,
        "company_address": company.address,
        "company_city": company.city,
        "employee_name": _employee_name(employee, language),
        "employee_number": employee.employee_number,
        "identity_number": employee.identity_number,
        "position": _position_name(position, language),
        "department": _dept_name(department, language),
        "branch": _branch_name(branch, language),
        "employment_type": employee.employment_type,
        "hire_date": employee.hire_date,
    }

    if letter_type == "employment":
        data.update(
            {
                "employment_status": employee.status,
                "contract_number": contract.contract_number if contract else None,
                "contract_start_date": contract.start_date if contract else None,
                "contract_end_date": contract.end_date if contract else None,
            }
        )
    elif letter_type == "salary":
        assignment = _active_assignment(db, employee.id)
        if assignment is None:
            raise HrLetterSourceMissingError(
                "The employee has no active salary assignment"
            )
        data.update(
            {
                "basic_salary": assignment.basic_salary,
                "currency": assignment.currency,
                "salary_effective_from": assignment.effective_from,
            }
        )
    elif letter_type == "experience":
        data.update(
            {
                "employment_status": employee.status,
                "contract_start_date": (
                    contract.start_date if contract else employee.hire_date
                ),
            }
        )
    elif letter_type == "work_address":
        data.update(
            {
                "branch_address": branch.address if branch else None,
                "branch_city": branch.city if branch else None,
            }
        )
    else:  # pragma: no cover - check constraints reject anything else
        raise HrLetterRequestError(f"Unsupported letter type '{letter_type}'")

    # Closed schema: extra=forbid, required fields enforced per type.
    model = CONTENT_MODELS[letter_type]
    return model(**data).model_dump(mode="json")


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
    row: HrLetter,
    principal: Principal,
    *,
    action: str,
    from_status: str | None,
    to_status: str,
    note: str | None = None,
    ip: str | None = None,
) -> None:
    db.add(
        HrLetterEvent(
            company_id=row.company_id,
            letter_id=row.id,
            action=action,
            from_status=from_status,
            to_status=to_status,
            actor_user_id=principal.user_id,
            actor_name=_actor_name(db, principal),
            note=(note[:500] if note else None),
            ip_address=ip,
        )
    )


def _snapshot(row: HrLetter) -> dict:
    """Audit snapshot - NEVER includes content (salary values stay out)."""
    return {
        "reference": row.reference,
        "employee_id": row.employee_id,
        "letter_type": row.letter_type,
        "language": row.language,
        "purpose": row.purpose,
        "status": row.status,
        "source_request_id": row.source_request_id,
        "issued_at": row.issued_at.isoformat() if row.issued_at else None,
        "cancelled_at": row.cancelled_at.isoformat() if row.cancelled_at else None,
        "voided_at": row.voided_at.isoformat() if row.voided_at else None,
        "version": row.version,
    }


def _audit(
    db: Session,
    *,
    action: str,
    row: HrLetter,
    principal: Principal,
    ip: str | None,
    old_value: dict | None = None,
) -> None:
    record_audit(
        db,
        action=action,
        entity="hr_letter",
        record_id=row.id,
        actor_user_id=principal.user_id,
        company_id=row.company_id,
        old_value=old_value,
        new_value=_snapshot(row),
        ip_address=ip,
    )


# ---------------------------------------------------------------------------
# Source request (Phase 7 approved hr_letter request)
# ---------------------------------------------------------------------------


def _validate_source_request(
    db: Session, source_request_id: int, *, company_id: int
) -> None:
    request = db.get(EmployeeRequest, source_request_id)
    if (
        request is None
        or request.company_id != company_id
        or request.request_type != "hr_letter"
        or request.status != "approved"
    ):
        raise HrLetterRequestError(
            "source_request_id must reference an approved hr_letter "
            "request in this company"
        )
    active = db.execute(
        select(HrLetter.id).where(
            HrLetter.source_request_id == source_request_id,
            HrLetter.status.in_(("draft", "issued")),
        )
    ).scalar_one_or_none()
    if active is not None:
        raise HrLetterRequestLinkedError(
            "An active letter already references this request"
        )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def _fetch_events(db: Session, letter_id: int) -> list[HrLetterEvent]:
    return list(
        db.execute(
            select(HrLetterEvent)
            .where(HrLetterEvent.letter_id == letter_id)
            .order_by(HrLetterEvent.id)
        ).scalars()
    )


def list_letters(
    db: Session,
    principal: Principal,
    *,
    company_id: int | None = None,
    employee_id: int | None = None,
    letter_type: str | None = None,
    status: str | None = None,
    page: PageParams | None = None,
) -> tuple[list[HrLetter], int]:
    """HR list: ``hr_letter.view`` scopes reads to the company (or to every
    membership company of the caller when no filter is given). Content is
    intentionally NOT part of the list projection."""
    stmt = select(HrLetter)
    count_stmt = select(func.count()).select_from(HrLetter)

    if company_id is not None:
        if not principal.can_access_company(company_id):
            raise ForbiddenError("You cannot access this company")
        _require(principal, "hr_letter.view", company_id)
        stmt = stmt.where(HrLetter.company_id == company_id)
        count_stmt = count_stmt.where(HrLetter.company_id == company_id)
    elif not principal.is_platform_admin:
        view_ids = principal.permitted_company_ids("hr_letter.view")
        if not view_ids:
            raise ForbiddenError("Missing permission: hr_letter.view")
        stmt = stmt.where(HrLetter.company_id.in_(view_ids))
        count_stmt = count_stmt.where(HrLetter.company_id.in_(view_ids))

    if employee_id is not None:
        stmt = stmt.where(HrLetter.employee_id == employee_id)
        count_stmt = count_stmt.where(HrLetter.employee_id == employee_id)
    if letter_type is not None:
        stmt = stmt.where(HrLetter.letter_type == letter_type)
        count_stmt = count_stmt.where(HrLetter.letter_type == letter_type)
    if status is not None:
        stmt = stmt.where(HrLetter.status == status)
        count_stmt = count_stmt.where(HrLetter.status == status)

    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(HrLetter.id.desc())
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


def get_letter_detail(
    db: Session, letter_id: int, principal: Principal
) -> tuple[HrLetter, list[HrLetterEvent]]:
    row = _fetch_letter(db, letter_id, principal)
    _require(principal, "hr_letter.view", row.company_id)
    return row, _fetch_events(db, row.id)


def list_own_letters(
    db: Session, principal: Principal, *, page: PageParams | None = None
) -> tuple[list[HrLetter], int]:
    """ESS list: always scoped to the caller's own employee link."""
    employee = self_employee(db, principal)
    stmt = select(HrLetter).where(HrLetter.employee_id == employee.id)
    count_stmt = (
        select(func.count())
        .select_from(HrLetter)
        .where(HrLetter.employee_id == employee.id)
    )
    total = int(db.execute(count_stmt).scalar_one())
    stmt = stmt.order_by(HrLetter.id.desc())
    if page is not None:
        stmt = stmt.limit(page.limit).offset(page.offset)
    return list(db.execute(stmt).scalars()), total


def get_own_letter_detail(
    db: Session, letter_id: int, principal: Principal
) -> tuple[HrLetter, list[HrLetterEvent]]:
    """ESS detail: non-owned letters 404 like missing ones (no leak)."""
    employee = self_employee(db, principal)
    row = db.get(HrLetter, letter_id)
    if (
        row is None
        or row.employee_id != employee.id
        or not principal.can_access_company(row.company_id)
    ):
        raise HrLetterNotFoundError("HR letter not found")
    return row, _fetch_events(db, row.id)


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


def create_letter(
    db: Session,
    *,
    payload: LetterCreate,
    principal: Principal,
    ip: str | None,
) -> HrLetter:
    employee = db.get(Employee, payload.employee_id)
    if employee is None or not principal.can_access_company(employee.company_id):
        raise HrLetterEmployeeInvalidError("Employee not found")
    _require(principal, "hr_letter.create", employee.company_id)
    if employee.status != "active":
        raise HrLetterEmployeeInvalidError(
            "Letters are only available for active employees"
        )
    if payload.source_request_id is not None:
        _validate_source_request(
            db, payload.source_request_id, company_id=employee.company_id
        )

    content = _build_content(
        db,
        letter_type=payload.letter_type,
        employee=employee,
        language=payload.language,
    )
    row = HrLetter(
        company_id=employee.company_id,
        employee_id=employee.id,
        letter_type=payload.letter_type,
        language=payload.language,
        purpose=(payload.purpose.strip() if payload.purpose else None),
        status="draft",
        content=content,
        source_request_id=payload.source_request_id,
        created_by=principal.user_id,
        version=1,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        if "uq_hr_letter_active_request" in str(exc.orig):
            raise HrLetterRequestLinkedError(
                "An active letter already references this request"
            ) from exc
        raise ConflictError("HR letter could not be created") from exc

    _add_event(
        db,
        row,
        principal,
        action="created",
        from_status=None,
        to_status="draft",
        ip=ip,
    )
    _audit(db, action="hr_letter.create", row=row, principal=principal, ip=ip)
    db.flush()
    return row


def update_letter(
    db: Session,
    *,
    letter_id: int,
    payload: LetterUpdate,
    principal: Principal,
    ip: str | None,
) -> HrLetter:
    row = _fetch_letter(db, letter_id, principal, lock=True)
    _require_state(row, {"draft"}, "update")
    _require(principal, "hr_letter.update", row.company_id)

    old = _snapshot(row)
    language_changed = (
        payload.language is not None and payload.language != row.language
    )
    if payload.purpose is not None:
        row.purpose = payload.purpose.strip() or None
    if language_changed:
        row.language = payload.language
        employee = db.get(Employee, row.employee_id)
        if employee is None:
            raise HrLetterSourceMissingError("The letter sources are unavailable")
        row.content = _build_content(
            db,
            letter_type=row.letter_type,
            employee=employee,
            language=row.language,
        )
    row.updated_by = principal.user_id
    row.version += 1

    db.add(row)
    db.flush()
    _add_event(
        db,
        row,
        principal,
        action="updated",
        from_status="draft",
        to_status="draft",
        ip=ip,
    )
    _audit(
        db,
        action="hr_letter.update",
        row=row,
        principal=principal,
        ip=ip,
        old_value=old,
    )
    db.flush()
    return row


def cancel_letter(
    db: Session,
    *,
    letter_id: int,
    reason: str | None,
    principal: Principal,
    ip: str | None,
) -> HrLetter:
    row = _fetch_letter(db, letter_id, principal, lock=True)
    _require_state(row, {"draft"}, "cancel")
    _require(principal, "hr_letter.update", row.company_id)

    old = _snapshot(row)
    cleaned = reason.strip() if reason and reason.strip() else None
    row.status = "cancelled"
    row.cancelled_at = _now()
    row.cancelled_by = principal.user_id
    row.cancel_reason = cleaned
    row.updated_by = principal.user_id
    row.version += 1

    db.add(row)
    db.flush()
    _add_event(
        db,
        row,
        principal,
        action="cancelled",
        from_status="draft",
        to_status="cancelled",
        note=cleaned,
        ip=ip,
    )
    _audit(
        db,
        action="hr_letter.cancel",
        row=row,
        principal=principal,
        ip=ip,
        old_value=old,
    )
    db.flush()
    return row


def issue_letter(
    db: Session,
    *,
    letter_id: int,
    principal: Principal,
    ip: str | None,
) -> HrLetter:
    row = _fetch_letter(db, letter_id, principal, lock=True)
    _require_state(row, {"draft"}, "issue")
    _require(principal, "hr_letter.issue", row.company_id)

    employee = db.get(Employee, row.employee_id)
    if (
        employee is None
        or not principal.can_access_company(employee.company_id)
        or employee.status != "active"
    ):
        raise HrLetterSourceMissingError(
            "The letter's source employee is no longer available"
        )
    # Re-assemble from frozen sources at issue; frozen forever after.
    content = _build_content(
        db, letter_type=row.letter_type, employee=employee, language=row.language
    )

    old = _snapshot(row)
    row.content = content
    row.status = "issued"
    row.issued_at = _now()
    row.issued_by = principal.user_id
    row.updated_by = principal.user_id
    row.version += 1

    db.add(row)
    db.flush()
    _add_event(
        db,
        row,
        principal,
        action="issued",
        from_status="draft",
        to_status="issued",
        ip=ip,
    )
    _audit(
        db,
        action="hr_letter.issue",
        row=row,
        principal=principal,
        ip=ip,
        old_value=old,
    )
    db.flush()
    return row


def void_letter(
    db: Session,
    *,
    letter_id: int,
    reason: str | None,
    principal: Principal,
    ip: str | None,
) -> HrLetter:
    row = _fetch_letter(db, letter_id, principal, lock=True)
    _require_state(row, {"issued"}, "void")
    _require(principal, "hr_letter.void", row.company_id)
    cleaned = reason.strip() if reason and reason.strip() else None
    if not cleaned:
        raise HrLetterReasonRequiredError("A reason is required to void a letter")

    old = _snapshot(row)
    row.status = "void"
    row.voided_at = _now()
    row.voided_by = principal.user_id
    row.void_reason = cleaned
    row.updated_by = principal.user_id
    row.version += 1

    db.add(row)
    db.flush()
    _add_event(
        db,
        row,
        principal,
        action="voided",
        from_status="issued",
        to_status="void",
        note=cleaned,
        ip=ip,
    )
    _audit(
        db,
        action="hr_letter.void",
        row=row,
        principal=principal,
        ip=ip,
        old_value=old,
    )
    db.flush()
    return row
