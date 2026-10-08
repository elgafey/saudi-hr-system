from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "ريما",
        "last_name_ar": "السبيعي",
        "first_name_en": "Reema",
        "last_name_en": "Alsubaie",
        **overrides,
    }
    response = client.post("/api/v1/employees", headers=auth["headers"], json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _schedule(client, env, code, *, timezone="Asia/Riyadh", **overrides):
    payload = {
        "company_id": env.company.id, "code": code,
        "name_ar": f"جدول {code}", "name_en": f"Schedule {code}",
        "timezone": timezone, "effective_from": "2025-01-01",
    }
    payload.update(overrides)
    response = client.post(
        "/api/v1/work-schedules", headers=env.auth["headers"], json=payload
    )
    assert response.status_code == 201, response.text
    return response.json()


def _put_days(client, env, schedule_id, days):
    response = client.put(
        f"/api/v1/work-schedules/{schedule_id}/days",
        headers=env.auth["headers"], json={"days": days},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _assign(client, env, employee_id, schedule_id, **overrides):
    payload = {"schedule_id": schedule_id, "effective_from": "2025-01-01"}
    payload.update(overrides)
    response = client.post(
        f"/api/v1/employees/{employee_id}/work-assignments",
        headers=env.auth["headers"], json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def calc_env(client, db_session):
    company = seed_company(db_session, "Calc Co")
    seed_user(db_session, "admin@calc.co", company, "company_admin")
    auth = login(client, "admin@calc.co")
    env = SimpleNamespace(company=company, auth=auth)

    employee = _create_employee(client, auth, company.id)
    schedule = _schedule(client, env, "STD")
    _put_days(client, env, schedule["id"], [
        {"weekday": wd, "start_time": "09:00:00", "end_time": "17:00:00",
         "breaks": [{"start_time": "12:30:00", "end_time": "13:30:00",
                     "is_paid": False}]}
        for wd in (0, 1, 2, 3, 4)
    ] + [
        {"weekday": 5, "is_working": False},
        {"weekday": 6, "is_working": False},
    ])
    _assign(client, env, employee["id"], schedule["id"])

    # second employee: schedule with a PAID break
    paid_employee = _create_employee(client, auth, company.id, first_name_en="Paid")
    paid_schedule = _schedule(client, env, "PAID")
    _put_days(client, env, paid_schedule["id"], [
        {"weekday": wd, "start_time": "09:00:00", "end_time": "17:00:00",
         "breaks": [{"start_time": "12:30:00", "end_time": "13:30:00",
                     "is_paid": True}]}
        for wd in (0, 1, 2, 3, 4)
    ])
    _assign(client, env, paid_employee["id"], paid_schedule["id"])

    # third employee: no work assignment at all
    bare_employee = _create_employee(client, auth, company.id, first_name_en="Bare")

    return SimpleNamespace(
        company=company, auth=auth, employee=employee,
        paid_employee=paid_employee, bare_employee=bare_employee,
        schedule=schedule, paid_schedule=paid_schedule,
    )


def _record(client, env, employee_id, check_in, check_out):
    response = client.post(
        "/api/v1/attendance", headers=env.auth["headers"],
        json={"employee_id": employee_id, "check_in": check_in,
              "check_out": check_out},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_on_time_day_has_no_penalties(client, calc_env):
    env = calc_env
    record = _record(
        client, env, env.employee["id"],
        "2025-01-06T09:00:00", "2025-01-06T17:00:00",
    )
    assert record["late_minutes"] == 0
    assert record["early_leave_minutes"] == 0
    assert record["overtime_candidate_minutes"] == 0
    assert record["scheduled_minutes"] == 420
    assert record["worked_minutes"] == 420
    assert record["break_minutes"] == 60


def test_late_arrival_and_early_leave(client, calc_env):
    env = calc_env
    record = _record(
        client, env, env.employee["id"],
        "2025-01-06T09:30:00", "2025-01-06T16:30:00",
    )
    assert record["late_minutes"] == 30
    assert record["early_leave_minutes"] == 30
    assert record["overtime_candidate_minutes"] == 0
    # span 09:30-16:30 = 420 min, minus 60 min unpaid break = 360
    assert record["worked_minutes"] == 360


def test_arriving_early_is_not_negative_late(client, calc_env):
    env = calc_env
    record = _record(
        client, env, env.employee["id"],
        "2025-01-06T08:15:00", "2025-01-06T17:45:00",
    )
    assert record["late_minutes"] == 0
    assert record["early_leave_minutes"] == 0
    assert record["overtime_candidate_minutes"] == 45


def test_minutes_are_whole_and_floored(client, calc_env):
    env = calc_env
    record = _record(
        client, env, env.employee["id"],
        "2025-01-06T09:05:59", "2025-01-06T17:00:30",
    )
    assert record["late_minutes"] == 5  # 09:05:59 floors to 5
    assert record["worked_minutes"] == 414  # 474.5 span floored, - 60 unpaid


def test_paid_break_is_not_deducted(client, calc_env):
    env = calc_env
    record = _record(
        client, env, env.paid_employee["id"],
        "2025-01-06T09:00:00", "2025-01-06T17:00:00",
    )
    assert record["break_minutes"] == 0
    assert record["scheduled_minutes"] == 480
    assert record["worked_minutes"] == 480


def test_rest_day_still_records_time_without_metrics(client, calc_env):
    env = calc_env
    record = _record(
        client, env, env.employee["id"],
        "2025-01-11T10:00:00", "2025-01-11T14:00:00",  # Saturday (rest)
    )
    assert record["status"] == "completed"
    assert record["scheduled_minutes"] == 0
    assert record["worked_minutes"] == 240
    assert record["break_minutes"] == 0
    assert record["late_minutes"] == 0
    assert record["early_leave_minutes"] == 0
    assert record["overtime_candidate_minutes"] == 0


def test_employee_without_assignment_falls_back_to_raw_span(client, calc_env):
    env = calc_env
    record = _record(
        client, env, env.bare_employee["id"],
        "2025-01-06T10:00:00", "2025-01-06T15:30:00",
    )
    assert record["schedule_id"] is None
    assert record["shift_id"] is None
    assert record["scheduled_minutes"] == 0
    assert record["worked_minutes"] == 330
    assert record["late_minutes"] == 0
    assert record["early_leave_minutes"] == 0
    assert record["overtime_candidate_minutes"] == 0


def test_shift_override_changes_the_window(client, calc_env):
    env = calc_env
    shift = client.post(
        "/api/v1/shifts", headers=env.auth["headers"],
        json={"company_id": env.company.id, "code": "EARLY",
              "name_ar": "مبكرة", "name_en": "Early",
              "start_time": "07:00:00", "end_time": "15:00:00",
              "breaks": [{"start_time": "11:00:00", "end_time": "11:30:00",
                          "is_paid": False}]},
    )
    assert shift.status_code == 201, shift.text

    employee = _create_employee(client, env.auth, env.company.id,
                                first_name_en="Shifted")
    _assign(client, env, employee["id"], env.schedule["id"],
            shift_id=shift.json()["id"])

    # arrives late for the 07:00 shift but leaves before the 15:00 end
    # schedule-day breaks (60 min) override shift breaks (30 min)
    record = _record(
        client, env, employee["id"],
        "2025-01-06T07:45:00", "2025-01-06T14:30:00",
    )
    assert record["shift_id"] == shift.json()["id"]
    # window 07:00-15:00 = 480 min, minus 60 min schedule-day break = 420
    assert record["scheduled_minutes"] == 420
    assert record["late_minutes"] == 45
    assert record["early_leave_minutes"] == 30
    # span 07:45-14:30 = 405 min, minus 60 min break = 345
    assert record["worked_minutes"] == 345


def test_open_record_keeps_metrics_null(client, calc_env):
    env = calc_env
    response = client.post(
        "/api/v1/attendance/check-in", headers=env.auth["headers"],
        json={"employee_id": env.employee["id"], "at": "2025-01-06T09:00:00"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "open"
    assert body["scheduled_minutes"] is None
    assert body["worked_minutes"] is None
    assert body["late_minutes"] is None
    assert body["overtime_candidate_minutes"] is None
