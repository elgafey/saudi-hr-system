"""phase 3 employee lifecycle: documents, contracts, history, user links

Revision ID: 0004_phase3_employee_lifecycle
Revises: 0003_phase2_employee_master_data
Create Date: 2026-10-06

Adds the Phase 3 employee-lifecycle tables:

- employee_document_types    (company-scoped lookup, unique (company_id, code);
                              default types are seeded lazily per company by
                              the document-types service)
- employee_documents         (metadata only; file bytes live in private
                              storage under a server-generated storage_key)
- employee_contracts         (CHECK-controlled status; partial unique index
                              enforcing ONE active contract per employee)
- employee_employment_history (effective-dated, append-only; partial unique
                              index for a single open record per employee and
                              a btree_gist EXCLUDE constraint rejecting any
                              overlapping range)

users.employee_id becomes a real unique FK to employees.id (ON DELETE
SET NULL) - Phase 1 left it as a nullable placeholder. Linking is only
performed through the controlled API; accounts are never auto-created.

Business rules encoded here (see docs/PHASE3.md):

- exactly one ACTIVE contract per employee (uq_employee_contract_active);
  other contract statuses may coexist;
- contract date rules are enforced by CHECK constraints as a backstop to
  the service-layer CONTRACT_INVALID_DATE_RANGE errors;
- employment history never overlaps: service validation produces stable
  error codes, the EXCLUDE constraint is the database-level guarantee.

Each table gets FORCE ROW LEVEL SECURITY with the standard tenant policy
(deny-by-default, platform-admin bypass), following the Phase 1/2 pattern.

Seeding notes: the 13 Phase 3 permission codes are declared in
PHASE3_PERMISSIONS below so this frozen migration owns exactly its own
codes. Default-role grants for existing companies are backfilled from the
current DEFAULT_ROLES catalog (idempotent).

Requires the btree_gist extension (trusted, PostgreSQL 13+) for the
history exclusion constraint. The extension is intentionally NOT dropped on
downgrade: extensions are cluster-level objects and other consumers may
depend on it.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.rls import RLS_REGISTRY, policy_sql
from app.core.rls_phase3 import PHASE3_RLS_TABLES, register_phase3_rls
from app.permissions.catalog import DEFAULT_ROLES

revision: str = "0004_phase3_employee_lifecycle"
down_revision: Union[str, None] = "0003_phase2_employee_master_data"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen snapshot of the Phase 3 permission codes owned by this migration.
PHASE3_PERMISSIONS: tuple[tuple[str, str, str], ...] = (
    ("employee_document.view", "View employee documents", "employee_documents"),
    ("employee_document.create", "Upload employee documents", "employee_documents"),
    (
        "employee_document.update",
        "Edit employee document metadata",
        "employee_documents",
    ),
    ("employee_document.delete", "Delete employee documents", "employee_documents"),
    (
        "employee_document.download",
        "Download employee documents",
        "employee_documents",
    ),
    ("employee_contract.view", "View employee contracts", "employee_contracts"),
    ("employee_contract.create", "Create employee contracts", "employee_contracts"),
    ("employee_contract.update", "Edit employee contracts", "employee_contracts"),
    ("employee_contract.delete", "Delete employee contracts", "employee_contracts"),
    ("employee_history.view", "View employment history", "employee_history"),
    (
        "employee_history.create",
        "Create employment history records",
        "employee_history",
    ),
    ("employee_user_link.view", "View employee account links", "employee_users"),
    (
        "employee_user_link.manage",
        "Link and unlink employee accounts",
        "employee_users",
    ),
)


def upgrade() -> None:
    # btree_gist: trusted extension (PostgreSQL 13+), needed for the
    # integer + range EXCLUDE constraint on employment history.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "employee_document_types",
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
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
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
            "company_id", "code", name="uq_employee_document_type_company_code"
        ),
    )

    op.create_table(
        "employee_documents",
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
            "document_type_id",
            sa.Integer(),
            sa.ForeignKey("employee_document_types.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column("document_number", sa.String(50)),
        sa.Column("issue_date", sa.Date()),
        sa.Column("expiry_date", sa.Date()),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
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
    )

    op.create_table(
        "employee_contracts",
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
        sa.Column("contract_type", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("contract_number", sa.String(50)),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date()),
        sa.Column("signed_date", sa.Date()),
        sa.Column("termination_date", sa.Date()),
        sa.Column("termination_reason", sa.String(500)),
        sa.Column("notes", sa.Text()),
        sa.Column("basic_salary", sa.Numeric(12, 2)),
        sa.Column("currency", sa.String(3), nullable=False, server_default="SAR"),
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
            "company_id", "contract_number", name="uq_employee_contract_company_number"
        ),
        sa.CheckConstraint(
            "status IN ('draft','active','expired','terminated','cancelled')",
            name="ck_employee_contract_status",
        ),
        sa.CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name="ck_employee_contract_end_after_start",
        ),
        sa.CheckConstraint(
            "termination_date IS NULL OR termination_date >= start_date",
            name="ck_employee_contract_termination_after_start",
        ),
        sa.CheckConstraint(
            "end_date IS NULL OR termination_date IS NULL "
            "OR termination_date <= end_date",
            name="ck_employee_contract_termination_within_term",
        ),
    )
    op.create_index(
        "uq_employee_contract_active",
        "employee_contracts",
        ["employee_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "employee_employment_history",
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
        sa.Column(
            "branch_id",
            sa.Integer(),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            index=True,
        ),
        sa.Column(
            "department_id",
            sa.Integer(),
            sa.ForeignKey("departments.id", ondelete="RESTRICT"),
            index=True,
        ),
        sa.Column(
            "position_id",
            sa.Integer(),
            sa.ForeignKey("job_positions.id", ondelete="RESTRICT"),
            index=True,
        ),
        sa.Column(
            "grade_id",
            sa.Integer(),
            sa.ForeignKey("job_grades.id", ondelete="RESTRICT"),
            index=True,
        ),
        sa.Column(
            "manager_id",
            sa.Integer(),
            sa.ForeignKey("employees.id", ondelete="SET NULL"),
            index=True,
        ),
        sa.Column("employment_status", sa.String(20), nullable=False),
        sa.Column("employment_type", sa.String(20), nullable=False),
        sa.Column("change_reason", sa.String(100)),
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
    )
    op.create_index(
        "uq_employee_history_open",
        "employee_employment_history",
        ["employee_id"],
        unique=True,
        postgresql_where=sa.text("effective_to IS NULL"),
    )
    op.create_index(
        "ix_employee_history_effective",
        "employee_employment_history",
        ["employee_id", "effective_from"],
    )
    # PostgreSQL-native overlap rejection for effective-dated records.
    op.execute(
        "ALTER TABLE employee_employment_history "
        "ADD CONSTRAINT exq_employee_history_no_overlap "
        "EXCLUDE USING gist (employee_id WITH =, "
        "daterange(effective_from, effective_to, '[)') WITH &&)"
    )

    # users.employee_id: placeholder index -> unique FK (one account per
    # employee, one employee per user; deleting either side keeps the other).
    op.drop_index("ix_users_employee_id", table_name="users")
    op.create_unique_constraint("users_employee_id_key", "users", ["employee_id"])
    op.create_foreign_key(
        "users_employee_id_fkey",
        "users",
        "employees",
        ["employee_id"],
        ["id"],
        ondelete="SET NULL",
    )

    bind = op.get_bind()
    # alembic never imports app.main, so ensure the Phase 3 rules are part
    # of the registry before applying their policies (idempotent).
    register_phase3_rls()
    for table in PHASE3_RLS_TABLES:
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
    for code, name, module in PHASE3_PERMISSIONS:
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
    codes = [code for code, _name, _module in PHASE3_PERMISSIONS]
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

    # Restore the Phase 1 placeholder state of users.employee_id.
    op.drop_constraint("users_employee_id_fkey", "users", type_="foreignkey")
    op.drop_constraint("users_employee_id_key", "users", type_="unique")
    op.create_index("ix_users_employee_id", "users", ["employee_id"])

    for table in (
        "employee_employment_history",
        "employee_contracts",
        "employee_documents",
        "employee_document_types",
    ):
        op.drop_table(table)
    # btree_gist is intentionally left in place (cluster-level object).
