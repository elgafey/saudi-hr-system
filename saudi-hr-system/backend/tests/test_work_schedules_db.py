from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "سارة",
        "last_name_ar": "العتيبي",
        "first_name_en": "Sara",
        "last_name_en": "Alotaibi",
        **overrides,
    }
    response = client.post("/api/v1/employees", headers=auth["headers"], json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def sched_env(client, db_session):
    company = seed_company(db_session, "Sched Co")
    seed_user(db_session, "admin@sched.co", company, "company_admin")
    auth = login(client, "admin@sched.co")
    employee = _create_employee(client, auth, company.id)
    return SimpleNamespace(
        company=company, auth=auth, employee=employee,
    )


def _payload(env, **overrides):
    payload = {
        "company_id": env.company.id,
        "code": "STD",
        "name_ar": "الجدول القياسي",
        "name_en": "Standard Schedule",
        "timezone": "Asia/Riyadh",
        "effective_from": "2025-01-01",
    }
    payload.update(overrides)
    return payload


def _create(client, env, **overrides):
    response = client.post(
        "/api/v1/work-schedules", headers=env.auth["headers"],
        json=_payload(env, **overrides),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_schedule_create_list_get_update_delete(client, sched_env):
    env = sched_env
    created = _create(client, env)
    assert created["timezone"] == "Asia/Riyadh"
    assert created["status"] == "active"

    page = client.get(
        "/api/v1/work-schedules",
        headers=env.auth["headers"],
        params={"company_id": env.company.id},
    ).json()
    assert page["page"]["total"] == 1
    assert page["items"][0]["id"] == created["id"]

    detail = client.get(
        f"/api/v1/work-schedules/{created['id']}", headers=env.auth["headers"]
    )
    assert detail.status_code == 200

    updated = client.patch(
        f"/api/v1/work-schedules/{created['id']}",
        headers=env.auth["headers"],
        json={"name_en": "Core Hours", "status": "archived"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name_en"] == "Core Hours"
    assert updated.json()["status"] == "archived"

    removed = client.delete(
        f"/api/v1/work-schedules/{created['id']}", headers=env.auth["headers"]
    )
    assert removed.status_code == 204
    assert client.get(
        f"/api/v1/work-schedules/{created['id']}", headers=env.auth["headers"]
    ).status_code == 404


def test_schedule_duplicate_code_same_window_rejected(client, sched_env):
    env = sched_env
    _create(client, env)
    duplicate = client.post(
        "/api/v1/work-schedules", headers=env.auth["headers"],
        json=_payload(env),
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "SCHEDULE_CODE_EXISTS"


def test_schedule_overlapping_version_rejected(client, sched_env):
    env = sched_env
    _create(client, env, effective_to="2025-06-30")
    overlapping = client.post(
        "/api/v1/work-schedules", headers=env.auth["headers"],
        json=_payload(env, effective_from="2025-03-01"),
    )
    assert overlapping.status_code == 409
    assert overlapping.json()["code"] == "SCHEDULE_CODE_EXISTS"


def test_schedule_versioning_non_overlapping_allowed(client, sched_env):
    env = sched_env
    _create(client, env, effective_to="2025-06-30")
    successor = client.post(
        "/api/v1/work-schedules", headers=env.auth["headers"],
        json=_payload(
            env, effective_from="2025-07-01", name_en="V2 Schedule"
        ),
    )
    assert successor.status_code == 201, successor.text
    assert successor.json()["effective_from"] == "2025-07-01"
    assert successor.json()["effective_to"] is None


def test_schedule_invalid_date_range(client, sched_env):
    env = sched_env
    response = client.post(
        "/api/v1/work-schedules", headers=env.auth["headers"],
        json=_payload(env, effective_from="2025-05-01", effective_to="2025-01-01"),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "SCHEDULE_INVALID_DATE_RANGE"


def test_schedule_invalid_timezone_rejected(client, sched_env):
    env = sched_env
    response = client.post(
        "/api/v1/work-schedules", headers=env.auth["headers"],
        json=_payload(env, timezone="Mars/Olympus"),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "SCHEDULE_INVALID_TIMEZONE"


def test_schedule_days_put_validation(client, sched_env):
    env = sched_env
    schedule = _create(client, env)
    url = f"/api/v1/work-schedules/{schedule['id']}/days"

    # only one of start/end
    response = client.put(
        url, headers=env.auth["headers"],
        json={"days": [{"weekday": 0, "start_time": "09:00:00"}]},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "SCHEDULE_INVALID_TIME_RANGE"

    # zero-duration window
    response = client.put(
        url, headers=env.auth["headers"],
        json={"days": [
            {"weekday": 0, "start_time": "09:00:00", "end_time": "09:00:00"}
        ]},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "SCHEDULE_INVALID_TIME_RANGE"

    # rest day with a window
    response = client.put(
        url, headers=env.auth["headers"],
        json={"days": [
            {"weekday": 5, "is_working": False,
             "start_time": "09:00:00", "end_time": "17:00:00"}
        ]},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "SCHEDULE_INVALID_TIME_RANGE"

    # break outside the window
    response = client.put(
        url, headers=env.auth["headers"],
        json={"days": [
            {"weekday": 0, "start_time": "09:00:00", "end_time": "17:00:00",
             "breaks": [{"start_time": "18:00:00", "end_time": "18:30:00"}]}
        ]},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "SCHEDULE_INVALID_BREAK"

    # duplicate weekday in one payload
    response = client.put(
        url, headers=env.auth["headers"],
        json={"days": [
            {"weekday": 0, "start_time": "09:00:00", "end_time": "17:00:00"},
            {"weekday": 0, "start_time": "10:00:00", "end_time": "18:00:00"},
        ]},
    )
    assert response.status_code == 409


def test_schedule_days_success_and_breaks(client, sched_env):
    env = sched_env
    schedule = _create(client, env)
    url = f"/api/v1/work-schedules/{schedule['id']}/days"
    response = client.put(
        url, headers=env.auth["headers"],
        json={"days": [
            {"weekday": 0, "start_time": "09:00:00", "end_time": "17:00:00",
             "breaks": [{"start_time": "12:30:00", "end_time": "13:30:00",
                         "is_paid": False}]},
            {"weekday": 4, "start_time": "09:00:00", "end_time": "15:00:00"},
            {"weekday": 5, "is_working": False},
        ]},
    )
    assert response.status_code == 200, response.text
    days = response.json()["items"]
    assert sorted(d["weekday"] for d in days) == [0, 4, 5]
    monday = next(d for d in days if d["weekday"] == 0)
    assert len(monday["breaks"]) == 1
    assert monday["breaks"][0]["is_paid"] is False

    fetched = client.get(url, headers=env.auth["headers"])
    assert fetched.status_code == 200
    assert len(fetched.json()["items"]) == 3


def test_schedule_overnight_window_and_break(client, sched_env):
    env = sched_env
    schedule = _create(client, env)
    url = f"/api/v1/work-schedules/{schedule['id']}/days"
    # window 22:00 -> 06:00 with a break in the middle of the night
    response = client.put(
        url, headers=env.auth["headers"],
        json={"days": [
            {"weekday": 6, "start_time": "22:00:00", "end_time": "06:00:00",
             "breaks": [{"start_time": "02:00:00", "end_time": "02:30:00"}]},
        ]},
    )
    assert response.status_code == 200, response.text
    day = response.json()["items"][0]
    assert day["start_time"] == "22:00:00"
    assert day["end_time"] == "06:00:00"
    assert len(day["breaks"]) == 1

    # a break outside the overnight window is still rejected
    rejected = client.put(
        url, headers=env.auth["headers"],
        json={"days": [
            {"weekday": 6, "start_time": "22:00:00", "end_time": "06:00:00",
             "breaks": [{"start_time": "12:00:00", "end_time": "12:30:00"}]},
        ]},
    )
    assert rejected.status_code == 400
    assert rejected.json()["code"] == "SCHEDULE_INVALID_BREAK"


def test_schedule_days_pin_shift_requires_company_shift(client, sched_env):
    env = sched_env
    schedule = _create(client, env)
    url = f"/api/v1/work-schedules/{schedule['id']}/days"
    response = client.put(
        url, headers=env.auth["headers"],
        json={"days": [{"weekday": 0, "shift_id": 999999}]},
    )
    assert response.status_code == 404
    assert response.json()["code"] == "SHIFT_NOT_FOUND"


def test_schedule_day_cannot_define_window_and_shift(client, sched_env):
    env = sched_env
    shift = client.post(
        "/api/v1/shifts", headers=env.auth["headers"],
        json={"company_id": env.company.id, "code": "NIGHT",
              "name_ar": "ليلي", "name_en": "Night",
              "start_time": "22:00:00", "end_time": "06:00:00"},
    )
    assert shift.status_code == 201, shift.text
    schedule = _create(client, env)
    response = client.put(
        f"/api/v1/work-schedules/{schedule['id']}/days",
        headers=env.auth["headers"],
        json={"days": [
            {"weekday": 0, "shift_id": shift.json()["id"],
             "start_time": "09:00:00", "end_time": "17:00:00"}
        ]},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "SCHEDULE_INVALID_TIME_RANGE"


def test_schedule_delete_in_use_rejected(client, sched_env):
    env = sched_env
    schedule = _create(client, env)
    assignment = client.post(
        f"/api/v1/employees/{env.employee['id']}/work-assignments",
        headers=env.auth["headers"],
        json={"schedule_id": schedule["id"], "effective_from": "2025-01-01"},
    )
    assert assignment.status_code == 201, assignment.text

    removed = client.delete(
        f"/api/v1/work-schedules/{schedule['id']}", headers=env.auth["headers"]
    )
    assert removed.status_code == 409
    assert removed.json()["code"] == "SCHEDULE_IN_USE"


def test_schedule_list_pagination_search_and_status(client, sched_env):
    env = sched_env
    for index in range(3):
        _create(
            client, env, code=f"SCH{index}",
            name_en=f"Schedule {index}",
            status="archived" if index == 2 else "active",
        )
    first = client.get(
        "/api/v1/work-schedules",
        headers=env.auth["headers"],
        params={"company_id": env.company.id, "page": 1, "page_size": 2},
    ).json()
    assert first["page"]["total"] == 3
    assert len(first["items"]) == 2

    second = client.get(
        "/api/v1/work-schedules",
        headers=env.auth["headers"],
        params={"company_id": env.company.id, "page": 2, "page_size": 2},
    ).json()
    assert len(second["items"]) == 1

    searched = client.get(
        "/api/v1/work-schedules",
        headers=env.auth["headers"],
        params={"company_id": env.company.id, "search": "Schedule 1"},
    ).json()
    assert searched["page"]["total"] == 1

    archived = client.get(
        "/api/v1/work-schedules",
        headers=env.auth["headers"],
        params={"company_id": env.company.id, "status": "archived"},
    ).json()
    assert archived["page"]["total"] == 1


def test_schedule_cross_company_is_404(client, sched_env, db_session):
    env = sched_env
    schedule = _create(client, env)
    other = seed_company(db_session, "Sched Other Co")
    seed_user(db_session, "admin@sched-other.co", other, "company_admin")
    outsider = login(client, "admin@sched-other.co")

    assert client.get(
        f"/api/v1/work-schedules/{schedule['id']}", headers=outsider["headers"]
    ).status_code == 404
    assert client.patch(
        f"/api/v1/work-schedules/{schedule['id']}",
        headers=outsider["headers"], json={"name_en": "Hijacked"},
    ).status_code == 404
    assert client.delete(
        f"/api/v1/work-schedules/{schedule['id']}", headers=outsider["headers"]
    ).status_code == 404

    # The outsider's own company list never contains the foreign schedule.
    listing = client.get(
        "/api/v1/work-schedules",
        headers=outsider["headers"],
        params={"company_id": other.id},
    ).json()
    assert listing["page"]["total"] == 0


def test_schedule_audit_actions(client, sched_env):
    env = sched_env
    schedule = _create(client, env)
    client.patch(
        f"/api/v1/work-schedules/{schedule['id']}",
        headers=env.auth["headers"], json={"name_en": "Renamed"},
    )
    client.put(
        f"/api/v1/work-schedules/{schedule['id']}/days",
        headers=env.auth["headers"],
        json={"days": [{"weekday": 0, "start_time": "09:00:00",
                        "end_time": "17:00:00"}]},
    )
    client.delete(
        f"/api/v1/work-schedules/{schedule['id']}", headers=env.auth["headers"]
    )
    audit = client.get(
        "/api/v1/audit-logs", headers=env.auth["headers"],
        params={"action": "work_schedule.create"},
    ).json()
    assert audit["page"]["total"] == 1
    actions = set()
    page = client.get("/api/v1/audit-logs", headers=env.auth["headers"]).json()
    for item in page["items"]:
        if item["entity"] == "work_schedule":
            actions.add(item["action"])
    assert actions == {
        "work_schedule.create",
        "work_schedule.update",
        "work_schedule.delete",
    }
