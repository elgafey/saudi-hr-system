from __future__ import annotations

import pytest
from sqlalchemy import text

from app.core.rls import clear_context, set_context
from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


def test_no_context_means_no_tenant_rows(db_session):
    seed_company(db_session, "Hidden Co")
    clear_context(db_session)
    count = db_session.execute(text("SELECT count(*) FROM companies")).scalar_one()
    assert count == 0


def test_admin_bypass_sees_all_companies(db_session):
    seed_company(db_session, "Visible Co")
    set_context(db_session, user_id=None, company_ids=[], is_platform_admin=True)
    count = db_session.execute(text("SELECT count(*) FROM companies")).scalar_one()
    assert count >= 1
    clear_context(db_session)


def test_member_context_scopes_companies(db_session):
    a = seed_company(db_session, "Isolation A")
    b = seed_company(db_session, "Isolation B")

    set_context(db_session, user_id=None, company_ids=[a.id], is_platform_admin=False)
    rows = db_session.execute(text("SELECT id FROM companies ORDER BY id")).scalars().all()
    assert list(rows) == [a.id]

    set_context(db_session, user_id=None, company_ids=[b.id], is_platform_admin=False)
    rows = db_session.execute(text("SELECT id FROM companies ORDER BY id")).scalars().all()
    assert list(rows) == [b.id]
    clear_context(db_session)


def test_cross_company_insert_blocked_by_rls(db_session):
    a = seed_company(db_session, "Writer A")
    seed_company(db_session, "Writer B")
    set_context(db_session, user_id=None, company_ids=[a.id], is_platform_admin=False)
    with pytest.raises(Exception) as excinfo:
        db_session.execute(
            text(
                "INSERT INTO branches (company_id, name, code, status) "
                "VALUES ((SELECT id FROM companies WHERE name = 'Writer B'), "
                "'Evil', 'EVIL', 'active')"
            )
        )
        db_session.flush()
    assert "row-level security" in str(excinfo.value).lower()
    db_session.rollback()
    clear_context(db_session)


def test_guc_values_never_crash_helper_functions(db_session):
    cases = [
        "NULL",
        "''",
        "'0'",
        "'0,0,0'",
        "'  '",
        "'abc'",
        "'1, two, 3'",
        "'1,,2'",
        "'0007'",
        "'1,2,3'",
        "'99999999999'",
    ]
    for value in cases:
        result = db_session.execute(
            text(
                "SELECT app.current_company_ids() "
                "FROM (SELECT set_config('app.company_ids', "
                + value
                + ", true)) s"
            )
        ).scalar_one()
        assert isinstance(result, list), f"{value} -> {result!r}"
    clear_context(db_session)


def test_helper_functions_tolerate_unset_and_bad_admin_guc(db_session):
    db_session.execute(text("SELECT set_config('app.company_ids', '', true)"))
    assert db_session.execute(text("SELECT app.current_company_ids()")).scalar_one() == []
    assert db_session.execute(text("SELECT app.is_platform_admin()")).scalar_one() is False
    db_session.execute(text("SELECT set_config('app.is_platform_admin', 'yes', true)"))
    assert db_session.execute(text("SELECT app.is_platform_admin()")).scalar_one() is False
    db_session.execute(text("SELECT set_config('app.is_platform_admin', 'true', true)"))
    assert db_session.execute(text("SELECT app.is_platform_admin()")).scalar_one() is True
    clear_context(db_session)


def test_context_does_not_leak_across_transactions(db_session):
    seed_company(db_session, "Leak Co")
    set_context(db_session, user_id=None, company_ids=[], is_platform_admin=True)
    visible = db_session.execute(text("SELECT count(*) FROM companies")).scalar_one()
    assert visible >= 1

    db_session.commit()
    count_after = db_session.execute(text("SELECT count(*) FROM companies")).scalar_one()
    assert count_after == 0


def test_users_self_read_but_not_others(db_session):
    company = seed_company(db_session, "Self Co")
    alice = seed_user(db_session, "alice@self.co", company, "company_admin")
    seed_user(db_session, "bob@self.co", company, "hr_officer")

    set_context(db_session, user_id=alice.id, company_ids=[company.id], is_platform_admin=False)
    rows = db_session.execute(text("SELECT email FROM users ORDER BY id")).scalars().all()
    assert "alice@self.co" in rows
    assert "bob@self.co" in rows

    set_context(db_session, user_id=alice.id, company_ids=[], is_platform_admin=False)
    rows = db_session.execute(text("SELECT email FROM users ORDER BY id")).scalars().all()
    assert list(rows) == ["alice@self.co"]
    clear_context(db_session)


def test_rls_forced_on_all_tenant_tables(db_session):
    rows = db_session.execute(
        text(
            "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relname IN ("
            "'companies','branches','users','roles','role_permissions',"
            "'user_roles','audit_logs',"
            "'departments','job_positions','job_grades','employees',"
            "'employee_document_types','employee_documents',"
            "'employee_contracts','employee_employment_history',"
            "'work_schedules','work_schedule_days','break_periods','shifts',"
            "'employee_work_assignments','attendance_records',"
            "'overtime_records',"
            "'company_holidays','leave_types','leave_statutory_rules',"
            "'leave_allocations','leave_requests','leave_consumptions',"
            "'salary_components','employee_salary_assignments',"
            "'salary_assignment_components','payroll_periods',"
            "'payroll_runs','payroll_run_lines','payslip_lines',"
            "'payroll_deduction_rules','payroll_adjustments',"
            "'payroll_statutory_rules',"
            "'employee_requests','employee_request_events',"
            "'employee_document_visibility',"
            "'salary_advances','salary_advance_events',"
            "'hr_letters','hr_letter_events'"
            ")"
        )
    ).all()
    assert len(rows) == 45
    for name, enabled, forced in rows:
        assert enabled, f"{name} RLS not enabled"
        assert forced, f"{name} FORCE RLS not set"


def test_policies_exist_for_all_tenant_tables(db_session):
    rows = db_session.execute(
        text(
            "SELECT tablename FROM pg_policies WHERE schemaname = 'public'"
        )
    ).scalars().all()
    assert set(rows) == {
        "companies",
        "branches",
        "users",
        "roles",
        "role_permissions",
        "user_roles",
        "audit_logs",
        "departments",
        "job_positions",
        "job_grades",
        "employees",
        "employee_document_types",
        "employee_documents",
        "employee_contracts",
        "employee_employment_history",
        "work_schedules",
        "work_schedule_days",
        "break_periods",
        "shifts",
        "employee_work_assignments",
        "attendance_records",
        "overtime_records",
        "company_holidays",
        "leave_types",
        "leave_statutory_rules",
        "leave_allocations",
        "leave_requests",
        "leave_consumptions",
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
        "employee_requests",
        "employee_request_events",
        "employee_document_visibility",
        "salary_advances",
        "salary_advance_events",
        "hr_letters",
        "hr_letter_events",
    }


def test_cross_company_user_listing_is_scoped(client, db_session):
    company_a = seed_company(db_session, "API Iso A")
    company_b = seed_company(db_session, "API Iso B")
    seed_user(db_session, "admin@a-iso.co", company_a, "company_admin")
    seed_user(db_session, "outsider@b-iso.co", company_b, "company_admin")
    seed_user(db_session, "admin@b-iso.co", company_b, "company_admin")

    auth_a = login(client, "admin@a-iso.co")
    emails = {u["email"] for u in client.get(
        "/api/v1/users", headers=auth_a["headers"]
    ).json()}
    assert "admin@a-iso.co" in emails
    assert "outsider@b-iso.co" not in emails
    assert "admin@b-iso.co" not in emails

    auth_b = login(client, "admin@b-iso.co")
    emails_b = {u["email"] for u in client.get(
        "/api/v1/users", headers=auth_b["headers"]
    ).json()}
    assert emails_b == {"admin@b-iso.co", "outsider@b-iso.co"}


def test_cross_company_branch_listing_is_scoped(client, db_session):
    company_a = seed_company(db_session, "Br Iso A")
    company_b = seed_company(db_session, "Br Iso B")
    seed_user(db_session, "admin@br-a.co", company_a, "company_admin")
    seed_user(db_session, "admin@br-b.co", company_b, "company_admin")

    auth_b = login(client, "admin@br-b.co")
    client.post(
        "/api/v1/branches",
        headers=auth_b["headers"],
        json={"company_id": company_b.id, "name": "B Branch", "code": "BB1"},
    )

    auth_a = login(client, "admin@br-a.co")
    branches_a = client.get("/api/v1/branches", headers=auth_a["headers"]).json()
    assert branches_a == []

    client.cookies.clear()
    branches_b = client.get("/api/v1/branches", headers=auth_b["headers"]).json()
    assert len(branches_b) == 1


def test_cross_company_detail_access_denied(client, db_session):
    company_a = seed_company(db_session, "Det A")
    company_b = seed_company(db_session, "Det B")
    seed_user(db_session, "admin@det-a.co", company_a, "company_admin")
    seed_user(db_session, "admin@det-b.co", company_b, "company_admin")

    auth_a = login(client, "admin@det-a.co")
    assert client.get(
        f"/api/v1/companies/{company_b.id}", headers=auth_a["headers"]
    ).status_code == 404
    assert client.patch(
        f"/api/v1/companies/{company_b.id}",
        headers=auth_a["headers"],
        json={"name": "Hijacked"},
    ).status_code == 404


def test_audit_logs_scoped_to_company(client, db_session):
    company_a = seed_company(db_session, "Aud A")
    company_b = seed_company(db_session, "Aud B")
    seed_user(db_session, "admin@aud-a.co", company_a, "company_admin")
    seed_user(db_session, "admin@aud-b.co", company_b, "company_admin")

    auth_b = login(client, "admin@aud-b.co")
    client.post(
        "/api/v1/branches",
        headers=auth_b["headers"],
        json={"company_id": company_b.id, "name": "B Aud", "code": "BA1"},
    )

    auth_a = login(client, "admin@aud-a.co")
    page_a = client.get("/api/v1/audit-logs", headers=auth_a["headers"]).json()
    actions_a = {i["action"] for i in page_a["items"]}
    assert "branch.create" not in actions_a
    assert "auth.login_success" in actions_a
    for item in page_a["items"]:
        assert item["company_id"] in (company_a.id, None)

    client.cookies.clear()
    page_b = client.get("/api/v1/audit-logs", headers=auth_b["headers"]).json()
    assert any(i["action"] == "branch.create" for i in page_b["items"])


def test_role_listing_scoped_to_company(client, db_session):
    company_a = seed_company(db_session, "Role A")
    company_b = seed_company(db_session, "Role B")
    seed_user(db_session, "admin@role-a.co", company_a, "company_admin")
    seed_user(db_session, "admin@role-b.co", company_b, "company_admin")

    auth_a = login(client, "admin@role-a.co")
    roles_a = client.get("/api/v1/roles", headers=auth_a["headers"]).json()
    assert {r["company_id"] for r in roles_a} == {company_a.id}

    auth_b = login(client, "admin@role-b.co")
    roles_b = client.get("/api/v1/roles", headers=auth_b["headers"]).json()
    assert {r["company_id"] for r in roles_b} == {company_b.id}


def test_seed_elevation_does_not_leak_into_request(client, db_session):
    company = seed_company(db_session, "Seed Leak Co")
    seed_user(db_session, "admin@seed-leak.co", company, "company_admin")

    auth = login(client, "admin@seed-leak.co")
    client.post(
        "/api/v1/branches",
        headers=auth["headers"],
        json={"company_id": company.id, "name": "Only", "code": "S1"},
    )

    set_context(db_session, user_id=None, company_ids=[], is_platform_admin=False)
    leak = db_session.execute(
        text("SELECT count(*) FROM companies")
    ).scalar_one()
    assert leak == 0
    clear_context(db_session)
