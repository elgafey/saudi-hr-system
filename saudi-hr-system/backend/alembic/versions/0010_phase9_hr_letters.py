"""phase 9 hr letters: employment certificates with an explicit state machine

Revision ID: 0010_phase9_hr_letters
Revises: 0009_phase8_salary_advances
Create Date: 2026-10-09

NOTE: alembic stores the revision id in alembic_version.version_num
VARCHAR(32), so the id stays within 32 chars while the file name keeps the
full phase-9 description.

Adds the Phase 9 HR-letter tables:

- hr_letters                        (draft -> issued -> void, plus
                                     draft -> cancelled; closed
                                     server-assembled JSONB content
                                     snapshot per letter type; optional
                                     link to a Phase 7 approved
                                     hr_letter request with at most one
                                     ACTIVE (draft|issued) letter per
                                     request - partial unique index)
- hr_letter_events                  (append-only, employee-visible
                                     history; rows are only inserted)

Business rules encoded here (see docs/PHASE9.md):

- letter_type IN employment/salary/experience/work_address;
  language IN ar/en; status IN draft/issued/void/cancelled;
- issue metadata exists exactly when the letter reached issued/void
  (void always follows issue);
- void requires a reason (DB CHECK, service also enforces);
- source_request_id: only approved Phase 7 hr_letter requests of the same
  company may be linked (service layer), one active letter per request
  (partial unique index uq_hr_letter_active_request);
- content is a closed server-assembled JSONB snapshot - no client input,
  no PDF/QR, no formula engine, no payroll/statutory writes;
- letters never mutate other domains: read-only snapshots of frozen
  sources (employees, contracts, salary assignments, org data);
- permission codes only - no hardcoded role names anywhere.

Each table gets FORCE ROW LEVEL SECURITY with the standard tenant policy
(deny-by-default, platform-admin bypass), following the Phase 1-8 pattern.

Seeding notes: the 6 Phase 9 permission codes are declared in
PHASE9_PERMISSIONS below so this migration owns exactly its own codes.
Default-role grants for existing companies are backfilled from the
current DEFAULT_ROLES catalog (idempotent) - hr_manager gains all six,
hr_officer gains five (no void), auditor gains hr_letter.view read-only,
employee gains ess.letter.view, company_admin auto-gains all six through
the catalog comprehension.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.rls import RLS_REGISTRY, policy_sql
from app.core.rls_phase9 import PHASE9_RLS_TABLES, register_phase9_rls
from app.permissions.catalog import DEFAULT_ROLES

revision: str = "0010_phase9_hr_letters"
down_revision: Union[str, None] = "0009_phase8_salary_advances"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen snapshot of the Phase 9 permission codes owned by this migration.
PHASE9_PERMISSIONS: tuple[tuple[str, str, str], ...] = (
    ("hr_letter.view", "View HR letters", "hr_letters"),
    ("hr_letter.create", "Create HR letter drafts", "hr_letters"),
    ("hr_letter.update", "Edit or cancel draft HR letters", "hr_letters"),
    ("hr_letter.issue", "Issue HR letters", "hr_letters"),
    ("hr_letter.void", "Void issued HR letters", "hr_letters"),
    ("ess.letter.view", "View own letters", "ess"),
)


def upgrade() -> None:
    op.create_table(
        "hr_letters",
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
        sa.Column("letter_type", sa.String(32), nullable=False),
        sa.Column("language", sa.String(2), nullable=False),
        sa.Column("purpose", sa.String(500)),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default="draft"
        ),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "source_request_id",
            sa.Integer(),
            sa.ForeignKey("employee_requests.id", ondelete="SET NULL"),
            index=True,
        ),
        sa.Column("issued_at", sa.DateTime(timezone=True)),
        sa.Column(
            "issued_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column(
            "cancelled_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("cancel_reason", sa.String(500)),
        sa.Column("voided_at", sa.DateTime(timezone=True)),
        sa.Column(
            "voided_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("void_reason", sa.String(500)),
        sa.Column(
            "created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column(
            "updated_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("version", sa.Integer(), nullable=False),
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
            "letter_type IN "
            "('employment','salary','experience','work_address')",
            name="ck_hr_letter_type",
        ),
        sa.CheckConstraint("language IN ('ar','en')", name="ck_hr_letter_language"),
        sa.CheckConstraint(
            "status IN ('draft','issued','void','cancelled')",
            name="ck_hr_letter_status",
        ),
        sa.CheckConstraint(
            "status IN ('issued','void') = (issued_at IS NOT NULL)",
            name="ck_hr_letter_issued_consistency",
        ),
        sa.CheckConstraint(
            "(status <> 'cancelled') = (cancelled_at IS NULL)",
            name="ck_hr_letter_cancelled_consistency",
        ),
        sa.CheckConstraint(
            "(status <> 'void') = (voided_at IS NULL AND void_reason IS NULL)",
            name="ck_hr_letter_void_consistency",
        ),
        sa.CheckConstraint(
            "status <> 'void' OR length(trim(void_reason)) > 0",
            name="ck_hr_letter_void_reason",
        ),
    )
    op.create_index(
        "ix_hr_letter_company_status",
        "hr_letters",
        ["company_id", "status"],
    )
    op.create_index(
        "ix_hr_letter_company_employee",
        "hr_letters",
        ["company_id", "employee_id"],
    )
    op.create_index(
        "ix_hr_letter_company_created",
        "hr_letters",
        ["company_id", "created_at"],
    )
    op.create_index(
        "uq_hr_letter_active_request",
        "hr_letters",
        ["source_request_id"],
        unique=True,
        postgresql_where=sa.text(
            "source_request_id IS NOT NULL AND status IN ('draft','issued')"
        ),
    )

    op.create_table(
        "hr_letter_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "letter_id",
            sa.Integer(),
            sa.ForeignKey("hr_letters.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("from_status", sa.String(16)),
        sa.Column("to_status", sa.String(16), nullable=False),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("actor_name", sa.String(255), nullable=False),
        sa.Column("note", sa.String(500)),
        sa.Column("ip_address", sa.String(64)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('created','updated','issued','cancelled','voided')",
            name="ck_hr_letter_event_action",
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN "
            "('draft','issued','void','cancelled')",
            name="ck_hr_letter_event_from_status",
        ),
        sa.CheckConstraint(
            "to_status IN ('draft','issued','void','cancelled')",
            name="ck_hr_letter_event_to_status",
        ),
        sa.CheckConstraint(
            "length(trim(actor_name)) > 0", name="ck_hr_letter_event_actor"
        ),
    )
    op.create_index(
        "ix_hr_letter_event_letter",
        "hr_letter_events",
        ["letter_id", "id"],
    )

    bind = op.get_bind()
    # alembic never imports app.main, so ensure the Phase 9 rules are part
    # of the registry before applying their policies (idempotent).
    register_phase9_rls()
    for table in PHASE9_RLS_TABLES:
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
    for code, name, module in PHASE9_PERMISSIONS:
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
    codes = [code for code, _name, _module in PHASE9_PERMISSIONS]
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
        "hr_letter_events",
        "hr_letters",
    ):
        op.drop_table(table)
