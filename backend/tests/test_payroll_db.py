from __future__ import annotations

import re
from decimal import Decimal
from types import SimpleNamespace

import pytest

from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db

COMPONENTS = "/api/v1/salary-components"
ASSIGNMENTS = "/api/v1/salary-assignments"
PERIODS = "/api/v1/payroll-periods"
RUNS = "/api/v1/payroll-runs"
ADJUSTMENTS = "/api/v1/payroll-adjustments"
DEDUCTIONS = "/api/v1/payroll-deductions"
RULES = "/api/v1/payroll-statutory-rules"


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "سالم",
        "last_name_ar": "العتيبي",
        "first_name_en": "Salem",
        "last_name_en": "Alotaibi",
        **overrides,
    }
    response = client.post("/api/v1/employees", headers=auth["headers"], json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def pay_env(client, db_session):
    company = seed_company(db_session, "Payroll Co")
    seed_user(db_session, "admin@payroll.co", company, "company_admin")
    auth = login(client, "admin@payroll.co")
    employee = _create_employee(client, auth, company.id, status="active")
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
    return SimpleNamespace(
        company=company,
        auth=auth,
        employee=employee,
        assignment=assignment.json(),
        period=period.json(),
    )


def _send(client, env, method, path, *, payload=None, expect=200):
    fn = getattr(client, method)
    kwargs = {"headers": env.auth["headers"]}
    if payload is not None:
        kwargs["json"] = payload
    response = fn(path, **kwargs)
    assert response.status_code == expect, response.text
    return response


def _component(client, env, **overrides):
    expect = overrides.pop("expect", 201)
    payload = {
        "company_id": env.company.id,
        "code": "HRA",
        "name_ar": "بدل السكن",
        "name_en": "Housing Allowance",
        "category": "earning",
        "calculation_basis": "fixed",
        "default_amount": "500",
    }
    payload.update(overrides)
    return _send(client, env, "post", COMPONENTS, payload=payload, expect=expect)


def _assignment(client, env, employee_id, **overrides):
    expect = overrides.pop("expect", 201)
    payload = {
        "company_id": env.company.id,
        "employee_id": employee_id,
        "effective_from": "2025-02-01",
        "basic_salary": "9500",
    }
    payload.update(overrides)
    return _send(client, env, "post", ASSIGNMENTS, payload=payload, expect=expect)


def _period(client, env, **overrides):
    expect = overrides.pop("expect", 201)
    payload = {
        "company_id": env.company.id,
        "name": "Feb 2025",
        "period_start": "2025-02-01",
        "period_end": "2025-02-28",
    }
    payload.update(overrides)
    return _send(client, env, "post", PERIODS, payload=payload, expect=expect)


def _deduction(client, env, **overrides):
    expect = overrides.pop("expect", 201)
    payload = {
        "company_id": env.company.id,
        "employee_id": env.employee["id"],
        "name": "Salary Advance",
        "amount": "300",
        "effective_from": "2025-01-01",
    }
    payload.update(overrides)
    return _send(client, env, "post", DEDUCTIONS, payload=payload, expect=expect)


def _adjustment(client, env, **overrides):
    expect = overrides.pop("expect", 201)
    payload = {
        "company_id": env.company.id,
        "employee_id": env.employee["id"],
        "period_id": env.period["id"],
        "amount": "100",
        "direction": "earning",
        "reason": "Approved payroll correction",
    }
    payload.update(overrides)
    return _send(client, env, "post", ADJUSTMENTS, payload=payload, expect=expect)


def _rule(client, env, **overrides):
    expect = overrides.pop("expect", 201)
    payload = {
        "company_id": env.company.id,
        "statutory_key": "overtime",
        "effective_from": "2025-01-01",
        "effective_to": "2025-12-31",
        "rule_json": {
            "overtime_rate_percent": 50,
            "days_per_month": 30,
            "hours_per_day": 8,
        },
        "source_reference": "HRSD overtime framework - internal policy REF-2025",
    }
    payload.update(overrides)
    return _send(client, env, "post", RULES, payload=payload, expect=expect)


def _calculate(client, env, period_id=None, *, expect=200):
    target = period_id or env.period["id"]
    return _send(client, env, "post", f"{PERIODS}/{target}/calculate", expect=expect)


def _review(client, env, period_id=None, *, expect=200):
    target = period_id or env.period["id"]
    return _send(client, env, "post", f"{PERIODS}/{target}/review", expect=expect)


def _approve(client, env, period_id=None, *, expect=200):
    target = period_id or env.period["id"]
    return _send(client, env, "post", f"{PERIODS}/{target}/approve", expect=expect)


def _mark_paid(client, env, period_id=None, *, expect=200):
    target = period_id or env.period["id"]
    return _send(client, env, "post", f"{PERIODS}/{target}/mark-paid", expect=expect)


def _lock(client, env, period_id=None, *, expect=200):
    target = period_id or env.period["id"]
    return _send(client, env, "post", f"{PERIODS}/{target}/lock", expect=expect)


def _approved_overtime(client, env, **overrides):
    payload = {
        "employee_id": env.employee["id"],
        "work_date": "2025-01-10",
        "requested_minutes": 60,
        "reason": "Month-end closing",
    }
    payload.update(overrides)
    created = _send(
        client, env, "post", "/api/v1/overtime", payload=payload, expect=201
    )
    overtime_id = created.json()["id"]
    for action in ("submit", "approve"):
        _send(
            client,
            env,
            "post",
            f"/api/v1/overtime/{overtime_id}/{action}",
            payload={},
        )
    return created.json()


def _verified_overtime_rule(client, env, **overrides):
    payload = {
        "requires_legal_verification": False,
        "source_reference": "Verified HRSD overtime framework - counsel memo 2025-01",
    }
    payload.update(overrides)
    return _rule(client, env, **payload)


# ---------------------------------------------------------------------------
# Salary components
# ---------------------------------------------------------------------------


def test_component_create_list_get_patch_deactivate(client, pay_env):
    env = pay_env
    created = _component(client, env).json()
    assert created["status"] == "active"
    assert created["default_amount"] == "500"
    assert created["category"] == "earning"

    detail = _send(client, env, "get", f"{COMPONENTS}/{created['id']}")
    assert detail.json()["id"] == created["id"]

    page = _send(
        client,
        env,
        "get",
        COMPONENTS,
        payload=None,
    )
    listed = client.get(
        COMPONENTS,
        headers=env.auth["headers"],
        params={"company_id": env.company.id},
    ).json()
    assert listed["page"]["total"] == 1
    assert listed["items"][0]["id"] == created["id"]
    assert page.status_code == 200

    patched = _send(
        client,
        env,
        "patch",
        f"{COMPONENTS}/{created['id']}",
        payload={"name_en": "Housing", "default_amount": "600"},
    )
    assert patched.json()["default_amount"] == "600"
    assert patched.json()["name_en"] == "Housing"

    deactivated = _send(client, env, "post", f"{COMPONENTS}/{created['id']}/deactivate")
    assert deactivated.json()["status"] == "inactive"
    inactive = client.get(
        COMPONENTS,
        headers=env.auth["headers"],
        params={"company_id": env.company.id, "status": "inactive"},
    ).json()
    assert inactive["page"]["total"] == 1
    active = client.get(
        COMPONENTS,
        headers=env.auth["headers"],
        params={"company_id": env.company.id, "status": "active"},
    ).json()
    assert active["page"]["total"] == 0


def test_component_duplicate_code_conflict(client, pay_env):
    env = pay_env
    _component(client, env)
    duplicate = _component(client, env, expect=409)
    assert duplicate.json()["code"] == "SALARY_COMPONENT_CODE_EXISTS"


def test_component_fixed_requires_amount(client, pay_env):
    env = pay_env
    response = _component(client, env, default_amount=None, expect=422)
    assert response.status_code == 422


def test_component_percent_requires_rate(client, pay_env):
    env = pay_env
    _component(
        client,
        env,
        calculation_basis="percent_of_basic",
        default_amount=None,
        expect=422,
    )
    ok = _component(
        client,
        env,
        code="COMM",
        calculation_basis="percent_of_basic",
        default_amount=None,
        default_rate="0.1",
    )
    assert ok.status_code == 201
    assert ok.json()["default_rate"] == "0.1"


def test_component_statutory_requires_key(client, pay_env):
    env = pay_env
    _component(client, env, is_statutory=True, expect=422)
    ok = _component(
        client,
        env,
        code="GOSI",
        is_statutory=True,
        statutory_key="gosi",
        category="deduction",
        calculation_basis="percent_of_basic",
        default_amount=None,
        default_rate="0.0975",
    )
    assert ok.status_code == 201
    assert ok.json()["statutory_key"] == "gosi"


def test_component_invalid_category(client, pay_env):
    env = pay_env
    response = _component(client, env, category="bonus", expect=422)
    assert response.status_code == 422


def test_component_rate_bounds(client, pay_env):
    env = pay_env
    _component(
        client,
        env,
        calculation_basis="percent_of_basic",
        default_amount=None,
        default_rate="0",
        expect=422,
    )
    _component(
        client,
        env,
        calculation_basis="percent_of_basic",
        default_amount=None,
        default_rate="1.5",
        expect=422,
    )


def test_component_not_found(client, pay_env):
    env = pay_env
    response = _send(client, env, "get", f"{COMPONENTS}/999999", expect=404)
    assert response.json()["code"] == "SALARY_COMPONENT_NOT_FOUND"


# ---------------------------------------------------------------------------
# Salary assignments
# ---------------------------------------------------------------------------


def test_assignment_create_and_list_as_of(client, pay_env):
    env = pay_env
    created = _assignment(client, env, env.employee["id"]).json()
    assert created["effective_from"] == "2025-02-01"
    assert created["effective_to"] is None

    page = client.get(
        ASSIGNMENTS,
        headers=env.auth["headers"],
        params={"company_id": env.company.id, "employee_id": env.employee["id"]},
    ).json()
    assert page["page"]["total"] == 2

    january = client.get(
        ASSIGNMENTS,
        headers=env.auth["headers"],
        params={"as_of": "2025-01-15"},
    ).json()
    assert january["page"]["total"] == 1
    assert january["items"][0]["id"] == env.assignment["id"]

    before = client.get(
        ASSIGNMENTS,
        headers=env.auth["headers"],
        params={"as_of": "2024-12-31"},
    ).json()
    assert before["page"]["total"] == 0

    march = client.get(
        ASSIGNMENTS,
        headers=env.auth["headers"],
        params={"as_of": "2025-03-15"},
    ).json()
    assert march["page"]["total"] == 1
    assert march["items"][0]["id"] == created["id"]


def test_assignment_autocloses_open_window(client, pay_env):
    env = pay_env
    _assignment(client, env, env.employee["id"])
    first = _send(client, env, "get", f"{ASSIGNMENTS}/{env.assignment['id']}").json()
    assert first["effective_to"] == "2025-01-31"
    assert Decimal(first["basic_salary"]) == Decimal("9300")


def test_assignment_overlap_rejected(client, pay_env):
    env = pay_env
    _assignment(
        client,
        env,
        env.employee["id"],
        effective_from="2025-02-01",
        effective_to="2025-02-28",
    )
    overlap = _assignment(
        client,
        env,
        env.employee["id"],
        effective_from="2025-02-10",
        effective_to="2025-03-31",
        expect=409,
    )
    assert overlap.json()["code"] == "SALARY_ASSIGNMENT_OVERLAP"


def test_assignment_invalid_date_range(client, pay_env):
    env = pay_env
    response = _assignment(
        client,
        env,
        env.employee["id"],
        effective_from="2025-03-01",
        effective_to="2025-02-01",
        expect=400,
    )
    assert response.json()["code"] == "SALARY_ASSIGNMENT_INVALID_DATE_RANGE"


def test_assignment_start_before_open_window(client, pay_env):
    env = pay_env
    response = _assignment(
        client,
        env,
        env.employee["id"],
        effective_from="2024-12-01",
        effective_to="2024-12-31",
        expect=409,
    )
    assert response.json()["code"] == "SALARY_ASSIGNMENT_OVERLAP"


def test_assignment_historical_immutable(client, pay_env):
    env = pay_env
    _assignment(client, env, env.employee["id"])
    response = _send(
        client,
        env,
        "patch",
        f"{ASSIGNMENTS}/{env.assignment['id']}",
        payload={"basic_salary": "100"},
        expect=409,
    )
    assert response.json()["code"] == "PAYROLL_IMMUTABLE"


def test_assignment_employee_must_exist(client, pay_env):
    env = pay_env
    response = _assignment(client, env, 999999, expect=404)
    assert response.json()["code"] == "SALARY_ASSIGNMENT_NOT_FOUND"


def test_seed_assignments_from_contract(client, pay_env):
    env = pay_env
    second = _create_employee(client, env.auth, env.company.id, status="active")
    contract = client.post(
        f"/api/v1/employees/{second['id']}/contracts",
        headers=env.auth["headers"],
        json={
            "company_id": env.company.id,
            "contract_type": "fixed_term",
            "start_date": "2025-01-01",
            "status": "active",
            "basic_salary": "8000",
        },
    )
    assert contract.status_code == 201, contract.text

    first = client.post(
        f"{ASSIGNMENTS}/seed",
        params={"company_id": env.company.id},
        headers=env.auth["headers"],
    )
    assert first.status_code == 201, first.text
    assert first.json() == {"created": 1, "skipped": 0}

    again = client.post(
        f"{ASSIGNMENTS}/seed",
        params={"company_id": env.company.id},
        headers=env.auth["headers"],
    )
    assert again.status_code == 201, again.text
    assert again.json() == {"created": 0, "skipped": 1}


# ---------------------------------------------------------------------------
# Payroll periods (single workflow state machine)
# ---------------------------------------------------------------------------


def test_period_create_list_get_filters(client, pay_env):
    env = pay_env
    assert env.period["status"] == "draft"

    draft = client.get(
        PERIODS,
        headers=env.auth["headers"],
        params={"company_id": env.company.id, "status": "draft"},
    ).json()
    assert draft["page"]["total"] == 1
    assert draft["items"][0]["name"] == "Jan 2025"

    detail = _send(client, env, "get", f"{PERIODS}/{env.period['id']}")
    assert detail.json()["period_start"] == "2025-01-01"
    assert detail.json()["period_end"] == "2025-01-31"

    _calculate(client, env)
    calculated = client.get(
        PERIODS,
        headers=env.auth["headers"],
        params={"company_id": env.company.id, "status": "calculated"},
    ).json()
    assert calculated["page"]["total"] == 1
    empty = client.get(
        PERIODS,
        headers=env.auth["headers"],
        params={"company_id": env.company.id, "status": "draft"},
    ).json()
    assert empty["page"]["total"] == 0


def test_period_overlap_conflict(client, pay_env):
    env = pay_env
    response = _period(
        client,
        env,
        name="Jan tail",
        period_start="2025-01-15",
        period_end="2025-02-15",
        expect=409,
    )
    assert response.json()["code"] == "PAYROLL_PERIOD_EXISTS"


def test_period_invalid_range_rejected(client, pay_env):
    env = pay_env
    response = _period(client, env, period_end="2024-12-01", expect=422)
    assert response.status_code == 422


def test_period_update_draft_ok(client, pay_env):
    env = pay_env
    response = _send(
        client,
        env,
        "patch",
        f"{PERIODS}/{env.period['id']}",
        payload={"name": "January 2025"},
    )
    assert response.json()["name"] == "January 2025"


def test_period_update_after_calculate_immutable(client, pay_env):
    env = pay_env
    _calculate(client, env)
    response = _send(
        client,
        env,
        "patch",
        f"{PERIODS}/{env.period['id']}",
        payload={"name": "nope"},
        expect=409,
    )
    assert response.json()["code"] == "PAYROLL_IMMUTABLE"


# ---------------------------------------------------------------------------
# Calculation, workflow, inputs integrity
# ---------------------------------------------------------------------------


def test_calculate_creates_run_lines_and_hash(client, pay_env):
    env = pay_env
    run = _calculate(client, env).json()
    assert run["status"] == "active"
    assert run["period_status"] == "calculated"
    assert run["engine_version"] == "1.0.0"
    assert run["employee_count"] == 1
    assert re.fullmatch(r"[0-9a-f]{64}", run["inputs_hash"])
    assert run["gross_total"] == "9300.00"
    assert run["deductions_total"] == "0.00"
    assert run["net_total"] == "9300.00"
    assert run["warnings"] == []

    period = _send(client, env, "get", f"{PERIODS}/{env.period['id']}").json()
    assert period["status"] == "calculated"
    assert period["calculated_at"] is not None

    lines = _send(client, env, "get", f"{RUNS}/{run['id']}/lines").json()
    assert lines["page"]["total"] == 1
    line = lines["items"][0]
    assert line["employee_id"] == env.employee["id"]
    assert line["basic_snapshot"] == "9300.00"
    assert line["net_pay"] == "9300.00"
    assert [entry["label_en"] for entry in line["lines"]] == ["Basic Pay"]


def test_full_lifecycle_to_locked(client, pay_env):
    env = pay_env
    assert _calculate(client, env).json()["period_status"] == "calculated"
    reviewed = _review(client, env).json()
    assert reviewed["status"] == "reviewed"
    assert reviewed["reviewed_at"] is not None
    approved = _approve(client, env).json()
    assert approved["status"] == "approved"
    assert approved["approved_at"] is not None
    paid = _mark_paid(client, env).json()
    assert paid["status"] == "paid"
    assert paid["paid_at"] is not None
    locked = _lock(client, env).json()
    assert locked["status"] == "locked"
    assert locked["locked_at"] is not None


@pytest.mark.parametrize(
    ("action", "setup"),
    [
        ("review", "draft"),
        ("approve", "draft"),
        ("approve", "calculated"),
        ("mark-paid", "reviewed"),
        ("lock", "approved"),
        ("calculate", "locked"),
    ],
)
def test_period_state_errors(client, pay_env, action, setup):
    env = pay_env
    if setup in ("calculated", "reviewed", "approved", "locked"):
        _calculate(client, env)
    if setup in ("reviewed", "approved", "locked"):
        _review(client, env)
    if setup in ("approved", "locked"):
        _approve(client, env)
    if setup == "locked":
        _mark_paid(client, env)
        _lock(client, env)
    response = _send(
        client,
        env,
        "post",
        f"{PERIODS}/{env.period['id']}/{action}",
        expect=409,
    )
    assert response.json()["code"] == "PAYROLL_PERIOD_STATE_INVALID"


def test_calculate_requires_salary_assignment(client, pay_env):
    env = pay_env
    second = _create_employee(client, env.auth, env.company.id, status="active")
    response = _calculate(client, env, expect=409)
    body = response.json()
    assert body["code"] == "PAYROLL_NO_SALARY_ASSIGNMENT"
    assert second["employee_number"] in body["detail"]


def test_open_attendance_blocks_calculate(client, pay_env):
    env = pay_env
    record = client.post(
        "/api/v1/attendance",
        headers=env.auth["headers"],
        json={"employee_id": env.employee["id"], "check_in": "2025-01-10T09:00:00"},
    )
    assert record.status_code == 201, record.text
    assert record.json()["status"] == "open"

    blocked = _calculate(client, env, expect=409)
    body = blocked.json()
    assert body["code"] == "PAYROLL_ATTENDANCE_OPEN"
    assert "2025-01-10" in body["detail"]
    assert str(env.employee["id"]) in body["detail"]

    closed = client.patch(
        f"/api/v1/attendance/{record.json()['id']}",
        headers=env.auth["headers"],
        json={"check_out": "2025-01-10T17:00:00"},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "completed"
    assert _calculate(client, env).json()["period_status"] == "calculated"


def test_inputs_changed_blocks_approve(client, pay_env):
    env = pay_env
    _calculate(client, env)
    _review(client, env)
    patched = _send(
        client,
        env,
        "patch",
        f"{ASSIGNMENTS}/{env.assignment['id']}",
        payload={"basic_salary": "9500"},
    )
    assert patched.status_code == 200
    response = _approve(client, env, expect=409)
    assert response.json()["code"] == "PAYROLL_INPUTS_CHANGED"


def test_missing_statutory_rule_blocks_approve_then_verified_passes(client, pay_env):
    env = pay_env
    _approved_overtime(client, env)
    run = _calculate(client, env).json()
    assert any(
        warning["code"] == "STATUTORY_RULE_MISSING"
        and warning["statutory_key"] == "overtime"
        for warning in run["warnings"]
    )

    _review(client, env)
    blocked = _approve(client, env, expect=409)
    body = blocked.json()
    assert body["code"] == "PAYROLL_STATUTORY_RULE_UNVERIFIED"
    assert "overtime" in body["detail"]

    _verified_overtime_rule(client, env)
    run = _calculate(client, env).json()
    assert run["warnings"] == []
    assert run["gross_total"] == "9358.13"
    assert run["net_total"] == "9358.13"
    _review(client, env)
    assert _approve(client, env).json()["status"] == "approved"


def test_recalculate_returns_to_calculated_and_reuses_run(client, pay_env):
    env = pay_env
    first = _calculate(client, env).json()
    _review(client, env)
    response = _send(client, env, "post", f"{RUNS}/{first['id']}/recalculate")
    second = response.json()
    assert second["id"] == first["id"]
    assert second["run_number"] == first["run_number"]
    assert second["period_status"] == "calculated"
    period = _send(client, env, "get", f"{PERIODS}/{env.period['id']}").json()
    assert period["status"] == "calculated"
    assert period["reviewed_at"] is None


def test_run_numbers_increment_across_periods(client, pay_env):
    env = pay_env
    first = _calculate(client, env).json()
    assert first["run_number"] == 1
    february = _period(client, env).json()
    second = _calculate(client, env, february["id"]).json()
    assert second["run_number"] == 2


# ---------------------------------------------------------------------------
# Runs, lines, payslips, accounting export
# ---------------------------------------------------------------------------


def test_run_detail_and_list_filters(client, pay_env):
    env = pay_env
    run = _calculate(client, env).json()
    detail = _send(client, env, "get", f"{RUNS}/{run['id']}").json()
    assert detail["inputs_hash"] == run["inputs_hash"]
    assert detail["engine_version"] == "1.0.0"

    page = client.get(
        RUNS,
        headers=env.auth["headers"],
        params={"company_id": env.company.id, "period_id": env.period["id"]},
    ).json()
    assert page["page"]["total"] == 1
    assert page["items"][0]["id"] == run["id"]

    missing = _send(client, env, "get", f"{RUNS}/999999", expect=404)
    assert missing.json()["code"] == "PAYROLL_RUN_NOT_FOUND"

    empty = _send(
        client,
        env,
        "get",
        f"{RUNS}/{run['id']}/lines",
    )
    filtered = client.get(
        f"{RUNS}/{run['id']}/lines",
        headers=env.auth["headers"],
        params={"employee_id": 999999},
    ).json()
    assert filtered["page"]["total"] == 0
    assert empty.json()["page"]["total"] == 1


def test_payslip_context_and_lines(client, pay_env):
    env = pay_env
    run = _calculate(client, env).json()
    lines = _send(client, env, "get", f"{RUNS}/{run['id']}/lines").json()
    line_id = lines["items"][0]["id"]
    payslip = _send(client, env, "get", f"/api/v1/payslips/{line_id}").json()
    assert payslip["run_status"] == "active"
    assert payslip["period_status"] == "calculated"
    assert payslip["inputs_hash"] == run["inputs_hash"]
    assert payslip["run_number"] == 1
    assert payslip["net_pay"] == "9300.00"
    basic = [entry for entry in payslip["lines"] if entry["label_en"] == "Basic Pay"]
    assert len(basic) == 1
    assert basic[0]["amount"] == "9300.00"
    assert basic[0]["line_type"] == "earning"


def test_accounting_export_contract(client, pay_env):
    env = pay_env
    run = _calculate(client, env).json()
    payload = _send(client, env, "get", f"{RUNS}/{run['id']}/export").json()
    assert payload["schema_name"] == "payroll.accounting_export.v1"
    assert payload["inputs_hash"] == run["inputs_hash"]
    assert payload["engine_version"] == "1.0.0"
    assert payload["period_id"] == env.period["id"]
    assert payload["currency"] == "SAR"
    assert payload["status"] == "calculated"
    assert payload["gross_total"] == "9300.00"
    assert payload["net_total"] == "9300.00"
    assert payload["employee_count"] == 1
    assert len(payload["lines"]) == 1
    entry = payload["lines"][0]
    assert entry["label_en"] == "Basic Pay"
    assert entry["line_type"] == "earning"
    assert entry["amount"] == "9300.00"
    assert entry["employee_number"] == env.employee["employee_number"]
    assert entry["component_code"] is None


# ---------------------------------------------------------------------------
# Deduction rules (consumed at APPROVE only)
# ---------------------------------------------------------------------------


def test_deduction_installment_consumed_at_approve(client, pay_env):
    env = pay_env
    created = _deduction(client, env, total_amount="1000").json()
    assert Decimal(created["remaining_amount"]) == Decimal("1000")
    assert created["status"] == "active"

    run = _calculate(client, env).json()
    assert run["deductions_total"] == "300.00"
    assert run["net_total"] == "9000.00"
    _review(client, env)
    _approve(client, env)

    row = _send(client, env, "get", f"{DEDUCTIONS}/{created['id']}").json()
    assert Decimal(row["remaining_amount"]) == Decimal("700")
    assert row["status"] == "active"


def test_deduction_non_installment_never_consumed(client, pay_env):
    env = pay_env
    created = _deduction(client, env).json()
    assert created["remaining_amount"] is None
    _calculate(client, env)
    _review(client, env)
    _approve(client, env)
    row = _send(client, env, "get", f"{DEDUCTIONS}/{created['id']}").json()
    assert row["remaining_amount"] is None
    assert row["status"] == "active"


def test_deduction_completed_when_remaining_zero(client, pay_env):
    env = pay_env
    created = _deduction(client, env, total_amount="300").json()
    _calculate(client, env)
    _review(client, env)
    _approve(client, env)
    row = _send(client, env, "get", f"{DEDUCTIONS}/{created['id']}").json()
    assert Decimal(row["remaining_amount"]) == Decimal("0")
    assert row["status"] == "completed"


def test_deduction_validation(client, pay_env):
    env = pay_env
    _deduction(client, env, total_amount="200", expect=422)
    _deduction(client, env, effective_to="2025-01-01", expect=422)


def test_deduction_update_only_active(client, pay_env):
    env = pay_env
    created = _deduction(client, env).json()
    cancelled = _send(
        client,
        env,
        "patch",
        f"{DEDUCTIONS}/{created['id']}",
        payload={"status": "cancelled"},
    )
    assert cancelled.json()["status"] == "cancelled"
    response = _send(
        client,
        env,
        "patch",
        f"{DEDUCTIONS}/{created['id']}",
        payload={"amount": "100"},
        expect=409,
    )
    assert response.json()["code"] == "PAYROLL_DEDUCTION_STATE_INVALID"


def test_deduction_not_found(client, pay_env):
    env = pay_env
    response = _send(client, env, "get", f"{DEDUCTIONS}/999999", expect=404)
    assert response.json()["code"] == "PAYROLL_DEDUCTION_NOT_FOUND"


# ---------------------------------------------------------------------------
# Adjustments (corrections flow to the next open period)
# ---------------------------------------------------------------------------


def test_adjustment_create_list_pending(client, pay_env):
    env = pay_env
    created = _adjustment(client, env).json()
    assert created["status"] == "pending"
    assert created["requested_by"] is not None
    page = client.get(
        ADJUSTMENTS,
        headers=env.auth["headers"],
        params={"company_id": env.company.id, "status": "pending"},
    ).json()
    assert page["page"]["total"] == 1
    assert page["items"][0]["id"] == created["id"]


def test_adjustment_approve_and_void(client, pay_env):
    env = pay_env
    created = _adjustment(client, env).json()
    approved = _send(
        client,
        env,
        "post",
        f"{ADJUSTMENTS}/{created['id']}/approve",
        payload={"decision_reason": "Verified"},
    )
    assert approved.json()["status"] == "approved"
    assert approved.json()["decided_at"] is not None
    voided = _send(
        client,
        env,
        "post",
        f"{ADJUSTMENTS}/{created['id']}/void",
        payload={},
    )
    assert voided.json()["status"] == "void"
    assert voided.json()["voided_at"] is not None


def test_adjustment_reject_then_state_errors(client, pay_env):
    env = pay_env
    first = _adjustment(client, env).json()
    rejected = _send(
        client,
        env,
        "post",
        f"{ADJUSTMENTS}/{first['id']}/reject",
        payload={"decision_reason": "Outside policy"},
    )
    assert rejected.json()["status"] == "rejected"
    approve_again = _send(
        client,
        env,
        "post",
        f"{ADJUSTMENTS}/{first['id']}/approve",
        payload={},
        expect=409,
    )
    assert approve_again.json()["code"] == "PAYROLL_ADJUSTMENT_STATE_INVALID"

    second = _adjustment(client, env, amount="50").json()
    _send(
        client,
        env,
        "post",
        f"{ADJUSTMENTS}/{second['id']}/approve",
        payload={},
    )
    reject_again = _send(
        client,
        env,
        "post",
        f"{ADJUSTMENTS}/{second['id']}/reject",
        payload={},
        expect=409,
    )
    assert reject_again.json()["code"] == "PAYROLL_ADJUSTMENT_STATE_INVALID"


def test_adjustment_invalid_target_approved_period(client, pay_env):
    env = pay_env
    _calculate(client, env)
    _review(client, env)
    _approve(client, env)
    response = _adjustment(client, env, expect=409)
    assert response.json()["code"] == "PAYROLL_ADJUSTMENT_INVALID_TARGET"
    assert "NEXT open period" in response.json()["detail"]


def test_adjustment_original_run_must_be_approved(client, pay_env):
    env = pay_env
    january_run = _calculate(client, env).json()
    february = _period(client, env).json()

    early = _adjustment(
        client,
        env,
        period_id=february["id"],
        original_run_id=january_run["id"],
        expect=409,
    )
    assert early.json()["code"] == "PAYROLL_ADJUSTMENT_INVALID_TARGET"
    assert "approved" in early.json()["detail"]

    _review(client, env)
    _approve(client, env)
    correction = _adjustment(
        client,
        env,
        period_id=february["id"],
        original_run_id=january_run["id"],
    )
    assert correction.status_code == 201
    assert correction.json()["original_run_id"] == january_run["id"]


def test_adjustment_included_in_calculation(client, pay_env):
    env = pay_env
    created = _adjustment(client, env, amount="100").json()
    _send(
        client,
        env,
        "post",
        f"{ADJUSTMENTS}/{created['id']}/approve",
        payload={},
    )
    run = _calculate(client, env).json()
    assert run["gross_total"] == "9400.00"
    assert run["net_total"] == "9400.00"


def test_adjustment_amount_must_be_positive(client, pay_env):
    env = pay_env
    _adjustment(client, env, amount="0", expect=422)
    _adjustment(client, env, amount="-5", expect=422)


# ---------------------------------------------------------------------------
# Statutory rules (framework - source_reference + effective dating)
# ---------------------------------------------------------------------------


def test_statutory_rule_create_version_and_as_of(client, pay_env):
    env = pay_env
    first = _rule(client, env).json()
    assert first["version"] == 1
    assert first["status"] == "active"
    assert first["requires_legal_verification"] is True

    inside = client.get(
        RULES,
        headers=env.auth["headers"],
        params={"company_id": env.company.id, "as_of": "2025-06-01"},
    ).json()
    assert inside["page"]["total"] == 1
    outside = client.get(
        RULES,
        headers=env.auth["headers"],
        params={"company_id": env.company.id, "as_of": "2026-06-01"},
    ).json()
    assert outside["page"]["total"] == 0

    second = _rule(client, env, effective_from="2026-01-01", effective_to=None).json()
    assert second["version"] == 2


def test_statutory_rule_source_required(client, pay_env):
    env = pay_env
    response = _rule(client, env, source_reference="   ", expect=400)
    assert response.json()["code"] == "PAYROLL_STATUTORY_RULE_SOURCE_REQUIRED"


def test_statutory_rule_invalid_rate(client, pay_env):
    env = pay_env
    response = _rule(
        client, env, statutory_key="gosi", rule_json={"rate": "1.5"}, expect=400
    )
    assert response.json()["code"] == "PAYROLL_STATUTORY_RULE_INVALID_VALUE"
    _rule(
        client,
        env,
        statutory_key="gosi",
        effective_from="2026-01-01",
        effective_to=None,
        rule_json={"rate": "0"},
        expect=400,
    )


def test_statutory_rule_overtime_requires_fields(client, pay_env):
    env = pay_env
    response = _rule(
        client,
        env,
        rule_json={"overtime_rate_percent": 50},
        expect=400,
    )
    assert response.json()["code"] == "PAYROLL_STATUTORY_RULE_INVALID_VALUE"
    assert "days_per_month" in response.json()["detail"]


@pytest.mark.parametrize(
    ("key", "values"),
    [
        ("daily_divisor", {"divisor": "0"}),
        ("proration_basis", {"basis": "weekly"}),
    ],
)
def test_statutory_rule_structured_value_validation(client, pay_env, key, values):
    env = pay_env
    response = _rule(client, env, statutory_key=key, rule_json=values, expect=400)
    assert response.json()["code"] == "PAYROLL_STATUTORY_RULE_INVALID_VALUE"


def test_statutory_rule_overlap_rejected(client, pay_env):
    env = pay_env
    _rule(client, env)
    response = _rule(
        client,
        env,
        effective_from="2025-06-01",
        effective_to="2025-12-31",
        expect=409,
    )
    assert response.json()["code"] == "PAYROLL_STATUTORY_RULE_OVERLAP"


def test_statutory_rule_invalid_date_range(client, pay_env):
    env = pay_env
    response = _rule(
        client,
        env,
        effective_from="2025-01-01",
        effective_to="2025-01-01",
        expect=400,
    )
    assert response.json()["code"] == "PAYROLL_STATUTORY_RULE_INVALID_DATE_RANGE"


def test_statutory_rule_deactivate_and_not_found(client, pay_env):
    env = pay_env
    created = _rule(client, env).json()
    deactivated = _send(
        client,
        env,
        "post",
        f"{RULES}/{created['id']}/deactivate",
        payload={},
    )
    assert deactivated.json()["status"] == "inactive"
    inactive = client.get(
        RULES,
        headers=env.auth["headers"],
        params={"company_id": env.company.id, "status": "inactive"},
    ).json()
    assert inactive["page"]["total"] == 1

    missing = _send(client, env, "get", f"{RULES}/999999", expect=404)
    assert missing.json()["code"] == "PAYROLL_STATUTORY_RULE_NOT_FOUND"
