from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import select, text

from app.permissions.catalog import DEFAULT_ROLES, PERMISSIONS
from app.shared.models import Permission, Role, RolePermission
from tests.conftest import BACKEND_DIR, seed_company

pytestmark = pytest.mark.db

# SHA-256 pins for the FROZEN Phase 1 / hardening / Phase 2 migrations.
# Phase 3 must never edit these files; any change fails this guard.
FROZEN_HASHES = {
    "0001_phase1.py": "5fe83204197a9ffcba377181188a1141fcbaafbc0606490b92ce699150d53e30",
    "0002_security_hardening.py": "2a6bc5292832040757409f42f2ba26ef565539cb671ae11003020f4a458aef8d",
    "0003_phase2_employee_master_data.py": "d5aae7696cb5fc15a0c8ea0e2bd6599375a5c2fb8b596c61fc2eb5d18e5ba324",
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


def test_migration_chain_is_0001_to_0009():
    script = ScriptDirectory.from_config(_alembic_config())
    assert script.get_current_head() == "0010_phase9_hr_letters"

    revisions = {r.revision: r for r in script.walk_revisions()}
    assert revisions["0001_phase1"].down_revision is None
    assert revisions["0002_security_hardening"].down_revision == "0001_phase1"
    assert (
        revisions["0003_phase2_employee_master_data"].down_revision
        == "0002_security_hardening"
    )
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


def test_alembic_check_reports_no_pending_operations():
    from alembic import command

    command.check(_alembic_config())


def test_permissions_table_matches_catalog(db_session):
    db_codes = set(db_session.execute(select(Permission.code)).scalars())
    catalog_codes = {code for code, _name, _module in PERMISSIONS}
    assert db_codes == catalog_codes
    # 16 Phase 1 + 16 Phase 2 + 13 Phase 3 + 24 Phase 4 + 25 Phase 5
    # + 28 Phase 6 + 12 Phase 7 + 10 Phase 8
    assert len(db_codes) == 150  # 45 P1-P3 + 24 P4 + 25 P5 + 28 P6 + 12 P7 + 10 P8 + 6 P9


def test_phase2_permission_codes_are_seeded(db_session):
    codes = set(db_session.execute(select(Permission.code)).scalars())
    for expected in (
        "department.read",
        "department.create",
        "department.update",
        "department.delete",
        "job_position.read",
        "job_position.create",
        "job_position.update",
        "job_position.delete",
        "job_grade.read",
        "job_grade.create",
        "job_grade.update",
        "job_grade.delete",
        "employee.read",
        "employee.create",
        "employee.update",
        "employee.delete",
    ):
        assert expected in codes


def test_default_roles_grant_phase2_permissions(db_session):
    from app.core.rls import clear_context, elevate_for_seed

    company = seed_company(db_session, "Role Grants Co")
    elevate_for_seed(db_session)

    role_perms: dict[str, set[str]] = {}
    for role_code, _n, _d, perms in DEFAULT_ROLES:
        role = db_session.execute(
            select(Role).where(
                Role.company_id == company.id, Role.code == role_code
            )
        ).scalar_one()
        rows = db_session.execute(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role.id)
        ).scalars()
        role_perms[role_code] = set(rows)
    clear_context(db_session)

    assert "department.create" in role_perms["hr_manager"]
    assert "employee.delete" not in role_perms["hr_manager"]
    assert "employee.create" in role_perms["hr_officer"]
    assert "department.create" not in role_perms["hr_officer"]
    assert "employee.read" in role_perms["auditor"]
    assert "employee.create" not in role_perms["auditor"]
    # company_admin receives every permission except company.create.
    assert "employee.delete" in role_perms["company_admin"]
    assert "company.create" not in role_perms["company_admin"]


def test_employee_number_sequence_exists(db_session):
    exists = db_session.execute(
        text(
            "SELECT count(*) FROM pg_class WHERE relname = 'employee_number_seq'"
        )
    ).scalar_one()
    assert exists == 1
