"""phase 2 employee master data tables, rls policies, permission catalog

Revision ID: 0003_phase2_employee_master_data
Revises: 0002_security_hardening
Create Date: 2026-10-06

Adds the Phase 2 organizational and employee tables:

- departments     (hierarchical via parent_id, unique (company_id, code))
- job_positions   (optional department link, unique (company_id, code))
- job_grades      (unique (company_id, code) and (company_id, level))
- employees       (unique (company_id, employee_number), identity_number
                   and work_email; personal_email deliberately NOT unique)

Each table gets FORCE ROW LEVEL SECURITY with the standard tenant policy
(deny-by-default, platform-admin bypass), following the Phase 1 pattern.

Seeding notes:

- The 16 Phase 2 permission codes are declared in PHASE2_PERMISSIONS below so
  this frozen migration owns exactly its own codes (0001_phase1 owns Phase 1).
- Default-role grants for companies that already exist are backfilled from the
  current DEFAULT_ROLES catalog (idempotent, existing rows untouched). New
  companies created after this migration get the grants from the normal
  seed_default_roles path.
- employee_number_seq is a plain sequence (not an RLS table) used by the
  default pluggable employee-number generator (E{company_id}-{n:06d}).
- Deleting employees that are referenced as managers is handled by the
  application (409) with manager_id ON DELETE SET NULL as a database
  backstop; all other employee FKs are ON DELETE RESTRICT so referenced
  organizations cannot disappear from under their employees.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.rls import RLS_REGISTRY, policy_sql
from app.core.rls_phase2 import PHASE2_RLS_TABLES, register_phase2_rls
from app.permissions.catalog import DEFAULT_ROLES

revision: str = "0003_phase2_employee_master_data"
down_revision: Union[str, None] = "0002_security_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen snapshot of the Phase 2 permission codes owned by this migration.
PHASE2_PERMISSIONS: tuple[tuple[str, str, str], ...] = (
    ("department.read", "View departments", "departments"),
    ("department.create", "Create departments", "departments"),
    ("department.update", "Edit departments", "departments"),
    ("department.delete", "Delete departments", "departments"),
    ("job_position.read", "View job positions", "job_positions"),
    ("job_position.create", "Create job positions", "job_positions"),
    ("job_position.update", "Edit job positions", "job_positions"),
    ("job_position.delete", "Delete job positions", "job_positions"),
    ("job_grade.read", "View job grades", "job_grades"),
    ("job_grade.create", "Create job grades", "job_grades"),
    ("job_grade.update", "Edit job grades", "job_grades"),
    ("job_grade.delete", "Delete job grades", "job_grades"),
    ("employee.read", "View employees", "employees"),
    ("employee.create", "Create employees", "employees"),
    ("employee.update", "Edit employees", "employees"),
    ("employee.delete", "Delete employees", "employees"),
)


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "parent_id",
            sa.Integer(),
            sa.ForeignKey("departments.id", ondelete="RESTRICT"),
            index=True,
        ),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name_ar", sa.String(255), nullable=False),
        sa.Column("name_en", sa.String(255), nullable=False),
        sa.Column("description", sa.String(500)),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="active"
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
        sa.UniqueConstraint("company_id", "code", name="uq_department_company_code"),
    )

    op.create_table(
        "job_positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "department_id",
            sa.Integer(),
            sa.ForeignKey("departments.id", ondelete="RESTRICT"),
            index=True,
        ),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name_ar", sa.String(255), nullable=False),
        sa.Column("name_en", sa.String(255), nullable=False),
        sa.Column("description", sa.String(500)),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="active"
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
            "company_id", "code", name="uq_job_position_company_code"
        ),
    )

    op.create_table(
        "job_grades",
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
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="active"
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
        sa.UniqueConstraint("company_id", "code", name="uq_job_grade_company_code"),
        sa.UniqueConstraint("company_id", "level", name="uq_job_grade_company_level"),
    )

    op.create_table(
        "employees",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
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
            "job_position_id",
            sa.Integer(),
            sa.ForeignKey("job_positions.id", ondelete="RESTRICT"),
            index=True,
        ),
        sa.Column(
            "job_grade_id",
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
        sa.Column("employee_number", sa.String(50), nullable=False),
        sa.Column("first_name_ar", sa.String(100), nullable=False),
        sa.Column("middle_name_ar", sa.String(100)),
        sa.Column("last_name_ar", sa.String(100), nullable=False),
        sa.Column("first_name_en", sa.String(100), nullable=False),
        sa.Column("middle_name_en", sa.String(100)),
        sa.Column("last_name_en", sa.String(100), nullable=False),
        sa.Column("date_of_birth", sa.Date()),
        sa.Column("gender", sa.String(10)),
        sa.Column(
            "nationality", sa.String(2), nullable=False, server_default="SA"
        ),
        sa.Column("personal_email", sa.String(255)),
        sa.Column("work_email", sa.String(255)),
        sa.Column("mobile_phone", sa.String(32)),
        sa.Column("emergency_contact_name", sa.String(255)),
        sa.Column("emergency_contact_phone", sa.String(32)),
        sa.Column("identity_type", sa.String(20)),
        sa.Column("identity_number", sa.String(50)),
        sa.Column("identity_issue_date", sa.Date()),
        sa.Column("identity_expiry_date", sa.Date()),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="draft"
        ),
        sa.Column(
            "employment_type",
            sa.String(20),
            nullable=False,
            server_default="full_time",
        ),
        sa.Column("hire_date", sa.Date()),
        sa.Column("probation_end_date", sa.Date()),
        sa.Column("termination_date", sa.Date()),
        sa.Column("notes", sa.Text()),
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
            "company_id", "employee_number", name="uq_employee_company_number"
        ),
        sa.UniqueConstraint(
            "company_id", "identity_number", name="uq_employee_company_identity"
        ),
        sa.UniqueConstraint(
            "company_id", "work_email", name="uq_employee_company_work_email"
        ),
    )

    op.execute("CREATE SEQUENCE IF NOT EXISTS employee_number_seq START 1")

    bind = op.get_bind()
    # alembic never imports app.main, so ensure the Phase 2 rules are part
    # of the registry before applying their policies (idempotent).
    register_phase2_rls()
    for table in PHASE2_RLS_TABLES:
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
    for code, name, module in PHASE2_PERMISSIONS:
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
    codes = [code for code, _name, _module in PHASE2_PERMISSIONS]
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

    for table in ("employees", "job_grades", "job_positions", "departments"):
        op.drop_table(table)
    op.execute("DROP SEQUENCE IF EXISTS employee_number_seq")
