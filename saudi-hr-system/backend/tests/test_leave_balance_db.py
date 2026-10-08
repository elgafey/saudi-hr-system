from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "Maha",
        "last_name_ar": "Alzahrani",
        "first_name_en": "Maha",
        "last_name_en": "Alzahrani",
        "status": "active",
        **overrides,
    }
    response = client.post(
        "/api/v1/employees", headers=auth["headers"], json=payload
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_type(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "code": "ANNUAL",
        "name_ar": "اجازة سنوية",
        "name_en": "Annual Leave",
        **overrides,
    }
    response = client.post(
        "/api/v1/leave-types", headers=auth["headers"], json=payload
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_allocation(client, auth, employee_id, leave_type_id, **overrides):
    payload = {
        "employee_id": employee_id,
        "leave_type_id": leave_type_id,
        "period_start": "2025-01-01",
        "period_end": "2025-12-31",
        "allocated_days": "21.00",
    }
    payload.update(overrides)
    response = client.post(
        "/api/v1/leave-allocations", headers=auth["headers"], json=payload
    )
    assert response.status_code == 201, response.text
    return response.json()


def _request(client, auth, employee_id, leave_type_id, **overrides):
    payload = {
        "employee_id": employee_id,
        "leave_type_id": leave_type_id,
        "start_date": "2025-03-03",
        "end_date": "2025-03-07",
    }
    payload.update(overrides)
    response = client.post(
        "/api/v1/leave-requests", headers=auth["headers"], json=payload
    )
    assert response.status_code == 201, response.text
    return response.json()


def _balance_line(client, auth, employee_id, **params):
    params = {"employee_id": employee_id, **params}
    response = client.get(
        "/api/v1/leave-balances", headers=auth["headers"], params=params
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    return next(item for item in items if item["code"] == "ANNUAL")


@pytest.fixture()
def balance_env(client, db_session):
    company = seed_company(db_session, "LV Balance")
    seed_user(db_session, "admin@bal.co", company, "company_admin")
    seed_user(db_session, "auditor@bal.co", company, "auditor")
    seed_user(db_session, "roleless@bal.co", company)

    admin = login(client, "admin@bal.co")
    employee = _create_employee(client, admin, company.id)
    annual = _create_type(client, admin, company.id)
    allocation = _create_allocation(client, admin, employee["id"], annual["id"])

    worker = seed_user(db_session, "worker@bal.co", company, "employee")
    linked = client.post(
        f"/api/v1/employees/{employee['id']}/user",
        headers=admin["headers"],
        json={"user_id": worker.id},
    )
    assert linked.status_code == 200, linked.text

    return SimpleNamespace(
        company=company,
        admin=admin,
        auditor=login(client, "auditor@bal.co"),
        roleless=login(client, "roleless@bal.co"),
        worker=login(client, "worker@bal.co"),
        employee=employee,
        annual=annual,
        allocation=allocation,
    )


PERIOD = {"period_start": "2025-03-01", "period_end": "2025-03-31"}


def test_balance_derivation_used_pending_remaining(client, balance_env):
    env = balance_env
    auth = env.admin

    line = _balance_line(
        client, auth, env.employee["id"], **PERIOD
    )
    assert line["allocated_days"] == "21.00"
    assert line["used_days"] == "0.00"
    assert line["pending_days"] == "0.00"
    assert line["remaining_days"] == "21.00"

    draft = _request(client, auth, env.employee["id"], env.annual["id"])
    line = _balance_line(client, auth, env.employee["id"], **PERIOD)
    assert line["pending_days"] == "0.00", "drafts never hold balance"

    submitted = client.post(
        f"/api/v1/leave-requests/{draft['id']}/submit",
        headers=auth["headers"],
        json={},
    )
    assert submitted.status_code == 200, submitted.text
    line = _balance_line(client, auth, env.employee["id"], **PERIOD)
    assert line["pending_days"] == "5.00"
    assert line["remaining_days"] == "16.00"

    approved = client.post(
        f"/api/v1/leave-requests/{draft['id']}/approve",
        headers=auth["headers"],
        json={"reason": "ok"},
    )
    assert approved.status_code == 200, approved.text
    line = _balance_line(client, auth, env.employee["id"], **PERIOD)
    assert line["used_days"] == "5.00"
    assert line["pending_days"] == "0.00"
    assert line["remaining_days"] == "16.00"

    # A rejected request never consumes anything.
    second = _request(
        client,
        auth,
        env.employee["id"],
        env.annual["id"],
        start_date="2025-03-10",
        end_date="2025-03-12",
    )
    client.post(
        f"/api/v1/leave-requests/{second['id']}/submit",
        headers=auth["headers"],
        json={},
    )
    rejected = client.post(
        f"/api/v1/leave-requests/{second['id']}/reject",
        headers=auth["headers"],
        json={"reason": "busy season"},
    )
    assert rejected.status_code == 200, rejected.text
    line = _balance_line(client, auth, env.employee["id"], **PERIOD)
    assert line["used_days"] == "5.00"
    assert line["pending_days"] == "0.00"
    assert line["remaining_days"] == "16.00"


def test_fifo_consumption_across_allocation_periods(client, balance_env):
    env = balance_env
    auth = env.admin

    # Two non-overlapping pools replace the fixture's single window.
    removed = client.delete(
        f"/api/v1/leave-allocations/{env.allocation['id']}",
        headers=auth["headers"],
    )
    assert removed.status_code == 204, removed.text
    first = _create_allocation(
        client,
        auth,
        env.employee["id"],
        env.annual["id"],
        period_start="2025-01-01",
        period_end="2025-06-30",
        allocated_days="5.00",
    )
    second = _create_allocation(
        client,
        auth,
        env.employee["id"],
        env.annual["id"],
        period_start="2025-07-01",
        period_end="2025-12-31",
        allocated_days="10.00",
    )

    request = _request(
        client,
        auth,
        env.employee["id"],
        env.annual["id"],
        start_date="2025-06-30",
        end_date="2025-07-11",
    )
    assert request["days"] == "12.00"
    assert (
        client.post(
            f"/api/v1/leave-requests/{request['id']}/submit",
            headers=auth["headers"],
            json={},
        ).status_code
        == 200
    )
    approved = client.post(
        f"/api/v1/leave-requests/{request['id']}/approve",
        headers=auth["headers"],
        json={},
    )
    assert approved.status_code == 200, approved.text

    # FIFO: the oldest period (5 days) drains first, remainder hits the
    # second pool.
    first_row = client.get(
        f"/api/v1/leave-allocations/{first['id']}", headers=auth["headers"]
    ).json()
    second_row = client.get(
        f"/api/v1/leave-allocations/{second['id']}", headers=auth["headers"]
    ).json()
    assert first_row["used_days"] == "5.00"
    assert second_row["used_days"] == "7.00"

    line = _balance_line(
        client,
        auth,
        env.employee["id"],
        period_start="2025-01-01",
        period_end="2025-12-31",
    )
    assert line["allocated_days"] == "15.00"
    assert line["used_days"] == "12.00"
    assert line["remaining_days"] == "3.00"


def test_insufficient_balance_blocks_submit(client, balance_env):
    env = balance_env
    auth = env.admin

    # A single tiny pool for August (the fixture's window is removed).
    removed = client.delete(
        f"/api/v1/leave-allocations/{env.allocation['id']}",
        headers=auth["headers"],
    )
    assert removed.status_code == 204, removed.text
    _create_allocation(
        client,
        auth,
        env.employee["id"],
        env.annual["id"],
        period_start="2025-08-01",
        period_end="2025-08-31",
        allocated_days="2.00",
    )
    request = _request(
        client,
        auth,
        env.employee["id"],
        env.annual["id"],
        start_date="2025-08-04",
        end_date="2025-08-08",
    )
    blocked = client.post(
        f"/api/v1/leave-requests/{request['id']}/submit",
        headers=auth["headers"],
        json={},
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["code"] == "LEAVE_INSUFFICIENT_BALANCE"

    # Still a draft, nothing was consumed.
    line = _balance_line(
        client,
        auth,
        env.employee["id"],
        period_start="2025-08-01",
        period_end="2025-08-31",
    )
    assert line["used_days"] == "0.00"
    assert line["pending_days"] == "0.00"


def test_negative_balance_flag_allows_drawdown(client, balance_env):
    env = balance_env
    auth = env.admin

    negative_type = _create_type(
        client,
        auth,
        env.company.id,
        code="NEGATIVE",
        name_ar="رصيد سالب",
        name_en="Negative allowed",
        negative_balance_allowed=True,
    )
    _create_allocation(
        client,
        auth,
        env.employee["id"],
        negative_type["id"],
        period_start="2025-09-01",
        period_end="2025-09-30",
        allocated_days="2.00",
    )
    request = _request(
        client,
        auth,
        env.employee["id"],
        negative_type["id"],
        start_date="2025-09-01",
        end_date="2025-09-05",
    )
    assert request["days"] == "5.00"
    assert (
        client.post(
            f"/api/v1/leave-requests/{request['id']}/submit",
            headers=auth["headers"],
            json={},
        ).status_code
        == 200
    )
    approved = client.post(
        f"/api/v1/leave-requests/{request['id']}/approve",
        headers=auth["headers"],
        json={},
    )
    assert approved.status_code == 200, approved.text

    page = client.get(
        "/api/v1/leave-allocations",
        headers=auth["headers"],
        params={"leave_type_id": negative_type["id"]},
    ).json()
    assert page["items"][0]["used_days"] == "5.00"

    response = client.get(
        "/api/v1/leave-balances",
        headers=auth["headers"],
        params={
            "employee_id": env.employee["id"],
            "leave_type_id": negative_type["id"],
            "period_start": "2025-09-01",
            "period_end": "2025-09-30",
        },
    ).json()
    line = next(
        item for item in response["items"] if item["code"] == "NEGATIVE"
    )
    assert line["remaining_days"] == "-3.00"
    assert line["negative_balance_allowed"] is True


def test_negative_balance_without_pool_still_rejected(client, balance_env):
    env = balance_env
    auth = env.admin

    negative_type = _create_type(
        client,
        auth,
        env.company.id,
        code="NOPOOL",
        name_ar="بدون تخصيص",
        name_en="No pool",
        negative_balance_allowed=True,
    )
    request = _request(
        client,
        auth,
        env.employee["id"],
        negative_type["id"],
        start_date="2025-10-06",
        end_date="2025-10-10",
    )
    blocked = client.post(
        f"/api/v1/leave-requests/{request['id']}/submit",
        headers=auth["headers"],
        json={},
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["code"] == "LEAVE_INSUFFICIENT_BALANCE"


def test_balance_scopes_as_of_and_period(client, balance_env):
    env = balance_env
    auth = env.admin

    # Replace the fixture window with two disjoint ones.
    removed = client.delete(
        f"/api/v1/leave-allocations/{env.allocation['id']}",
        headers=auth["headers"],
    )
    assert removed.status_code == 204, removed.text
    _create_allocation(
        client,
        auth,
        env.employee["id"],
        env.annual["id"],
        period_start="2025-01-01",
        period_end="2025-06-30",
        allocated_days="5.00",
    )
    _create_allocation(
        client,
        auth,
        env.employee["id"],
        env.annual["id"],
        period_start="2025-07-01",
        period_end="2025-12-31",
        allocated_days="10.00",
    )

    # as_of inside the first window only.
    as_of = client.get(
        "/api/v1/leave-balances",
        headers=auth["headers"],
        params={"employee_id": env.employee["id"], "as_of": "2025-03-15"},
    ).json()
    annual_line = next(item for item in as_of["items"] if item["code"] == "ANNUAL")
    assert annual_line["allocated_days"] == "5.00"

    as_of_late = client.get(
        "/api/v1/leave-balances",
        headers=auth["headers"],
        params={"employee_id": env.employee["id"], "as_of": "2025-09-15"},
    ).json()
    late_line = next(
        item for item in as_of_late["items"] if item["code"] == "ANNUAL"
    )
    assert late_line["allocated_days"] == "10.00"

    # Period query pins both endpoints of the scope.
    period_line = _balance_line(
        client,
        auth,
        env.employee["id"],
        period_start="2025-08-01",
        period_end="2025-08-31",
    )
    assert period_line["allocated_days"] == "10.00"

    early_period = _balance_line(
        client,
        auth,
        env.employee["id"],
        period_start="2025-02-01",
        period_end="2025-02-28",
    )
    assert early_period["allocated_days"] == "5.00"

    # No parameters at all: today (2026) is outside every 2025 window.
    today = client.get(
        "/api/v1/leave-balances",
        headers=auth["headers"],
        params={"employee_id": env.employee["id"]},
    ).json()
    today_line = next(item for item in today["items"] if item["code"] == "ANNUAL")
    assert today_line["allocated_days"] == "0.00"
    assert today_line["remaining_days"] == "0.00"


def test_balance_endpoints_and_permissions(client, balance_env):
    env = balance_env

    # /leave-balances requires leave_balance.view.
    assert (
        client.get(
            "/api/v1/leave-balances",
            headers=env.roleless["headers"],
            params={"employee_id": env.employee["id"]},
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/api/v1/leave-balances",
            headers=env.worker["headers"],
            params={"employee_id": env.employee["id"]},
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/api/v1/leave-balances",
            headers=env.auditor["headers"],
            params={"employee_id": env.employee["id"]},
        ).status_code
        == 200
    )

    # /leave-balances/me needs only authentication + an employee link.
    mine = client.get(
        "/api/v1/leave-balances/me",
        headers=env.worker["headers"],
        params={"as_of": "2025-03-15"},
    )
    assert mine.status_code == 200, mine.text
    codes = [item["code"] for item in mine.json()["items"]]
    assert "ANNUAL" in codes

    # Authenticated but not linked to an employee -> 403.
    not_linked = client.get(
        "/api/v1/leave-balances/me", headers=env.admin["headers"]
    )
    assert not_linked.status_code == 403, not_linked.text
    assert not_linked.json()["code"] == "forbidden"


def test_balance_is_company_isolated(client, balance_env, db_session):
    from tests.conftest import seed_company

    env = balance_env
    other = seed_company(db_session, "LV Balance Other")
    seed_user(db_session, "admin@bal-other.co", other, "company_admin")
    other_admin = login(client, "admin@bal-other.co")

    response = client.get(
        "/api/v1/leave-balances",
        headers=other_admin["headers"],
        params={"employee_id": env.employee["id"]},
    )
    assert response.status_code == 404, response.text
    assert response.json()["code"] == "LEAVE_REQUEST_NOT_FOUND"
