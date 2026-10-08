from __future__ import annotations

import hashlib
from importlib import util as importlib_util
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, select, text

from alembic import command
from app.core.rls_phase8 import PHASE8_RLS_TABLES
from app.permissions.catalog import PERMISSIONS
from app.shared.models import Permission, Role, RolePermission
from tests.conftest import BACKEND_DIR, seed_company

pytestmark = pytest.mark.db

# SHA-256 pins: migrations 0001-0008 are frozen upstream history, 0009 is
# this phase's artifact. Editing any frozen file fails these guards.
FROZEN_HASHES = {
    "0001_phase1.py": "5fe83204197a9ffcba377181188a1141fcbaafbc0606490b92ce699150d53e30",
    "0002_security_hardening.py": "2a6bc5292832040757409f42f2ba26ef565539cb671ae11003020f4a458aef8d",
    "0003_phase2_employee_master_data.py": "d5aae7696cb5fc15a0c8ea0e2bd6599375a5c2fb8b596c61fc2eb5d18e5ba324",
    "0004_phase3_employee_lifecycle.py": "798a87c0d92312866a7fa8480d74fd670fa04a43453819eedf4d2f115ffc921a",
    "0005_phase4_attendance_schedules_shifts_overtime.py": "1d3c7d91996c73f6994603d917956753cc9f5261c6bc6eabf5f033e380a6297e",
    "0006_phase5_leave_management.py": "5681ca44c38eed5e08328d8297034dd795202d31c28d22286b160101cf31db7e",
    "0007_phase6_payroll.py": "dd3b88005771d1883fd3f12f01945e87af3a007788ca0776fd83b7ef1c4b9bd0",
    "0008_phase7_ess_requests.py": "dbbaa5fc2efd5185eaf71d6bbe2649dc05ad3dfef5632570eb8c0886a9378c73",
}

# This phase's own migration artifact, pinned once written.
PHASE8_FILE = "0009_phase8_salary_advances.py"
PHASE8_HASH = (
    "00994a0bb8ae5aee333227cf31358e7446ffbb4e572fb94aba6e485723f8341e"
)

ADVANCE_CODES = {
    "salary_advance.view",
    "salary_advance.create",
    "salary_advance.update",
    "salary_advance.submit",
    "salary_advance.cancel",
    "salary_advance.approve",
    "salary_advance.reject",
    "salary_advance.disburse",
    "salary_advance.settle",
    "salary_advance.manage",
}

EXPECTED_ADVANCE_GRANTS = {
    "company_admin": ADVANCE_CODES,
    "hr_manager": ADVANCE_CODES,
    # HR runs the money but never decides: no approve/reject/manage (SoD).
    "hr_officer": {
        "salary_advance.view",
        "salary_advance.create",
        "salary_advance.update",
        "salary_advance.submit",
        "salary_advance.cancel",
        "salary_advance.disburse",
        "salary_advance.settle",
    },
    "auditor": {"salary_advance.view"},
    # The default self-service role: paperwork verbs only.
    "employee": {
        "salary_advance.create",
        "salary_advance.update",
        "salary_advance.submit",
        "salary_advance.cancel",
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


def test_phase8_migration_file_is_unchanged():
    path = Path(BACKEND_DIR / "alembic" / "versions" / PHASE8_FILE)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == PHASE8_HASH, f"{PHASE8_FILE} was modified"


def test_migration_0009_is_head_and_child_of_0008():
    script = ScriptDirectory.from_config(_alembic_config())
    assert script.get_current_head() == "0009_phase8_salary_advances"
    revisions = {r.revision: r for r in script.walk_revisions()}
    assert revisions["0006_phase5_leave"].down_revision == (
        "0005_phase4_attendance"
    )
    assert revisions["0007_phase6_payroll"].down_revision == "0006_phase5_leave"
    assert revisions["0008_phase7_ess"].down_revision == "0007_phase6_payroll"
    assert (
        revisions["0009_phase8_salary_advances"].down_revision
        == "0008_phase7_ess"
    )


def test_phase8_permissions_seeded_exactly(db_session):
    from app.core.rls import clear_context, elevate_for_seed

    elevate_for_seed(db_session)
    db_codes = set(db_session.execute(select(Permission.code)).scalars())
    clear_context(db_session)

    catalog_codes = {code for code, _name, _module in PERMISSIONS}
    assert db_codes == catalog_codes
    assert len(db_codes) == 144  # 45 P1-P3 + 24 P4 + 25 P5 + 28 P6 + 12 P7 + 10 P8
    assert ADVANCE_CODES <= db_codes
    assert len([c for c in db_codes if c.startswith("salary_advance.")]) == 10


def test_migration_0009_owns_phase8_permission_snapshot():
    path = BACKEND_DIR / "alembic" / "versions" / PHASE8_FILE
    spec = importlib_util.spec_from_file_location("m0009", path)
    module = importlib_util.module_from_spec(spec)
    spec.loader.exec_module(module)
    migration_codes = {code for code, _n, _m in module.PHASE8_PERMISSIONS}
    assert migration_codes == ADVANCE_CODES
    assert ADVANCE_CODES <= {code for code, _n, _m in PERMISSIONS}


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


def test_default_roles_advance_grants_match_plan(db_session):
    from app.core.rls import clear_context, elevate_for_seed

    company = seed_company(db_session, "P8 Role Grants Co")
    elevate_for_seed(db_session)
    grants = {
        code: _role_perms(db_session, company, code) & ADVANCE_CODES
        for code in EXPECTED_ADVANCE_GRANTS
    }
    clear_context(db_session)

    for role_code, expected in EXPECTED_ADVANCE_GRANTS.items():
        assert grants[role_code] == expected, role_code


def test_phase8_constraints_exist(db_session):
    from app.core.rls import clear_context, elevate_for_seed

    elevate_for_seed(db_session)

    for conname, relname in (
        ("ck_salary_advance_amount", "salary_advances"),
        ("ck_salary_advance_installment", "salary_advances"),
        ("ck_salary_advance_status", "salary_advances"),
        ("ck_salary_advance_decision_consistency", "salary_advances"),
        ("ck_salary_advance_decided_before_disburse", "salary_advances"),
        ("ck_salary_advance_reject_reason", "salary_advances"),
        ("ck_salary_advance_disbursed_rule", "salary_advances"),
        ("ck_salary_advance_reason", "salary_advances"),
        ("uq_salary_advance_deduction_rule", "salary_advances"),
        ("ck_salary_advance_event_type", "salary_advance_events"),
        ("ck_salary_advance_event_actor", "salary_advance_events"),
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

    unique_index = db_session.execute(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE indexname = 'uq_salary_advance_deduction_rule'"
        )
    ).scalar_one()
    assert "UNIQUE" in unique_index
    assert "deduction_rule_id" in unique_index

    partial_index = db_session.execute(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE indexname = 'ix_salary_advance_employee_open'"
        )
    ).scalar_one()
    assert "WHERE" in partial_index
    assert "draft" in partial_index

    clear_context(db_session)


def test_phase8_tables_have_forced_rls_policies(db_session):
    from app.core.rls import clear_context, elevate_for_seed

    elevate_for_seed(db_session)
    for table in PHASE8_RLS_TABLES:
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


def test_0009_downgrade_and_upgrade_roundtrip(db_schema):
    cfg = _alembic_config()

    command.downgrade(cfg, "0008_phase7_ess")

    engine = create_engine(db_schema, future=True)
    try:
        with engine.connect() as conn:
            version = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert version == "0008_phase7_ess", version
            leftover = conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_name IN "
                    "('salary_advances','salary_advance_events')"
                )
            ).scalar_one()
            assert leftover == 0, leftover
            # The Phase 7 ESS tables stay put during the roundtrip.
            ess_restored = conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_name IN "
                    "('employee_requests','employee_request_events',"
                    "'employee_document_visibility')"
                )
            ).scalar_one()
            assert ess_restored == 3, ess_restored
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
                    "('salary_advances','salary_advance_events')"
                )
            ).scalar_one()
            assert restored == 2, restored
            perms = conn.execute(
                text(
                    "SELECT count(*) FROM permissions "
                    "WHERE code LIKE 'salary_advance%'"
                )
            ).scalar_one()
            assert perms == 10, perms
            policies = conn.execute(
                text(
                    "SELECT count(*) FROM pg_policy WHERE polname IN "
                    "('salary_advances_tenant_isolation',"
                    "'salary_advance_events_tenant_isolation')"
                )
            ).scalar_one()
            assert policies == 2, policies
    finally:
        engine.dispose()
