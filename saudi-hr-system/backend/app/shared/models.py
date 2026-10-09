from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.rls import company_scoped
from app.shared.base import Base, TimestampMixin


class Company(Base, TimestampMixin):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_ar: Mapped[str | None] = mapped_column(String(255))
    name_en: Mapped[str | None] = mapped_column(String(255))
    commercial_registration_number: Mapped[str | None] = mapped_column(String(64))
    tax_number: Mapped[str | None] = mapped_column(String(64))
    address: Mapped[str | None] = mapped_column(String(500))
    city: Mapped[str | None] = mapped_column(String(128))
    country: Mapped[str] = mapped_column(String(2), default="SA", nullable=False)
    default_currency: Mapped[str] = mapped_column(
        String(3), default="SAR", nullable=False
    )
    timezone: Mapped[str] = mapped_column(
        String(64), default="Asia/Riyadh", nullable=False
    )
    working_week: Mapped[str] = mapped_column(
        String(64),
        default="sun-thu",
        nullable=False,
    )
    logo_path: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(
        String(20), default="active", nullable=False
    )


class Branch(Base, TimestampMixin):
    __tablename__ = "branches"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_branch_company_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_ar: Mapped[str | None] = mapped_column(String(255))
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    address: Mapped[str | None] = mapped_column(String(500))
    city: Mapped[str | None] = mapped_column(String(128))
    manager_id: Mapped[int | None] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(
        String(20), default="active", nullable=False
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_platform_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    # Phase 3: explicit employee <-> user account link (unique both ways;
    # one user account per employee and vice versa). Accounts are linked
    # only through the controlled API - never automatically.
    employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"),
        unique=True,
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Role(Base, TimestampMixin):
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_role_company_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    module: Mapped[str] = mapped_column(String(50), nullable=False, index=True)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint(
            "role_id", "permission_id", name="uq_role_permission"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    permission_id: Mapped[int] = mapped_column(
        ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "role_id", "company_id", name="uq_user_role_company"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )


class Department(Base, TimestampMixin):
    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_department_company_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name_ar: Mapped[str] = mapped_column(String(255), nullable=False)
    name_en: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(
        String(20), default="active", nullable=False
    )


class JobPosition(Base, TimestampMixin):
    __tablename__ = "job_positions"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_job_position_company_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name_ar: Mapped[str] = mapped_column(String(255), nullable=False)
    name_en: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(
        String(20), default="active", nullable=False
    )


class JobGrade(Base, TimestampMixin):
    __tablename__ = "job_grades"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_job_grade_company_code"),
        UniqueConstraint("company_id", "level", name="uq_job_grade_company_level"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name_ar: Mapped[str] = mapped_column(String(255), nullable=False)
    name_en: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="active", nullable=False
    )


class Employee(Base, TimestampMixin):
    __tablename__ = "employees"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "employee_number", name="uq_employee_company_number"
        ),
        UniqueConstraint(
            "company_id", "identity_number", name="uq_employee_company_identity"
        ),
        UniqueConstraint(
            "company_id", "work_email", name="uq_employee_company_work_email"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    branch_id: Mapped[int | None] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), index=True
    )
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    job_position_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_positions.id", ondelete="RESTRICT"), index=True
    )
    job_grade_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_grades.id", ondelete="RESTRICT"), index=True
    )
    manager_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), index=True
    )
    employee_number: Mapped[str] = mapped_column(String(50), nullable=False)
    first_name_ar: Mapped[str] = mapped_column(String(100), nullable=False)
    middle_name_ar: Mapped[str | None] = mapped_column(String(100))
    last_name_ar: Mapped[str] = mapped_column(String(100), nullable=False)
    first_name_en: Mapped[str] = mapped_column(String(100), nullable=False)
    middle_name_en: Mapped[str | None] = mapped_column(String(100))
    last_name_en: Mapped[str] = mapped_column(String(100), nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    gender: Mapped[str | None] = mapped_column(String(10))
    nationality: Mapped[str] = mapped_column(
        String(2), default="SA", nullable=False
    )
    # personal_email is intentionally NOT unique (see migration 0003 docstring).
    personal_email: Mapped[str | None] = mapped_column(String(255))
    work_email: Mapped[str | None] = mapped_column(String(255))
    mobile_phone: Mapped[str | None] = mapped_column(String(32))
    emergency_contact_name: Mapped[str | None] = mapped_column(String(255))
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(32))
    identity_type: Mapped[str | None] = mapped_column(String(20))
    identity_number: Mapped[str | None] = mapped_column(String(50))
    identity_issue_date: Mapped[date | None] = mapped_column(Date)
    identity_expiry_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        String(20), default="draft", nullable=False
    )
    employment_type: Mapped[str] = mapped_column(
        String(20), default="full_time", nullable=False
    )
    hire_date: Mapped[date | None] = mapped_column(Date)
    probation_end_date: Mapped[date | None] = mapped_column(Date)
    termination_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------------------
# Phase 3 - employee lifecycle
# ---------------------------------------------------------------------------


class EmployeeDocumentType(Base, TimestampMixin):
    """Company-configurable document type lookup (bilingual names)."""

    __tablename__ = "employee_document_types"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "code", name="uq_employee_document_type_company_code"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name_ar: Mapped[str] = mapped_column(String(255), nullable=False)
    name_en: Mapped[str] = mapped_column(String(255), nullable=False)
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )


class EmployeeDocument(Base, TimestampMixin):
    """Uploaded employee document metadata. Bytes live in private storage
    under a server-generated ``storage_key``; ``file_name`` is display-only."""

    __tablename__ = "employee_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_type_id: Mapped[int] = mapped_column(
        ForeignKey("employee_document_types.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    document_number: Mapped[str | None] = mapped_column(String(50))
    issue_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class EmployeeContract(Base, TimestampMixin):
    """Employment contract. One ACTIVE contract per employee is enforced by
    a partial unique index (documented Phase 3 business rule); draft /
    expired / terminated contracts may coexist. ``basic_salary`` is the
    contractual basic pay kept safe for the future payroll phase (Phase 6
    reads it; this phase performs no calculations)."""

    __tablename__ = "employee_contracts"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "contract_number",
            name="uq_employee_contract_company_number",
        ),
        CheckConstraint(
            "status IN ('draft','active','expired','terminated','cancelled')",
            name="ck_employee_contract_status",
        ),
        CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name="ck_employee_contract_end_after_start",
        ),
        CheckConstraint(
            "termination_date IS NULL OR termination_date >= start_date",
            name="ck_employee_contract_termination_after_start",
        ),
        CheckConstraint(
            "end_date IS NULL OR termination_date IS NULL "
            "OR termination_date <= end_date",
            name="ck_employee_contract_termination_within_term",
        ),
        Index(
            "uq_employee_contract_active",
            "employee_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contract_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="draft", nullable=False
    )
    contract_number: Mapped[str | None] = mapped_column(String(50))
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    signed_date: Mapped[date | None] = mapped_column(Date)
    termination_date: Mapped[date | None] = mapped_column(Date)
    termination_reason: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)
    # Future payroll (Phase 6) reads the contracted basic pay directly from
    # the active contract - single source of truth, no payroll logic here.
    basic_salary: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="SAR", nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class EmployeeEmploymentHistory(Base, TimestampMixin):
    """Append-only, effective-dated employment history.

    Overlapping ranges for the same employee are prevented in the service
    layer (precise, stable error codes) and backed by PostgreSQL-native
    constraints created in migration 0004:

    - a partial unique index guarantees at most ONE open record
      (``effective_to IS NULL``) per employee;
    - an EXCLUDE USING gist constraint on
      ``daterange(effective_from, effective_to, '[)')`` rejects any
      overlapping range (requires btree_gist, created by the migration).
    """

    __tablename__ = "employee_employment_history"
    __table_args__ = (
        Index(
            "uq_employee_history_open",
            "employee_id",
            unique=True,
            postgresql_where=text("effective_to IS NULL"),
        ),
        Index(
            "ix_employee_history_effective",
            "employee_id",
            "effective_from",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    branch_id: Mapped[int | None] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), index=True
    )
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    position_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_positions.id", ondelete="RESTRICT"), index=True
    )
    grade_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_grades.id", ondelete="RESTRICT"), index=True
    )
    manager_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), index=True
    )
    employment_status: Mapped[str] = mapped_column(String(20), nullable=False)
    employment_type: Mapped[str] = mapped_column(String(20), nullable=False)
    change_reason: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


# ---------------------------------------------------------------------------
# Phase 4 - work schedules, shifts, assignments, attendance, overtime
# ---------------------------------------------------------------------------


class WorkSchedule(Base, TimestampMixin):
    """Company work-schedule template, versioned by an applicability window.

    ``timezone`` is per-schedule (default ``Asia/Riyadh``) - the whole
    attendance domain interprets naive ``Time`` values in this timezone and
    stores instants as timezone-aware UTC. The same ``code`` may exist in
    several non-overlapping windows (schedule versioning); overlapping
    windows for one code are rejected by an EXCLUDE constraint created in
    migration 0005.
    """

    __tablename__ = "work_schedules"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "code",
            "effective_from",
            name="uq_work_schedule_company_code_from",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_work_schedule_date_range",
        ),
        CheckConstraint(
            "status IN ('active','archived')",
            name="ck_work_schedule_status",
        ),
        Index(
            "ix_work_schedule_company_code",
            "company_id",
            "code",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name_ar: Mapped[str] = mapped_column(String(255), nullable=False)
    name_en: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(
        String(64), default="Asia/Riyadh", nullable=False
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        String(20), default="active", nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class Shift(Base, TimestampMixin):
    """Named shift with a naive daily window.

    ``crosses_midnight`` is computed by the service (``end < start`` means
    the shift runs into the next calendar day, e.g. 22:00 -> 06:00). Zero
    duration windows (``start == end``) are rejected by CHECK.
    """

    __tablename__ = "shifts"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_shift_company_code"),
        CheckConstraint("start_time <> end_time", name="ck_shift_time_range"),
        CheckConstraint(
            "status IN ('active','archived')", name="ck_shift_status"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name_ar: Mapped[str] = mapped_column(String(255), nullable=False)
    name_en: Mapped[str] = mapped_column(String(255), nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    crosses_midnight: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default="active", nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class WorkScheduleDay(Base, TimestampMixin):
    """Per-weekday rule of a schedule (ISO weekday: Monday=0 ... Sunday=6).

    A day either carries a plain working window (``start_time``/``end_time``,
    ``end < start`` = overnight day) or pins a named ``shift`` for that
    weekday - one row per weekday, ``is_working`` marks rest days.
    """

    __tablename__ = "work_schedule_days"
    __table_args__ = (
        UniqueConstraint(
            "schedule_id", "weekday", name="uq_work_schedule_day_weekday"
        ),
        CheckConstraint(
            "(start_time IS NULL) = (end_time IS NULL)",
            name="ck_work_schedule_day_times_both_or_neither",
        ),
        CheckConstraint(
            "start_time IS NULL OR start_time <> end_time",
            name="ck_work_schedule_day_time_range",
        ),
        CheckConstraint(
            "weekday BETWEEN 0 AND 6", name="ck_work_schedule_day_weekday"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    schedule_id: Mapped[int] = mapped_column(
        ForeignKey("work_schedules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    is_working: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    start_time: Mapped[time | None] = mapped_column(Time)
    end_time: Mapped[time | None] = mapped_column(Time)
    shift_id: Mapped[int | None] = mapped_column(
        ForeignKey("shifts.id", ondelete="SET NULL"), index=True
    )


class BreakPeriod(Base, TimestampMixin):
    """Rest/break window owned by exactly ONE parent: a schedule day XOR a
    shift. Multiple breaks per parent are supported from day one (the
    calculation service sums every unpaid break inside the window)."""

    __tablename__ = "break_periods"
    __table_args__ = (
        CheckConstraint(
            "start_time <> end_time", name="ck_break_period_time_range"
        ),
        CheckConstraint(
            "num_nonnulls(schedule_day_id, shift_id) = 1",
            name="ck_break_period_single_parent",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    schedule_day_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_schedule_days.id", ondelete="CASCADE"), index=True
    )
    shift_id: Mapped[int | None] = mapped_column(
        ForeignKey("shifts.id", ondelete="CASCADE"), index=True
    )
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class EmployeeWorkAssignment(Base, TimestampMixin):
    """Effective-dated schedule assignment for an employee.

    At most ONE open (``effective_to IS NULL``) assignment per employee is
    enforced by a partial unique index; any overlapping ranges are rejected
    by an EXCLUDE constraint (btree_gist) created in migration 0005.
    ``shift_id`` optionally overrides the schedule's weekday shift.
    """

    __tablename__ = "employee_work_assignments"
    __table_args__ = (
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_work_assignment_date_range",
        ),
        Index(
            "uq_work_assignment_open",
            "employee_id",
            unique=True,
            postgresql_where=text("effective_to IS NULL"),
        ),
        Index(
            "ix_work_assignment_employee_effective",
            "employee_id",
            "effective_from",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    schedule_id: Mapped[int] = mapped_column(
        ForeignKey("work_schedules.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    shift_id: Mapped[int | None] = mapped_column(
        ForeignKey("shifts.id", ondelete="SET NULL"), index=True
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class AttendanceRecord(Base, TimestampMixin):
    """One attendance day for an employee.

    Timestamps are timezone-aware (stored UTC, serialized ISO-8601 UTC).
    ``work_date`` is the attendance date derived from ``check_in`` in the
    owning schedule's timezone (fallback: company timezone). Minute columns
    are computed at check-out (manual close) and stay NULL while the record
    is open. DB-level guarantees: one OPEN record per employee (partial
    unique index) and no overlapping known windows (EXCLUDE constraint,
    created in migration 0005).
    """

    __tablename__ = "attendance_records"
    __table_args__ = (
        CheckConstraint(
            "check_out IS NULL OR check_out > check_in",
            name="ck_attendance_time_range",
        ),
        CheckConstraint(
            "status <> 'completed' OR check_out IS NOT NULL",
            name="ck_attendance_completed_has_checkout",
        ),
        CheckConstraint(
            "status IN ('open','completed','missing_checkout')",
            name="ck_attendance_status",
        ),
        CheckConstraint(
            "source IN ('manual','device','import','api')",
            name="ck_attendance_source",
        ),
        Index(
            "uq_attendance_open",
            "employee_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        # Company date-range scans (list endpoint date_from/date_to filters).
        Index("ix_attendance_company_work_date", "company_id", "work_date"),
        # Per-employee timeline (employee detail tab, overlap pre-checks).
        Index("ix_attendance_employee_checkin", "employee_id", "check_in"),
        # "Open right now" dashboard queries avoid scanning closed history.
        Index(
            "ix_attendance_company_open",
            "company_id",
            postgresql_where=text("status = 'open'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    schedule_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_schedules.id", ondelete="SET NULL"), index=True
    )
    shift_id: Mapped[int | None] = mapped_column(
        ForeignKey("shifts.id", ondelete="SET NULL"), index=True
    )
    check_in: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    check_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(20), default="open", nullable=False
    )
    source: Mapped[str] = mapped_column(
        String(20), default="manual", nullable=False
    )
    # Computed at close; NULL while the record is open.
    scheduled_minutes: Mapped[int | None] = mapped_column(Integer)
    worked_minutes: Mapped[int | None] = mapped_column(Integer)
    break_minutes: Mapped[int | None] = mapped_column(Integer)
    late_minutes: Mapped[int | None] = mapped_column(Integer)
    early_leave_minutes: Mapped[int | None] = mapped_column(Integer)
    overtime_candidate_minutes: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    correction_reason: Mapped[str | None] = mapped_column(String(500))
    corrected_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class OvertimeRecord(Base, TimestampMixin):
    """Overtime request with a draft -> submitted -> approved/rejected
    workflow. ``requested_minutes`` (candidate) and ``approved_minutes``
    are deliberately separate; NO monetary amount is ever computed here
    (Phase 6 payroll consumes the approved minutes)."""

    __tablename__ = "overtime_records"
    __table_args__ = (
        CheckConstraint(
            "requested_minutes > 0 AND requested_minutes <= 1440",
            name="ck_overtime_requested_minutes",
        ),
        CheckConstraint(
            "approved_minutes IS NULL OR "
            "(approved_minutes > 0 AND approved_minutes <= requested_minutes)",
            name="ck_overtime_approved_minutes",
        ),
        CheckConstraint(
            "status IN ('draft','submitted','approved','rejected','cancelled')",
            name="ck_overtime_status",
        ),
        Index(
            "ix_overtime_company_status_date",
            "company_id",
            "status",
            "work_date",
        ),
        Index("ix_overtime_employee_date", "employee_id", "work_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attendance_id: Mapped[int | None] = mapped_column(
        ForeignKey("attendance_records.id", ondelete="SET NULL"), index=True
    )
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    requested_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    approved_minutes: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(20), default="draft", nullable=False
    )
    reason: Mapped[str | None] = mapped_column(String(500))
    decision_reason: Mapped[str | None] = mapped_column(String(500))
    decided_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    correction_reason: Mapped[str | None] = mapped_column(String(500))
    corrected_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )



# ---------------------------------------------------------------------------
# Phase 5 - leave management (migration 0006_phase5_leave_management).
#
# Balances are DERIVED from leave_allocations + leave_consumptions +
# leave_requests; there is deliberately NO leave_balances table (see
# docs/PHASE5.md). used_days is a lock-protected denormalized optimization.
# No Saudi statutory entitlement values are stored here or seeded anywhere:
# leave_statutory_rules rows are company-configured and must carry a
# source_reference plus effective_from (DB CHECK enforced).
# ---------------------------------------------------------------------------


class CompanyHoliday(Base, TimestampMixin):
    """Company holiday calendar entry (single date).

    Used by the leave day-counting engine to exclude non-working days and
    (later) by payroll reporting. No legal/public-holiday values are seeded;
    companies maintain their own calendar.
    """

    __tablename__ = "company_holidays"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "date", name="uq_company_holiday_company_date"
        ),
        CheckConstraint(
            "status IN ('active','inactive')", name="ck_company_holiday_status"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name_ar: Mapped[str] = mapped_column(String(255), nullable=False)
    name_en: Mapped[str] = mapped_column(String(255), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="active", nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class LeaveType(Base, TimestampMixin):
    """Company leave type configuration.

    Everything is configurable per company: paid/unpaid, approval
    requirement, attachment rules, carry-forward rules, allowance treatment
    (Phase 6 payroll input) and day-counting mode. ``statutory_key`` only
    LINKS a type to versioned ``leave_statutory_rules`` entries - no legal
    value lives in code or in this row's schema.
    """

    __tablename__ = "leave_types"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_leave_type_company_code"),
        CheckConstraint(
            "status IN ('active','inactive')", name="ck_leave_type_status"
        ),
        CheckConstraint(
            "day_counting_mode IN ('working_days','calendar_days')",
            name="ck_leave_type_day_counting_mode",
        ),
        CheckConstraint(
            "allowance_treatment IN ('continue','deduct','prorate')",
            name="ck_leave_type_allowance_treatment",
        ),
        CheckConstraint(
            "carry_forward_expiry IN ('none','end_of_year','end_of_next_year')",
            name="ck_leave_type_carry_forward_expiry",
        ),
        CheckConstraint(
            "min_request_days IS NULL OR min_request_days > 0",
            name="ck_leave_type_min_request_days",
        ),
        CheckConstraint(
            "max_request_days IS NULL OR max_request_days > 0",
            name="ck_leave_type_max_request_days",
        ),
        CheckConstraint(
            "min_request_days IS NULL OR max_request_days IS NULL "
            "OR min_request_days <= max_request_days",
            name="ck_leave_type_request_days_range",
        ),
        CheckConstraint(
            "default_entitlement_days IS NULL OR default_entitlement_days >= 0",
            name="ck_leave_type_default_entitlement",
        ),
        CheckConstraint(
            "carry_forward_max_days IS NULL OR carry_forward_max_days >= 0",
            name="ck_leave_type_carry_forward_max",
        ),
        CheckConstraint(
            "attachment_threshold_days IS NULL OR attachment_threshold_days > 0",
            name="ck_leave_type_attachment_threshold",
        ),
        Index("ix_leave_type_company_status", "company_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name_ar: Mapped[str] = mapped_column(String(255), nullable=False)
    name_en: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    is_paid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    requires_approval: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    allocation_requires_approval: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    day_counting_mode: Mapped[str] = mapped_column(
        String(20), default="working_days", nullable=False
    )
    requires_attachment: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    attachment_threshold_days: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    requires_reason: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    negative_balance_allowed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    min_request_days: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    max_request_days: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    default_entitlement_days: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    carry_forward_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    carry_forward_max_days: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    carry_forward_expiry: Mapped[str] = mapped_column(
        String(25), default="end_of_next_year", nullable=False
    )
    allowance_treatment: Mapped[str] = mapped_column(
        String(15), default="continue", nullable=False
    )
    is_statutory: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    statutory_key: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class LeaveStatutoryRule(Base, TimestampMixin):
    """Versioned, company-configured statutory leave rule.

    Legal values are NEVER hardcoded or seeded: every row must carry a
    ``source_reference`` (citation) and ``effective_from`` date (both DB
    CHECK enforced) and starts with ``requires_legal_verification = true``.
    Versions are immutable - a change inserts a new version; the row
    effective on a given date wins. ``rule_json`` holds entitlement /
    eligibility / pay-structure data as configured by the company.
    """

    __tablename__ = "leave_statutory_rules"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "statutory_key",
            "version",
            name="uq_leave_statutory_rule_version",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_leave_statutory_rule_dates",
        ),
        CheckConstraint(
            "status IN ('active','inactive')",
            name="ck_leave_statutory_rule_status",
        ),
        CheckConstraint(
            "length(trim(source_reference)) > 0",
            name="ck_leave_statutory_rule_source",
        ),
        # Non-overlapping effective windows per (company, statutory_key) are
        # enforced by an EXCLUDE constraint created in migration 0006.
        Index(
            "ix_leave_statutory_rule_company_key",
            "company_id",
            "statutory_key",
            "effective_from",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    statutory_key: Mapped[str] = mapped_column(String(50), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(
        String(20), default="SA", nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    rule_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    source_date: Mapped[date | None] = mapped_column(Date)
    requires_legal_verification: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class LeaveAllocation(Base, TimestampMixin):
    """Entitlement granted to an employee for one leave type over a period.

    ``used_days`` is written ONLY by the balance engine under
    ``SELECT ... FOR UPDATE`` (deterministic period_start/id order).
    Overlapping periods for the same (employee, leave type) are rejected by
    an EXCLUDE constraint created in migration 0006; a carry-forward row
    points at exactly one source allocation (partial unique index).
    """

    __tablename__ = "leave_allocations"
    __table_args__ = (
        CheckConstraint(
            "period_end >= period_start", name="ck_leave_allocation_period"
        ),
        CheckConstraint(
            "allocated_days > 0", name="ck_leave_allocation_allocated_days"
        ),
        CheckConstraint(
            "used_days >= 0", name="ck_leave_allocation_used_days"
        ),
        CheckConstraint(
            "status IN ('submitted','approved','rejected','revoked')",
            name="ck_leave_allocation_status",
        ),
        CheckConstraint(
            "source IN ('manual','generate','carry_forward','statutory')",
            name="ck_leave_allocation_source",
        ),
        # Period overlap for the same employee+type is an EXCLUDE constraint
        # (exq_leave_allocation_no_overlap) created in migration 0006.
        Index(
            "ix_leave_allocation_employee_type",
            "employee_id",
            "leave_type_id",
            "period_start",
        ),
        Index("ix_leave_allocation_company_status", "company_id", "status"),
        # A carry-forward row may point at a given source allocation once.
        Index(
            "uq_leave_allocation_carried_from",
            "carried_from_id",
            unique=True,
            postgresql_where=text("carried_from_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    leave_type_id: Mapped[int] = mapped_column(
        ForeignKey("leave_types.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    allocated_days: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    used_days: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=0, nullable=False
    )
    source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    carried_from_id: Mapped[int | None] = mapped_column(
        ForeignKey("leave_allocations.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default="approved", nullable=False
    )
    reason: Mapped[str | None] = mapped_column(Text)
    decision_reason: Mapped[str | None] = mapped_column(String(500))
    approved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class LeaveRequest(Base, TimestampMixin):
    """Leave request with a draft -> submitted -> approved/rejected/cancelled
    workflow.

    ``days`` and ``count_details`` are snapshots computed by the shared
    day-counting engine at create/update/submit time (rest days, holidays
    and the mode used are recorded per date for audit and Phase 6 payroll).
    Overlapping SUBMITTED/APPROVED ranges for the same employee are rejected
    by an EXCLUDE constraint created in migration 0006.
    """

    __tablename__ = "leave_requests"
    __table_args__ = (
        CheckConstraint(
            "end_date >= start_date", name="ck_leave_request_dates"
        ),
        CheckConstraint(
            "(start_time IS NULL) = (end_time IS NULL)",
            name="ck_leave_request_times_both_or_neither",
        ),
        CheckConstraint(
            "start_time IS NULL OR start_date = end_date",
            name="ck_leave_request_times_single_day",
        ),
        CheckConstraint("days > 0", name="ck_leave_request_days"),
        CheckConstraint(
            "status IN ('draft','submitted','approved','rejected','cancelled')",
            name="ck_leave_request_status",
        ),
        Index("ix_leave_request_company_start", "company_id", "start_date"),
        Index("ix_leave_request_employee_start", "employee_id", "start_date"),
        Index("ix_leave_request_company_status", "company_id", "status"),
        Index("ix_leave_request_company_type", "company_id", "leave_type_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    leave_type_id: Mapped[int] = mapped_column(
        ForeignKey("leave_types.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Same-day partial leave only (DB CHECK enforces start_date = end_date).
    start_time: Mapped[time | None] = mapped_column(Time)
    end_time: Mapped[time | None] = mapped_column(Time)
    days: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    # Single optional attachment (storage key + metadata), Phase 5 scope.
    attachment_path: Mapped[str | None] = mapped_column(String(500))
    attachment_name: Mapped[str | None] = mapped_column(String(255))
    attachment_mime: Mapped[str | None] = mapped_column(String(100))
    attachment_size: Mapped[int | None] = mapped_column(Integer)
    attachment_uploaded_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    count_details: Mapped[dict | None] = mapped_column(JSONB)
    submitted_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(String(500))
    cancelled_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class LeaveConsumption(Base, TimestampMixin):
    """FIFO draw-down of one allocation by one approved leave request.

    Rows exist only while the owning request is APPROVED; cancelling the
    request deletes them and restores ``leave_allocations.used_days`` (both
    inside the same transaction, allocations locked in period_start/id order).
    """

    __tablename__ = "leave_consumptions"
    __table_args__ = (
        CheckConstraint("days > 0", name="ck_leave_consumption_days"),
        Index("ix_leave_consumption_allocation", "leave_allocation_id"),
        Index("ix_leave_consumption_request", "leave_request_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    leave_request_id: Mapped[int] = mapped_column(
        ForeignKey("leave_requests.id", ondelete="CASCADE"), nullable=False
    )
    leave_allocation_id: Mapped[int] = mapped_column(
        ForeignKey("leave_allocations.id", ondelete="RESTRICT"), nullable=False
    )
    days: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    for_date: Mapped[date | None] = mapped_column(Date)


# ---------------------------------------------------------------------------
# Phase 6 - payroll & salary management
# ---------------------------------------------------------------------------


class SalaryComponent(Base, TimestampMixin):
    """Named payroll component bucket (earning / deduction / employer
    contribution).

    ``calculation_basis`` is a CLOSED vocabulary resolved by the payroll
    engine - never a stored expression (no eval/exec, no code in the DB).
    ``statutory`` components take their rate from a versioned
    ``payroll_statutory_rules`` row; no legal value is stored here.
    """

    __tablename__ = "salary_components"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "code", name="uq_salary_component_company_code"
        ),
        CheckConstraint(
            "category IN ('earning','deduction','employer_contribution')",
            name="ck_salary_component_category",
        ),
        CheckConstraint(
            "calculation_basis IN ('fixed','percent_of_basic','engine_derived')",
            name="ck_salary_component_basis",
        ),
        CheckConstraint(
            "default_amount IS NULL OR default_amount >= 0",
            name="ck_salary_component_amount",
        ),
        CheckConstraint(
            "default_rate IS NULL OR default_rate > 0",
            name="ck_salary_component_rate",
        ),
        CheckConstraint(
            "status IN ('active','inactive')", name="ck_salary_component_status"
        ),
        CheckConstraint(
            "length(trim(code)) > 0", name="ck_salary_component_code"
        ),
        Index(
            "ix_salary_component_company_status",
            "company_id",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name_ar: Mapped[str] = mapped_column(String(255), nullable=False)
    name_en: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    calculation_basis: Mapped[str] = mapped_column(String(30), nullable=False)
    default_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    default_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    is_statutory: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    statutory_key: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class EmployeeSalaryAssignment(Base, TimestampMixin):
    """Effective-dated salary history - the payroll source of truth for pay.

    Overlapping windows per employee are rejected by an EXCLUDE constraint
    created in migration 0007; at most one row may stay open (partial
    unique index). Historical rows are never overwritten: a raise is a NEW
    row, so approved payroll keeps its snapshot (docs/PHASE6.md).
    ``EmployeeContract.basic_salary`` only seeds the first row.
    """

    __tablename__ = "employee_salary_assignments"
    __table_args__ = (
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_salary_assignment_dates",
        ),
        CheckConstraint(
            "basic_salary >= 0", name="ck_salary_assignment_basic_salary"
        ),
        CheckConstraint(
            "length(trim(currency)) = 3", name="ck_salary_assignment_currency"
        ),
        # Overlap per employee is EXCLUDE exq_salary_assignment_no_overlap
        # (migration 0007). One open-ended row per employee:
        Index(
            "uq_salary_assignment_open",
            "employee_id",
            unique=True,
            postgresql_where=text("effective_to IS NULL"),
        ),
        Index(
            "ix_salary_assignment_employee_from",
            "employee_id",
            "effective_from",
        ),
        Index(
            "ix_salary_assignment_company_from",
            "company_id",
            "effective_from",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    basic_salary: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="SAR", nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class SalaryAssignmentComponent(Base, TimestampMixin):
    """Optional per-assignment component override (fixed amount or rate).

    ``uq_salary_assignment_component`` guarantees one row per component per
    assignment, which makes override resolution deterministic in the engine.
    """

    __tablename__ = "salary_assignment_components"
    __table_args__ = (
        UniqueConstraint(
            "assignment_id",
            "component_id",
            name="uq_salary_assignment_component",
        ),
        CheckConstraint(
            "amount IS NULL OR amount >= 0",
            name="ck_salary_assignment_component_amount",
        ),
        CheckConstraint(
            "rate IS NULL OR rate > 0",
            name="ck_salary_assignment_component_rate",
        ),
        CheckConstraint(
            "amount IS NOT NULL OR rate IS NOT NULL",
            name="ck_salary_assignment_component_value",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assignment_id: Mapped[int] = mapped_column(
        ForeignKey("employee_salary_assignments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    component_id: Mapped[int] = mapped_column(
        ForeignKey("salary_components.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))


class PayrollPeriod(Base, TimestampMixin):
    """Payroll period - the SINGLE workflow source of truth (Phase 6).

    DRAFT -> CALCULATED -> REVIEWED -> APPROVED -> PAID -> LOCKED; a
    recalculation (from CALCULATED/REVIEWED) always returns the period to
    CALCULATED. ``payroll_runs`` are calculation artifacts only and never
    carry workflow state. Overlapping windows per company are rejected by
    an EXCLUDE constraint created in migration 0007.
    """

    __tablename__ = "payroll_periods"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "period_start",
            "period_end",
            name="uq_payroll_period_company_range",
        ),
        CheckConstraint(
            "period_end >= period_start", name="ck_payroll_period_range"
        ),
        CheckConstraint(
            "status IN ('draft','calculated','reviewed','approved','paid','locked')",
            name="ck_payroll_period_status",
        ),
        CheckConstraint(
            "length(trim(name)) > 0", name="ck_payroll_period_name"
        ),
        CheckConstraint(
            "length(trim(currency)) = 3", name="ck_payroll_period_currency"
        ),
        Index("ix_payroll_period_company_status", "company_id", "status"),
        Index("ix_payroll_period_company_start", "company_id", "period_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="SAR", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    calculated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class PayrollRun(Base, TimestampMixin):
    """Calculation artifact for a payroll period (NOT a workflow machine).

    ``status`` tracks artifact lifecycle only (active/void/superseded); the
    period owns DRAFT..LOCKED. ``input_snapshot`` + ``inputs_hash`` +
    ``engine_version`` make every calculation reproducible: APPROVE rebuilds
    the snapshot and rejects a mismatch with PAYROLL_INPUTS_CHANGED.
    Totals are sums of the already-rounded payslip lines.
    """

    __tablename__ = "payroll_runs"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "run_number", name="uq_payroll_run_company_number"
        ),
        CheckConstraint(
            "status IN ('active','void','superseded')",
            name="ck_payroll_run_status",
        ),
        CheckConstraint(
            "employee_count >= 0", name="ck_payroll_run_employee_count"
        ),
        CheckConstraint(
            "gross_total >= 0", name="ck_payroll_run_gross"
        ),
        CheckConstraint(
            "inputs_hash IS NULL OR length(inputs_hash) = 64",
            name="ck_payroll_run_inputs_hash",
        ),
        # One artifact run per period at a time (the service may replace
        # its lines on recalculation but never opens a second live run).
        Index(
            "uq_payroll_run_active",
            "period_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_payroll_run_company_period", "company_id", "period_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_periods.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    input_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    inputs_hash: Mapped[str | None] = mapped_column(String(64))
    engine_version: Mapped[str | None] = mapped_column(String(20))
    employee_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    gross_total: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=0, nullable=False
    )
    deductions_total: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=0, nullable=False
    )
    employer_total: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=0, nullable=False
    )
    net_total: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=0, nullable=False
    )
    warnings: Mapped[list | None] = mapped_column(JSONB)
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    calculated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    void_reason: Mapped[str | None] = mapped_column(String(500))
    voided_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class PayrollRunLine(Base, TimestampMixin):
    """The payslip header for one employee in one run (Phase 6 has NO
    separate ``payslips`` table - the API exposes these rows at
    ``/payslips/{run_line_id}``).

    One active run has at most one line per employee (unique index).
    Every money field is a snapshot: later salary/component changes never
    rewrite history; corrections flow through payroll_adjustments.
    """

    __tablename__ = "payroll_run_lines"
    __table_args__ = (
        UniqueConstraint("run_id", "employee_id", name="uq_payroll_run_line_employee"),
        CheckConstraint(
            "earnings_total >= 0", name="ck_payroll_run_line_earnings"
        ),
        CheckConstraint(
            "deductions_total >= 0", name="ck_payroll_run_line_deductions"
        ),
        CheckConstraint(
            "employer_total >= 0", name="ck_payroll_run_line_employer"
        ),
        CheckConstraint(
            "length(trim(currency)) = 3", name="ck_payroll_run_line_currency"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    basic_snapshot: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    earnings_total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=0, nullable=False
    )
    deductions_total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=0, nullable=False
    )
    employer_total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=0, nullable=False
    )
    net_pay: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    worked_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    overtime_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    paid_leave_days: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=0, nullable=False
    )
    unpaid_leave_days: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=0, nullable=False
    )
    absent_days: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=0, nullable=False
    )
    late_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    warnings: Mapped[list | None] = mapped_column(JSONB)


class PayslipLine(Base, TimestampMixin):
    """One monetary/summary line of a payslip.

    ``label_*`` and ``unit`` are snapshots so component renames or
    deactivation never alter historical payslips. ``amount`` is always
    ROUND_HALF_UP quantized to 0.01 by the engine (never a float).
    """

    __tablename__ = "payslip_lines"
    __table_args__ = (
        CheckConstraint(
            "line_type IN ('earning','deduction','employer_contribution')",
            name="ck_payslip_line_type",
        ),
        CheckConstraint(
            "unit IN ('amount','minutes','days','percent')",
            name="ck_payslip_line_unit",
        ),
        CheckConstraint(
            "amount IS NOT NULL", name="ck_payslip_line_amount_required"
        ),
        Index("ix_payslip_line_run_line", "run_line_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_line_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_run_lines.id", ondelete="CASCADE"),
        nullable=False,
    )
    component_id: Mapped[int | None] = mapped_column(
        ForeignKey("salary_components.id", ondelete="RESTRICT"), index=True
    )
    line_type: Mapped[str] = mapped_column(String(30), nullable=False)
    label_ar: Mapped[str] = mapped_column(String(255), nullable=False)
    label_en: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class PayrollDeductionRule(Base, TimestampMixin):
    """Recurring / installment-based deduction instruction (Phase 6: NOT a
    loan module - no interest, no schedules beyond installment drawdown).

    ``remaining_amount`` is consumed ONLY when the containing period is
    APPROVED, rows locked with SELECT FOR UPDATE in deterministic
    (effective_from, id) order - so recalculation never double-spends.
    """

    __tablename__ = "payroll_deduction_rules"
    __table_args__ = (
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_payroll_deduction_dates",
        ),
        CheckConstraint(
            "amount > 0", name="ck_payroll_deduction_amount"
        ),
        CheckConstraint(
            "total_amount IS NULL OR total_amount > 0",
            name="ck_payroll_deduction_total",
        ),
        CheckConstraint(
            "remaining_amount IS NULL OR remaining_amount >= 0",
            name="ck_payroll_deduction_remaining",
        ),
        CheckConstraint(
            "status IN ('active','completed','cancelled')",
            name="ck_payroll_deduction_status",
        ),
        Index("ix_payroll_deduction_employee", "employee_id", "effective_from"),
        Index("ix_payroll_deduction_company_status", "company_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    component_id: Mapped[int | None] = mapped_column(
        ForeignKey("salary_components.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    remaining_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class PayrollAdjustment(Base, TimestampMixin):
    """One-off earning/deduction posted against a payroll period.

    Corrections to APPROVED/PAID/LOCKED payroll must target a LATER open
    period and carry ``original_run_id`` pointing at the run being fixed;
    historical rows are never mutated (docs/PHASE6.md, immutability).
    """

    __tablename__ = "payroll_adjustments"
    __table_args__ = (
        CheckConstraint(
            "amount > 0", name="ck_payroll_adjustment_amount"
        ),
        CheckConstraint(
            "direction IN ('earning','deduction')",
            name="ck_payroll_adjustment_direction",
        ),
        CheckConstraint(
            "status IN ('draft','pending','approved','rejected','void')",
            name="ck_payroll_adjustment_status",
        ),
        CheckConstraint(
            "length(trim(reason)) > 0", name="ck_payroll_adjustment_reason"
        ),
        Index("ix_payroll_adjustment_company_status", "company_id", "status"),
        Index("ix_payroll_adjustment_period", "period_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_periods.id", ondelete="CASCADE"),
        nullable=False,
    )
    original_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("payroll_runs.id", ondelete="SET NULL"), index=True
    )
    component_id: Mapped[int | None] = mapped_column(
        ForeignKey("salary_components.id", ondelete="RESTRICT"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    requested_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(String(500))
    voided_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class PayrollStatutoryRule(Base, TimestampMixin):
    """Versioned Saudi statutory/config rule for payroll (GOSI, overtime,
    divisors, proration) - framework only, NO hardcoded legal values.

    ``source_reference`` and ``effective_from`` are mandatory (DB CHECKs);
    ``requires_legal_verification`` starts true. Missing or unverified
    rules block period APPROVED (warnings otherwise). Versioned windows
    [effective_from, effective_to) may not overlap (EXCLUDE, migration
    0007).
    """

    __tablename__ = "payroll_statutory_rules"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "statutory_key",
            "version",
            name="uq_payroll_statutory_rule_version",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_payroll_statutory_rule_dates",
        ),
        CheckConstraint(
            "status IN ('active','inactive')",
            name="ck_payroll_statutory_rule_status",
        ),
        CheckConstraint(
            "length(trim(source_reference)) > 0",
            name="ck_payroll_statutory_rule_source",
        ),
        CheckConstraint(
            "version >= 1", name="ck_payroll_statutory_rule_version"
        ),
        Index(
            "ix_payroll_statutory_rule_company_key",
            "company_id",
            "statutory_key",
            "effective_from",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    statutory_key: Mapped[str] = mapped_column(String(50), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(
        String(20), default="SA", nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    rule_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    source_date: Mapped[date | None] = mapped_column(Date)
    requires_legal_verification: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


# ---------------------------------------------------------------------------
# Phase 7 - employee self-service & request/approval framework
# ---------------------------------------------------------------------------


class EmployeeRequest(Base, TimestampMixin):
    """Generic employee request with an explicit, auditable state machine.

    draft -> submitted -> approved / rejected; draft/submitted may be
    cancelled. ``payload`` is validated against a CLOSED per-type schema in
    the service layer (no generic formula/workflow engine). Approver access
    is authorization-based: either the caller resolved the snapshot
    ``approver_employee_id`` (set from ``employees.manager_id`` at submit
    time) and holds ``employee_request.approve``/``reject``, or holds the
    HR override ``employee_request.manage``. Employees may only ever touch
    their own requests (service-layer self scope).
    """

    __tablename__ = "employee_requests"
    __table_args__ = (
        CheckConstraint(
            "request_type IN "
            "('attendance_correction','hr_letter','document_request','other')",
            name="ck_employee_request_type",
        ),
        CheckConstraint(
            "status IN ('draft','submitted','approved','rejected','cancelled')",
            name="ck_employee_request_status",
        ),
        CheckConstraint(
            "(status = 'approved' OR status = 'rejected') "
            "= (decided_at IS NOT NULL)",
            name="ck_employee_request_decision_consistency",
        ),
        CheckConstraint(
            "status <> 'rejected' OR length(trim(coalesce(decision_reason,''))) > 0",
            name="ck_employee_request_reject_reason",
        ),
        # One open attendance-correction per employee per day.
        Index(
            "uq_employee_request_attendance_open",
            "company_id",
            "employee_id",
            "work_date",
            unique=True,
            postgresql_where=text(
                "request_type = 'attendance_correction' "
                "AND status IN ('draft','submitted')"
            ),
        ),
        Index("ix_employee_request_company_status", "company_id", "status"),
        Index("ix_employee_request_company_type", "company_id", "request_type"),
        Index("ix_employee_request_employee", "employee_id", "status"),
        Index("ix_employee_request_approver", "approver_employee_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Snapshot of employees.manager_id taken at submit time; NULL means no
    # manager is assigned and only employee_request.manage holders decide.
    approver_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), index=True
    )
    request_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Attendance-correction target date (NULL for other types); enforced by
    # the service layer to match the payload work_date.
    work_date: Mapped[date | None] = mapped_column(Date, index=True)
    submitted_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(String(500))
    cancelled_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(500))
    # Set by the attendance-correction handler when the approval wrote the
    # attendance_records row (links request -> produced record).
    attendance_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("attendance_records.id", ondelete="SET NULL"), index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class EmployeeRequestEvent(Base):
    """Append-only, employee-visible history of one request.

    Rows are only ever inserted (service never updates/deletes them); RLS
    scopes reads to the owning company, and the service scopes reads to the
    request owner, the resolved approver, or employee_request.manage.
    """

    __tablename__ = "employee_request_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN "
            "('created','updated','submitted','approved','rejected','cancelled')",
            name="ck_employee_request_event_type",
        ),
        CheckConstraint(
            "length(trim(actor_name)) > 0", name="ck_employee_request_event_actor"
        ),
        Index("ix_employee_request_event_request", "request_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_id: Mapped[int] = mapped_column(
        ForeignKey("employee_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Denormalized display name so history survives user deletion.
    actor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EmployeeDocumentVisibility(TimestampMixin, Base):
    """Sidecar opt-in flag: which documents the owning employee may see.

    Default-deny: the ABSENCE of a row (or ``employee_visible = false``)
    means the document stays HR-only. The frozen ``employee_documents``
    table (Phases 1-3/6) is not modified; HR manages this flag through the
    ESS-aware document endpoints with ``employee_document.update``.
    """

    __tablename__ = "employee_document_visibility"
    __table_args__ = (
        CheckConstraint(
            "employee_visible IN (true, false)",
            name="ck_employee_document_visibility_flag",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("employee_documents.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    employee_visible: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


# Phase 1 RLS registrations. Phase 2 tables (departments, job_positions,
# job_grades, employees) are registered by app.core.rls_phase2 at runtime
# and from migration 0003 - NOT here - so a fresh `alembic upgrade` runs
# 0001_phase1 with exactly the Phase 1 registry (0001 applies policies for
# every registered table and those tables do not exist yet at that point).
# The same rule applies to the Phase 3 tables (app.core.rls_phase3 / 0004)
# and the Phase 4 attendance tables (app.core.rls_phase4 / 0005).
company_scoped("companies", company_column="id")
company_scoped("branches")
company_scoped(
    "users",
    extra_using="id = app.current_user_id()",
    extra_check="id = app.current_user_id()",
)
company_scoped("roles")
company_scoped("role_permissions")
company_scoped("user_roles", extra_using="user_id = app.current_user_id()")


# ---------------------------------------------------------------------------
# Phase 8 - salary advances (interest-free advances repaid through the
# frozen Phase 6 payroll deduction-rule machinery; see docs/PHASE8.md)
# ---------------------------------------------------------------------------


class SalaryAdvance(Base, TimestampMixin):
    """One interest-free salary advance with an explicit state machine.

    draft -> submitted -> approved -> disbursed -> settled; submitted may
    also be rejected, draft/submitted cancelled. Disbursement creates a
    Phase 6 ``payroll_deduction_rules`` row through the frozen
    ``create_payroll_deduction`` service (real principal - no bypass) and
    links it in ``deduction_rule_id``; repayment then happens inside the
    frozen payroll-approve consumption. Approver access mirrors Phase 7:
    the snapshot ``approver_employee_id`` (from ``employees.manager_id``
    at submit) plus the decision verbs, or the HR override
    ``salary_advance.manage``. Employees only ever touch their own rows
    (service-layer self scope). No interest, no formula engine.
    """

    __tablename__ = "salary_advances"
    __table_args__ = (
        CheckConstraint(
            "amount > 0", name="ck_salary_advance_amount"
        ),
        CheckConstraint(
            "installment_amount IS NULL OR "
            "(installment_amount > 0 AND installment_amount <= amount)",
            name="ck_salary_advance_installment",
        ),
        CheckConstraint(
            "status IN ('draft','submitted','approved','rejected',"
            "'cancelled','disbursed','settled')",
            name="ck_salary_advance_status",
        ),
        CheckConstraint(
            "(status IN ('approved','rejected','disbursed','settled')) "
            "= (decided_at IS NOT NULL)",
            name="ck_salary_advance_decision_consistency",
        ),
        CheckConstraint(
            "status NOT IN ('disbursed','settled') OR decided_at IS NOT NULL",
            name="ck_salary_advance_decided_before_disburse",
        ),
        CheckConstraint(
            "status <> 'rejected' "
            "OR length(trim(coalesce(decision_reason,''))) > 0",
            name="ck_salary_advance_reject_reason",
        ),
        CheckConstraint(
            "status <> 'disbursed' OR deduction_rule_id IS NOT NULL",
            name="ck_salary_advance_disbursed_rule",
        ),
        CheckConstraint(
            "length(trim(reason)) > 0", name="ck_salary_advance_reason"
        ),
        # One advance can never share its repayment rule with another
        # advance (multiple NULLs are allowed by PostgreSQL).
        UniqueConstraint(
            "deduction_rule_id", name="uq_salary_advance_deduction_rule"
        ),
        Index("ix_salary_advance_company_status", "company_id", "status"),
        Index("ix_salary_advance_employee_status", "employee_id", "status"),
        Index("ix_salary_advance_approver", "approver_employee_id", "status"),
        Index(
            "ix_salary_advance_employee_open",
            "employee_id",
            postgresql_where=text(
                "status IN ('draft','submitted','approved')"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Snapshot of employees.manager_id taken at submit time; NULL means no
    # manager is assigned and only salary_advance.manage holders decide.
    approver_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Installment per payroll period; set at disbursement (NULL = the full
    # amount is collected in one drawdown).
    installment_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    submitted_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(String(500))
    disbursed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    disbursed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settled_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settle_note: Mapped[str | None] = mapped_column(String(500))
    # Set by disbursement via the frozen create_payroll_deduction service;
    # the frozen Phase 6 consumption draws it down inside payroll approve.
    deduction_rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("payroll_deduction_rules.id", ondelete="SET NULL"), index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class SalaryAdvanceEvent(Base):
    """Append-only, employee-visible history of one salary advance.

    Rows are only ever inserted (the service never updates/deletes them);
    RLS scopes reads to the owning company, and the service scopes reads to
    the advance owner, the resolved approver, or salary_advance.manage.
    """

    __tablename__ = "salary_advance_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN "
            "('created','submitted','approved','rejected','cancelled',"
            "'disbursed','settled')",
            name="ck_salary_advance_event_type",
        ),
        CheckConstraint(
            "length(trim(actor_name)) > 0", name="ck_salary_advance_event_actor"
        ),
        Index("ix_salary_advance_event_advance", "advance_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    advance_id: Mapped[int] = mapped_column(
        ForeignKey("salary_advances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Denormalized display name so history survives user deletion. System-
    # attributed events (auto-reconcile) use the literal "system".
    actor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Phase 9 - HR letters
# ---------------------------------------------------------------------------


class HrLetter(Base, TimestampMixin):
    """One HR employment-related letter with an explicit state machine.

    draft -> issued -> void; draft -> cancelled (Phase 9 design, docs/PHASE9.md).
    ``content`` is a closed, server-assembled JSONB snapshot built from
    frozen source records (employee, contract, history, salary assignment -
    read-only) at draft creation and re-assembled at issue; once issued the
    content never changes (no application path mutates it outside draft).
    ``source_request_id`` optionally links the Phase 7 approved ``hr_letter``
    request the letter fulfils; at most one ACTIVE (draft|issued) letter may
    reference a given request (partial unique index). Salary letters read the
    active ``employee_salary_assignments`` row only - no payroll writes, no
    statutory values, no formula engine.
    """

    __tablename__ = "hr_letters"
    __table_args__ = (
        CheckConstraint(
            "letter_type IN "
            "('employment','salary','experience','work_address')",
            name="ck_hr_letter_type",
        ),
        CheckConstraint("language IN ('ar','en')", name="ck_hr_letter_language"),
        CheckConstraint(
            "status IN ('draft','issued','void','cancelled')",
            name="ck_hr_letter_status",
        ),
        # Issue metadata exists exactly when the letter reached issued/void
        # (void always follows issue, so the check covers both terminal
        # post-issue states).
        CheckConstraint(
            "status IN ('issued','void') = (issued_at IS NOT NULL)",
            name="ck_hr_letter_issued_consistency",
        ),
        CheckConstraint(
            "(status <> 'cancelled') = (cancelled_at IS NULL)",
            name="ck_hr_letter_cancelled_consistency",
        ),
        CheckConstraint(
            "(status <> 'void') = (voided_at IS NULL AND void_reason IS NULL)",
            name="ck_hr_letter_void_consistency",
        ),
        CheckConstraint(
            "status <> 'void' OR length(trim(void_reason)) > 0",
            name="ck_hr_letter_void_reason",
        ),
        Index("ix_hr_letter_company_status", "company_id", "status"),
        Index("ix_hr_letter_company_employee", "company_id", "employee_id"),
        Index("ix_hr_letter_company_created", "company_id", "created_at"),
        Index(
            "uq_hr_letter_active_request",
            "source_request_id",
            unique=True,
            postgresql_where=text(
                "source_request_id IS NOT NULL AND status IN ('draft','issued')"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    letter_type: Mapped[str] = mapped_column(String(32), nullable=False)
    language: Mapped[str] = mapped_column(String(2), nullable=False)
    purpose: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(
        String(16), default="draft", server_default="draft", nullable=False
    )
    # Closed server-assembled snapshot (validated per letter_type in the
    # service layer; frozen forever once the letter is issued).
    content: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("employee_requests.id", ondelete="SET NULL"), index=True
    )
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issued_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    cancel_reason: Mapped[str | None] = mapped_column(String(500))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    void_reason: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    @property
    def reference(self) -> str:
        """Human-facing letter reference - derived from the id (no column)."""
        return f"LTR-{self.id:06d}"


class HrLetterEvent(Base):
    """Append-only, employee-visible history of one HR letter.

    Rows are only ever inserted (the service never updates/deletes them);
    RLS scopes reads to the owning company, and the detail endpoints scope
    reads to the owning letter. ``void_reason`` lives on the letter row and
    is redacted from ESS responses; event ``note`` carries the cancel/void
    text for HR and is likewise redacted from ESS.
    """

    __tablename__ = "hr_letter_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ('created','updated','issued','cancelled','voided')",
            name="ck_hr_letter_event_action",
        ),
        CheckConstraint(
            "from_status IS NULL OR from_status IN "
            "('draft','issued','void','cancelled')",
            name="ck_hr_letter_event_from_status",
        ),
        CheckConstraint(
            "to_status IN ('draft','issued','void','cancelled')",
            name="ck_hr_letter_event_to_status",
        ),
        CheckConstraint(
            "length(trim(actor_name)) > 0", name="ck_hr_letter_event_actor"
        ),
        Index("ix_hr_letter_event_letter", "letter_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    letter_id: Mapped[int] = mapped_column(
        ForeignKey("hr_letters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(16))
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Denormalized display name so history survives user deletion.
    actor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))
    # Same convention as audit_logs.ip_address (String(64)).
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
