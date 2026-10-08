from __future__ import annotations

import re

from app.audit import model as audit_model  # noqa: F401 - registers audit_logs RLS
from app.core.rls import RLS_REGISTRY, SQL_FUNCTIONS, policy_sql
from app.core.rls_phase2 import register_phase2_rls
from app.core.rls_phase3 import register_phase3_rls
from app.core.rls_phase4 import register_phase4_rls
from app.core.rls_phase5 import register_phase5_rls
from app.core.rls_phase6 import register_phase6_rls
from app.core.rls_phase7 import register_phase7_rls
from app.core.rls_phase8 import register_phase8_rls
from app.shared.models import Company  # noqa: F401 - registers rules

# Phase 2/3/4/5/6/7/8 rules are registered by app.main at runtime and by
# their migrations; register them here so this unit test is deterministic
# standalone (registration is idempotent).
register_phase2_rls()
register_phase3_rls()
register_phase4_rls()
register_phase5_rls()
register_phase6_rls()
register_phase7_rls()
register_phase8_rls()

EXPECTED_RLS_TABLES = {
    "companies",
    "branches",
    "users",
    "roles",
    "role_permissions",
    "user_roles",
    "audit_logs",
    # Phase 2 (employee master data)
    "departments",
    "job_positions",
    "job_grades",
    "employees",
    # Phase 3 (employee lifecycle)
    "employee_document_types",
    "employee_documents",
    "employee_contracts",
    "employee_employment_history",
    # Phase 4 (attendance domain)
    "work_schedules",
    "work_schedule_days",
    "break_periods",
    "shifts",
    "employee_work_assignments",
    "attendance_records",
    "overtime_records",
    # Phase 5 (leave domain)
    "company_holidays",
    "leave_types",
    "leave_statutory_rules",
    "leave_allocations",
    "leave_requests",
    "leave_consumptions",
    # Phase 6 (payroll domain)
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
    # Phase 7 (ESS domain)
    "employee_requests",
    "employee_request_events",
    "employee_document_visibility",
    # Phase 8 (salary advances)
    "salary_advances",
    "salary_advance_events",
}


def test_registry_covers_all_company_scoped_tables():
    assert set(RLS_REGISTRY.keys()) == EXPECTED_RLS_TABLES


def test_permissions_and_refresh_tokens_are_not_company_scoped():
    assert "permissions" not in RLS_REGISTRY
    assert "refresh_tokens" not in RLS_REGISTRY


def test_policies_are_forced():
    for rule in RLS_REGISTRY.values():
        assert f"ON {rule.table}" in policy_sql(rule)
        assert "USING" in policy_sql(rule)
        assert "WITH CHECK" in policy_sql(rule)
        assert "app.is_platform_admin()" in policy_sql(rule)
        assert "app.current_company_ids()" in policy_sql(rule)


def test_companies_policy_uses_id_column():
    sql = policy_sql(RLS_REGISTRY["companies"])
    assert "id = ANY (app.current_company_ids())" in sql


def test_users_policy_allows_self_read():
    rule = RLS_REGISTRY["users"]
    assert rule.extra_using == "id = app.current_user_id()"


def test_sql_functions_present_and_defensive():
    for fn in ("app.current_company_ids()", "app.is_platform_admin()", "app.current_user_id()"):
        assert f"FUNCTION {fn}" in SQL_FUNCTIONS
    assert "EXCEPTION" in SQL_FUNCTIONS
    assert "current_setting('app.company_ids', true)" in SQL_FUNCTIONS


def test_current_company_ids_handles_garbage_tokens():
    body = SQL_FUNCTIONS.split("app.current_company_ids()")[1]
    assert "part ~ '^[0-9]{1,10}$'" in body
    assert "part <> '0'" in body


def test_policy_sql_renders_extras():
    rule = RLS_REGISTRY["audit_logs"]
    sql = policy_sql(rule)
    assert "actor_user_id = app.current_user_id()" in sql


def test_no_placeholder_future_tables_registered():
    # employee_contracts/employee_documents are live as of Phase 3, the
    # attendance domain is live as of Phase 4, the leave domain is live as
    # of Phase 5 and the payroll domain is live as of Phase 6; gosi remains
    # a future module (its placeholder name must never appear in the
    # registry).
    for name in RLS_REGISTRY:
        assert not re.match(r"^gosi", name)
