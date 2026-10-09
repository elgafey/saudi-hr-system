from __future__ import annotations

import hashlib
from importlib import util as importlib_util
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import bindparam, create_engine, select, text

from alembic import command
from app.core.rls_phase6 import PHASE6_RLS_TABLES
from app.permissions.catalog import PERMISSIONS
from app.shared.models import Permission, Role, RolePermission
from tests.conftest import BACKEND_DIR, seed_company

pytestmark = pytest.mark.db

# SHA-256 pins: migrations 0001-0006 are frozen upstream history, 0007 is
# this phase's artifact. Editing any frozen file fails these guards.
FROZEN_HASHES = {
    "0001_phase1.py": "5fe83204197a9ffcba377181188a1141fcbaafbc0606490b92ce699150d53e30",
    "0002_security_hardening.py": "2a6bc5292832040757409f42f2ba26ef565539cb671ae11003020f4a458aef8d",
    "0003_phase2_employee_master_data.py": "d5aae7696cb5fc15a0c8ea0e2bd6599375a5c2fb8b596c61fc2eb5d18e5ba324",
    "0004_phase3_employee_lifecycle.py": "798a87c0d92312866a7fa8480d74fd670fa04a43453819eedf4d2f115ffc921a",
    "0005_phase4_attendance_schedules_shifts_overtime.py": "1d3c7d91996c73f6994603d917956753cc9f5261c6bc6eabf5f033e380a6297e",
    "0006_phase5_leave_management.py": "5681ca44c38eed5e08328d8297034dd795202d31c28d22286b160101cf31db7e",
}

PHASE6_HASHES = {
    "0007_phase6_payroll.py": "dd3b88005771d1883fd3f12f01945e87af3a007788ca0776fd83b7ef1c4b9bd0",
}

PAYROLL_CODES = {
    "salary_component.view",
    "salary_component.create",
    "salary_component.update",
    "salary_component.deactivate",
    "salary_assignment.view",
    "salary_assignment.create",
    "salary_assignment.update",
    "payroll_period.view",
    "payroll_period.create",
    "payroll_period.update",
    "payroll_run.view",
    "payroll_run.calculate",
    "payroll_run.review",
    "payroll_run.approve",
    "payroll_run.mark_paid",
    "payroll_run.lock",
    "payroll_adjustment.view",
    "payroll_adjustment.create",
    "payroll_adjustment.approve",
    "payroll_adjustment.reject",
    "payroll_adjustment.void",
    "payroll_deduction.view",
    "payroll_deduction.create",
    "payroll_deduction.update",
    "payroll_statutory_rule.view",
    "payroll_statutory_rule.create",
    "payroll_statutory_rule.deactivate",
    "payroll_export.execute",
}
assert len(PAYROLL_CODES) == 28

OFFICER_CODES = PAYROLL_CODES - {
    "salary_component.deactivate",
    "payroll_run.approve",
    "payroll_run.mark_paid",
    "payroll_run.lock",
    "payroll_adjustment.approve",
    "payroll_adjustment.reject",
    "payroll_adjustment.void",
    "payroll_statutory_rule.create",
    "payroll_statutory_rule.deactivate",
}
assert len(OFFICER_CODES) == 19

AUDITOR_CODES = {
    "salary_component.view",
    "salary_assignment.view",
    "payroll_period.view",
    "payroll_run.view",
    "payroll_adjustment.view",
    "payroll_deduction.view",
    "payroll_statutory_rule.view",
    "payroll_export.execute",
}
assert len(AUDITOR_CODES) == 8

EXPECTED_PAYROLL_GRANTS = {
    "company_admin": PAYROLL_CODES,
    "hr_manager": PAYROLL_CODES,
    "hr_officer": OFFICER_CODES,
    "auditor": AUDITOR_CODES,
    "employee": set(),
}


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


def test_frozen_migration_files_are_unchanged():
    for name, expected in {**FROZEN_HASHES, **PHASE6_HASHES}.items():
        path = Path(BACKEND_DIR / "alembic" / "versions" / name)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == expected, f"{name} was modified"


def test_migration_chain_is_frozen_through_0007():
    script = ScriptDirectory.from_config(_alembic_config())
    assert script.get_current_head() == "0010_phase9_hr_letters"
    revisions = {r.revision: r for r in script.walk_revisions()}
    assert revisions["0006_phase5_leave"].down_revision == ("0005_phase4_attendance")
    assert revisions["0007_phase6_payroll"].down_revision == "0006_phase5_leave"
    assert revisions["0008_phase7_ess"].down_revision == "0007_phase6_payroll"
    assert (
        revisions["0009_phase8_salary_advances"].down_revision
        == "0008_phase7_ess"
    )


def test_phase6_permissions_seeded_exactly(db_session):
    from app.core.rls import clear_context, elevate_for_seed

    elevate_for_seed(db_session)
    db_codes = set(db_session.execute(select(Permission.code)).scalars())
    clear_context(db_session)

    catalog_codes = {code for code, _name, _module in PERMISSIONS}
    assert db_codes == catalog_codes
    assert len(db_codes) == 150  # 45 P1-P3 + 24 P4 + 25 P5 + 28 P6 + 12 P7 + 10 P8 + 6 P9
    assert PAYROLL_CODES <= db_codes
    payroll_owned = [
        c
        for c in db_codes
        if (c.startswith("salary_") or c.startswith("payroll_"))
        and not c.startswith("salary_advance.")
    ]
    assert set(payroll_owned) == PAYROLL_CODES
    assert len(payroll_owned) == 28


def test_migration_0007_owns_payroll_permission_snapshot():
    path = BACKEND_DIR / "alembic" / "versions" / "0007_phase6_payroll.py"
    spec = importlib_util.spec_from_file_location("m0007", path)
    module = importlib_util.module_from_spec(spec)
    spec.loader.exec_module(module)
    migration_codes = {code for code, _n, _m in module.PHASE6_PERMISSIONS}
    assert migration_codes == PAYROLL_CODES
    assert PAYROLL_CODES <= {code for code, _n, _m in PERMISSIONS}


def _role_perms(db, company, role_code) -> set[str]:
    role = db.execute(
        select(Role).where(Role.company_id == company.id, Role.code == role_code)
    ).scalar_one()
    return set(
        db.execute(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role.id)
        ).scalars()
    )


def test_default_roles_payroll_grants_match_plan(db_session):
    from app.core.rls import clear_context, elevate_for_seed

    company = seed_company(db_session, "P6 Role Grants Co")
    elevate_for_seed(db_session)
    grants = {
        code: _role_perms(db_session, company, code) & PAYROLL_CODES
        for code in EXPECTED_PAYROLL_GRANTS
    }
    employee_all = _role_perms(db_session, company, "employee")
    clear_context(db_session)

    for role_code, expected in EXPECTED_PAYROLL_GRANTS.items():
        assert grants[role_code] == expected, role_code
    assert employee_all & PAYROLL_CODES == set()


def test_phase6_constraints_exist(db_session):
    from app.core.rls import clear_context, elevate_for_seed

    elevate_for_seed(db_session)

    for conname, relname in (
        ("exq_salary_assignment_no_overlap", "employee_salary_assignments"),
        ("exq_payroll_period_no_overlap", "payroll_periods"),
        (
            "exq_payroll_statutory_rule_no_overlap",
            "payroll_statutory_rules",
        ),
        ("ck_payroll_adjustment_amount", "payroll_adjustments"),
        ("ck_payroll_deduction_amount", "payroll_deduction_rules"),
    ):
        count = db_session.execute(
            text(
                "SELECT count(*) FROM pg_constraint "
                "WHERE conname = :name "
                "AND conrelid = CAST(:rel AS regclass)"
            ),
            {"name": conname, "rel": relname},
        ).scalar_one()
        assert count == 1, f"{conname} missing on {relname}"

    for indexname, fragment in (
        ("uq_salary_assignment_open", "effective_to IS NULL"),
        ("uq_payroll_run_active", "status"),
    ):
        indexdef = db_session.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = :name"),
            {"name": indexname},
        ).scalar_one()
        assert "UNIQUE" in indexdef, indexname
        assert fragment in indexdef, indexname

    legal_default = db_session.execute(
        text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name = 'payroll_statutory_rules' "
            "AND column_name = 'requires_legal_verification'"
        )
    ).scalar_one()
    assert "true" in legal_default.lower()

    clear_context(db_session)


def test_phase6_tables_have_forced_rls_policies(db_session):
    from app.core.rls import clear_context, elevate_for_seed

    elevate_for_seed(db_session)
    for table in PHASE6_RLS_TABLES:
        row = db_session.execute(
            text(
                "SELECT c.relrowsecurity, c.relforcerowsecurity, "
                "       count(p.polname) AS policies "
                "FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "LEFT JOIN pg_policy p ON p.polrelid = c.oid "
                "WHERE c.relname = :table "
                "  AND p.polname = :policy "
                "GROUP BY c.relrowsecurity, c.relforcerowsecurity"
            ),
            {"table": table, "policy": f"{table}_tenant_isolation"},
        ).first()
        assert row is not None, f"policy missing for {table}"
        assert row.relrowsecurity and row.relforcerowsecurity, table
        assert row.policies == 1, table
    clear_context(db_session)


def test_0007_downgrade_and_upgrade_roundtrip(db_schema):
    cfg = _alembic_config()

    command.downgrade(cfg, "0006_phase5_leave")

    engine = create_engine(db_schema, future=True)
    try:
        with engine.connect() as conn:
            version = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert version == "0006_phase5_leave", version
            payroll_leftover = conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_name IN "
                    "('salary_components','employee_salary_assignments',"
                    "'salary_assignment_components','payroll_periods',"
                    "'payroll_runs','payroll_run_lines','payslip_lines',"
                    "'payroll_deduction_rules','payroll_adjustments',"
                    "'payroll_statutory_rules')"
                )
            ).scalar_one()
            assert payroll_leftover == 0, payroll_leftover
            permissions_left = conn.execute(
                text(
                    "SELECT count(*) FROM permissions WHERE code IN :codes"
                ).bindparams(bindparam("codes", expanding=True)),
                {"codes": tuple(sorted(PAYROLL_CODES))},
            ).scalar_one()
            assert permissions_left == 0, permissions_left
    finally:
        engine.dispose()

    command.upgrade(cfg, "head")

    engine = create_engine(db_schema, future=True)
    try:
        with engine.connect() as conn:
            version = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert version == "0010_phase9_hr_letters", version
            payroll_restored = conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_name IN "
                    "('salary_components','employee_salary_assignments',"
                    "'salary_assignment_components','payroll_periods',"
                    "'payroll_runs','payroll_run_lines','payslip_lines',"
                    "'payroll_deduction_rules','payroll_adjustments',"
                    "'payroll_statutory_rules')"
                )
            ).scalar_one()
            assert payroll_restored == 10, payroll_restored
            permissions_restored = conn.execute(
                text(
                    "SELECT count(*) FROM permissions WHERE code IN :codes"
                ).bindparams(bindparam("codes", expanding=True)),
                {"codes": tuple(sorted(PAYROLL_CODES))},
            ).scalar_one()
            assert permissions_restored == 28, permissions_restored
    finally:
        engine.dispose()
