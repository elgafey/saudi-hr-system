"""phase 8 salary advances: apply/approve/disburse/repay through payroll deduction rules

Revision ID: 0009_phase8_salary_advances
Revises: 0008_phase7_ess
Create Date: 2026-10-08

NOTE: alembic stores the revision id in alembic_version.version_num
VARCHAR(32), so the id stays within 32 chars while the file name keeps the
full phase-8 description.

Adds the Phase 8 salary-advance tables:

- salary_advances                  (explicit state machine draft ->
                                    submitted -> approved -> disbursed ->
                                    settled, plus rejected/cancelled;
                                    approver is a snapshot of
                                    employees.manager_id taken at submit
                                    time; disbursement links the Phase 6
                                    payroll_deduction_rules row created
                                    through the frozen
                                    create_payroll_deduction service)
- salary_advance_events            (append-only, employee-visible history;
                                    rows are only inserted)

Business rules encoded here (see docs/PHASE8.md):

- amount > 0; installment (when set) > 0 and <= amount;
- decision consistency: approved/rejected/disbursed/settled <=>
  decided_at IS NOT NULL;
  disbursed/settled require decided_at;
- reject requires a decision reason (DB CHECK, service also enforces);
- disbursed requires the linked deduction rule (DB CHECK);
- one advance can never share its repayment rule with another advance
  (UNIQUE on deduction_rule_id; multiple NULLs are allowed);
- no interest, no legal values, no formula engine - repayment reuses the
  frozen Phase 6 installment drawdown;
- employees only ever touch their own rows (service-layer self scope);
  manager/approver access is authorization-based via permission codes,
  never hardcoded role names.

Each table gets FORCE ROW LEVEL SECURITY with the standard tenant policy
(deny-by-default, platform-admin bypass), following the Phase 1-7 pattern.

Seeding notes: the 10 Phase 8 permission codes are declared in
PHASE8_PERMISSIONS below so this migration owns exactly its own codes.
Default-role grants for existing companies are backfilled from the
current DEFAULT_ROLES catalog (idempotent).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.rls import RLS_REGISTRY, policy_sql
from app.core.rls_phase8 import PHASE8_RLS_TABLES, register_phase8_rls
from app.permissions.catalog import DEFAULT_ROLES

revision: str = "0009_phase8_salary_advances"
down_revision: Union[str, None] = "0008_phase7_ess"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen snapshot of the Phase 8 permission codes owned by this migration.
PHASE8_PERMISSIONS: tuple[tuple[str, str, str], ...] = (
    ("salary_advance.view", "View salary advances", "salary_advances"),
    ("salary_advance.create", "Create salary advances", "salary_advances"),
    (
        "salary_advance.update",
        "Edit draft salary advances",
        "salary_advances",
    ),
    ("salary_advance.submit", "Submit salary advances", "salary_advances"),
    ("salary_advance.cancel", "Cancel salary advances", "salary_advances"),
    ("salary_advance.approve", "Approve salary advances", "salary_advances"),
    ("salary_advance.reject", "Reject salary advances", "salary_advances"),
    ("salary_advance.disburse", "Disburse salary advances", "salary_advances"),
    ("salary_advance.settle", "Settle salary advances", "salary_advances"),
    ("salary_advance.manage", "Decide any salary advance", "salary_advances"),
)


def upgrade() -> None:
    op.create_table(
        "salary_advances",
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
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("requested_date", sa.Date(), nullable=False),
        sa.Column("installment_amount", sa.Numeric(12, 2)),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="draft"
        ),
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
            "disbursed_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("disbursed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "settled_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.Column("settle_note", sa.String(500)),
        sa.Column(
            "deduction_rule_id",
            sa.Integer(),
            sa.ForeignKey("payroll_deduction_rules.id", ondelete="SET NULL"),
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
        sa.CheckConstraint("amount > 0", name="ck_salary_advance_amount"),
        sa.CheckConstraint(
            "installment_amount IS NULL OR "
            "(installment_amount > 0 AND installment_amount <= amount)",
            name="ck_salary_advance_installment",
        ),
        sa.CheckConstraint(
            "status IN ('draft','submitted','approved','rejected',"
            "'cancelled','disbursed','settled')",
            name="ck_salary_advance_status",
        ),
        sa.CheckConstraint(
            "(status IN ('approved','rejected','disbursed','settled')) "
            "= (decided_at IS NOT NULL)",
            name="ck_salary_advance_decision_consistency",
        ),
        sa.CheckConstraint(
            "status NOT IN ('disbursed','settled') OR decided_at IS NOT NULL",
            name="ck_salary_advance_decided_before_disburse",
        ),
        sa.CheckConstraint(
            "status <> 'rejected' "
            "OR length(trim(coalesce(decision_reason,''))) > 0",
            name="ck_salary_advance_reject_reason",
        ),
        sa.CheckConstraint(
            "status <> 'disbursed' OR deduction_rule_id IS NOT NULL",
            name="ck_salary_advance_disbursed_rule",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) > 0", name="ck_salary_advance_reason"
        ),
        sa.UniqueConstraint(
            "deduction_rule_id", name="uq_salary_advance_deduction_rule"
        ),
    )
    op.create_index(
        "ix_salary_advance_company_status",
        "salary_advances",
        ["company_id", "status"],
    )
    op.create_index(
        "ix_salary_advance_employee_status",
        "salary_advances",
        ["employee_id", "status"],
    )
    op.create_index(
        "ix_salary_advance_approver",
        "salary_advances",
        ["approver_employee_id", "status"],
    )
    op.create_index(
        "ix_salary_advance_employee_open",
        "salary_advances",
        ["employee_id"],
        postgresql_where=sa.text(
            "status IN ('draft','submitted','approved')"
        ),
    )

    op.create_table(
        "salary_advance_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "advance_id",
            sa.Integer(),
            sa.ForeignKey("salary_advances.id", ondelete="CASCADE"),
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
            "('created','submitted','approved','rejected','cancelled',"
            "'disbursed','settled')",
            name="ck_salary_advance_event_type",
        ),
        sa.CheckConstraint(
            "length(trim(actor_name)) > 0", name="ck_salary_advance_event_actor"
        ),
    )
    op.create_index(
        "ix_salary_advance_event_advance",
        "salary_advance_events",
        ["advance_id", "id"],
    )

    bind = op.get_bind()
    # alembic never imports app.main, so ensure the Phase 8 rules are part
    # of the registry before applying their policies (idempotent).
    register_phase8_rls()
    for table in PHASE8_RLS_TABLES:
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
    for code, name, module in PHASE8_PERMISSIONS:
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
    codes = [code for code, _name, _module in PHASE8_PERMISSIONS]
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
        "salary_advance_events",
        "salary_advances",
    ):
        op.drop_table(table)
