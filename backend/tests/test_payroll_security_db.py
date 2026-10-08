from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import text

from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db

COMPONENTS = "/api/v1/salary-components"
ASSIGNMENTS = "/api/v1/salary-assignments"
PERIODS = "/api/v1/payroll-periods"
RUNS = "/api/v1/payroll-runs"
ADJUSTMENTS = "/api/v1/payroll-adjustments"
DEDUCTIONS = "/api/v1/payroll-deductions"
RULES = "/api/v1/payroll-statutory-rules"

SALARY_COMPONENT_CODES = {
    "salary_component.view",
    "salary_component.create",
    "salary_component.update",
    "salary_component.deactivate",
}
SALARY_ASSIGNMENT_CODES = {
    "salary_assignment.view",
    "salary_assignment.create",
    "salary_assignment.update",
}
PAYROLL_PERIOD_CODES = {
    "payroll_period.view",
    "payroll_period.create",
    "payroll_period.update",
}
PAYROLL_RUN_CODES = {
    "payroll_run.view",
    "payroll_run.calculate",
    "payroll_run.review",
    "payroll_run.approve",
    "payroll_run.mark_paid",
    "payroll_run.lock",
}
PAYROLL_ADJUSTMENT_CODES = {
    "payroll_adjustment.view",
    "payroll_adjustment.create",
    "payroll_adjustment.approve",
    "payroll_adjustment.reject",
    "payroll_adjustment.void",
}
PAYROLL_DEDUCTION_CODES = {
    "payroll_deduction.view",
    "payroll_deduction.create",
    "payroll_deduction.update",
}
PAYROLL_STATUTORY_CODES = {
    "payroll_statutory_rule.view",
    "payroll_statutory_rule.create",
    "payroll_statutory_rule.deactivate",
}
PAYROLL_ALL = (
    SALARY_COMPONENT_CODES
    | SALARY_ASSIGNMENT_CODES
    | PAYROLL_PERIOD_CODES
    | PAYROLL_RUN_CODES
    | PAYROLL_ADJUSTMENT_CODES
    | PAYROLL_DEDUCTION_CODES
    | PAYROLL_STATUTORY_CODES
    | {"payroll_export.execute"}
)
assert len(PAYROLL_ALL) == 28

OFFICER_ALLOWED = (
    PAYROLL_ALL
    - {"payroll_statutory_rule.create", "payroll_statutory_rule.deactivate"}
    - {"payroll_run.approve", "payroll_run.mark_paid", "payroll_run.lock"}
    - {
        "payroll_adjustment.approve",
        "payroll_adjustment.reject",
        "payroll_adjustment.void",
    }
    - {"salary_component.deactivate"}
)
assert len(OFFICER_ALLOWED) == 19

AUDITOR_ALLOWED = {
    "salary_component.view",
    "salary_assignment.view",
    "payroll_period.view",
    "payroll_run.view",
    "payroll_adjustment.view",
    "payroll_deduction.view",
    "payroll_statutory_rule.view",
    "payroll_export.execute",
}
assert len(AUDITOR_ALLOWED) == 8


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "نورة",
        "last_name_ar": "القحطاني",
        "first_name_en": "Noura",
        "last_name_en": "Alqahtani",
        **overrides,
    }
    response = client.post("/api/v1/employees", headers=auth["headers"], json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def sec_env(client, db_session):
    company_a = seed_company(db_session, "Sec A")
    company_b = seed_company(db_session, "Sec B")
    seed_user(db_session, "admin@sec-a.co", company_a, "company_admin")
    seed_user(db_session, "manager@sec-a.co", company_a, "hr_manager")
    seed_user(db_session, "officer@sec-a.co", company_a, "hr_officer")
    seed_user(db_session, "auditor@sec-a.co", company_a, "auditor")
    seed_user(db_session, "staff@sec-a.co", company_a, "employee")
    seed_user(db_session, "noperm@sec-a.co", company_a)
    seed_user(db_session, "admin@sec-b.co", company_b, "company_admin")

    admin_a = login(client, "admin@sec-a.co")
    admin_b = login(client, "admin@sec-b.co")
    employee_a = _create_employee(client, admin_a, company_a.id, status="active")
    employee_b = _create_employee(client, admin_b, company_b.id, status="active")

    def _seed_payloads(auth, company, employee, code):
        assignment = client.post(
            ASSIGNMENTS,
            headers=auth["headers"],
            json={
                "company_id": company.id,
                "employee_id": employee["id"],
                "effective_from": "2025-01-01",
                "basic_salary": "9300",
            },
        )
        assert assignment.status_code == 201, assignment.text
        period = client.post(
            PERIODS,
            headers=auth["headers"],
            json={
                "company_id": company.id,
                "name": "Jan 2025",
                "period_start": "2025-01-01",
                "period_end": "2025-01-31",
            },
        )
        assert period.status_code == 201, period.text
        component = client.post(
            COMPONENTS,
            headers=auth["headers"],
            json={
                "company_id": company.id,
                "code": code,
                "name_ar": "بدل",
                "name_en": "Allowance",
                "category": "earning",
                "calculation_basis": "fixed",
                "default_amount": "500",
            },
        )
        assert component.status_code == 201, component.text
        return assignment.json(), period.json(), component.json()

    assignment_a, period_a, component_a = _seed_payloads(
        admin_a, company_a, employee_a, "HRA"
    )
    assignment_b, period_b, component_b = _seed_payloads(
        admin_b, company_b, employee_b, "HRA"
    )

    deduction = client.post(
        DEDUCTIONS,
        headers=admin_a["headers"],
        json={
            "company_id": company_a.id,
            "employee_id": employee_a["id"],
            "name": "Advance",
            "amount": "300",
            "effective_from": "2025-01-01",
        },
    )
    assert deduction.status_code == 201, deduction.text
    adjustment = client.post(
        ADJUSTMENTS,
        headers=admin_a["headers"],
        json={
            "company_id": company_a.id,
            "employee_id": employee_a["id"],
            "period_id": period_a["id"],
            "amount": "100",
            "direction": "earning",
            "reason": "Spot bonus",
        },
    )
    assert adjustment.status_code == 201, adjustment.text
    rule = client.post(
        RULES,
        headers=admin_a["headers"],
        json={
            "company_id": company_a.id,
            "statutory_key": "overtime",
            "effective_from": "2025-01-01",
            "effective_to": "2025-12-31",
            "rule_json": {
                "overtime_rate_percent": 50,
                "days_per_month": 30,
                "hours_per_day": 8,
            },
            "source_reference": "HRSD overtime framework - policy REF-1",
        },
    )
    assert rule.status_code == 201, rule.text

    return SimpleNamespace(
        company_a=company_a,
        company_b=company_b,
        admin_a=admin_a,
        admin_b=admin_b,
        employee_a=employee_a,
        employee_b=employee_b,
        assignment_a=assignment_a,
        assignment_b=assignment_b,
        period_a=period_a,
        period_b=period_b,
        component_a=component_a,
        component_b=component_b,
        deduction_a=deduction.json(),
        adjustment_a=adjustment.json(),
        rule_a=rule.json(),
    )


def _scoped(auth, company_id):
    return {**auth["headers"], "X-Company-Id": str(company_id)}


# ---------------------------------------------------------------------------
# Role -> permission grants (catalog contract)
# ---------------------------------------------------------------------------


def test_phase6_permission_grants_per_role(client, db_session):
    from app.core.rls import clear_context, elevate_for_seed

    company = seed_company(db_session, "Grant Co")
    elevate_for_seed(db_session)
    rows = db_session.execute(
        text(
            "SELECT r.code AS role_code, p.code AS permission_code "
            "FROM roles r "
            "JOIN role_permissions rp ON rp.role_id = r.id "
            "JOIN permissions p ON p.id = rp.permission_id "
            "WHERE r.company_id = :cid"
        ),
        {"cid": company.id},
    ).all()
    clear_context(db_session)
    grants: dict[str, set[str]] = {}
    for role_code, permission_code in rows:
        grants.setdefault(role_code, set()).add(permission_code)

    assert PAYROLL_ALL <= grants["company_admin"]
    assert PAYROLL_ALL <= grants["hr_manager"]
    assert grants["hr_officer"] & PAYROLL_ALL == OFFICER_ALLOWED
    assert grants["auditor"] & PAYROLL_ALL == AUDITOR_ALLOWED
    assert grants.get("employee", set()) & PAYROLL_ALL == set()


# ---------------------------------------------------------------------------
# Route-level permission gates
# ---------------------------------------------------------------------------


def test_roleless_user_denied_every_payroll_route(client, sec_env):
    env = sec_env
    auth = login(client, "noperm@sec-a.co")
    headers = _scoped(auth, env.company_a.id)

    for path in (
        COMPONENTS,
        ASSIGNMENTS,
        PERIODS,
        RUNS,
        ADJUSTMENTS,
        DEDUCTIONS,
        RULES,
    ):
        assert client.get(path, headers=headers).status_code == 403, path

    assert (
        client.post(
            COMPONENTS,
            headers=headers,
            json={
                "company_id": env.company_a.id,
                "code": "X1",
                "name_ar": "x",
                "name_en": "x",
                "category": "earning",
                "calculation_basis": "fixed",
                "default_amount": "10",
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            PERIODS,
            headers=headers,
            json={
                "company_id": env.company_a.id,
                "name": "Feb",
                "period_start": "2025-02-01",
                "period_end": "2025-02-28",
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{PERIODS}/{env.period_a['id']}/calculate", headers=headers
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{PERIODS}/{env.period_a['id']}/approve", headers=headers
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"{PERIODS}/{env.period_a['id']}", headers=headers, json={"name": "x"}
        ).status_code
        == 403
    )
    assert client.get(f"{RUNS}/1/export", headers=headers).status_code == 403
    assert (
        client.post(
            RULES,
            headers=headers,
            json={
                "company_id": env.company_a.id,
                "statutory_key": "overtime",
                "effective_from": "2025-01-01",
                "rule_json": {},
                "source_reference": "x",
            },
        ).status_code
        == 403
    )


def test_employee_role_has_zero_payroll_access(client, sec_env):
    env = sec_env
    auth = login(client, "staff@sec-a.co")
    headers = _scoped(auth, env.company_a.id)

    assert client.get(PERIODS, headers=headers).status_code == 403
    assert client.get(RUNS, headers=headers).status_code == 403
    assert (
        client.get(f"{PERIODS}/{env.period_a['id']}", headers=headers).status_code
        == 403
    )
    assert (
        client.post(
            COMPONENTS,
            headers=headers,
            json={
                "company_id": env.company_a.id,
                "code": "SELF",
                "name_ar": "x",
                "name_en": "x",
                "category": "earning",
                "calculation_basis": "fixed",
                "default_amount": "1",
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{PERIODS}/{env.period_a['id']}/calculate", headers=headers
        ).status_code
        == 403
    )
    assert client.get(f"{RUNS}/1/export", headers=headers).status_code == 403


def test_auditor_reads_payroll_but_cannot_write(client, sec_env):
    env = sec_env
    auth = login(client, "auditor@sec-a.co")
    headers = _scoped(auth, env.company_a.id)

    for path in (
        COMPONENTS,
        ASSIGNMENTS,
        PERIODS,
        ADJUSTMENTS,
        DEDUCTIONS,
        RULES,
    ):
        listed = client.get(path, headers=headers)
        assert listed.status_code == 200, path
        for item in listed.json()["items"]:
            assert item["company_id"] == env.company_a.id

    assert (
        client.get(f"{PERIODS}/{env.period_a['id']}", headers=headers).status_code
        == 200
    )

    # the accounting export is the auditor's one write-adjacent action
    run = client.post(
        f"{PERIODS}/{env.period_a['id']}/calculate", headers=env.admin_a["headers"]
    )
    assert run.status_code == 200, run.text
    assert (
        client.get(f"{RUNS}/{run.json()['id']}/lines", headers=headers).status_code
        == 200
    )
    assert (
        client.get(f"{RUNS}/{run.json()['id']}/export", headers=headers).status_code
        == 200
    )

    # every mutation route is denied
    assert (
        client.post(
            COMPONENTS,
            headers=headers,
            json={
                "company_id": env.company_a.id,
                "code": "NO",
                "name_ar": "x",
                "name_en": "x",
                "category": "earning",
                "calculation_basis": "fixed",
                "default_amount": "1",
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{COMPONENTS}/{env.component_a['id']}/deactivate", headers=headers
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"{ASSIGNMENTS}/{env.assignment_a['id']}",
            headers=headers,
            json={"basic_salary": "1"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{PERIODS}/{env.period_a['id']}/calculate", headers=headers
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{PERIODS}/{env.period_a['id']}/review", headers=headers
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{PERIODS}/{env.period_a['id']}/approve", headers=headers
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{PERIODS}/{env.period_a['id']}/mark-paid", headers=headers
        ).status_code
        == 403
    )
    assert (
        client.post(
            ADJUSTMENTS,
            headers=headers,
            json={
                "company_id": env.company_a.id,
                "employee_id": env.employee_a["id"],
                "period_id": env.period_a["id"],
                "amount": "1",
                "direction": "earning",
                "reason": "x",
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            DEDUCTIONS,
            headers=headers,
            json={
                "company_id": env.company_a.id,
                "employee_id": env.employee_a["id"],
                "name": "x",
                "amount": "1",
                "effective_from": "2025-01-01",
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            RULES,
            headers=headers,
            json={
                "company_id": env.company_a.id,
                "statutory_key": "daily_divisor",
                "effective_from": "2025-01-01",
                "rule_json": {"divisor": 30},
                "source_reference": "x",
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{RULES}/{env.rule_a['id']}/deactivate", headers=headers, json={}
        ).status_code
        == 403
    )


def test_officer_calculates_and_reviews_but_cannot_approve(client, sec_env):
    env = sec_env
    auth = login(client, "officer@sec-a.co")

    component = client.post(
        COMPONENTS,
        headers=auth["headers"],
        json={
            "company_id": env.company_a.id,
            "code": "BONUS",
            "name_ar": "حافز",
            "name_en": "Bonus",
            "category": "earning",
            "calculation_basis": "fixed",
            "default_amount": "200",
        },
    )
    assert component.status_code == 201, component.text
    patched = client.patch(
        f"{COMPONENTS}/{component.json()['id']}",
        headers=auth["headers"],
        json={"default_amount": "250"},
    )
    assert patched.status_code == 200, patched.text

    adjustment = client.post(
        ADJUSTMENTS,
        headers=auth["headers"],
        json={
            "company_id": env.company_a.id,
            "employee_id": env.employee_a["id"],
            "period_id": env.period_a["id"],
            "amount": "50",
            "direction": "deduction",
            "reason": "Recovery",
        },
    )
    assert adjustment.status_code == 201, adjustment.text

    calculated = client.post(
        f"{PERIODS}/{env.period_a['id']}/calculate", headers=auth["headers"]
    )
    assert calculated.status_code == 200, calculated.text
    reviewed = client.post(
        f"{PERIODS}/{env.period_a['id']}/review", headers=auth["headers"]
    )
    assert reviewed.status_code == 200, reviewed.text

    approve = client.post(
        f"{PERIODS}/{env.period_a['id']}/approve", headers=auth["headers"]
    )
    assert approve.status_code == 403
    assert approve.json()["code"] == "forbidden"
    assert (
        client.post(
            f"{PERIODS}/{env.period_a['id']}/mark-paid", headers=auth["headers"]
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{PERIODS}/{env.period_a['id']}/lock", headers=auth["headers"]
        ).status_code
        == 403
    )

    assert (
        client.post(
            RULES,
            headers=auth["headers"],
            json={
                "company_id": env.company_a.id,
                "statutory_key": "daily_divisor",
                "effective_from": "2025-01-01",
                "rule_json": {"divisor": 26},
                "source_reference": "x",
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{RULES}/{env.rule_a['id']}/deactivate", headers=auth["headers"], json={}
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{ADJUSTMENTS}/{env.adjustment_a['id']}/approve",
            headers=auth["headers"],
            json={},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{ADJUSTMENTS}/{env.adjustment_a['id']}/reject",
            headers=auth["headers"],
            json={},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{ADJUSTMENTS}/{env.adjustment_a['id']}/void",
            headers=auth["headers"],
            json={},
        ).status_code
        == 403
    )

    export = client.get(
        f"{RUNS}/{calculated.json()['id']}/export", headers=auth["headers"]
    )
    assert export.status_code == 200, export.text


def test_manager_runs_full_lifecycle_and_statutory_admin(client, sec_env):
    env = sec_env
    auth = login(client, "manager@sec-a.co")

    rule = client.post(
        RULES,
        headers=auth["headers"],
        json={
            "company_id": env.company_a.id,
            "statutory_key": "daily_divisor",
            "effective_from": "2025-01-01",
            "rule_json": {"divisor": 30},
            "source_reference": "Company payroll policy REF-2",
            "requires_legal_verification": False,
        },
    )
    assert rule.status_code == 201, rule.text

    component = client.post(
        COMPONENTS,
        headers=auth["headers"],
        json={
            "company_id": env.company_a.id,
            "code": "MGR",
            "name_ar": "x",
            "name_en": "Manager Line",
            "category": "earning",
            "calculation_basis": "fixed",
            "default_amount": "100",
        },
    )
    assert component.status_code == 201, component.text
    assert (
        client.post(
            f"{COMPONENTS}/{component.json()['id']}/deactivate", headers=auth["headers"]
        ).status_code
        == 200
    )

    adjustment = client.post(
        ADJUSTMENTS,
        headers=auth["headers"],
        json={
            "company_id": env.company_a.id,
            "employee_id": env.employee_a["id"],
            "period_id": env.period_a["id"],
            "amount": "25",
            "direction": "earning",
            "reason": "Spot award",
        },
    )
    assert adjustment.status_code == 201, adjustment.text
    assert (
        client.post(
            f"{ADJUSTMENTS}/{adjustment.json()['id']}/approve",
            headers=auth["headers"],
            json={},
        ).status_code
        == 200
    )

    for action in ("calculate", "review", "approve", "mark-paid", "lock"):
        response = client.post(
            f"{PERIODS}/{env.period_a['id']}/{action}", headers=auth["headers"]
        )
        assert response.status_code == 200, f"{action}: {response.text}"

    assert (
        client.post(
            f"{RULES}/{rule.json()['id']}/deactivate", headers=auth["headers"], json={}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"{RULES}/{env.rule_a['id']}/deactivate", headers=auth["headers"], json={}
        ).status_code
        == 200
    )


# ---------------------------------------------------------------------------
# Cross-company isolation
# ---------------------------------------------------------------------------


def test_cross_company_detail_404(client, sec_env):
    env = sec_env
    auth = env.admin_b
    headers = _scoped(auth, env.company_b.id)

    assert (
        client.get(f"{PERIODS}/{env.period_a['id']}", headers=headers).status_code
        == 404
    )
    assert (
        client.patch(
            f"{PERIODS}/{env.period_a['id']}", headers=headers, json={"name": "x"}
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"{PERIODS}/{env.period_a['id']}/calculate", headers=headers
        ).status_code
        == 404
    )
    assert (
        client.get(f"{COMPONENTS}/{env.component_a['id']}", headers=headers).status_code
        == 404
    )
    assert (
        client.get(
            f"{ASSIGNMENTS}/{env.assignment_a['id']}", headers=headers
        ).status_code
        == 404
    )
    assert (
        client.get(f"{DEDUCTIONS}/{env.deduction_a['id']}", headers=headers).status_code
        == 404
    )
    assert (
        client.get(
            f"{ADJUSTMENTS}/{env.adjustment_a['id']}", headers=headers
        ).status_code
        == 404
    )
    assert client.get(f"{RULES}/{env.rule_a['id']}", headers=headers).status_code == 404

    run = client.post(
        f"{PERIODS}/{env.period_a['id']}/calculate", headers=env.admin_a["headers"]
    )
    assert run.status_code == 200, run.text
    assert client.get(f"{RUNS}/{run.json()['id']}", headers=headers).status_code == 404
    assert (
        client.get(f"{RUNS}/{run.json()['id']}/export", headers=headers).status_code
        == 404
    )


def test_cross_company_list_scoping(client, sec_env):
    env = sec_env
    auth_b = env.admin_b

    forbidden = client.get(
        COMPONENTS,
        headers=auth_b["headers"],
        params={"company_id": env.company_a.id},
    )
    assert forbidden.status_code == 403
    forbidden = client.get(
        PERIODS,
        headers=auth_b["headers"],
        params={"company_id": env.company_a.id},
    )
    assert forbidden.status_code == 403

    own = client.get(
        COMPONENTS,
        headers=_scoped(auth_b, env.company_b.id),
    ).json()
    assert own["page"]["total"] == 1
    assert own["items"][0]["company_id"] == env.company_b.id
    assert own["items"][0]["id"] == env.component_b["id"]

    own_periods = client.get(
        PERIODS,
        headers=_scoped(auth_b, env.company_b.id),
    ).json()
    assert own_periods["page"]["total"] == 1
    assert own_periods["items"][0]["id"] == env.period_b["id"]

    auth_a = env.admin_a
    wrong_header = client.get(
        COMPONENTS,
        headers=_scoped(auth_a, env.company_b.id),
    )
    assert wrong_header.status_code == 403


def test_cross_company_create_403(client, sec_env):
    env = sec_env
    auth = env.admin_a
    assert (
        client.post(
            COMPONENTS,
            headers=auth["headers"],
            json={
                "company_id": env.company_b.id,
                "code": "HIJACK",
                "name_ar": "x",
                "name_en": "x",
                "category": "earning",
                "calculation_basis": "fixed",
                "default_amount": "1",
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            PERIODS,
            headers=auth["headers"],
            json={
                "company_id": env.company_b.id,
                "name": "Hijack",
                "period_start": "2025-03-01",
                "period_end": "2025-03-31",
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            ASSIGNMENTS,
            headers=auth["headers"],
            json={
                "company_id": env.company_b.id,
                "employee_id": env.employee_b["id"],
                "effective_from": "2025-03-01",
                "basic_salary": "1",
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            DEDUCTIONS,
            headers=auth["headers"],
            json={
                "company_id": env.company_b.id,
                "employee_id": env.employee_b["id"],
                "name": "x",
                "amount": "1",
                "effective_from": "2025-01-01",
            },
        ).status_code
        == 403
    )


def test_cross_company_foreign_keys_rejected(client, sec_env):
    env = sec_env
    auth = env.admin_a

    assignment = client.post(
        ASSIGNMENTS,
        headers=auth["headers"],
        json={
            "company_id": env.company_a.id,
            "employee_id": env.employee_b["id"],
            "effective_from": "2025-03-01",
            "basic_salary": "100",
        },
    )
    assert assignment.status_code == 404
    assert assignment.json()["code"] == "SALARY_ASSIGNMENT_NOT_FOUND"

    adjustment = client.post(
        ADJUSTMENTS,
        headers=auth["headers"],
        json={
            "company_id": env.company_a.id,
            "employee_id": env.employee_a["id"],
            "period_id": env.period_b["id"],
            "amount": "1",
            "direction": "earning",
            "reason": "x",
        },
    )
    assert adjustment.status_code == 404
    assert adjustment.json()["code"] == "PAYROLL_PERIOD_NOT_FOUND"

    deduction = client.post(
        DEDUCTIONS,
        headers=auth["headers"],
        json={
            "company_id": env.company_a.id,
            "employee_id": env.employee_b["id"],
            "name": "x",
            "amount": "1",
            "effective_from": "2025-01-01",
        },
    )
    assert deduction.status_code == 404
    assert deduction.json()["code"] == "PAYROLL_DEDUCTION_NOT_FOUND"

    # a run from company B may never anchor a correction in company A
    run_b = client.post(
        f"{PERIODS}/{env.period_b['id']}/calculate", headers=env.admin_b["headers"]
    )
    assert run_b.status_code == 200, run_b.text
    correction = client.post(
        ADJUSTMENTS,
        headers=auth["headers"],
        json={
            "company_id": env.company_a.id,
            "employee_id": env.employee_a["id"],
            "period_id": env.period_a["id"],
            "original_run_id": run_b.json()["id"],
            "amount": "1",
            "direction": "earning",
            "reason": "x",
        },
    )
    assert correction.status_code == 409
    assert correction.json()["code"] == "PAYROLL_ADJUSTMENT_INVALID_TARGET"


# ---------------------------------------------------------------------------
# Audit isolation
# ---------------------------------------------------------------------------


def test_payroll_audit_log_company_isolated(client, sec_env):
    env = sec_env
    page_a = client.get(
        "/api/v1/audit-logs",
        headers=_scoped(env.admin_a, env.company_a.id),
        params={"action": "salary_component.create"},
    ).json()
    assert page_a["page"]["total"] >= 1
    for item in page_a["items"]:
        assert item["company_id"] == env.company_a.id

    page_b = client.get(
        "/api/v1/audit-logs",
        headers=_scoped(env.admin_b, env.company_b.id),
        params={"action": "salary_component.create"},
    ).json()
    assert page_b["page"]["total"] >= 1
    for item in page_b["items"]:
        assert item["company_id"] == env.company_b.id
