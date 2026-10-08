from __future__ import annotations

import hashlib
from importlib import util as importlib_util
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, select, text

from alembic import command
from app.core.rls_phase7 import PHASE7_RLS_TABLES
from app.permissions.catalog import PERMISSIONS
from app.shared.models import Permission, Role, RolePermission
from tests.conftest import BACKEND_DIR, seed_company

pytestmark = pytest.mark.db

# SHA-256 pins: migrations 0001-0007 are frozen upstream history, 0008 is
# this phase's artifact. Editing any frozen file fails these guards.
FROZEN_HASHES = {
    "0001_phase1.py": "5fe83204197a9ffcba377181188a1141fcbaafbc0606490b92ce699150d53e30",
    "0002_security_hardening.py": "2a6bc5292832040757409f42f2ba26ef565539cb671ae11003020f4a458aef8d",
    "0003_phase2_employee_master_data.py": "d5aae7696cb5fc15a0c8ea0e2bd6599375a5c2fb8b596c61fc2eb5d18e5ba324",
    "0004_phase3_employee_lifecycle.py": "798a87c0d92312866a7fa8480d74fd670fa04a43453819eedf4d2f115ffc921a",
    "0005_phase4_attendance_schedules_shifts_overtime.py": "1d3c7d91996c73f6994603d917956753cc9f5261c6bc6eabf5f033e380a6297e",
    "0006_phase5_leave_management.py": "5681ca44c38eed5e08328d8297034dd795202d31c28d22286b160101cf31db7e",
    "0007_phase6_payroll.py": "dd3b88005771d1883fd3f12f01945e87af3a007788ca0776fd83b7ef1c4b9bd0",
}

PHASE7_HASH = (
    "dbbaa5fc2efd5185eaf71d6bbe2649dc05ad3dfef5632570eb8c0886a9378c73"
)

PHASE7_CODES = {
    "ess.profile.view",
    "ess.document.view",
    "ess.attendance.view",
    "ess.payslip.view",
    "employee_request.create",
    "employee_request.update",
    "employee_request.submit",
    "employee_request.cancel",
    "employee_request.view",
    "employee_request.approve",
    "employee_request.reject",
    "employee_request.manage",
}

# Exact Phase 7 grant intersections per default role.
EXPECTED_PHASE7_GRANTS = {
    "company_admin": PHASE7_CODES,
    "hr_manager": PHASE7_CODES,
    "hr_officer": {
        "ess.profile.view",
        "ess.document.view",
        "ess.attendance.view",
        "ess.payslip.view",
        "employee_request.create",
        "employee_request.update",
        "employee_request.submit",
        "employee_request.cancel",
        "employee_request.view",
    },
    "auditor": {"employee_request.view"},
    "employee": {
        "ess.profile.view",
        "ess.document.view",
        "ess.attendance.view",
        "ess.payslip.view",
        "employee_request.create",
        "employee_request.update",
        "employee_request.submit",
        "employee_request.cancel",
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


def test_phase7_migration_artifact_is_unchanged():
    path = Path(BACKEND_DIR / "alembic" / "versions" / "0008_phase7_ess_requests.py")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == PHASE7_HASH, "0008_phase7_ess_requests.py was modified"


def test_migration_0008_is_head_and_child_of_0007():
    script = ScriptDirectory.from_config(_alembic_config())
    assert script.get_current_head() == "0009_phase8_salary_advances"
    revisions = {r.revision: r for r in script.walk_revisions()}
    assert revisions["0007_phase6_payroll"].down_revision == "0006_phase5_leave"
    assert revisions["0008_phase7_ess"].down_revision == "0007_phase6_payroll"
    assert (
        revisions["0009_phase8_salary_advances"].down_revision
        == "0008_phase7_ess"
    )


def test_phase7_permissions_seeded_exactly(db_session):
    from app.core.rls import clear_context, elevate_for_seed

    elevate_for_seed(db_session)
    db_codes = set(db_session.execute(select(Permission.code)).scalars())
    clear_context(db_session)

    catalog_codes = {code for code, _name, _module in PERMISSIONS}
    assert db_codes == catalog_codes
    assert len(db_codes) == 144  # 122 through Phase 6 + 12 P7 + 10 P8
    assert PHASE7_CODES <= db_codes
    assert len([c for c in db_codes if c.startswith("ess.")]) == 4
    assert len([c for c in db_codes if c.startswith("employee_request.")]) == 8


def test_migration_0008_owns_phase7_permission_snapshot():
    path = BACKEND_DIR / "alembic" / "versions" / "0008_phase7_ess_requests.py"
    spec = importlib_util.spec_from_file_location("m0008", path)
    module = importlib_util.module_from_spec(spec)
    spec.loader.exec_module(module)
    migration_codes = {code for code, _n, _m in module.PHASE7_PERMISSIONS}
    assert migration_codes == PHASE7_CODES
    assert PHASE7_CODES <= {code for code, _n, _m in PERMISSIONS}


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


def test_default_roles_phase7_grants_match_plan(db_session):
    from app.core.rls import clear_context, elevate_for_seed

    company = seed_company(db_session, "P7 Role Grants Co")
    elevate_for_seed(db_session)
    grants = {
        code: _role_perms(db_session, company, code) & PHASE7_CODES
        for code in EXPECTED_PHASE7_GRANTS
    }
    clear_context(db_session)

    for role_code, expected in EXPECTED_PHASE7_GRANTS.items():
        assert grants[role_code] == expected, role_code


def test_phase7_constraints_exist(db_session):
    from app.core.rls import clear_context, elevate_for_seed

    elevate_for_seed(db_session)

    for conname, relname in (
        ("ck_employee_request_type", "employee_requests"),
        ("ck_employee_request_status", "employee_requests"),
        ("ck_employee_request_decision_consistency", "employee_requests"),
        ("ck_employee_request_reject_reason", "employee_requests"),
        ("ck_employee_request_event_type", "employee_request_events"),
        ("ck_employee_request_event_actor", "employee_request_events"),
        ("ck_employee_document_visibility_flag", "employee_document_visibility"),
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

    open_index = db_session.execute(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE indexname = 'uq_employee_request_attendance_open'"
        )
    ).scalar_one()
    assert "UNIQUE" in open_index
    assert "status IN ('draft'::employee_request_status" in open_index or (
        "draft" in open_index and "submitted" in open_index
    )
    assert "work_date" in open_index

    visible_default = db_session.execute(
        text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name = 'employee_document_visibility' "
            "AND column_name = 'employee_visible'"
        )
    ).scalar_one()
    assert "false" in visible_default.lower()

    clear_context(db_session)


def test_phase7_tables_have_forced_rls_policies(db_session):
    from app.core.rls import clear_context, elevate_for_seed

    elevate_for_seed(db_session)
    for table in PHASE7_RLS_TABLES:
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


def test_0008_downgrade_and_upgrade_roundtrip(db_schema):
    cfg = _alembic_config()

    command.downgrade(cfg, "0007_phase6_payroll")

    engine = create_engine(db_schema, future=True)
    try:
        with engine.connect() as conn:
            version = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert version == "0007_phase6_payroll", version
            leftover = conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_name IN "
                    "('employee_requests','employee_request_events',"
                    "'employee_document_visibility')"
                )
            ).scalar_one()
            assert leftover == 0, leftover
            permissions_left = conn.execute(
                text("SELECT count(*) FROM permissions")
            ).scalar_one()
            assert permissions_left == 122, permissions_left
            grants_left = conn.execute(
                text(
                    "SELECT count(*) FROM role_permissions rp "
                    "JOIN permissions p ON p.id = rp.permission_id "
                    "WHERE p.code LIKE 'employee_request.%' "
                    "   OR p.code LIKE 'ess.%'"
                )
            ).scalar_one()
            assert grants_left == 0, grants_left
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
                    "('employee_requests','employee_request_events',"
                    "'employee_document_visibility')"
                )
            ).scalar_one()
            assert restored == 3, restored
            permissions_restored = conn.execute(
                text("SELECT count(*) FROM permissions")
            ).scalar_one()
            assert permissions_restored == 144, permissions_restored
    finally:
        engine.dispose()
