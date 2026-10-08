from __future__ import annotations

from app.core.rls import company_scoped

# Phase 6 tenant tables (payroll domain). Registered separately from
# app.shared.models so that a fresh `alembic upgrade` runs 0001_phase1 with
# only the Phase 1 registry (0001 applies policies for every registered
# table, and the Phase 6 tables do not exist until 0007).
#
# Registration is idempotent (dict overwrite). Callers:
# - app.main / app.cli        -> runtime registry (health endpoint, apply-rls)
# - migration 0007            -> policies for the new tables
# - tests/conftest.py         -> hidden during the 0001 upgrade window
# - tests/test_rls_unit.py    -> standalone registry assertions
PHASE6_RLS_TABLES: tuple[str, ...] = (
    "salary_components",
    "employee_salary_assignments",
    "salary_assignment_components",
    "payroll_periods",
    "payroll_runs",
    "payroll_run_lines",
    "payslip_lines",
    "payroll_deduction_rules",
    "payroll_adjustments",
    "payroll_statutory_rules",
)


def register_phase6_rls() -> None:
    for table in PHASE6_RLS_TABLES:
        company_scoped(table)
