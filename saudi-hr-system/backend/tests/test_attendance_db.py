from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "سعود",
        "last_name_ar": "الحربي",
        "first_name_en": "Saud",
        "last_name_en": "Alharbi",
        **overrides,
    }
    response = client.post("/api/v1/employees", headers=auth["headers"], json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def att_env(client, db_session):
    company = seed_company(db_session, "Att Co")
    seed_user(db_session, "admin@att.co", company, "company_admin")
    auth = login(client, "admin@att.co")
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
            {"weekday": wd, "start_time": "09:00:00", "end_time": "17:00:00",
             "breaks": [{"start_time": "12:30:00", "end_time": "13:30:00",
                         "is_paid": False}]}
            for wd in (0, 1, 2, 3, 4)
        ] + [
            {"weekday": 5, "is_working": False},
            {"weekday": 6, "start_time": "22:00:00", "end_time": "06:00:00",
             "breaks": [{"start_time": "02:00:00", "end_time": "02:30:00",
                         "is_paid": False}]},
        ]},
    )
    assert days.status_code == 200, days.text

    assignment = client.post(
        f"/api/v1/employees/{employee['id']}/work-assignments",
        headers=auth["headers"],
        json={"schedule_id": schedule["id"], "effective_from": "2025-01-01"},
    )
    assert assignment.status_code == 201, assignment.text

    return SimpleNamespace(
        company=company, auth=auth, employee=employee, schedule=schedule,
    )


def _check_in(client, env, at, **overrides):
    payload = {"employee_id": env.employee["id"], "at": at}
    payload.update(overrides)
    return client.post(
        "/api/v1/attendance/check-in", headers=env.auth["headers"], json=payload
    )


def _check_out(client, env, at, **overrides):
    payload = {"employee_id": env.employee["id"], "at": at}
    payload.update(overrides)
    return client.post(
        "/api/v1/attendance/check-out", headers=env.auth["headers"], json=payload
    )


def _create(client, env, **payload):
    payload.setdefault("employee_id", env.employee["id"])
    return client.post(
        "/api/v1/attendance", headers=env.auth["headers"], json=payload
    )

def test_check_in_creates_open_record(client, att_env):
    env = att_env
    response = _check_in(client, env, "2025-01-06T08:45:00")
    assert response.status_code == 201, response.text
    record = response.json()
    assert record["status"] == "open"
    assert record["work_date"] == "2025-01-06"
    assert record["check_out"] is None
    assert record["check_in"].endswith("+03:00")  # schedule tz (Asia/Riyadh)
    assert record["schedule_id"] == env.schedule["id"]
    assert record["source"] == "api"
    assert record["worked_minutes"] is None
    assert record["late_minutes"] is None


def test_check_in_twice_is_rejected(client, att_env):
    env = att_env
    assert _check_in(client, env, "2025-01-06T08:45:00").status_code == 201
    second = _check_in(client, env, "2025-01-07T08:45:00")
    assert second.status_code == 409
    assert second.json()["code"] == "ATTENDANCE_ALREADY_OPEN"


def test_check_out_completes_record_with_metrics(client, att_env):
    env = att_env
    opened = _check_in(client, env, "2025-01-06T09:00:00")
    assert opened.status_code == 201

    closed = _check_out(client, env, "2025-01-06T17:00:00")
    assert closed.status_code == 200, closed.text
    record = closed.json()
    assert record["status"] == "completed"
    assert record["check_out"].endswith("+03:00")
    assert record["scheduled_minutes"] == 420  # 480 window - 60 unpaid break
    assert record["worked_minutes"] == 420
    assert record["break_minutes"] == 60
    assert record["late_minutes"] == 0
    assert record["early_leave_minutes"] == 0
    assert record["overtime_candidate_minutes"] == 0
    assert record["closed_by"] is not None

    actions = set()
    page = client.get("/api/v1/audit-logs", headers=env.auth["headers"]).json()
    for item in page["items"]:
        if item["entity"] == "attendance_record":
            actions.add(item["action"])
    assert "attendance.check_in" in actions
    assert "attendance.check_out" in actions


def test_check_out_without_open_record_is_404(client, att_env):
    env = att_env
    response = _check_out(client, env, "2025-01-06T17:00:00")
    assert response.status_code == 404
    assert response.json()["code"] == "ATTENDANCE_NOT_FOUND"


def test_check_out_before_check_in_rejected(client, att_env):
    env = att_env
    _check_in(client, env, "2025-01-06T09:00:00")
    response = _check_out(client, env, "2025-01-06T08:00:00")
    assert response.status_code == 400
    assert response.json()["code"] == "ATTENDANCE_INVALID_TIME_RANGE"


def test_create_completed_record(client, att_env):
    env = att_env
    response = _create(
        client, env, check_in="2025-01-07T08:30:00",
        check_out="2025-01-07T17:15:00", source="manual",
        notes="punched by HR",
    )
    assert response.status_code == 201, response.text
    record = response.json()
    assert record["status"] == "completed"
    assert record["late_minutes"] == 0
    assert record["early_leave_minutes"] == 0
    assert record["overtime_candidate_minutes"] == 15

    page = client.get(
        "/api/v1/audit-logs", headers=env.auth["headers"],
        params={"action": "attendance.create"},
    ).json()
    assert page["page"]["total"] == 1


def test_create_while_open_exists_rejected(client, att_env):
    env = att_env
    _check_in(client, env, "2025-01-06T08:45:00")
    response = _create(
        client, env, check_in="2025-01-07T08:45:00"
    )
    assert response.status_code == 409
    assert response.json()["code"] == "ATTENDANCE_ALREADY_OPEN"


def test_create_overlap_and_half_open_boundary(client, att_env):
    env = att_env
    assert _create(
        client, env, check_in="2025-01-06T09:00:00",
        check_out="2025-01-06T17:00:00",
    ).status_code == 201

    overlapping = _create(
        client, env, check_in="2025-01-06T16:00:00",
        check_out="2025-01-06T18:00:00",
    )
    assert overlapping.status_code == 409
    assert overlapping.json()["code"] == "ATTENDANCE_OVERLAP"

    # half-open [check_in, check_out): touching the end is allowed
    adjacent = _create(
        client, env, check_in="2025-01-06T17:00:00",
        check_out="2025-01-06T18:00:00",
    )
    assert adjacent.status_code == 201, adjacent.text


def test_create_completed_without_checkout_rejected(client, att_env):
    env = att_env
    response = _create(
        client, env, check_in="2025-01-06T09:00:00", status="completed"
    )
    assert response.status_code == 400
    assert response.json()["code"] == "ATTENDANCE_MISSING_CHECKOUT"


def test_create_invalid_range_rejected(client, att_env):
    env = att_env
    response = _create(
        client, env, check_in="2025-01-06T17:00:00",
        check_out="2025-01-06T09:00:00",
    )
    assert response.status_code == 400
    assert response.json()["code"] == "ATTENDANCE_INVALID_TIME_RANGE"


def test_missing_checkout_rows_are_inert(client, att_env):
    env = att_env
    flagged = _create(
        client, env, check_in="2025-01-06T08:00:00",
        status="missing_checkout", source="device",
    )
    assert flagged.status_code == 201, flagged.text
    assert flagged.json()["status"] == "missing_checkout"
    assert flagged.json()["worked_minutes"] is None

    # a completed record covering the same hours is still accepted
    overlapping = _create(
        client, env, check_in="2025-01-06T09:00:00",
        check_out="2025-01-06T17:00:00",
    )
    assert overlapping.status_code == 201, overlapping.text


def test_list_filters_and_pagination(client, att_env):
    env = att_env
    _create(client, env, check_in="2025-01-06T09:00:00",
            check_out="2025-01-06T17:00:00")
    _create(client, env, check_in="2025-01-07T09:00:00",
            check_out="2025-01-07T17:00:00")
    _create(client, env, check_in="2025-01-08T08:00:00",
            status="missing_checkout")

    all_rows = client.get(
        "/api/v1/attendance",
        headers=env.auth["headers"],
        params={"company_id": env.company.id},
    ).json()
    assert all_rows["page"]["total"] == 3

    by_status = client.get(
        "/api/v1/attendance",
        headers=env.auth["headers"],
        params={"company_id": env.company.id, "status": "missing_checkout"},
    ).json()
    assert by_status["page"]["total"] == 1

    ranged = client.get(
        "/api/v1/attendance",
        headers=env.auth["headers"],
        params={"company_id": env.company.id, "date_from": "2025-01-07",
                "date_to": "2025-01-07"},
    ).json()
    assert ranged["page"]["total"] == 1
    assert ranged["items"][0]["work_date"] == "2025-01-07"

    by_employee = client.get(
        "/api/v1/attendance",
        headers=env.auth["headers"],
        params={"company_id": env.company.id,
                "employee_id": env.employee["id"]},
    ).json()
    assert by_employee["page"]["total"] == 3

    by_schedule = client.get(
        "/api/v1/attendance",
        headers=env.auth["headers"],
        params={"company_id": env.company.id,
                "schedule_id": env.schedule["id"]},
    ).json()
    assert by_schedule["page"]["total"] == 3

    paged = client.get(
        "/api/v1/attendance",
        headers=env.auth["headers"],
        params={"company_id": env.company.id, "page": 2, "page_size": 2},
    ).json()
    assert paged["page"]["total"] == 3
    assert len(paged["items"]) == 1


def test_correction_requires_reason_and_audits(client, att_env):
    env = att_env
    created = _create(
        client, env, check_in="2025-01-06T09:00:00",
        check_out="2025-01-06T17:00:00",
    )
    assert created.status_code == 201
    record_id = created.json()["id"]

    reasonless = client.patch(
        f"/api/v1/attendance/{record_id}",
        headers=env.auth["headers"],
        json={"check_in": "2025-01-06T09:30:00"},
    )
    assert reasonless.status_code == 400
    assert reasonless.json()["code"] == "CORRECTION_REASON_REQUIRED"

    corrected = client.patch(
        f"/api/v1/attendance/{record_id}",
        headers=env.auth["headers"],
        json={"check_in": "2025-01-06T09:30:00",
              "reason": "device clock drift"},
    )
    assert corrected.status_code == 200, corrected.text
    body = corrected.json()
    assert body["correction_reason"] == "device clock drift"
    assert body["corrected_by"] is not None
    assert body["corrected_at"] is not None
    assert body["late_minutes"] == 30

    page = client.get(
        "/api/v1/audit-logs", headers=env.auth["headers"],
        params={"action": "attendance.correct"},
    ).json()
    assert page["page"]["total"] == 1
    entry = page["items"][0]
    old_value = json.loads(entry["old_value"])
    new_value = json.loads(entry["new_value"])
    assert old_value["check_in"] != new_value["check_in"]
    assert new_value["reason"] == "device clock drift"


def test_open_record_edit_needs_no_reason(client, att_env):
    env = att_env
    opened = _check_in(client, env, "2025-01-06T08:45:00")
    record_id = opened.json()["id"]

    updated = client.patch(
        f"/api/v1/attendance/{record_id}",
        headers=env.auth["headers"],
        json={"notes": "visitor badge"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["notes"] == "visitor badge"
    assert updated.json()["status"] == "open"

    page = client.get(
        "/api/v1/audit-logs", headers=env.auth["headers"],
        params={"action": "attendance.update"},
    ).json()
    assert page["page"]["total"] == 1


def test_delete_open_record(client, att_env):
    env = att_env
    opened = _check_in(client, env, "2025-01-06T08:45:00")
    record_id = opened.json()["id"]

    removed = client.delete(
        f"/api/v1/attendance/{record_id}", headers=env.auth["headers"]
    )
    assert removed.status_code == 204
    assert client.get(
        f"/api/v1/attendance/{record_id}", headers=env.auth["headers"]
    ).status_code == 404


def test_delete_closed_record_requires_reason(client, att_env):
    env = att_env
    created = _create(
        client, env, check_in="2025-01-06T09:00:00",
        check_out="2025-01-06T17:00:00",
    )
    record_id = created.json()["id"]

    rejected = client.delete(
        f"/api/v1/attendance/{record_id}", headers=env.auth["headers"]
    )
    assert rejected.status_code == 400
    assert rejected.json()["code"] == "CORRECTION_REASON_REQUIRED"

    removed = client.delete(
        f"/api/v1/attendance/{record_id}", headers=env.auth["headers"],
        params={"reason": "duplicate punch"},
    )
    assert removed.status_code == 204

    page = client.get(
        "/api/v1/audit-logs", headers=env.auth["headers"],
        params={"action": "attendance.delete"},
    ).json()
    assert page["page"]["total"] == 1
    assert json.loads(page["items"][0]["new_value"])["reason"] == (
        "duplicate punch"
    )


def test_overnight_attendance_span(client, att_env):
    env = att_env
    # Sunday 2025-01-12 22:00 -> Monday 06:00 window (weekday 6 rule)
    created = _create(
        client, env, check_in="2025-01-12T21:50:00",
        check_out="2025-01-13T06:20:00",
    )
    assert created.status_code == 201, created.text
    record = created.json()
    assert record["work_date"] == "2025-01-12"
    assert record["scheduled_minutes"] == 450  # 480 - 30 unpaid
    assert record["worked_minutes"] == 480  # 510 span - 30 unpaid
    assert record["late_minutes"] == 0
    assert record["early_leave_minutes"] == 0
    assert record["overtime_candidate_minutes"] == 20


def test_morning_punch_after_overnight_record_is_allowed(client, att_env):
    env = att_env
    assert _create(
        client, env, check_in="2025-01-12T22:00:00",
        check_out="2025-01-13T06:00:00",
    ).status_code == 201
    # the Monday window opens after the overnight record closed
    morning = _create(
        client, env, check_in="2025-01-13T09:00:00",
        check_out="2025-01-13T17:00:00",
    )
    assert morning.status_code == 201, morning.text


def test_naive_timestamps_use_schedule_timezone(client, att_env, db_session):
    env = att_env
    # a fresh employee (no assignment yet) on a schedule in Dubai (+04:00)
    employee = _create_employee(client, env.auth, env.company.id)
    dubai = client.post(
        "/api/v1/work-schedules", headers=env.auth["headers"],
        json={"company_id": env.company.id, "code": "DXB",
              "name_ar": "دبي", "name_en": "Dubai", "timezone": "Asia/Dubai",
              "effective_from": "2024-01-01"},
    )
    assert dubai.status_code == 201, dubai.text
    client.put(
        f"/api/v1/work-schedules/{dubai.json()['id']}/days",
        headers=env.auth["headers"],
        json={"days": [
            {"weekday": wd, "start_time": "09:00:00", "end_time": "17:00:00"}
            for wd in (0, 1, 2, 3, 4, 5, 6)
        ]},
    )
    assigned = client.post(
        f"/api/v1/employees/{employee['id']}/work-assignments",
        headers=env.auth["headers"],
        json={"schedule_id": dubai.json()["id"], "effective_from": "2024-01-01"},
    )
    assert assigned.status_code == 201, assigned.text

    response = _create(
        client, env, employee_id=employee["id"],
        check_in="2024-06-03T09:00:00",  # Monday
        check_out="2024-06-03T17:00:00",
    )
    assert response.status_code == 201, response.text
    record = response.json()
    # naive wall time is read in the SCHEDULE timezone (+04:00)
    assert record["check_in"] == "2024-06-03T09:00:00+04:00"
    assert record["check_out"] == "2024-06-03T17:00:00+04:00"
    assert record["schedule_id"] == dubai.json()["id"]
    assert record["worked_minutes"] == 480
    assert record["late_minutes"] == 0


def test_attendance_cross_company_is_404(client, att_env, db_session):
    env = att_env
    created = _create(
        client, env, check_in="2025-01-06T09:00:00",
        check_out="2025-01-06T17:00:00",
    )
    record_id = created.json()["id"]

    other = seed_company(db_session, "Att Other Co")
    seed_user(db_session, "admin@att-other.co", other, "company_admin")
    outsider = login(client, "admin@att-other.co")

    assert client.get(
        f"/api/v1/attendance/{record_id}", headers=outsider["headers"]
    ).status_code == 404
    assert client.patch(
        f"/api/v1/attendance/{record_id}", headers=outsider["headers"],
        json={"notes": "hijack", "reason": "nope"},
    ).status_code == 404
    assert client.delete(
        f"/api/v1/attendance/{record_id}", headers=outsider["headers"],
        params={"reason": "nope"},
    ).status_code == 404

    listing = client.get(
        "/api/v1/attendance",
        headers=outsider["headers"],
        params={"company_id": other.id},
    ).json()
    assert listing["page"]["total"] == 0
