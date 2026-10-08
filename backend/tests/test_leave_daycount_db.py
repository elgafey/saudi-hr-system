from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "Omar",
        "last_name_ar": "Alghamdi",
        "first_name_en": "Omar",
        "last_name_en": "Alghamdi",
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


@pytest.fixture()
def daycount_env(client, db_session):
    company = seed_company(db_session, "LV Days")
    other = seed_company(db_session, "LV Days Other")
    seed_user(db_session, "admin@days.co", company, "company_admin")
    seed_user(db_session, "auditor@days.co", company, "auditor")
    seed_user(db_session, "roleless@days.co", company)
    seed_user(db_session, "admin@days-other.co", other, "company_admin")

    admin = login(client, "admin@days.co")
    assigned = _create_employee(client, admin, company.id)
    unassigned = _create_employee(
        client,
        admin,
        company.id,
        first_name_en="Rana",
        last_name_en="Alsubaie",
        first_name_ar="Rana",
        last_name_ar="Alsubaie",
    )

    schedule = client.post(
        "/api/v1/work-schedules",
        headers=admin["headers"],
        json={
            "company_id": company.id,
            "code": "STD",
            "name_ar": "قياسي",
            "name_en": "Standard",
            "effective_from": "2025-01-01",
        },
    )
    assert schedule.status_code == 201, schedule.text
    days = client.put(
        f"/api/v1/work-schedules/{schedule.json()['id']}/days",
        headers=admin["headers"],
        json={
            "days": [
                {
                    "weekday": weekday,
                    "start_time": "09:00:00",
                    "end_time": "17:00:00",
                }
                for weekday in range(5)
            ]
        },
    )
    assert days.status_code == 200, days.text

    assignment = client.post(
        f"/api/v1/employees/{assigned['id']}/work-assignments",
        headers=admin["headers"],
        json={
            "schedule_id": schedule.json()["id"],
            "effective_from": "2025-01-01",
        },
    )
    assert assignment.status_code == 201, assignment.text

    annual = _create_type(client, admin, company.id)
    calendar = _create_type(
        client,
        admin,
        company.id,
        code="CALENDAR",
        name_ar="تقويمية",
        name_en="Calendar days",
        day_counting_mode="calendar_days",
    )
    return SimpleNamespace(
        company=company,
        other=other,
        admin=admin,
        auditor=login(client, "auditor@days.co"),
        roleless=login(client, "roleless@days.co"),
        other_admin=login(client, "admin@days-other.co"),
        assigned=assigned,
        unassigned=unassigned,
        schedule=schedule.json(),
        annual=annual,
        calendar=calendar,
    )


def _preview(client, auth, employee_id, leave_type_id, **overrides):
    payload = {
        "employee_id": employee_id,
        "leave_type_id": leave_type_id,
        "start_date": "2025-01-06",
        "end_date": "2025-01-12",
    }
    payload.update(overrides)
    response = client.post(
        "/api/v1/leave-requests/preview", headers=auth["headers"], json=payload
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_working_days_skips_weekends_and_holidays(client, daycount_env):
    env = daycount_env
    auth = env.admin

    holiday = client.post(
        "/api/v1/company-holidays",
        headers=auth["headers"],
        json={
            "company_id": env.company.id,
            "date": "2025-01-08",
            "name_ar": "يوم وطني",
            "name_en": "National Day",
        },
    )
    assert holiday.status_code == 201, holiday.text

    body = _preview(
        client, auth, env.assigned["id"], env.annual["id"]
    )
    assert body["days"] == "4.00"
    assert body["day_counting_mode"] == "working_days"
    reasons = [entry["reason"] for entry in body["count_details"]["entries"]]
    assert reasons == [
        "counted",
        "counted",
        "holiday",
        "counted",
        "counted",
        "rest_day",
        "rest_day",
    ]

    # Deactivating the holiday puts the date back into the count.
    deactivated = client.patch(
        f"/api/v1/company-holidays/{holiday.json()['id']}",
        headers=auth["headers"],
        json={"status": "inactive"},
    )
    assert deactivated.status_code == 200, deactivated.text
    after = _preview(client, auth, env.assigned["id"], env.annual["id"])
    assert after["days"] == "5.00"

    # calendar_days mode ignores weekends and holidays entirely.
    calendar = _preview(client, auth, env.assigned["id"], env.calendar["id"])
    assert calendar["days"] == "7.00"
    assert calendar["day_counting_mode"] == "calendar_days"


def test_employee_without_schedule_counts_every_date(client, daycount_env):
    env = daycount_env
    auth = env.admin

    body = _preview(client, auth, env.unassigned["id"], env.annual["id"])
    # No schedule means no rest pattern yet: all dates count.
    assert body["days"] == "7.00"
    reasons = [entry["reason"] for entry in body["count_details"]["entries"]]
    assert reasons == ["counted"] * 7


def test_all_non_working_ranges_are_rejected(client, daycount_env):
    env = daycount_env
    auth = env.admin

    weekend = client.post(
        "/api/v1/leave-requests/preview",
        headers=auth["headers"],
        json={
            "employee_id": env.assigned["id"],
            "leave_type_id": env.annual["id"],
            "start_date": "2025-01-11",
            "end_date": "2025-01-12",
        },
    )
    assert weekend.status_code == 400, weekend.text
    assert weekend.json()["code"] == "LEAVE_ONLY_NON_WORKING_DAYS"

    # The same weekend is fine in calendar mode.
    calendar = _preview(
        client,
        auth,
        env.assigned["id"],
        env.calendar["id"],
        start_date="2025-01-11",
        end_date="2025-01-12",
    )
    assert calendar["days"] == "2.00"

    client.post(
        "/api/v1/company-holidays",
        headers=auth["headers"],
        json={
            "company_id": env.company.id,
            "date": "2025-01-09",
            "name_ar": "عطلة",
            "name_en": "Holiday",
        },
    )
    holiday_only = client.post(
        "/api/v1/leave-requests/preview",
        headers=auth["headers"],
        json={
            "employee_id": env.assigned["id"],
            "leave_type_id": env.annual["id"],
            "start_date": "2025-01-09",
            "end_date": "2025-01-09",
        },
    )
    assert holiday_only.status_code == 400, holiday_only.text
    assert holiday_only.json()["code"] == "LEAVE_ONLY_NON_WORKING_DAYS"


def test_partial_day_fraction_and_conflicts(client, daycount_env):
    env = daycount_env
    auth = env.admin

    half = _preview(
        client,
        auth,
        env.assigned["id"],
        env.annual["id"],
        start_date="2025-01-06",
        end_date="2025-01-06",
        start_time="09:00:00",
        end_time="13:00:00",
    )
    assert half["days"] == "0.50"
    entry = half["count_details"]["entries"][0]
    assert entry["fraction"] == "0.50"
    assert entry["reason"] == "counted"

    full = _preview(
        client,
        auth,
        env.assigned["id"],
        env.annual["id"],
        start_date="2025-01-06",
        end_date="2025-01-06",
        start_time="09:00:00",
        end_time="17:00:00",
    )
    assert full["days"] == "1.00"

    created = client.post(
        "/api/v1/leave-requests",
        headers=auth["headers"],
        json={
            "employee_id": env.assigned["id"],
            "leave_type_id": env.annual["id"],
            "start_date": "2025-01-06",
            "end_date": "2025-01-06",
            "start_time": "09:00:00",
            "end_time": "13:00:00",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["days"] == "0.50"

    outside = client.post(
        "/api/v1/leave-requests/preview",
        headers=auth["headers"],
        json={
            "employee_id": env.assigned["id"],
            "leave_type_id": env.annual["id"],
            "start_date": "2025-01-06",
            "end_date": "2025-01-06",
            "start_time": "07:00:00",
            "end_time": "08:00:00",
        },
    )
    assert outside.status_code == 400, outside.text
    assert outside.json()["code"] == "LEAVE_REQUEST_INVALID_TIMES"

    rest_day = client.post(
        "/api/v1/leave-requests/preview",
        headers=auth["headers"],
        json={
            "employee_id": env.assigned["id"],
            "leave_type_id": env.annual["id"],
            "start_date": "2025-01-11",
            "end_date": "2025-01-11",
            "start_time": "09:00:00",
            "end_time": "13:00:00",
        },
    )
    assert rest_day.status_code == 400, rest_day.text
    assert rest_day.json()["code"] == "LEAVE_ONLY_NON_WORKING_DAYS"

    client.post(
        "/api/v1/company-holidays",
        headers=auth["headers"],
        json={
            "company_id": env.company.id,
            "date": "2025-01-07",
            "name_ar": "عطلة رسمية",
            "name_en": "Official holiday",
        },
    )
    holiday_partial = client.post(
        "/api/v1/leave-requests/preview",
        headers=auth["headers"],
        json={
            "employee_id": env.assigned["id"],
            "leave_type_id": env.annual["id"],
            "start_date": "2025-01-07",
            "end_date": "2025-01-07",
            "start_time": "09:00:00",
            "end_time": "13:00:00",
        },
    )
    assert holiday_partial.status_code == 400, holiday_partial.text
    assert holiday_partial.json()["code"] == "LEAVE_ONLY_NON_WORKING_DAYS"

    # Partial-day leave requires a resolvable schedule window.
    no_schedule = client.post(
        "/api/v1/leave-requests/preview",
        headers=auth["headers"],
        json={
            "employee_id": env.unassigned["id"],
            "leave_type_id": env.annual["id"],
            "start_date": "2025-01-06",
            "end_date": "2025-01-06",
            "start_time": "09:00:00",
            "end_time": "13:00:00",
        },
    )
    assert no_schedule.status_code == 400, no_schedule.text
    assert no_schedule.json()["code"] == "LEAVE_NO_SCHEDULE"


def test_range_and_span_guards(client, daycount_env):
    env = daycount_env
    auth = env.admin

    inverted = client.post(
        "/api/v1/leave-requests/preview",
        headers=auth["headers"],
        json={
            "employee_id": env.assigned["id"],
            "leave_type_id": env.annual["id"],
            "start_date": "2025-01-12",
            "end_date": "2025-01-06",
        },
    )
    assert inverted.status_code == 400, inverted.text
    assert inverted.json()["code"] == "LEAVE_REQUEST_INVALID_RANGE"

    span = client.post(
        "/api/v1/leave-requests/preview",
        headers=auth["headers"],
        json={
            "employee_id": env.assigned["id"],
            "leave_type_id": env.annual["id"],
            "start_date": "2024-01-01",
            "end_date": "2025-06-01",
        },
    )
    assert span.status_code == 400, span.text
    assert span.json()["code"] == "LEAVE_REQUEST_INVALID_RANGE"

    half_times = client.post(
        "/api/v1/leave-requests/preview",
        headers=auth["headers"],
        json={
            "employee_id": env.assigned["id"],
            "leave_type_id": env.annual["id"],
            "start_date": "2025-01-06",
            "end_date": "2025-01-06",
            "end_time": "13:00:00",
        },
    )
    assert half_times.status_code == 400, half_times.text
    assert half_times.json()["code"] == "LEAVE_REQUEST_INVALID_TIMES"


def test_holiday_crud_and_permissions(client, daycount_env):
    env = daycount_env
    auth = env.admin

    created = client.post(
        "/api/v1/company-holidays",
        headers=auth["headers"],
        json={
            "company_id": env.company.id,
            "date": "2025-09-23",
            "name_ar": "اليوم الوطني",
            "name_en": "National Day",
            "notes": "celebrations",
        },
    )
    assert created.status_code == 201, created.text
    holiday_id = created.json()["id"]
    assert created.json()["status"] == "active"

    duplicate = client.post(
        "/api/v1/company-holidays",
        headers=auth["headers"],
        json={
            "company_id": env.company.id,
            "date": "2025-09-23",
            "name_ar": "مكرر",
            "name_en": "Duplicate",
        },
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["code"] == "HOLIDAY_EXISTS"

    read = client.get(
        f"/api/v1/company-holidays/{holiday_id}", headers=auth["headers"]
    )
    assert read.status_code == 200, read.text
    assert read.json()["notes"] == "celebrations"

    page = client.get(
        "/api/v1/company-holidays",
        headers=auth["headers"],
        params={"company_id": env.company.id, "year": 2025, "status": "active"},
    ).json()
    assert page["page"]["total"] == 1

    updated = client.patch(
        f"/api/v1/company-holidays/{holiday_id}",
        headers=auth["headers"],
        json={"name_en": "National Day (renamed)"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name_en"] == "National Day (renamed)"

    # Role matrix.
    assert (
        client.get(
            "/api/v1/company-holidays", headers=env.roleless["headers"]
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/api/v1/company-holidays", headers=env.auditor["headers"]
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/company-holidays",
            headers=env.auditor["headers"],
            json={
                "company_id": env.company.id,
                "date": "2025-12-25",
                "name_ar": "x",
                "name_en": "x",
            },
        ).status_code
        == 403
    )

    # Cross company: 404 per row, 403 for scoped listing.
    other_headers = env.other_admin["headers"]
    assert (
        client.get(
            f"/api/v1/company-holidays/{holiday_id}", headers=other_headers
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/company-holidays/{holiday_id}", headers=other_headers
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/api/v1/company-holidays",
            headers=other_headers,
            params={"company_id": env.company.id},
        ).status_code
        == 403
    )

    removed = client.delete(
        f"/api/v1/company-holidays/{holiday_id}", headers=auth["headers"]
    )
    assert removed.status_code == 204, removed.text
    assert (
        client.get(
            f"/api/v1/company-holidays/{holiday_id}", headers=auth["headers"]
        ).status_code
        == 404
    )
