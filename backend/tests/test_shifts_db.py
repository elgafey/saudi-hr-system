from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "خالد",
        "last_name_ar": "القحطاني",
        "first_name_en": "Khaled",
        "last_name_en": "Alqahtani",
        **overrides,
    }
    response = client.post("/api/v1/employees", headers=auth["headers"], json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def shift_env(client, db_session):
    company = seed_company(db_session, "Shift Co")
    seed_user(db_session, "admin@shift.co", company, "company_admin")
    auth = login(client, "admin@shift.co")
    employee = _create_employee(client, auth, company.id)
    return SimpleNamespace(company=company, auth=auth, employee=employee)


def _payload(env, **overrides):
    payload = {
        "company_id": env.company.id,
        "code": "DAY",
        "name_ar": "الوردية النهارية",
        "name_en": "Day Shift",
        "start_time": "09:00:00",
        "end_time": "17:00:00",
    }
    payload.update(overrides)
    return payload


def _create(client, env, **overrides):
    response = client.post(
        "/api/v1/shifts", headers=env.auth["headers"], json=_payload(env, **overrides)
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_shift_create_list_get_update_delete(client, shift_env):
    env = shift_env
    created = _create(client, env)
    assert created["crosses_midnight"] is False
    assert created["status"] == "active"

    page = client.get(
        "/api/v1/shifts",
        headers=env.auth["headers"],
        params={"company_id": env.company.id},
    ).json()
    assert page["page"]["total"] == 1

    detail = client.get(f"/api/v1/shifts/{created['id']}", headers=env.auth["headers"])
    assert detail.status_code == 200
    assert detail.json()["code"] == "DAY"

    updated = client.patch(
        f"/api/v1/shifts/{created['id']}",
        headers=env.auth["headers"],
        json={"name_en": "General Shift", "status": "archived"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name_en"] == "General Shift"

    assert client.delete(
        f"/api/v1/shifts/{created['id']}", headers=env.auth["headers"]
    ).status_code == 204
    assert client.get(
        f"/api/v1/shifts/{created['id']}", headers=env.auth["headers"]
    ).status_code == 404


def test_shift_zero_duration_rejected(client, shift_env):
    env = shift_env
    response = client.post(
        "/api/v1/shifts", headers=env.auth["headers"],
        json=_payload(env, code="ZERO", start_time="09:00:00", end_time="09:00:00"),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "SHIFT_INVALID_TIME_RANGE"


def test_shift_overnight_flag(client, shift_env):
    env = shift_env
    overnight = _create(
        client, env, code="NIGHT", start_time="22:00:00", end_time="06:00:00"
    )
    assert overnight["crosses_midnight"] is True

    day = _create(client, env, code="DAY2")
    assert day["crosses_midnight"] is False

    flipped = client.patch(
        f"/api/v1/shifts/{day['id']}",
        headers=env.auth["headers"],
        json={"start_time": "22:00:00", "end_time": "06:00:00"},
    )
    assert flipped.status_code == 200
    assert flipped.json()["crosses_midnight"] is True


def test_shift_break_validation(client, shift_env):
    env = shift_env
    # break outside the window
    rejected = client.post(
        "/api/v1/shifts", headers=env.auth["headers"],
        json=_payload(env, code="BRK", breaks=[
            {"start_time": "18:00:00", "end_time": "18:30:00", "is_paid": False}
        ]),
    )
    assert rejected.status_code == 400
    assert rejected.json()["code"] == "SCHEDULE_INVALID_BREAK"

    # break allowed when it sits inside the window
    created = _create(client, env, code="BRK2", breaks=[
        {"start_time": "12:30:00", "end_time": "13:30:00", "is_paid": False}
    ])
    assert len(created["breaks"]) == 1
    assert created["breaks"][0]["is_paid"] is False

    # replacing breaks via update
    updated = client.patch(
        f"/api/v1/shifts/{created['id']}",
        headers=env.auth["headers"],
        json={"breaks": [{"start_time": "13:00:00", "end_time": "13:30:00"}]},
    )
    assert updated.status_code == 200
    assert len(updated.json()["breaks"]) == 1
    assert updated.json()["breaks"][0]["is_paid"] is True


def test_shift_overnight_breaks_validated(client, shift_env):
    env = shift_env
    created = _create(
        client, env, code="NGT", start_time="22:00:00", end_time="06:00:00",
        breaks=[{"start_time": "02:00:00", "end_time": "02:30:00"}],
    )
    assert created["crosses_midnight"] is True
    assert len(created["breaks"]) == 1

    rejected = client.post(
        "/api/v1/shifts", headers=env.auth["headers"],
        json=_payload(env, code="NGT2", start_time="22:00:00",
                      end_time="06:00:00",
                      breaks=[{"start_time": "12:00:00",
                               "end_time": "12:30:00"}]),
    )
    assert rejected.status_code == 400
    assert rejected.json()["code"] == "SCHEDULE_INVALID_BREAK"


def test_shift_duplicate_code_rejected(client, shift_env):
    env = shift_env
    _create(client, env)
    duplicate = client.post(
        "/api/v1/shifts", headers=env.auth["headers"], json=_payload(env)
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "SHIFT_CODE_EXISTS"


def test_shift_in_use_by_assignment_cannot_be_deleted(client, shift_env):
    env = shift_env
    shift = _create(client, env, code="USEME")
    schedule = client.post(
        "/api/v1/work-schedules", headers=env.auth["headers"],
        json={"company_id": env.company.id, "code": "S1",
              "name_ar": "جدول", "name_en": "S1", "effective_from": "2025-01-01"},
    )
    assert schedule.status_code == 201, schedule.text
    assignment = client.post(
        f"/api/v1/employees/{env.employee['id']}/work-assignments",
        headers=env.auth["headers"],
        json={"schedule_id": schedule.json()["id"], "shift_id": shift["id"],
              "effective_from": "2025-01-01"},
    )
    assert assignment.status_code == 201, assignment.text

    removed = client.delete(
        f"/api/v1/shifts/{shift['id']}", headers=env.auth["headers"]
    )
    assert removed.status_code == 409
    assert removed.json()["code"] == "SHIFT_IN_USE"


def test_shift_in_use_by_schedule_day_cannot_be_deleted(client, shift_env):
    env = shift_env
    shift = _create(client, env, code="PIN")
    schedule = client.post(
        "/api/v1/work-schedules", headers=env.auth["headers"],
        json={"company_id": env.company.id, "code": "S2",
              "name_ar": "جدول", "name_en": "S2", "effective_from": "2025-01-01"},
    )
    assert schedule.status_code == 201, schedule.text
    days = client.put(
        f"/api/v1/work-schedules/{schedule.json()['id']}/days",
        headers=env.auth["headers"],
        json={"days": [{"weekday": 0, "shift_id": shift["id"]}]},
    )
    assert days.status_code == 200, days.text

    removed = client.delete(
        f"/api/v1/shifts/{shift['id']}", headers=env.auth["headers"]
    )
    assert removed.status_code == 409
    assert removed.json()["code"] == "SHIFT_IN_USE"


def test_shift_list_search_pagination(client, shift_env):
    env = shift_env
    for index in range(3):
        _create(client, env, code=f"SC{index}", name_en=f"Shift {index}")

    page = client.get(
        "/api/v1/shifts",
        headers=env.auth["headers"],
        params={"company_id": env.company.id, "page": 1, "page_size": 2},
    ).json()
    assert page["page"]["total"] == 3
    assert len(page["items"]) == 2

    searched = client.get(
        "/api/v1/shifts",
        headers=env.auth["headers"],
        params={"company_id": env.company.id, "search": "Shift 1"},
    ).json()
    assert searched["page"]["total"] == 1


def test_shift_cross_company_is_404(client, shift_env, db_session):
    env = shift_env
    shift = _create(client, env, code="XCO")
    other = seed_company(db_session, "Shift Other Co")
    seed_user(db_session, "admin@shift-other.co", other, "company_admin")
    outsider = login(client, "admin@shift-other.co")

    assert client.get(
        f"/api/v1/shifts/{shift['id']}", headers=outsider["headers"]
    ).status_code == 404
    assert client.patch(
        f"/api/v1/shifts/{shift['id']}", headers=outsider["headers"],
        json={"name_en": "Hijacked"},
    ).status_code == 404
    assert client.delete(
        f"/api/v1/shifts/{shift['id']}", headers=outsider["headers"]
    ).status_code == 404


def test_shift_audit_actions(client, shift_env):
    env = shift_env
    shift = _create(client, env, code="AUD")
    client.patch(
        f"/api/v1/shifts/{shift['id']}", headers=env.auth["headers"],
        json={"name_en": "Renamed"},
    )
    client.delete(f"/api/v1/shifts/{shift['id']}", headers=env.auth["headers"])

    actions = set()
    page = client.get("/api/v1/audit-logs", headers=env.auth["headers"]).json()
    for item in page["items"]:
        if item["entity"] == "shift":
            actions.add(item["action"])
    assert actions == {"shift.create", "shift.update", "shift.delete"}
