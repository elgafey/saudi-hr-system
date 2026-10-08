from __future__ import annotations

from app.core.rls import company_scoped

# Phase 4 tenant tables (attendance domain). Registered separately from
# app.shared.models so that a fresh `alembic upgrade` runs 0001_phase1 with
# only the Phase 1 registry (0001 applies policies for every registered
# table, and the Phase 4 tables do not exist until 0005).
#
# Registration is idempotent (dict overwrite). Callers:
# - app.main / app.cli        -> runtime registry (health endpoint, apply-rls)
# - migration 0005            -> policies for the new tables
# - tests/test_rls_unit.py    -> standalone registry assertions
PHASE4_RLS_TABLES: tuple[str, ...] = (
    "work_schedules",
    "work_schedule_days",
    "break_periods",
    "shifts",
    "employee_work_assignments",
    "attendance_records",
    "overtime_records",
)


def register_phase4_rls() -> None:
    for table in PHASE4_RLS_TABLES:
        company_scoped(table)
