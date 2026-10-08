"""phase 4 attendance: work schedules, shifts, assignments, attendance, overtime

Revision ID: 0005_phase4_attendance
Revises: 0004_phase3_employee_lifecycle
Create Date: 2026-10-06

NOTE: alembic stores the revision id in alembic_version.version_num
VARCHAR(32), so the id is abbreviated while the file name keeps the full
phase-4 description.

Adds the Phase 4 attendance-domain tables:

- work_schedules             (company template, per-schedule timezone,
                              versioned by an applicability window;
                              unique (company_id, code, effective_from) plus
                              a gist EXCLUDE constraint preventing two
                              overlapping windows for the same code)
- shifts                     (naive daily window; CHECK start <> end so
                              zero-duration shifts are impossible;
                              crosses_midnight is service-computed)
- work_schedule_days         (ISO weekday rules, Monday=0; plain
                              start/end window OR a pinned shift, both or
                              neither; rest days are is_working = false)
- break_periods              (breaks owned by exactly ONE parent: a
                              schedule day XOR a shift - multiple breaks
                              per parent are supported from day one)
- employee_work_assignments  (effective-dated schedule assignment; partial
                              unique index for a single OPEN assignment per
                              employee and a gist EXCLUDE constraint
                              rejecting overlapping ranges)
- attendance_records         (timezone-aware check-in/check-out instants,
                              work_date in schedule timezone, computed
                              minute columns; partial unique index for one
                              OPEN record per employee and a gist EXCLUDE
                              constraint rejecting overlapping windows)
- overtime_records           (draft -> submitted -> approved/rejected
                              workflow; requested_minutes vs approved_minutes
                              are distinct; no monetary amounts here)

Business rules encoded here (see docs/PHASE4.md):

- overlaps are rejected at the service layer with stable error codes
  (SCHEDULE_ASSIGNMENT_OVERLAP, ATTENDANCE_OVERLAP, ...); the EXCLUDE
  constraints are the database-level guarantee;
- attendance works overnight: check_out > check_in compares instants, so a
  22:00 -> 06:00 shift closes on the next calendar day naturally;
- a completed record always carries a check_out (CHECK), and one OPEN
  record per employee is the partial unique index;
- minute columns (scheduled/worked/break/late/early-leave/overtime
  candidate) are computed by the service at close time and stored for fast
  listing; they stay NULL while the record is open.

Each table gets FORCE ROW LEVEL SECURITY with the standard tenant policy
(deny-by-default, platform-admin bypass), following the Phase 1/2/3
pattern. Break periods inherit the schedule/shift tenant - they are their
own table so RLS, cascades and multi-break rows stay consistent.

Seeding notes: the 24 Phase 4 permission codes are declared in
PHASE4_PERMISSIONS below so this frozen migration owns exactly its own
codes. Default-role grants for existing companies are backfilled from the
current DEFAULT_ROLES catalog (idempotent).

Requires the btree_gist extension (created by migration 0004) for the
integer/range and employee/range EXCLUDE constraints. Not dropped on
downgrade: extensions are cluster-level objects.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.rls import RLS_REGISTRY, policy_sql
from app.core.rls_phase4 import PHASE4_RLS_TABLES, register_phase4_rls
from app.permissions.catalog import DEFAULT_ROLES

revision: str = "0005_phase4_attendance"
down_revision: Union[str, None] = "0004_phase3_employee_lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen snapshot of the Phase 4 permission codes owned by this migration.
PHASE4_PERMISSIONS: tuple[tuple[str, str, str], ...] = (
    ("work_schedule.view", "View work schedules", "work_schedules"),
    ("work_schedule.create", "Create work schedules", "work_schedules"),
    ("work_schedule.update", "Edit work schedules", "work_schedules"),
    ("work_schedule.delete", "Delete work schedules", "work_schedules"),
    ("shift.view", "View shifts", "shifts"),
    ("shift.create", "Create shifts", "shifts"),
    ("shift.update", "Edit shifts", "shifts"),
    ("shift.delete", "Delete shifts", "shifts"),
    (
        "employee_work_assignment.view",
        "View employee work assignments",
        "employee_work_assignments",
    ),
    (
        "employee_work_assignment.create",
        "Create employee work assignments",
        "employee_work_assignments",
    ),
    (
        "employee_work_assignment.update",
        "Edit employee work assignments",
        "employee_work_assignments",
    ),
    (
        "employee_work_assignment.delete",
        "Delete employee work assignments",
        "employee_work_assignments",
    ),
    ("attendance.view", "View attendance records", "attendance"),
    ("attendance.create", "Create attendance records", "attendance"),
    ("attendance.update", "Edit attendance records", "attendance"),
    ("attendance.delete", "Delete attendance records", "attendance"),
    ("attendance.correct", "Correct closed attendance records", "attendance"),
    ("overtime.view", "View overtime requests", "overtime"),
    ("overtime.create", "Create overtime requests", "overtime"),
    ("overtime.update", "Edit draft overtime requests", "overtime"),
    ("overtime.submit", "Submit overtime requests", "overtime"),
    ("overtime.approve", "Approve overtime requests", "overtime"),
    ("overtime.reject", "Reject overtime requests", "overtime"),
    ("overtime.cancel", "Cancel overtime requests", "overtime"),
)


def upgrade() -> None:
    op.create_table(
        "work_schedules",
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
        # Per-schedule timezone: naive shift/day times are interpreted here.
        sa.Column(
            "timezone",
            sa.String(64),
            nullable=False,
            server_default="Asia/Riyadh",
        ),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
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
            "company_id",
            "code",
            "effective_from",
            name="uq_work_schedule_company_code_from",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_work_schedule_date_range",
        ),
        sa.CheckConstraint(
            "status IN ('active','archived')",
            name="ck_work_schedule_status",
        ),
    )
    op.create_index(
        "ix_work_schedule_company_code",
        "work_schedules",
        ["company_id", "code"],
    )
    # Schedule versioning: one code may only cover non-overlapping windows
    # (a second open-ended version of the same code would be ambiguous).
    # Uses code WITH = so different codes can have overlapping windows.
    op.execute(
        "ALTER TABLE work_schedules "
        "ADD CONSTRAINT exq_work_schedule_code_no_overlap "
        "EXCLUDE USING gist (company_id WITH =, code WITH =, "
        "daterange(effective_from, effective_to, '[)') WITH &&)"
    )

    op.create_table(
        "shifts",
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
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        # Service-computed: end_time < start_time means the shift crosses
        # midnight (e.g. 22:00 -> 06:00). Stored for fast display/filtering.
        sa.Column(
            "crosses_midnight",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
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
        sa.UniqueConstraint("company_id", "code", name="uq_shift_company_code"),
        # Zero-duration shifts are invalid regardless of the service layer.
        sa.CheckConstraint("start_time <> end_time", name="ck_shift_time_range"),
        sa.CheckConstraint(
            "status IN ('active','archived')", name="ck_shift_status"
        ),
    )

    op.create_table(
        "work_schedule_days",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "schedule_id",
            sa.Integer(),
            sa.ForeignKey("work_schedules.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # ISO weekday: Monday=0 ... Sunday=6 (Python date.weekday()).
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column(
            "is_working", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("start_time", sa.Time()),
        sa.Column("end_time", sa.Time()),
        sa.Column(
            "shift_id",
            sa.Integer(),
            sa.ForeignKey("shifts.id", ondelete="SET NULL"),
            index=True,
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
            "schedule_id", "weekday", name="uq_work_schedule_day_weekday"
        ),
        sa.CheckConstraint(
            "(start_time IS NULL) = (end_time IS NULL)",
            name="ck_work_schedule_day_times_both_or_neither",
        ),
        sa.CheckConstraint(
            "start_time IS NULL OR start_time <> end_time",
            name="ck_work_schedule_day_time_range",
        ),
        sa.CheckConstraint(
            "weekday BETWEEN 0 AND 6", name="ck_work_schedule_day_weekday"
        ),
    )

    op.create_table(
        "break_periods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "schedule_day_id",
            sa.Integer(),
            sa.ForeignKey("work_schedule_days.id", ondelete="CASCADE"),
            index=True,
        ),
        sa.Column(
            "shift_id",
            sa.Integer(),
            sa.ForeignKey("shifts.id", ondelete="CASCADE"),
            index=True,
        ),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column(
            "is_paid", sa.Boolean(), nullable=False, server_default=sa.true()
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
        # Exactly one parent: a schedule day XOR a shift.
        sa.CheckConstraint(
            "num_nonnulls(schedule_day_id, shift_id) = 1",
            name="ck_break_period_single_parent",
        ),
        sa.CheckConstraint(
            "start_time <> end_time", name="ck_break_period_time_range"
        ),
    )

    op.create_table(
        "employee_work_assignments",
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
            "schedule_id",
            sa.Integer(),
            sa.ForeignKey("work_schedules.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "shift_id",
            sa.Integer(),
            sa.ForeignKey("shifts.id", ondelete="SET NULL"),
            index=True,
        ),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
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
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_work_assignment_date_range",
        ),
    )
    # At most ONE open assignment per employee.
    op.create_index(
        "uq_work_assignment_open",
        "employee_work_assignments",
        ["employee_id"],
        unique=True,
        postgresql_where=sa.text("effective_to IS NULL"),
    )
    op.create_index(
        "ix_work_assignment_employee_effective",
        "employee_work_assignments",
        ["employee_id", "effective_from"],
    )
    # PostgreSQL-native overlap rejection for effective-dated assignments.
    op.execute(
        "ALTER TABLE employee_work_assignments "
        "ADD CONSTRAINT exq_work_assignment_no_overlap "
        "EXCLUDE USING gist (employee_id WITH =, "
        "daterange(effective_from, effective_to, '[)') WITH &&)"
    )

    op.create_table(
        "attendance_records",
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
        # Attendance date derived from check_in in the schedule timezone.
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column(
            "schedule_id",
            sa.Integer(),
            sa.ForeignKey("work_schedules.id", ondelete="SET NULL"),
            index=True,
        ),
        sa.Column(
            "shift_id",
            sa.Integer(),
            sa.ForeignKey("shifts.id", ondelete="SET NULL"),
            index=True,
        ),
        # Timezone-aware instants (UTC on the wire, ISO-8601 with offset).
        sa.Column("check_in", sa.DateTime(timezone=True), nullable=False),
        sa.Column("check_out", sa.DateTime(timezone=True)),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="open",
        ),
        sa.Column(
            "source",
            sa.String(20),
            nullable=False,
            server_default="manual",
        ),
        # Computed at close time; NULL while the record is open.
        sa.Column("scheduled_minutes", sa.Integer()),
        sa.Column("worked_minutes", sa.Integer()),
        sa.Column("break_minutes", sa.Integer()),
        sa.Column("late_minutes", sa.Integer()),
        sa.Column("early_leave_minutes", sa.Integer()),
        sa.Column("overtime_candidate_minutes", sa.Integer()),
        sa.Column("notes", sa.Text()),
        sa.Column("correction_reason", sa.String(500)),
        sa.Column(
            "corrected_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("corrected_at", sa.DateTime(timezone=True)),
        sa.Column(
            "closed_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
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
        sa.CheckConstraint(
            "check_out IS NULL OR check_out > check_in",
            name="ck_attendance_time_range",
        ),
        sa.CheckConstraint(
            "status <> 'completed' OR check_out IS NOT NULL",
            name="ck_attendance_completed_has_checkout",
        ),
        sa.CheckConstraint(
            "status IN ('open','completed','missing_checkout')",
            name="ck_attendance_status",
        ),
        sa.CheckConstraint(
            "source IN ('manual','device','import','api')",
            name="ck_attendance_source",
        ),
    )
    # One OPEN record per employee.
    op.create_index(
        "uq_attendance_open",
        "attendance_records",
        ["employee_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    # List endpoint: date_from/date_to filters within one company.
    op.create_index(
        "ix_attendance_company_work_date",
        "attendance_records",
        ["company_id", "work_date"],
    )
    # Employee detail timeline + overlap pre-checks.
    op.create_index(
        "ix_attendance_employee_checkin",
        "attendance_records",
        ["employee_id", "check_in"],
    )
    # "Currently open" queries skip the closed history entirely.
    op.create_index(
        "ix_attendance_company_open",
        "attendance_records",
        ["company_id"],
        postgresql_where=sa.text("status = 'open'"),
    )
    # Database-level overlap guarantee for every record with a known
    # window (open records are empty until check-out and are covered by
    # uq_attendance_open plus the service-layer pre-check).
    op.execute(
        "ALTER TABLE attendance_records "
        "ADD CONSTRAINT exq_attendance_no_overlap "
        "EXCLUDE USING gist (employee_id WITH =, "
        "tstzrange(check_in, check_out, '[)') WITH &&) "
        "WHERE (check_out IS NOT NULL)"
    )

    op.create_table(
        "overtime_records",
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
            "attendance_id",
            sa.Integer(),
            sa.ForeignKey("attendance_records.id", ondelete="SET NULL"),
            index=True,
        ),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("requested_minutes", sa.Integer(), nullable=False),
        sa.Column("approved_minutes", sa.Integer()),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("reason", sa.String(500)),
        sa.Column("decision_reason", sa.String(500)),
        sa.Column(
            "decided_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column(
            "submitted_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("correction_reason", sa.String(500)),
        sa.Column(
            "corrected_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("corrected_at", sa.DateTime(timezone=True)),
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
        sa.CheckConstraint(
            "requested_minutes > 0 AND requested_minutes <= 1440",
            name="ck_overtime_requested_minutes",
        ),
        sa.CheckConstraint(
            "approved_minutes IS NULL OR "
            "(approved_minutes > 0 AND approved_minutes <= requested_minutes)",
            name="ck_overtime_approved_minutes",
        ),
        sa.CheckConstraint(
            "status IN ('draft','submitted','approved','rejected','cancelled')",
            name="ck_overtime_status",
        ),
    )
    # Workflow dashboard: "pending approvals" scoped to the company.
    op.create_index(
        "ix_overtime_company_status_date",
        "overtime_records",
        ["company_id", "status", "work_date"],
    )
    # Employee overtime history / date filters.
    op.create_index(
        "ix_overtime_employee_date",
        "overtime_records",
        ["employee_id", "work_date"],
    )

    bind = op.get_bind()
    # alembic never imports app.main, so ensure the Phase 4 rules are part
    # of the registry before applying their policies (idempotent).
    register_phase4_rls()
    for table in PHASE4_RLS_TABLES:
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
    for code, name, module in PHASE4_PERMISSIONS:
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
    codes = [code for code, _name, _module in PHASE4_PERMISSIONS]
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
        "overtime_records",
        "attendance_records",
        "employee_work_assignments",
        "break_periods",
        "work_schedule_days",
        "shifts",
        "work_schedules",
    ):
        op.drop_table(table)
    # btree_gist is intentionally left in place (cluster-level object).
