from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "نورة",
        "last_name_ar": "الشمري",
        "first_name_en": "Noura",
        "last_name_en": "Alshammari",
        **overrides,
    }
    response = client.post("/api/v1/employees", headers=auth["headers"], json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def asg_env(client, db_session):
    company = seed_company(db_session, "Asg Co")
    seed_user(db_session, "admin@asg.co", company, "company_admin")
    auth = login(client, "admin@asg.co")
    employee = _create_employee(client, auth, company.id)

    schedule = client.post(
        "/api/v1/work-schedules", headers=auth["headers"],
        json={"company_id": company.id, "code": "STD",
              "name_ar": "الجدول القياسي", "name_en": "Standard",
              "effective_from": "2025-01-01"},
    )
    assert schedule.status_code == 201, schedule.text
    schedule = schedule.json()

    days = client.put(
        f"/api/v1/work-schedules/{schedule['id']}/days",
        headers=auth["headers"],
        json={"days": [
            {"weekday": wd, "start_time": "09:00:00", "end_time": "17:00:00"}
            for wd in (0, 1, 2, 3, 4)
        ] + [{"weekday": 5, "is_working": False},
             {"weekday": 6, "is_working": False}]},
    )
    assert days.status_code == 200, days.text

    shift = client.post(
        "/api/v1/shifts", headers=auth["headers"],
        json={"company_id": company.id, "code": "EARLY",
              "name_ar": "مبكرة", "name_en": "Early",
              "start_time": "07:00:00", "end_time": "15:00:00"},
    )
    assert shift.status_code == 201, shift.text

    return SimpleNamespace(
        company=company, auth=auth, employee=employee,
        schedule=schedule, shift=shift.json(),
    )


def _assign(client, env, **overrides):
    payload = {"schedule_id": env.schedule["id"], "effective_from": "2025-01-01"}
    payload.update(overrides)
    response = client.post(
        f"/api/v1/employees/{env.employee['id']}/work-assignments",
        headers=env.auth["headers"], json=payload,
    )
    return response


def test_assignment_crud_and_audit(client, asg_env):
    env = asg_env
    created = _assign(client, env)
    assert created.status_code == 201, created.text
    row = created.json()
    assert row["schedule_id"] == env.schedule["id"]
    assert row["effective_to"] is None

    listing = client.get(
        f"/api/v1/employees/{env.employee['id']}/work-assignments",
        headers=env.auth["headers"],
    )
    assert listing.status_code == 200
    assert listing.json()["page"]["total"] == 1

    detail = client.get(
        f"/api/v1/employees/{env.employee['id']}/work-assignments/{row['id']}",
        headers=env.auth["headers"],
    )
    assert detail.status_code == 200

    updated = client.patch(
        f"/api/v1/employees/{env.employee['id']}/work-assignments/{row['id']}",
        headers=env.auth["headers"],
        json={"notes": "from January", "shift_id": env.shift["id"]},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["shift_id"] == env.shift["id"]

    removed = client.delete(
        f"/api/v1/employees/{env.employee['id']}/work-assignments/{row['id']}",
        headers=env.auth["headers"],
    )
    assert removed.status_code == 204

    actions = set()
    page = client.get("/api/v1/audit-logs", headers=env.auth["headers"]).json()
    for item in page["items"]:
        if item["entity"] == "employee_work_assignment":
            actions.add(item["action"])
    assert actions == {
        "work_assignment.create",
        "work_assignment.update",
        "work_assignment.delete",
    }


def test_assignment_create_autocloses_open_record(client, asg_env):
    env = asg_env
    first = _assign(client, env, effective_from="2025-01-01")
    assert first.status_code == 201, first.text

    second = _assign(client, env, effective_from="2025-07-01")
    assert second.status_code == 201, second.text

    rows = client.get(
        f"/api/v1/employees/{env.employee['id']}/work-assignments",
        headers=env.auth["headers"],
    ).json()["items"]
    assert len(rows) == 2
    closed = next(r for r in rows if r["id"] == first.json()["id"])
    open_row = next(r for r in rows if r["id"] == second.json()["id"])
    assert closed["effective_to"] == "2025-06-30"
    assert open_row["effective_to"] is None


def test_assignment_backdate_before_open_start_rejected(client, asg_env):
    env = asg_env
    _assign(client, env, effective_from="2025-01-01")
    backdated = _assign(client, env, effective_from="2024-06-01")
    assert backdated.status_code == 409
    assert backdated.json()["code"] == "SCHEDULE_ASSIGNMENT_OVERLAP"


def test_assignment_closed_overlap_rejected(client, asg_env):
    env = asg_env
    _assign(client, env, effective_from="2025-01-01", effective_to="2025-06-30")
    overlapping = _assign(
        client, env, effective_from="2025-03-01", effective_to="2025-09-30"
    )
    assert overlapping.status_code == 409
    assert overlapping.json()["code"] == "SCHEDULE_ASSIGNMENT_OVERLAP"

    adjacent = _assign(
        client, env, effective_from="2025-07-01", effective_to="2025-12-31"
    )
    assert adjacent.status_code == 201, adjacent.text


def test_assignment_touching_boundary_rejected(client, asg_env):
    env = asg_env
    _assign(client, env, effective_from="2025-01-01", effective_to="2025-06-30")
    # starts on the last day of the closed window -> not adjacent
    touching = _assign(client, env, effective_from="2025-06-30")
    assert touching.status_code == 409
    assert touching.json()["code"] == "SCHEDULE_ASSIGNMENT_OVERLAP"


def test_assignment_date_order_rejected(client, asg_env):
    env = asg_env
    response = _assign(
        client, env, effective_from="2025-05-01", effective_to="2025-01-01"
    )
    assert response.status_code == 400
    assert response.json()["code"] == "ASSIGNMENT_INVALID_DATE_RANGE"


def test_assignment_update_overlap_rejected(client, asg_env):
    env = asg_env
    first = _assign(client, env, effective_from="2025-01-01",
                    effective_to="2025-03-31")
    second = _assign(client, env, effective_from="2025-04-01",
                     effective_to="2025-06-30")
    assert first.status_code == 201 and second.status_code == 201

    moved = client.patch(
        f"/api/v1/employees/{env.employee['id']}/work-assignments/"
        f"{second.json()['id']}",
        headers=env.auth["headers"],
        json={"effective_from": "2025-02-01"},
    )
    assert moved.status_code == 409
    assert moved.json()["code"] == "SCHEDULE_ASSIGNMENT_OVERLAP"


def test_assignment_cannot_reopen_second_open_record(client, asg_env):
    env = asg_env
    _assign(client, env, effective_from="2025-01-01")
    second = _assign(client, env, effective_from="2025-07-01")
    assert second.status_code == 201
    reopened = client.patch(
        f"/api/v1/employees/{env.employee['id']}/work-assignments/"
        f"{second.json()['id']}",
        headers=env.auth["headers"],
        json={"effective_to": "2025-12-31", "effective_from": "2025-01-01"},
    )
    assert reopened.status_code == 409
    assert reopened.json()["code"] == "SCHEDULE_ASSIGNMENT_OVERLAP"


def test_assignment_foreign_schedule_rejected(client, asg_env, db_session):
    env = asg_env
    other = seed_company(db_session, "Asg Other Co")
    schedule = client.post(
        "/api/v1/work-schedules", headers=env.auth["headers"],
        json={"company_id": other.id, "code": "OTH",
              "name_ar": "خارجي", "name_en": "Other",
              "effective_from": "2025-01-01"},
    )
    # the other company's schedule is not even visible to this admin
    assert schedule.status_code == 403, schedule.text

    response = _assign(client, env, schedule_id=999999)
    assert response.status_code == 404
    assert response.json()["code"] == "WORK_SCHEDULE_NOT_FOUND"


def test_assignment_cross_company_employee_is_404(client, asg_env, db_session):
    env = asg_env
    other = seed_company(db_session, "Asg Other Co")
    seed_user(db_session, "admin@asg-other.co", other, "company_admin")
    outsider = login(client, "admin@asg-other.co")

    listing = client.get(
        f"/api/v1/employees/{env.employee['id']}/work-assignments",
        headers=outsider["headers"],
    )
    assert listing.status_code == 404
    assert listing.json()["code"] == "EMPLOYEE_NOT_FOUND"


def test_schedule_resolution_endpoint(client, asg_env):
    env = asg_env
    unresolved = client.get(
        f"/api/v1/employees/{env.employee['id']}/schedule",
        headers=env.auth["headers"], params={"date": "2025-01-06"},  # Monday
    )
    assert unresolved.status_code == 200, unresolved.text
    body = unresolved.json()
    assert body["assignment_id"] is None
    assert body["schedule_id"] is None
    assert body["is_working"] is False

    _assign(client, env, effective_from="2025-01-01")

    monday = client.get(
        f"/api/v1/employees/{env.employee['id']}/schedule",
        headers=env.auth["headers"], params={"date": "2025-01-06"},
    ).json()
    assert monday["is_working"] is True
    assert monday["schedule_id"] == env.schedule["id"]
    assert monday["start_time"] == "09:00:00"
    assert monday["end_time"] == "17:00:00"
    assert monday["crosses_midnight"] is False
    assert monday["weekday"] == 0

    sunday = client.get(
        f"/api/v1/employees/{env.employee['id']}/schedule",
        headers=env.auth["headers"], params={"date": "2025-01-12"},  # Sunday
    ).json()
    assert sunday["is_working"] is False
    assert sunday["schedule_id"] == env.schedule["id"]
    assert sunday["start_time"] is None


def test_schedule_resolution_assignment_shift_override(client, asg_env):
    env = asg_env
    created = _assign(
        client, env, effective_from="2025-01-01", shift_id=env.shift["id"]
    )
    assert created.status_code == 201, created.text

    resolved = client.get(
        f"/api/v1/employees/{env.employee['id']}/schedule",
        headers=env.auth["headers"], params={"date": "2025-01-06"},
    ).json()
    assert resolved["shift_id"] == env.shift["id"]
    assert resolved["shift_code"] == "EARLY"
    assert resolved["start_time"] == "07:00:00"
    assert resolved["end_time"] == "15:00:00"


def test_assignment_list_pagination(client, asg_env):
    env = asg_env
    _assign(client, env, effective_from="2025-01-01", effective_to="2025-02-28")
    _assign(client, env, effective_from="2025-03-01", effective_to="2025-04-30")
    _assign(client, env, effective_from="2025-05-01")

    page = client.get(
        f"/api/v1/employees/{env.employee['id']}/work-assignments",
        headers=env.auth["headers"], params={"page": 1, "page_size": 2},
    ).json()
    assert page["page"]["total"] == 3
    assert len(page["items"]) == 2
    # ordered by effective_from descending
    assert page["items"][0]["effective_from"] == "2025-05-01"
