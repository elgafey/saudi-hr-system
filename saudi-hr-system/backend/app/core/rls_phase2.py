from __future__ import annotations

from app.core.rls import company_scoped

# Phase 2 tenant tables. Registered separately from app.shared.models so
# that a fresh `alembic upgrade` runs 0001_phase1 with only the Phase 1
# registry (0001 applies policies for every registered table, and the
# Phase 2 tables do not exist until 0003).
#
# Registration is idempotent (dict overwrite). Callers:
# - app.main / app.cli        -> runtime registry (health endpoint, apply-rls)
# - migration 0003            -> policies for the new tables
# - tests/test_rls_unit.py    -> standalone registry assertions
PHASE2_RLS_TABLES: tuple[str, ...] = (
    "departments",
    "job_positions",
    "job_grades",
    "employees",
)


def register_phase2_rls() -> None:
    for table in PHASE2_RLS_TABLES:
        company_scoped(table)
