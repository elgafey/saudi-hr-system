from __future__ import annotations

from app.core.rls import company_scoped

# Phase 9 tenant tables (HR letters).
# Registered separately from app.shared.models so that a fresh
# `alembic upgrade` runs 0001_phase1 with only the Phase 1 registry (0001
# applies policies for every registered table, and the Phase 9 tables do
# not exist until 0010).
#
# Registration is idempotent (dict overwrite). Callers:
# - app.main / app.cli        -> runtime registry (health endpoint, apply-rls)
# - migration 0010            -> policies for the new tables
# - tests/conftest.py         -> hidden during the 0001 upgrade window
# - tests/test_rls_unit.py    -> standalone registry assertions
PHASE9_RLS_TABLES: tuple[str, ...] = (
    "hr_letters",
    "hr_letter_events",
)


def register_phase9_rls() -> None:
    for table in PHASE9_RLS_TABLES:
        company_scoped(table)
