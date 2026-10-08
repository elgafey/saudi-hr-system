"""phase 6 payroll & salary management: components, assignments, periods, runs, payslips, adjustments, deductions, statutory rules

Revision ID: 0007_phase6_payroll
Revises: 0006_phase5_leave
Create Date: 2026-10-07

NOTE: alembic stores the revision id in alembic_version.version_num
VARCHAR(32), so the id is abbreviated while the file name keeps the full
phase-6 description.

Adds the Phase 6 payroll-domain tables:

- salary_components               (earning / deduction / employer_contribution
                                   buckets; CLOSED calculation_basis vocabulary
                                   resolved by the engine - never a stored
                                   expression; unique (company_id, code))
- employee_salary_assignments     (effective-dated salary history - the payroll
                                   source of truth; EXCLUDE rejects overlapping
                                   windows per employee with INCLUSIVE ends
                                   '[]'; partial unique index keeps at most one
                                   open-ended row; historical rows are never
                                   overwritten)
- salary_assignment_components    (optional per-assignment fixed-amount/rate
                                   overrides; unique (assignment_id,
                                   component_id))
- payroll_periods                 (the SINGLE workflow machine: draft ->
                                   calculated -> reviewed -> approved -> paid
                                   -> locked; EXCLUDE rejects overlapping
                                   windows per company, inclusive '[]')
- payroll_runs                    (calculation artifact ONLY: active / void /
                                   superseded; carries input_snapshot +
                                   inputs_hash (sha256) + engine_version;
                                   partial unique index keeps one active run
                                   per period)
- payroll_run_lines               (the payslip HEADER per employee per run -
                                   Phase 6 has no separate payslips table;
                                   unique (run_id, employee_id); every money
                                   field is a snapshot)
- payslip_lines                   (snapshot labels + rounded amounts; sort_order
                                   drives payslip rendering and export order)
- payroll_deduction_rules         (recurring / installment deductions; NO loan
                                   module; remaining_amount is consumed only
                                   at period APPROVE under SELECT FOR UPDATE)
- payroll_adjustments             (one-off earning/deduction; corrections to
                                   approved/paid/locked payroll must target a
                                   LATER open period and reference the
                                   original_run_id)
- payroll_statutory_rules         (versioned Saudi statutory/config rules -
                                   framework only; source_reference is a DB
                                   CHECK, requires_legal_verification starts
                                   true; EXCLUDE rejects overlapping versions
                                   per key with half-open '[)' windows)

Business rules encoded here (see docs/PHASE6.md):

- payroll_periods.status is authoritative; payroll_runs.status never carries
  workflow state (DRAFT..LOCKED live on the period only);
- run lines ARE the payslips (GET /payslips/{run_line_id});
- no legal values are seeded - statutory rules must cite their source;
- money columns are NUMERIC (never float) and the engine quantizes to 0.01
  with ROUND_HALF_UP before persisting.

Each table gets FORCE ROW LEVEL SECURITY with the standard tenant policy
(deny-by-default, platform-admin bypass), following the Phase 1-5 pattern.

Seeding notes: the 28 Phase 6 permission codes are declared in
PHASE6_PERMISSIONS below so this frozen migration owns exactly its own
codes. Default-role grants for existing companies are backfilled from the
current DEFAULT_ROLES catalog (idempotent).

Requires the btree_gist extension (created by migration 0004) for the
integer/range EXCLUDE constraints. Not dropped on downgrade: extensions
are cluster-level objects.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.rls import RLS_REGISTRY, policy_sql
from app.core.rls_phase6 import PHASE6_RLS_TABLES, register_phase6_rls
from app.permissions.catalog import DEFAULT_ROLES

revision: str = "0007_phase6_payroll"
down_revision: Union[str, None] = "0006_phase5_leave"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen snapshot of the Phase 6 permission codes owned by this migration.
PHASE6_PERMISSIONS: tuple[tuple[str, str, str], ...] = (
    ("salary_component.view", "View salary components", "salary_components"),
    ("salary_component.create", "Create salary components", "salary_components"),
    ("salary_component.update", "Edit salary components", "salary_components"),
    (
        "salary_component.deactivate",
        "Deactivate salary components",
        "salary_components",
    ),
    ("salary_assignment.view", "View salary assignments", "salary_assignments"),
    ("salary_assignment.create", "Create salary assignments", "salary_assignments"),
    ("salary_assignment.update", "Edit salary assignments", "salary_assignments"),
    ("payroll_period.view", "View payroll periods", "payroll_periods"),
    ("payroll_period.create", "Create payroll periods", "payroll_periods"),
    (
        "payroll_period.update",
        "Edit draft payroll periods",
        "payroll_periods",
    ),
    ("payroll_run.view", "View payroll runs and payslips", "payroll_runs"),
    ("payroll_run.calculate", "Calculate payroll runs", "payroll_runs"),
    ("payroll_run.review", "Review payroll runs", "payroll_runs"),
    ("payroll_run.approve", "Approve payroll runs", "payroll_runs"),
    ("payroll_run.mark_paid", "Mark payroll runs as paid", "payroll_runs"),
    ("payroll_run.lock", "Lock payroll periods", "payroll_runs"),
    (
        "payroll_adjustment.view",
        "View payroll adjustments",
        "payroll_adjustments",
    ),
    (
        "payroll_adjustment.create",
        "Create payroll adjustments",
        "payroll_adjustments",
    ),
    (
        "payroll_adjustment.approve",
        "Approve payroll adjustments",
        "payroll_adjustments",
    ),
    (
        "payroll_adjustment.reject",
        "Reject payroll adjustments",
        "payroll_adjustments",
    ),
    (
        "payroll_adjustment.void",
        "Void payroll adjustments",
        "payroll_adjustments",
    ),
    ("payroll_deduction.view", "View payroll deduction rules", "payroll_deductions"),
    (
        "payroll_deduction.create",
        "Create payroll deduction rules",
        "payroll_deductions",
    ),
    (
        "payroll_deduction.update",
        "Edit payroll deduction rules",
        "payroll_deductions",
    ),
    (
        "payroll_statutory_rule.view",
        "View payroll statutory rules",
        "payroll_statutory_rules",
    ),
    (
        "payroll_statutory_rule.create",
        "Create payroll statutory rules",
        "payroll_statutory_rules",
    ),
    (
        "payroll_statutory_rule.deactivate",
        "Deactivate payroll statutory rules",
        "payroll_statutory_rules",
    ),
    ("payroll_export.execute", "Export payroll for accounting", "payroll_runs"),
)


def upgrade() -> None:
    op.create_table(
        "salary_components",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name_ar", sa.String(255), nullable=False),
        sa.Column("name_en", sa.String(255), nullable=False),
        sa.Column("description", sa.String(500)),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("calculation_basis", sa.String(30), nullable=False),
        sa.Column("default_amount", sa.Numeric(12, 2)),
        sa.Column("default_rate", sa.Numeric(6, 4)),
        sa.Column(
            "is_statutory", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("statutory_key", sa.String(50)),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="active"
        ),
        sa.Column(
            "sort_order", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "company_id", "code", name="uq_salary_component_company_code"
        ),
        sa.CheckConstraint(
            "category IN ('earning','deduction','employer_contribution')",
            name="ck_salary_component_category",
        ),
        sa.CheckConstraint(
            "calculation_basis IN ('fixed','percent_of_basic','engine_derived')",
            name="ck_salary_component_basis",
        ),
        sa.CheckConstraint(
            "default_amount IS NULL OR default_amount >= 0",
            name="ck_salary_component_amount",
        ),
        sa.CheckConstraint(
            "default_rate IS NULL OR default_rate > 0",
            name="ck_salary_component_rate",
        ),
        sa.CheckConstraint(
            "status IN ('active','inactive')", name="ck_salary_component_status"
        ),
        sa.CheckConstraint(
            "length(trim(code)) > 0", name="ck_salary_component_code"
        ),
    )
    op.create_index(
        "ix_salary_component_company_status",
        "salary_components",
        ["company_id", "status"],
    )

    op.create_table(
        "employee_salary_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "employee_id",
            sa.Integer(),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("basic_salary", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "currency", sa.String(3), nullable=False, server_default="SAR"
        ),
        sa.Column("reason", sa.String(500)),
        sa.Column(
            "created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_salary_assignment_dates",
        ),
        sa.CheckConstraint(
            "basic_salary >= 0", name="ck_salary_assignment_basic_salary"
        ),
        sa.CheckConstraint(
            "length(trim(currency)) = 3", name="ck_salary_assignment_currency"
        ),
    )
    # At most one open-ended row per employee (the service closes the
    # previous window before inserting its successor).
    op.create_index(
        "uq_salary_assignment_open",
        "employee_salary_assignments",
        ["employee_id"],
        unique=True,
        postgresql_where=sa.text("effective_to IS NULL"),
    )
    op.create_index(
        "ix_salary_assignment_employee_from",
        "employee_salary_assignments",
        ["employee_id", "effective_from"],
    )
    op.create_index(
        "ix_salary_assignment_company_from",
        "employee_salary_assignments",
        ["company_id", "effective_from"],
    )
    # Overlapping windows per employee are rejected. Periods are INCLUSIVE
    # on both ends ('[]'), matching the service-layer overlap check:
    # existing.start <= new.end AND existing.end >= new.start (NULL end =
    # open-ended), so closing the old row at new.start - 1 day stays legal.
    op.execute(
        "ALTER TABLE employee_salary_assignments "
        "ADD CONSTRAINT exq_salary_assignment_no_overlap "
        "EXCLUDE USING gist (employee_id WITH =, "
        "daterange(effective_from, effective_to, '[]') WITH &&)"
    )

    op.create_table(
        "salary_assignment_components",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "assignment_id",
            sa.Integer(),
            sa.ForeignKey("employee_salary_assignments.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "component_id",
            sa.Integer(),
            sa.ForeignKey("salary_components.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column("amount", sa.Numeric(12, 2)),
        sa.Column("rate", sa.Numeric(6, 4)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "assignment_id",
            "component_id",
            name="uq_salary_assignment_component",
        ),
        sa.CheckConstraint(
            "amount IS NULL OR amount >= 0",
            name="ck_salary_assignment_component_amount",
        ),
        sa.CheckConstraint(
            "rate IS NULL OR rate > 0",
            name="ck_salary_assignment_component_rate",
        ),
        sa.CheckConstraint(
            "amount IS NOT NULL OR rate IS NOT NULL",
            name="ck_salary_assignment_component_value",
        ),
    )

    op.create_table(
        "payroll_periods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column(
            "currency", sa.String(3), nullable=False, server_default="SAR"
        ),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="draft"
        ),
        sa.Column("calculated_at", sa.DateTime(timezone=True)),
        sa.Column(
            "calculated_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "reviewed_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column(
            "approved_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column(
            "paid_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "locked_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "company_id",
            "period_start",
            "period_end",
            name="uq_payroll_period_company_range",
        ),
        sa.CheckConstraint(
            "period_end >= period_start", name="ck_payroll_period_range"
        ),
        sa.CheckConstraint(
            "status IN ('draft','calculated','reviewed','approved','paid','locked')",
            name="ck_payroll_period_status",
        ),
        sa.CheckConstraint(
            "length(trim(name)) > 0", name="ck_payroll_period_name"
        ),
        sa.CheckConstraint(
            "length(trim(currency)) = 3", name="ck_payroll_period_currency"
        ),
    )
    op.create_index(
        "ix_payroll_period_company_status",
        "payroll_periods",
        ["company_id", "status"],
    )
    op.create_index(
        "ix_payroll_period_company_start",
        "payroll_periods",
        ["company_id", "period_start"],
    )
    # One company may not run two payroll periods over the same dates.
    # Inclusive '[]' matches the service-layer overlap check.
    op.execute(
        "ALTER TABLE payroll_periods "
        "ADD CONSTRAINT exq_payroll_period_no_overlap "
        "EXCLUDE USING gist (company_id WITH =, "
        "daterange(period_start, period_end, '[]') WITH &&)"
    )

    op.create_table(
        "payroll_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "period_id",
            sa.Integer(),
            sa.ForeignKey("payroll_periods.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="active"
        ),
        sa.Column("input_snapshot", postgresql.JSONB()),
        sa.Column("inputs_hash", sa.String(64)),
        sa.Column("engine_version", sa.String(20)),
        sa.Column(
            "employee_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "gross_total", sa.Numeric(14, 2), nullable=False, server_default="0"
        ),
        sa.Column(
            "deductions_total",
            sa.Numeric(14, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "employer_total", sa.Numeric(14, 2), nullable=False, server_default="0"
        ),
        sa.Column(
            "net_total", sa.Numeric(14, 2), nullable=False, server_default="0"
        ),
        sa.Column("warnings", postgresql.JSONB()),
        sa.Column("calculated_at", sa.DateTime(timezone=True)),
        sa.Column(
            "calculated_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("void_reason", sa.String(500)),
        sa.Column(
            "voided_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("voided_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "company_id", "run_number", name="uq_payroll_run_company_number"
        ),
        sa.CheckConstraint(
            "status IN ('active','void','superseded')",
            name="ck_payroll_run_status",
        ),
        sa.CheckConstraint(
            "employee_count >= 0", name="ck_payroll_run_employee_count"
        ),
        sa.CheckConstraint("gross_total >= 0", name="ck_payroll_run_gross"),
        sa.CheckConstraint(
            "inputs_hash IS NULL OR length(inputs_hash) = 64",
            name="ck_payroll_run_inputs_hash",
        ),
    )
    # One artifact run per period at a time (recalculation replaces the
    # lines of the existing run but never opens a second live run).
    op.create_index(
        "uq_payroll_run_active",
        "payroll_runs",
        ["period_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_payroll_run_company_period",
        "payroll_runs",
        ["company_id", "period_id"],
    )

    op.create_table(
        "payroll_run_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("payroll_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "employee_id",
            sa.Integer(),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("basic_snapshot", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "earnings_total", sa.Numeric(12, 2), nullable=False, server_default="0"
        ),
        sa.Column(
            "deductions_total", sa.Numeric(12, 2), nullable=False, server_default="0"
        ),
        sa.Column(
            "employer_total", sa.Numeric(12, 2), nullable=False, server_default="0"
        ),
        sa.Column("net_pay", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column(
            "worked_minutes", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "overtime_minutes", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "paid_leave_days", sa.Numeric(5, 2), nullable=False, server_default="0"
        ),
        sa.Column(
            "unpaid_leave_days",
            sa.Numeric(5, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "absent_days", sa.Numeric(5, 2), nullable=False, server_default="0"
        ),
        sa.Column(
            "late_minutes", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("warnings", postgresql.JSONB()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "run_id", "employee_id", name="uq_payroll_run_line_employee"
        ),
        sa.CheckConstraint(
            "earnings_total >= 0", name="ck_payroll_run_line_earnings"
        ),
        sa.CheckConstraint(
            "deductions_total >= 0", name="ck_payroll_run_line_deductions"
        ),
        sa.CheckConstraint(
            "employer_total >= 0", name="ck_payroll_run_line_employer"
        ),
        sa.CheckConstraint(
            "length(trim(currency)) = 3", name="ck_payroll_run_line_currency"
        ),
    )

    op.create_table(
        "payslip_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "run_line_id",
            sa.Integer(),
            sa.ForeignKey("payroll_run_lines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "component_id",
            sa.Integer(),
            sa.ForeignKey("salary_components.id", ondelete="RESTRICT"),
            index=True,
        ),
        sa.Column("line_type", sa.String(30), nullable=False),
        sa.Column("label_ar", sa.String(255), nullable=False),
        sa.Column("label_en", sa.String(255), nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 4)),
        sa.Column("rate", sa.Numeric(12, 6)),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "sort_order", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "line_type IN ('earning','deduction','employer_contribution')",
            name="ck_payslip_line_type",
        ),
        sa.CheckConstraint(
            "unit IN ('amount','minutes','days','percent')",
            name="ck_payslip_line_unit",
        ),
        sa.CheckConstraint(
            "amount IS NOT NULL", name="ck_payslip_line_amount_required"
        ),
    )
    op.create_index(
        "ix_payslip_line_run_line", "payslip_lines", ["run_line_id"]
    )

    op.create_table(
        "payroll_deduction_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "employee_id",
            sa.Integer(),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "component_id",
            sa.Integer(),
            sa.ForeignKey("salary_components.id", ondelete="RESTRICT"),
            index=True,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("total_amount", sa.Numeric(12, 2)),
        sa.Column("remaining_amount", sa.Numeric(12, 2)),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="active"
        ),
        sa.Column("reason", sa.String(500)),
        sa.Column(
            "created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_payroll_deduction_dates",
        ),
        sa.CheckConstraint("amount > 0", name="ck_payroll_deduction_amount"),
        sa.CheckConstraint(
            "total_amount IS NULL OR total_amount > 0",
            name="ck_payroll_deduction_total",
        ),
        sa.CheckConstraint(
            "remaining_amount IS NULL OR remaining_amount >= 0",
            name="ck_payroll_deduction_remaining",
        ),
        sa.CheckConstraint(
            "status IN ('active','completed','cancelled')",
            name="ck_payroll_deduction_status",
        ),
    )
    op.create_index(
        "ix_payroll_deduction_employee",
        "payroll_deduction_rules",
        ["employee_id", "effective_from"],
    )
    op.create_index(
        "ix_payroll_deduction_company_status",
        "payroll_deduction_rules",
        ["company_id", "status"],
    )

    op.create_table(
        "payroll_adjustments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "employee_id",
            sa.Integer(),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "period_id",
            sa.Integer(),
            sa.ForeignKey("payroll_periods.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "original_run_id",
            sa.Integer(),
            sa.ForeignKey("payroll_runs.id", ondelete="SET NULL"),
            index=True,
        ),
        sa.Column(
            "component_id",
            sa.Integer(),
            sa.ForeignKey("salary_components.id", ondelete="RESTRICT"),
            index=True,
        ),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="pending"
        ),
        sa.Column(
            "requested_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "decided_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decision_reason", sa.String(500)),
        sa.Column(
            "voided_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("voided_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("amount > 0", name="ck_payroll_adjustment_amount"),
        sa.CheckConstraint(
            "direction IN ('earning','deduction')",
            name="ck_payroll_adjustment_direction",
        ),
        sa.CheckConstraint(
            "status IN ('draft','pending','approved','rejected','void')",
            name="ck_payroll_adjustment_status",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) > 0", name="ck_payroll_adjustment_reason"
        ),
    )
    op.create_index(
        "ix_payroll_adjustment_company_status",
        "payroll_adjustments",
        ["company_id", "status"],
    )
    op.create_index(
        "ix_payroll_adjustment_period", "payroll_adjustments", ["period_id"]
    )

    op.create_table(
        "payroll_statutory_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("statutory_key", sa.String(50), nullable=False),
        sa.Column(
            "jurisdiction", sa.String(20), nullable=False, server_default="SA"
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("rule_json", postgresql.JSONB(), nullable=False),
        sa.Column("source_reference", sa.String(500), nullable=False),
        sa.Column("source_date", sa.Date()),
        sa.Column(
            "requires_legal_verification",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="active"
        ),
        sa.Column(
            "created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "company_id",
            "statutory_key",
            "version",
            name="uq_payroll_statutory_rule_version",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_payroll_statutory_rule_dates",
        ),
        sa.CheckConstraint(
            "status IN ('active','inactive')",
            name="ck_payroll_statutory_rule_status",
        ),
        sa.CheckConstraint(
            "length(trim(source_reference)) > 0",
            name="ck_payroll_statutory_rule_source",
        ),
        sa.CheckConstraint(
            "version >= 1", name="ck_payroll_statutory_rule_version"
        ),
    )
    op.create_index(
        "ix_payroll_statutory_rule_company_key",
        "payroll_statutory_rules",
        ["company_id", "statutory_key", "effective_from"],
    )
    # Versioned rules may not overlap for the same statutory key. Windows
    # are [effective_from, effective_to) with NULL = open-ended, so adjacent
    # versions (v1 ends where v2 starts) are legal.
    op.execute(
        "ALTER TABLE payroll_statutory_rules "
        "ADD CONSTRAINT exq_payroll_statutory_rule_no_overlap "
        "EXCLUDE USING gist (company_id WITH =, statutory_key WITH =, "
        "daterange(effective_from, effective_to, '[)') WITH &&)"
    )

    bind = op.get_bind()
    # alembic never imports app.main, so ensure the Phase 6 rules are part
    # of the registry before applying their policies (idempotent).
    register_phase6_rls()
    for table in PHASE6_RLS_TABLES:
        rule = RLS_REGISTRY[table]
        bind.execute(sa.text(f"ALTER TABLE {rule.table} ENABLE ROW LEVEL SECURITY"))
        bind.execute(sa.text(f"ALTER TABLE {rule.table} FORCE ROW LEVEL SECURITY"))
        bind.execute(
            sa.text(f"DROP POLICY IF EXISTS {rule.policy_name} ON {rule.table}")
        )
        bind.execute(sa.text(policy_sql(rule)))

    bind.execute(sa.text("SELECT set_config('app.is_platform_admin','true',true)"))

    perm_table = sa.table(
        "permissions",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("module", sa.String),
    )
    for code, name, module in PHASE6_PERMISSIONS:
        bind.execute(
            postgresql.insert(perm_table)
            .values(code=code, name=name, module=module)
            .on_conflict_do_nothing(index_elements=["code"])
        )

    # Backfill grants on pre-existing default roles. The JOIN restricts rows
    # to permissions that exist at this point in the migration chain and the
    # ON CONFLICT makes the operation idempotent.
    for _code, _name, _desc, perms in DEFAULT_ROLES:
        for perm_code in perms:
            bind.execute(
                sa.text(
                    "INSERT INTO role_permissions (role_id, permission_id, company_id) "
                    "SELECT r.id, p.id, r.company_id "
                    "FROM roles r JOIN permissions p ON p.code = :perm "
                    "WHERE r.code = :role "
                    "ON CONFLICT (role_id, permission_id) DO NOTHING"
                ),
                {"perm": perm_code, "role": _code},
            )

    bind.execute(sa.text("SELECT set_config('app.is_platform_admin','false',true)"))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("SELECT set_config('app.is_platform_admin','true',true)"))
    codes = [code for code, _name, _module in PHASE6_PERMISSIONS]
    bind.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE code = ANY (:codes))"
        ),
        {"codes": codes},
    )
    bind.execute(
        sa.text("DELETE FROM permissions WHERE code = ANY (:codes)"),
        {"codes": codes},
    )
    bind.execute(sa.text("SELECT set_config('app.is_platform_admin','false',true)"))

    for table in (
        "payroll_statutory_rules",
        "payroll_adjustments",
        "payroll_deduction_rules",
        "payslip_lines",
        "payroll_run_lines",
        "payroll_runs",
        "payroll_periods",
        "salary_assignment_components",
        "employee_salary_assignments",
        "salary_components",
    ):
        op.drop_table(table)
    # btree_gist is intentionally left in place (cluster-level object).
