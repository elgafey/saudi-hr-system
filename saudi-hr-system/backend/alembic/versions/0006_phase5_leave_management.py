"""phase 5 leave management: types, statutory rules, allocations, requests, balances, holidays

Revision ID: 0006_phase5_leave
Revises: 0005_phase4_attendance
Create Date: 2026-10-07

NOTE: alembic stores the revision id in alembic_version.version_num
VARCHAR(32), so the id is abbreviated while the file name keeps the full
phase-5 description.

Adds the Phase 5 leave-domain tables:

- company_holidays          (D1: dedicated company-scoped holiday calendar;
                              unique (company_id, date); no legal/public
                              holiday values are seeded - companies maintain
                              their own calendar)
- leave_types               (per-company configuration: paid/unpaid,
                              approval requirement, attachment rules,
                              day-counting mode, carry-forward rules,
                              allowance treatment for Phase 6 payroll;
                              unique (company_id, code))
- leave_statutory_rules     (D2: versioned, company-configured rules;
                              source_reference + effective_from are DB
                              CHECKs, requires_legal_verification starts
                              true; versions never overlap for the same
                              statutory key - gist EXCLUDE on the
                              [effective_from, effective_to) window)
- leave_allocations         (entitlement pool per employee/type/period;
                              used_days is written only by the balance
                              engine under SELECT FOR UPDATE; gist EXCLUDE
                              rejects overlapping periods for the same
                              employee+type across ALL statuses; a
                              carry-forward row points at exactly one
                              source allocation via a partial unique index)
- leave_requests            (draft -> submitted -> approved/rejected/
                              cancelled workflow with snapshot day counts
                              in JSONB; gist EXCLUDE rejects overlapping
                              SUBMITTED/APPROVED ranges per employee)
- leave_consumptions        (FIFO draw-down of one allocation by one
                              APPROVED request; rows exist only while the
                              request stays approved)

Business rules encoded here (see docs/PHASE5.md):

- range semantics: request/allocation periods are INCLUSIVE on both ends
  (daterange '[) is NOT used here - '[]' matches the service-layer overlap
  checks); statutory windows are [effective_from, effective_to) with
  NULL end = open-ended, so adjacent versions are legal;
- overlapping requests are rejected at the service layer with a stable
  error code (LEAVE_REQUEST_OVERLAP); the EXCLUDE constraints are the
  database-level guarantee;
- no leave_intervals hook, no payroll amounts, no notification/scheduler
  machinery in this phase (carry-forward is an explicit endpoint).

Each table gets FORCE ROW LEVEL SECURITY with the standard tenant policy
(deny-by-default, platform-admin bypass), following the Phase 1-4 pattern.

Seeding notes: the 25 Phase 5 permission codes are declared in
PHASE5_PERMISSIONS below so this frozen migration owns exactly its own
codes. Default-role grants for existing companies are backfilled from the
current DEFAULT_ROLES catalog (idempotent), and the new default
``employee`` role (D4 - self-service leave only) is created for every
existing company that does not have it yet.

Requires the btree_gist extension (created by migration 0004) for the
integer/range EXCLUDE constraints. Not dropped on downgrade: extensions
are cluster-level objects.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.rls import RLS_REGISTRY, policy_sql
from app.core.rls_phase5 import PHASE5_RLS_TABLES, register_phase5_rls
from app.permissions.catalog import DEFAULT_ROLES

revision: str = "0006_phase5_leave"
down_revision: Union[str, None] = "0005_phase4_attendance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen snapshot of the Phase 5 permission codes owned by this migration.
PHASE5_PERMISSIONS: tuple[tuple[str, str, str], ...] = (
    ("leave_type.view", "View leave types", "leave_types"),
    ("leave_type.create", "Create leave types", "leave_types"),
    ("leave_type.update", "Edit leave types", "leave_types"),
    ("leave_type.delete", "Delete leave types", "leave_types"),
    ("leave_allocation.view", "View leave allocations", "leave_allocations"),
    ("leave_allocation.create", "Create leave allocations", "leave_allocations"),
    ("leave_allocation.update", "Edit leave allocations", "leave_allocations"),
    ("leave_allocation.delete", "Delete leave allocations", "leave_allocations"),
    ("leave_allocation.submit", "Submit leave allocations", "leave_allocations"),
    ("leave_allocation.approve", "Approve leave allocations", "leave_allocations"),
    ("leave_allocation.reject", "Reject leave allocations", "leave_allocations"),
    (
        "leave_allocation.carry_forward",
        "Run leave carry-forward",
        "leave_allocations",
    ),
    ("leave_request.view", "View leave requests", "leave_requests"),
    ("leave_request.create", "Create leave requests", "leave_requests"),
    ("leave_request.update", "Edit draft leave requests", "leave_requests"),
    ("leave_request.delete", "Delete draft leave requests", "leave_requests"),
    ("leave_request.submit", "Submit leave requests", "leave_requests"),
    ("leave_request.approve", "Approve leave requests", "leave_requests"),
    ("leave_request.reject", "Reject leave requests", "leave_requests"),
    ("leave_request.cancel", "Cancel leave requests", "leave_requests"),
    ("leave_balance.view", "View employee leave balances", "leave_balances"),
    ("leave_holiday.view", "View company holidays", "leave_holidays"),
    ("leave_holiday.create", "Create company holidays", "leave_holidays"),
    ("leave_holiday.update", "Edit company holidays", "leave_holidays"),
    ("leave_holiday.delete", "Delete company holidays", "leave_holidays"),
)


def upgrade() -> None:
    op.create_table(
        "company_holidays",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name_ar", sa.String(255), nullable=False),
        sa.Column("name_en", sa.String(255), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="active"
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
            "company_id", "date", name="uq_company_holiday_company_date"
        ),
        sa.CheckConstraint(
            "status IN ('active','inactive')", name="ck_company_holiday_status"
        ),
    )

    op.create_table(
        "leave_types",
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
        sa.Column(
            "is_paid", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "requires_approval",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "allocation_requires_approval",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "day_counting_mode",
            sa.String(20),
            nullable=False,
            server_default="working_days",
        ),
        sa.Column(
            "requires_attachment",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("attachment_threshold_days", sa.Numeric(5, 2)),
        sa.Column(
            "requires_reason",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "negative_balance_allowed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("min_request_days", sa.Numeric(5, 2)),
        sa.Column("max_request_days", sa.Numeric(5, 2)),
        sa.Column("default_entitlement_days", sa.Numeric(5, 2)),
        sa.Column(
            "carry_forward_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("carry_forward_max_days", sa.Numeric(5, 2)),
        sa.Column(
            "carry_forward_expiry",
            sa.String(25),
            nullable=False,
            server_default="end_of_next_year",
        ),
        sa.Column(
            "allowance_treatment",
            sa.String(15),
            nullable=False,
            server_default="continue",
        ),
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
        sa.UniqueConstraint("company_id", "code", name="uq_leave_type_company_code"),
        sa.CheckConstraint(
            "status IN ('active','inactive')", name="ck_leave_type_status"
        ),
        sa.CheckConstraint(
            "day_counting_mode IN ('working_days','calendar_days')",
            name="ck_leave_type_day_counting_mode",
        ),
        sa.CheckConstraint(
            "allowance_treatment IN ('continue','deduct','prorate')",
            name="ck_leave_type_allowance_treatment",
        ),
        sa.CheckConstraint(
            "carry_forward_expiry IN ('none','end_of_year','end_of_next_year')",
            name="ck_leave_type_carry_forward_expiry",
        ),
        sa.CheckConstraint(
            "min_request_days IS NULL OR min_request_days > 0",
            name="ck_leave_type_min_request_days",
        ),
        sa.CheckConstraint(
            "max_request_days IS NULL OR max_request_days > 0",
            name="ck_leave_type_max_request_days",
        ),
        sa.CheckConstraint(
            "min_request_days IS NULL OR max_request_days IS NULL "
            "OR min_request_days <= max_request_days",
            name="ck_leave_type_request_days_range",
        ),
        sa.CheckConstraint(
            "default_entitlement_days IS NULL OR default_entitlement_days >= 0",
            name="ck_leave_type_default_entitlement",
        ),
        sa.CheckConstraint(
            "carry_forward_max_days IS NULL OR carry_forward_max_days >= 0",
            name="ck_leave_type_carry_forward_max",
        ),
        sa.CheckConstraint(
            "attachment_threshold_days IS NULL OR attachment_threshold_days > 0",
            name="ck_leave_type_attachment_threshold",
        ),
    )
    op.create_index(
        "ix_leave_type_company_status",
        "leave_types",
        ["company_id", "status"],
    )

    op.create_table(
        "leave_statutory_rules",
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
            name="uq_leave_statutory_rule_version",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_leave_statutory_rule_dates",
        ),
        sa.CheckConstraint(
            "status IN ('active','inactive')",
            name="ck_leave_statutory_rule_status",
        ),
        sa.CheckConstraint(
            "length(trim(source_reference)) > 0",
            name="ck_leave_statutory_rule_source",
        ),
    )
    op.create_index(
        "ix_leave_statutory_rule_company_key",
        "leave_statutory_rules",
        ["company_id", "statutory_key", "effective_from"],
    )
    # Versioned rules may not overlap for the same statutory key. Windows are
    # [effective_from, effective_to) with NULL = open-ended, so adjacent
    # versions (v1 ends where v2 starts) are legal.
    op.execute(
        "ALTER TABLE leave_statutory_rules "
        "ADD CONSTRAINT exq_leave_statutory_rule_no_overlap "
        "EXCLUDE USING gist (company_id WITH =, statutory_key WITH =, "
        "daterange(effective_from, effective_to, '[)') WITH &&)"
    )

    op.create_table(
        "leave_allocations",
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
            "leave_type_id",
            sa.Integer(),
            sa.ForeignKey("leave_types.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("allocated_days", sa.Numeric(5, 2), nullable=False),
        sa.Column(
            "used_days", sa.Numeric(5, 2), nullable=False, server_default="0"
        ),
        sa.Column(
            "source", sa.String(20), nullable=False, server_default="manual"
        ),
        sa.Column(
            "carried_from_id",
            sa.Integer(),
            sa.ForeignKey("leave_allocations.id", ondelete="SET NULL"),
            index=True,
        ),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="approved"
        ),
        sa.Column("reason", sa.Text()),
        sa.Column("decision_reason", sa.String(500)),
        sa.Column(
            "approved_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column(
            "rejected_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("rejected_at", sa.DateTime(timezone=True)),
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
            "period_end >= period_start", name="ck_leave_allocation_period"
        ),
        sa.CheckConstraint(
            "allocated_days > 0", name="ck_leave_allocation_allocated_days"
        ),
        sa.CheckConstraint(
            "used_days >= 0", name="ck_leave_allocation_used_days"
        ),
        sa.CheckConstraint(
            "status IN ('submitted','approved','rejected','revoked')",
            name="ck_leave_allocation_status",
        ),
        sa.CheckConstraint(
            "source IN ('manual','generate','carry_forward','statutory')",
            name="ck_leave_allocation_source",
        ),
    )
    op.create_index(
        "ix_leave_allocation_employee_type",
        "leave_allocations",
        ["employee_id", "leave_type_id", "period_start"],
    )
    op.create_index(
        "ix_leave_allocation_company_status",
        "leave_allocations",
        ["company_id", "status"],
    )
    # One carry-forward row may point at a given source allocation only once.
    op.create_index(
        "uq_leave_allocation_carried_from",
        "leave_allocations",
        ["carried_from_id"],
        unique=True,
        postgresql_where=sa.text("carried_from_id IS NOT NULL"),
    )
    # Period overlap for the same employee + type, ALL statuses (a rejected
    # or revoked period still blocks the window - the service layer mirrors
    # this). Periods are inclusive on both ends, matching the service-layer
    # overlap check (start <= other_end AND end >= other_start).
    op.execute(
        "ALTER TABLE leave_allocations "
        "ADD CONSTRAINT exq_leave_allocation_no_overlap "
        "EXCLUDE USING gist (employee_id WITH =, leave_type_id WITH =, "
        "daterange(period_start, period_end, '[]') WITH &&)"
    )

    op.create_table(
        "leave_requests",
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
            "leave_type_id",
            sa.Integer(),
            sa.ForeignKey("leave_types.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        # Same-day partial leave only (DB CHECK enforces start_date = end_date).
        sa.Column("start_time", sa.Time()),
        sa.Column("end_time", sa.Time()),
        sa.Column("days", sa.Numeric(5, 2), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("attachment_path", sa.String(500)),
        sa.Column("attachment_name", sa.String(255)),
        sa.Column("attachment_mime", sa.String(100)),
        sa.Column("attachment_size", sa.Integer()),
        sa.Column(
            "attachment_uploaded_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("count_details", postgresql.JSONB()),
        sa.Column(
            "submitted_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column(
            "decided_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decision_reason", sa.String(500)),
        sa.Column(
            "cancelled_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("cancel_reason", sa.String(500)),
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
        sa.CheckConstraint("end_date >= start_date", name="ck_leave_request_dates"),
        sa.CheckConstraint(
            "(start_time IS NULL) = (end_time IS NULL)",
            name="ck_leave_request_times_both_or_neither",
        ),
        sa.CheckConstraint(
            "start_time IS NULL OR start_date = end_date",
            name="ck_leave_request_times_single_day",
        ),
        sa.CheckConstraint("days > 0", name="ck_leave_request_days"),
        sa.CheckConstraint(
            "status IN ('draft','submitted','approved','rejected','cancelled')",
            name="ck_leave_request_status",
        ),
    )
    op.create_index(
        "ix_leave_request_company_start",
        "leave_requests",
        ["company_id", "start_date"],
    )
    op.create_index(
        "ix_leave_request_employee_start",
        "leave_requests",
        ["employee_id", "start_date"],
    )
    op.create_index(
        "ix_leave_request_company_status",
        "leave_requests",
        ["company_id", "status"],
    )
    op.create_index(
        "ix_leave_request_company_type",
        "leave_requests",
        ["company_id", "leave_type_id"],
    )
    # Only SUBMITTED/APPROVED requests block a date range (drafts may
    # coexist; rejected/cancelled history does not block). Periods are
    # inclusive on both ends, matching the service-layer overlap check.
    op.execute(
        "ALTER TABLE leave_requests "
        "ADD CONSTRAINT exq_leave_request_no_overlap "
        "EXCLUDE USING gist (employee_id WITH =, "
        "daterange(start_date, end_date, '[]') WITH &&) "
        "WHERE (status IN ('submitted','approved'))"
    )

    op.create_table(
        "leave_consumptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "leave_request_id",
            sa.Integer(),
            sa.ForeignKey("leave_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "leave_allocation_id",
            sa.Integer(),
            sa.ForeignKey("leave_allocations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("days", sa.Numeric(5, 2), nullable=False),
        sa.Column("for_date", sa.Date()),
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
        sa.CheckConstraint("days > 0", name="ck_leave_consumption_days"),
    )
    op.create_index(
        "ix_leave_consumption_allocation",
        "leave_consumptions",
        ["leave_allocation_id"],
    )
    op.create_index(
        "ix_leave_consumption_request",
        "leave_consumptions",
        ["leave_request_id"],
    )

    bind = op.get_bind()
    # alembic never imports app.main, so ensure the Phase 5 rules are part
    # of the registry before applying their policies (idempotent).
    register_phase5_rls()
    for table in PHASE5_RLS_TABLES:
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
    for code, name, module in PHASE5_PERMISSIONS:
        bind.execute(
            postgresql.insert(perm_table)
            .values(code=code, name=name, module=module)
            .on_conflict_do_nothing(index_elements=["code"])
        )

    # D4: every existing company gets the default ``employee`` role
    # (self-service leave only). Idempotent: companies that already have a
    # role with that code are skipped, and companies created later receive
    # it through seed_default_roles.
    bind.execute(
        sa.text(
            "INSERT INTO roles (company_id, name, code, description, created_at, updated_at) "
            "SELECT c.id, 'Employee (Self Service)', 'employee', "
            "'Manages own leave requests only', now(), now() "
            "FROM companies c "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM roles r "
            "  WHERE r.company_id = c.id AND r.code = 'employee'"
            ")"
        )
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
    codes = [code for code, _name, _module in PHASE5_PERMISSIONS]
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
    # Remove the D4 default roles this migration created (cascades their
    # remaining role_permissions and any user assignments).
    bind.execute(sa.text("DELETE FROM roles WHERE code = 'employee'"))
    bind.execute(sa.text("SELECT set_config('app.is_platform_admin','false',true)"))

    for table in (
        "leave_consumptions",
        "leave_requests",
        "leave_allocations",
        "leave_statutory_rules",
        "leave_types",
        "company_holidays",
    ):
        op.drop_table(table)
    # btree_gist is intentionally left in place (cluster-level object).
