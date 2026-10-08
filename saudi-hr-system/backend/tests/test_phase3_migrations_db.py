from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import select, text

from app.permissions.catalog import PERMISSIONS
from app.shared.models import Permission, Role, RolePermission
from tests.conftest import BACKEND_DIR, seed_company

pytestmark = pytest.mark.db

# SHA-256 pins: migrations 0001-0003 are frozen upstream history, 0004 is
# this phase's artifact. Editing any of them fails these guards immediately.
FROZEN_HASHES = {
    "0001_phase1.py": "5fe83204197a9ffcba377181188a1141fcbaafbc0606490b92ce699150d53e30",
    "0002_security_hardening.py": "2a6bc5292832040757409f42f2ba26ef565539cb671ae11003020f4a458aef8d",
    "0003_phase2_employee_master_data.py": "d5aae7696cb5fc15a0c8ea0e2bd6599375a5c2fb8b596c61fc2eb5d18e5ba324",
    "0004_phase3_employee_lifecycle.py": "798a87c0d92312866a7fa8480d74fd670fa04a43453819eedf4d2f115ffc921a",
}

PHASE3_CODES = {
    "employee_document.view",
    "employee_document.create",
    "employee_document.update",
    "employee_document.delete",
    "employee_document.download",
    "employee_contract.view",
    "employee_contract.create",
    "employee_contract.update",
    "employee_contract.delete",
    "employee_history.view",
    "employee_history.create",
    "employee_user_link.view",
    "employee_user_link.manage",
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


def test_migration_chain_ends_at_0009():
    script = ScriptDirectory.from_config(_alembic_config())
    assert script.get_current_head() == "0009_phase8_salary_advances"
    revisions = {r.revision: r for r in script.walk_revisions()}
    assert (
        revisions["0004_phase3_employee_lifecycle"].down_revision
        == "0003_phase2_employee_master_data"
    )
    assert (
        revisions["0005_phase4_attendance"].down_revision
        == "0004_phase3_employee_lifecycle"
    )
    assert (
        revisions["0006_phase5_leave"].down_revision
        == "0005_phase4_attendance"
    )
    assert (
        revisions["0007_phase6_payroll"].down_revision
        == "0006_phase5_leave"
    )
    assert (
        revisions["0008_phase7_ess"].down_revision
        == "0007_phase6_payroll"
    )
    assert (
        revisions["0009_phase8_salary_advances"].down_revision
        == "0008_phase7_ess"
    )


def test_phase3_permissions_seeded_exactly(db_session):
    from app.core.rls import clear_context, elevate_for_seed

    elevate_for_seed(db_session)
    db_codes = set(db_session.execute(select(Permission.code)).scalars())
    clear_context(db_session)

    catalog_codes = {code for code, _name, _module in PERMISSIONS}
    assert db_codes == catalog_codes
    assert len(db_codes) == 144  # 45 through Phase 3 + 24 P4 + 25 P5 + 28 P6 + 12 P7 + 10 P8
    assert PHASE3_CODES <= db_codes


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


def test_default_roles_grant_phase3_permissions(db_session):
    from app.core.rls import clear_context, elevate_for_seed

    company = seed_company(db_session, "P3 Role Grants Co")
    elevate_for_seed(db_session)
    grants = {
        code: _role_perms(db_session, company, code)
        for code in ("company_admin", "hr_manager", "hr_officer", "auditor")
    }
    clear_context(db_session)

    for code in PHASE3_CODES:
        assert code in grants["company_admin"], code

    assert "employee_contract.create" in grants["hr_manager"]
    assert "employee_contract.delete" not in grants["hr_manager"]
    assert "employee_document.download" in grants["hr_manager"]
    assert "employee_user_link.manage" in grants["hr_manager"]

    assert "employee_document.create" in grants["hr_officer"]
    assert "employee_document.delete" not in grants["hr_officer"]
    assert "employee_contract.view" in grants["hr_officer"]
    assert "employee_contract.create" not in grants["hr_officer"]
    assert "employee_user_link.view" in grants["hr_officer"]
    assert "employee_user_link.manage" not in grants["hr_officer"]

    assert "employee_document.view" in grants["auditor"]
    assert "employee_document.download" in grants["auditor"]
    assert "employee_document.create" not in grants["auditor"]
    assert "employee_history.view" in grants["auditor"]
    assert "employee_history.create" not in grants["auditor"]
    assert "employee_contract.view" in grants["auditor"]
    assert "employee_contract.delete" not in grants["auditor"]


def test_catalog_defaults_are_exactly_the_seeded_codes(db_session):
    # The frozen migration owns a snapshot tuple; the live catalog must not
    # drift from what 0004 actually seeded.
    from importlib import util as importlib_util

    path = BACKEND_DIR / "alembic" / "versions" / "0004_phase3_employee_lifecycle.py"
    spec = importlib_util.spec_from_file_location("m0004", path)
    module = importlib_util.module_from_spec(spec)
    spec.loader.exec_module(module)
    migration_codes = {code for code, _n, _m in module.PHASE3_PERMISSIONS}
    assert migration_codes == PHASE3_CODES
    assert PHASE3_CODES <= {code for code, _n, _m in PERMISSIONS}


def test_phase3_database_constraints_exist(db_session):
    from app.core.rls import clear_context, elevate_for_seed

    elevate_for_seed(db_session)

    extension = db_session.execute(
        text("SELECT count(*) FROM pg_extension WHERE extname = 'btree_gist'")
    ).scalar_one()
    assert extension == 1

    exclusion = db_session.execute(
        text(
            "SELECT count(*) FROM pg_constraint "
            "WHERE conname = 'exq_employee_history_no_overlap' "
            "AND conrelid = 'employee_employment_history'::regclass"
        )
    ).scalar_one()
    assert exclusion == 1

    active_index = db_session.execute(
        text(
            "SELECT count(*) FROM pg_indexes "
            "WHERE indexname = 'uq_employee_contract_active'"
        )
    ).scalar_one()
    assert active_index == 1

    open_index = db_session.execute(
        text(
            "SELECT count(*) FROM pg_indexes "
            "WHERE indexname = 'uq_employee_history_open'"
        )
    ).scalar_one()
    assert open_index == 1

    user_fk = db_session.execute(
        text(
            "SELECT count(*) FROM pg_constraint "
            "WHERE conname = 'users_employee_id_fkey'"
        )
    ).scalar_one()
    assert user_fk == 1

    user_unique = db_session.execute(
        text(
            "SELECT count(*) FROM pg_constraint "
            "WHERE conname = 'users_employee_id_key'"
        )
    ).scalar_one()
    assert user_unique == 1

    clear_context(db_session)


def test_alembic_check_reports_no_pending_operations():
    from alembic import command

    command.check(_alembic_config())
