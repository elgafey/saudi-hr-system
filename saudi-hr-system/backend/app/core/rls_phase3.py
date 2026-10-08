from __future__ import annotations

from app.core.rls import company_scoped

# Phase 3 tenant tables. Registered separately from app.shared.models so
# that a fresh `alembic upgrade` runs 0001_phase1 with only the Phase 1
# registry (0001 applies policies for every registered table, and the
# Phase 3 tables do not exist until 0004).
#
# Registration is idempotent (dict overwrite). Callers:
# - app.main / app.cli        -> runtime registry (health endpoint, apply-rls)
# - migration 0004            -> policies for the new tables
# - tests/test_rls_unit.py    -> standalone registry assertions
PHASE3_RLS_TABLES: tuple[str, ...] = (
    "employee_document_types",
    "employee_documents",
    "employee_contracts",
    "employee_employment_history",
)


def register_phase3_rls() -> None:
    for table in PHASE3_RLS_TABLES:
        company_scoped(table)
