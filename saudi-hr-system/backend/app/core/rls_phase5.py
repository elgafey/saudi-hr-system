from __future__ import annotations

from app.core.rls import company_scoped

# Phase 5 tenant tables (leave domain). Registered separately from
# app.shared.models so that a fresh `alembic upgrade` runs 0001_phase1 with
# only the Phase 1 registry (0001 applies policies for every registered
# table, and the Phase 5 tables do not exist until 0006).
#
# Registration is idempotent (dict overwrite). Callers:
# - app.main / app.cli        -> runtime registry (health endpoint, apply-rls)
# - migration 0006            -> policies for the new tables
# - tests/conftest.py         -> hidden during the 0001 upgrade window
# - tests/test_rls_unit.py    -> standalone registry assertions
PHASE5_RLS_TABLES: tuple[str, ...] = (
    "company_holidays",
    "leave_types",
    "leave_statutory_rules",
    "leave_allocations",
    "leave_requests",
    "leave_consumptions",
)


def register_phase5_rls() -> None:
    for table in PHASE5_RLS_TABLES:
        company_scoped(table)
