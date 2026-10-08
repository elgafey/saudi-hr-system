from __future__ import annotations

from app.core.rls import company_scoped

# Phase 8 tenant tables (salary advances).
# Registered separately from app.shared.models so that a fresh
# `alembic upgrade` runs 0001_phase1 with only the Phase 1 registry (0001
# applies policies for every registered table, and the Phase 8 tables do
# not exist until 0009).
#
# Registration is idempotent (dict overwrite). Callers:
# - app.main / app.cli        -> runtime registry (health endpoint, apply-rls)
# - migration 0009            -> policies for the new tables
# - tests/conftest.py         -> hidden during the 0001 upgrade window
# - tests/test_rls_unit.py    -> standalone registry assertions
PHASE8_RLS_TABLES: tuple[str, ...] = (
    "salary_advances",
    "salary_advance_events",
)


def register_phase8_rls() -> None:
    for table in PHASE8_RLS_TABLES:
        company_scoped(table)
