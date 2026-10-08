from __future__ import annotations

from app.core.rls import company_scoped

# Phase 7 tenant tables (employee self-service & request/approval).
# Registered separately from app.shared.models so that a fresh
# `alembic upgrade` runs 0001_phase1 with only the Phase 1 registry (0001
# applies policies for every registered table, and the Phase 7 tables do
# not exist until 0008).
#
# Registration is idempotent (dict overwrite). Callers:
# - app.main / app.cli        -> runtime registry (health endpoint, apply-rls)
# - migration 0008            -> policies for the new tables
# - tests/conftest.py         -> hidden during the 0001 upgrade window
# - tests/test_rls_unit.py    -> standalone registry assertions
PHASE7_RLS_TABLES: tuple[str, ...] = (
    "employee_requests",
    "employee_request_events",
    "employee_document_visibility",
)


def register_phase7_rls() -> None:
    for table in PHASE7_RLS_TABLES:
        company_scoped(table)
