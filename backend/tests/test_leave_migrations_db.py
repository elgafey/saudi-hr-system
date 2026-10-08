from __future__ import annotations

import hashlib
from importlib import util as importlib_util
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, select, text

from alembic import command
from app.core.rls_phase5 import PHASE5_RLS_TABLES
from app.permissions.catalog import PERMISSIONS
from app.shared.models import Permission, Role, RolePermission
from tests.conftest import BACKEND_DIR, seed_company

pytestmark = pytest.mark.db

# SHA-256 pins: migrations 0001-0005 are frozen upstream history, 0006 is
# this phase's artifact. Editing any frozen file fails these guards.
FROZEN_HASHES = {
    "0001_phase1.py": "5fe83204197a9ffcba377181188a1141fcbaafbc0606490b92ce699150d53e30",
    "0002_security_hardening.py": "2a6bc5292832040757409f42f2ba26ef565539cb671ae11003020f4a458aef8d",
    "0003_phase2_employee_master_data.py": "d5aae7696cb5fc15a0c8ea0e2bd6599375a5c2fb8b596c61fc2eb5d18e5ba324",
    "0004_phase3_employee_lifecycle.py": "798a87c0d92312866a7fa8480d74fd670fa04a43453819eedf4d2f115ffc921a",
    "0005_phase4_attendance_schedules_shifts_overtime.py": "1d3c7d91996c73f6994603d917956753cc9f5261c6bc6eabf5f033e380a6297e",
}

LEAVE_CODES = {
    "leave_type.view",
    "leave_type.create",
    "leave_type.update",
    "leave_type.delete",
    "leave_allocation.view",
    "leave_allocation.create",
    "leave_allocation.update",
    "leave_allocation.delete",
    "leave_allocation.submit",
    "leave_allocation.approve",
    "leave_allocation.reject",
    "leave_allocation.carry_forward",
    "leave_request.view",
    "leave_request.create",
    "leave_request.update",
    "leave_request.delete",
    "leave_request.submit",
    "leave_request.approve",
    "leave_request.reject",
    "leave_request.cancel",
    "leave_balance.view",
    "leave_holiday.view",
    "leave_holiday.create",
    "leave_holiday.update",
    "leave_holiday.delete",
}

EXPECTED_LEAVE_GRANTS = {
    "company_admin": LEAVE_CODES,
    "hr_manager": {
        "leave_type.view",
        "leave_type.create",
        "leave_type.update",
        "leave_allocation.view",
        "leave_allocation.create",
        "leave_allocation.update",
        "leave_allocation.submit",
        "leave_allocation.approve",
        "leave_allocation.carry_forward",
        "leave_request.view",
        "leave_request.create",
        "leave_request.update",
        "leave_request.submit",
        "leave_request.approve",
        "leave_request.reject",
        "leave_request.cancel",
        "leave_balance.view",
        "leave_holiday.view",
        "leave_holiday.create",
        "leave_holiday.update",
    },
    "hr_officer": {
        "leave_type.view",
        "leave_allocation.view",
        "leave_allocation.create",
        "leave_allocation.submit",
        "leave_request.view",
        "leave_request.create",
        "leave_request.update",
        "leave_request.submit",
        "leave_request.cancel",
        "leave_balance.view",
        "leave_holiday.view",
    },
    "auditor": {
        "leave_type.view",
        "leave_allocation.view",
        "leave_request.view",
        "leave_balance.view",
        "leave_holiday.view",
    },
    # The default self-service role (D4): request verbs only.
    "employee": {
        "leave_request.create",
        "leave_request.update",
        "leave_request.submit",
        "leave_request.cancel",
    },
}


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


def test_frozen_migration_files_are_unchanged():
    for name, expected in FROZEN_HASHES.items():
        path = Path(BACKEND_DIR / "alembic" / "versions" / name)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == expected, f"{name} was modified"


def test_migration_0006_is_head_and_child_of_0005():
    script = ScriptDirectory.from_config(_alembic_config())
    assert script.get_current_head() == "0009_phase8_salary_advances"
    revisions = {r.revision: r for r in script.walk_revisions()}
    assert (
        revisions["0006_phase5_leave"].down_revision
        == "0005_phase4_attendance"
    )
    assert revisions["0007_phase6_payroll"].down_revision == "0006_phase5_leave"
    assert revisions["0008_phase7_ess"].down_revision == "0007_phase6_payroll"
    assert (
        revisions["0009_phase8_salary_advances"].down_revision
        == "0008_phase7_ess"
    )


def test_phase5_permissions_seeded_exactly(db_session):
    from app.core.rls import clear_context, elevate_for_seed

    elevate_for_seed(db_session)
    db_codes = set(db_session.execute(select(Permission.code)).scalars())
    clear_context(db_session)

    catalog_codes = {code for code, _name, _module in PERMISSIONS}
    assert db_codes == catalog_codes
    assert len(db_codes) == 144  # 45 P1-P3 + 24 P4 + 25 P5 + 28 P6 + 12 P7 + 10 P8
    assert LEAVE_CODES <= db_codes
    assert len([c for c in db_codes if c.startswith("leave_")]) == 25


def test_migration_0006_owns_leave_permission_snapshot():
    path = BACKEND_DIR / "alembic" / "versions" / "0006_phase5_leave_management.py"
    spec = importlib_util.spec_from_file_location("m0006", path)
    module = importlib_util.module_from_spec(spec)
    spec.loader.exec_module(module)
    migration_codes = {code for code, _n, _m in module.PHASE5_PERMISSIONS}
    assert migration_codes == LEAVE_CODES
    assert LEAVE_CODES <= {code for code, _n, _m in PERMISSIONS}


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


def test_default_roles_leave_grants_match_plan(db_session):
    from app.core.rls import clear_context, elevate_for_seed

    company = seed_company(db_session, "P5 Role Grants Co")
    elevate_for_seed(db_session)
    grants = {
        code: _role_perms(db_session, company, code)
        & LEAVE_CODES
        for code in EXPECTED_LEAVE_GRANTS
    }
    clear_context(db_session)

    for role_code, expected in EXPECTED_LEAVE_GRANTS.items():
        assert grants[role_code] == expected, role_code

    # The default self-service role gains exactly the Phase 7 ESS codes
    # on top of the four leave verbs, plus the Phase 8 advance paperwork
    # verbs (nothing else).
    elevate_for_seed(db_session)
    employee_all = _role_perms(db_session, company, "employee")
    clear_context(db_session)
    assert employee_all - LEAVE_CODES == {
        "ess.profile.view",
        "ess.document.view",
        "ess.attendance.view",
        "ess.payslip.view",
        "employee_request.create",
        "employee_request.update",
        "employee_request.submit",
        "employee_request.cancel",
        "salary_advance.create",
        "salary_advance.update",
        "salary_advance.submit",
        "salary_advance.cancel",
    }


def test_phase5_constraints_exist(db_session):
    from app.core.rls import clear_context, elevate_for_seed

    elevate_for_seed(db_session)

    for conname, relname in (
        ("exq_leave_request_no_overlap", "leave_requests"),
        ("exq_leave_allocation_no_overlap", "leave_allocations"),
        ("exq_leave_statutory_rule_no_overlap", "leave_statutory_rules"),
        ("ck_leave_statutory_rule_source", "leave_statutory_rules"),
        ("uq_leave_type_company_code", "leave_types"),
        ("uq_leave_statutory_rule_version", "leave_statutory_rules"),
        ("uq_company_holiday_company_date", "company_holidays"),
        ("ck_leave_allocation_period", "leave_allocations"),
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

    carried_index = db_session.execute(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE indexname = 'uq_leave_allocation_carried_from'"
        )
    ).scalar_one()
    assert "UNIQUE" in carried_index
    assert "carried_from_id IS NOT NULL" in carried_index

    legal_default = db_session.execute(
        text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name = 'leave_statutory_rules' "
            "AND column_name = 'requires_legal_verification'"
        )
    ).scalar_one()
    assert "true" in legal_default.lower()

    clear_context(db_session)


def test_phase5_tables_have_forced_rls_policies(db_session):
    from app.core.rls import clear_context, elevate_for_seed

    elevate_for_seed(db_session)
    for table in PHASE5_RLS_TABLES:
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


def test_0006_downgrade_and_upgrade_roundtrip(db_schema):
    cfg = _alembic_config()

    command.downgrade(cfg, "0005_phase4_attendance")

    engine = create_engine(db_schema, future=True)
    try:
        with engine.connect() as conn:
            version = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert version == "0005_phase4_attendance", version
            leftover = conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_name = 'leave_types'"
                )
            ).scalar_one()
            assert leftover == 0
            # Phase 6 tables are dropped as part of the same roundtrip.
            payroll_leftover = conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_name = 'payroll_periods'"
                )
            ).scalar_one()
            assert payroll_leftover == 0
    finally:
        engine.dispose()

    command.upgrade(cfg, "head")

    engine = create_engine(db_schema, future=True)
    try:
        with engine.connect() as conn:
            version = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert version == "0009_phase8_salary_advances", version
            restored = conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_name IN "
                    "('leave_types','leave_statutory_rules',"
                    "'leave_allocations','leave_requests',"
                    "'leave_consumptions','company_holidays')"
                )
            ).scalar_one()
            assert restored == 6, restored
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
    finally:
        engine.dispose()
