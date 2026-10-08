"""phase 7 employee self-service & request/approval framework: employee requests, events, document visibility

Revision ID: 0008_phase7_ess
Revises: 0007_phase6_payroll
Create Date: 2026-10-08

NOTE: alembic stores the revision id in alembic_version.version_num
VARCHAR(32), so the id is abbreviated while the file name keeps the full
phase-7 description.

Adds the Phase 7 ESS/request tables:

- employee_requests                (generic request with an explicit state
                                    machine draft -> submitted -> approved/
                                    rejected/cancelled; JSONB payload
                                    validated against a CLOSED per-type
                                    schema in the service layer; approver is
                                    a snapshot of employees.manager_id taken
                                    at submit time; partial unique index
                                    keeps one open attendance_correction per
                                    employee per day)
- employee_request_events          (append-only, employee-visible history;
                                    rows are only inserted)
- employee_document_visibility     (sidecar default-deny flag: only
                                    explicitly shared documents are visible
                                    to the owning employee; the frozen
                                    employee_documents table is untouched)

Business rules encoded here (see docs/PHASE7.md):

- decision consistency: approved/rejected <=> decided_at IS NOT NULL;
- reject requires a decision reason (DB CHECK, service also enforces);
- no legal values are seeded - this phase adds no statutory data;
- employees only ever touch their own rows (service-layer self scope);
  manager/approver access is authorization-based via permission codes,
  never hardcoded role names.

Each table gets FORCE ROW LEVEL SECURITY with the standard tenant policy
(deny-by-default, platform-admin bypass), following the Phase 1-6 pattern.

Seeding notes: the 12 Phase 7 permission codes are declared in
PHASE7_PERMISSIONS below so this frozen migration owns exactly its own
codes. Default-role grants for existing companies are backfilled from the
current DEFAULT_ROLES catalog (idempotent).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.rls import RLS_REGISTRY, policy_sql
from app.core.rls_phase7 import PHASE7_RLS_TABLES, register_phase7_rls
from app.permissions.catalog import DEFAULT_ROLES

revision: str = "0008_phase7_ess"
down_revision: Union[str, None] = "0007_phase6_payroll"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen snapshot of the Phase 7 permission codes owned by this migration.
PHASE7_PERMISSIONS: tuple[tuple[str, str, str], ...] = (
    ("ess.profile.view", "View own employee profile", "ess"),
    ("ess.document.view", "View own shared documents", "ess"),
    ("ess.attendance.view", "View own attendance records", "ess"),
    ("ess.payslip.view", "View own payslips", "ess"),
    (
        "employee_request.create",
        "Create employee requests",
        "employee_requests",
    ),
    (
        "employee_request.update",
        "Edit draft employee requests",
        "employee_requests",
    ),
    (
        "employee_request.submit",
        "Submit employee requests",
        "employee_requests",
    ),
    (
        "employee_request.cancel",
        "Cancel employee requests",
        "employee_requests",
    ),
    ("employee_request.view", "View employee requests", "employee_requests"),
    (
        "employee_request.approve",
        "Approve employee requests",
        "employee_requests",
    ),
    (
        "employee_request.reject",
        "Reject employee requests",
        "employee_requests",
    ),
    (
        "employee_request.manage",
        "Decide any employee request",
        "employee_requests",
    ),
)


def upgrade() -> None:
    op.create_table(
        "employee_requests",
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
            "approver_employee_id",
            sa.Integer(),
            sa.ForeignKey("employees.id", ondelete="SET NULL"),
            index=True,
        ),
        sa.Column("request_type", sa.String(40), nullable=False),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="draft"
        ),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column(
            "payload", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column("work_date", sa.Date(), index=True),
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
            "attendance_record_id",
            sa.Integer(),
            sa.ForeignKey("attendance_records.id", ondelete="SET NULL"),
            index=True,
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
            "request_type IN "
            "('attendance_correction','hr_letter','document_request','other')",
            name="ck_employee_request_type",
        ),
        sa.CheckConstraint(
            "status IN ('draft','submitted','approved','rejected','cancelled')",
            name="ck_employee_request_status",
        ),
        sa.CheckConstraint(
            "(status = 'approved' OR status = 'rejected') "
            "= (decided_at IS NOT NULL)",
            name="ck_employee_request_decision_consistency",
        ),
        sa.CheckConstraint(
            "status <> 'rejected' OR length(trim(coalesce(decision_reason,''))) > 0",
            name="ck_employee_request_reject_reason",
        ),
    )
    op.create_index(
        "ix_employee_request_company_status",
        "employee_requests",
        ["company_id", "status"],
    )
    op.create_index(
        "ix_employee_request_company_type",
        "employee_requests",
        ["company_id", "request_type"],
    )
    op.create_index(
        "ix_employee_request_employee", "employee_requests", ["employee_id", "status"]
    )
    op.create_index(
        "ix_employee_request_approver",
        "employee_requests",
        ["approver_employee_id", "status"],
    )
    # One open attendance-correction per employee per day (draft or
    # submitted only; decided/cancelled rows release the slot).
    op.create_index(
        "uq_employee_request_attendance_open",
        "employee_requests",
        ["company_id", "employee_id", "work_date"],
        unique=True,
        postgresql_where=sa.text(
            "request_type = 'attendance_correction' "
            "AND status IN ('draft','submitted')"
        ),
    )

    op.create_table(
        "employee_request_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "request_id",
            sa.Integer(),
            sa.ForeignKey("employee_requests.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("actor_name", sa.String(255), nullable=False),
        sa.Column("note", sa.String(500)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN "
            "('created','updated','submitted','approved','rejected','cancelled')",
            name="ck_employee_request_event_type",
        ),
        sa.CheckConstraint(
            "length(trim(actor_name)) > 0", name="ck_employee_request_event_actor"
        ),
    )
    op.create_index(
        "ix_employee_request_event_request",
        "employee_request_events",
        ["request_id", "id"],
    )

    op.create_table(
        "employee_document_visibility",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("employee_documents.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "employee_visible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "updated_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
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
            "employee_visible IN (true, false)",
            name="ck_employee_document_visibility_flag",
        ),
    )

    bind = op.get_bind()
    # alembic never imports app.main, so ensure the Phase 7 rules are part
    # of the registry before applying their policies (idempotent).
    register_phase7_rls()
    for table in PHASE7_RLS_TABLES:
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
    for code, name, module in PHASE7_PERMISSIONS:
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
    codes = [code for code, _name, _module in PHASE7_PERMISSIONS]
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
        "employee_document_visibility",
        "employee_request_events",
        "employee_requests",
    ):
        op.drop_table(table)
