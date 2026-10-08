from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import text

from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "لمى",
        "last_name_ar": "المطيري",
        "first_name_en": "Lama",
        "last_name_en": "Almutairi",
        **overrides,
    }
    response = client.post("/api/v1/employees", headers=auth["headers"], json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def matrix_env(client, db_session):
    company_a = seed_company(db_session, "P4 A")
    company_b = seed_company(db_session, "P4 B")
    seed_user(db_session, "admin@p4-a.co", company_a, "company_admin")
    seed_user(db_session, "auditor@p4-a.co", company_a, "auditor")
    seed_user(db_session, "manager@p4-a.co", company_a, "hr_manager")
    seed_user(db_session, "officer@p4-a.co", company_a, "hr_officer")
    seed_user(db_session, "noperm@p4-a.co", company_a)
    seed_user(db_session, "admin@p4-b.co", company_b, "company_admin")

    admin_a = login(client, "admin@p4-a.co")
    admin_b = login(client, "admin@p4-b.co")
    employee_a = _create_employee(client, admin_a, company_a.id)
    employee_b = _create_employee(client, admin_b, company_b.id)

    schedule_a = client.post(
        "/api/v1/work-schedules", headers=admin_a["headers"],
        json={"company_id": company_a.id, "code": "A1",
              "name_ar": "جدول أ", "name_en": "A1",
              "effective_from": "2025-01-01"},
    )
    assert schedule_a.status_code == 201, schedule_a.text
    schedule_b = client.post(
        "/api/v1/work-schedules", headers=admin_b["headers"],
        json={"company_id": company_b.id, "code": "B1",
              "name_ar": "جدول ب", "name_en": "B1",
              "effective_from": "2025-01-01"},
    )
    assert schedule_b.status_code == 201, schedule_b.text

    attendance = client.post(
        "/api/v1/attendance", headers=admin_a["headers"],
        json={"employee_id": employee_a["id"],
              "check_in": "2025-01-06T09:00:00",
              "check_out": "2025-01-06T17:00:00"},
    )
    assert attendance.status_code == 201, attendance.text

    overtime = client.post(
        "/api/v1/overtime", headers=admin_a["headers"],
        json={"employee_id": employee_a["id"], "work_date": "2025-01-06",
              "requested_minutes": 60},
    )
    assert overtime.status_code == 201, overtime.text

    return SimpleNamespace(
        company_a=company_a, company_b=company_b,
        employee_a=employee_a, employee_b=employee_b,
        schedule_a=schedule_a.json(), schedule_b=schedule_b.json(),
        attendance=attendance.json(), overtime=overtime.json(),
        admin_a=admin_a, admin_b=admin_b,
    )


def test_roleless_user_denied_every_phase4_route(client, matrix_env):
    env = matrix_env
    auth = login(client, "noperm@p4-a.co")
    headers = {**auth["headers"], "X-Company-Id": str(env.company_a.id)}

    assert client.get(
        "/api/v1/work-schedules", headers=headers
    ).status_code == 403
    assert client.get("/api/v1/shifts", headers=headers).status_code == 403
    assert client.get(
        "/api/v1/attendance", headers=headers
    ).status_code == 403
    assert client.get("/api/v1/overtime", headers=headers).status_code == 403
    assert client.get(
        f"/api/v1/employees/{env.employee_a['id']}/work-assignments",
        headers=headers,
    ).status_code == 403
    assert client.get(
        f"/api/v1/employees/{env.employee_a['id']}/schedule",
        headers=headers, params={"date": "2025-01-06"},
    ).status_code == 403

    assert client.post(
        "/api/v1/work-schedules", headers=headers,
        json={"company_id": env.company_a.id, "code": "X",
              "name_ar": "x", "name_en": "x",
              "effective_from": "2025-01-01"},
    ).status_code == 403
    assert client.post(
        "/api/v1/attendance/check-in", headers=headers,
        json={"employee_id": env.employee_a["id"],
              "at": "2025-01-06T08:00:00"},
    ).status_code == 403
    assert client.post(
        "/api/v1/overtime", headers=headers,
        json={"employee_id": env.employee_a["id"],
              "work_date": "2025-01-06", "requested_minutes": 30},
    ).status_code == 403


def test_auditor_reads_phase4_but_cannot_write(client, matrix_env):
    env = matrix_env
    auth = login(client, "auditor@p4-a.co")
    headers = {**auth["headers"], "X-Company-Id": str(env.company_a.id)}

    assert client.get(
        "/api/v1/work-schedules", headers=headers
    ).status_code == 200
    assert client.get("/api/v1/shifts", headers=headers).status_code == 200
    assert client.get("/api/v1/attendance", headers=headers).status_code == 200
    assert client.get("/api/v1/overtime", headers=headers).status_code == 200

    assert client.post(
        "/api/v1/shifts", headers=headers,
        json={"company_id": env.company_a.id, "code": "AUD",
              "name_ar": "x", "name_en": "x",
              "start_time": "09:00:00", "end_time": "17:00:00"},
    ).status_code == 403
    assert client.patch(
        f"/api/v1/work-schedules/{env.schedule_a['id']}", headers=headers,
        json={"name_en": "changed"},
    ).status_code == 403
    assert client.delete(
        f"/api/v1/work-schedules/{env.schedule_a['id']}", headers=headers
    ).status_code == 403
    assert client.post(
        "/api/v1/overtime", headers=headers,
        json={"employee_id": env.employee_a["id"],
              "work_date": "2025-01-06", "requested_minutes": 30},
    ).status_code == 403
    assert client.patch(
        f"/api/v1/attendance/{env.attendance['id']}", headers=headers,
        json={"notes": "x", "reason": "x"},
    ).status_code == 403


def test_officer_captures_attendance_but_cannot_approve_or_correct(
    client, matrix_env
):
    env = matrix_env
    auth = login(client, "officer@p4-a.co")

    check_in = client.post(
        "/api/v1/attendance/check-in", headers=auth["headers"],
        json={"employee_id": env.employee_a["id"],
              "at": "2025-01-07T08:45:00"},
    )
    assert check_in.status_code == 201, check_in.text

    # closed attendance cannot be corrected without attendance.correct
    correction = client.patch(
        f"/api/v1/attendance/{env.attendance['id']}", headers=auth["headers"],
        json={"check_in": "2025-01-06T09:15:00", "reason": "fix"},
    )
    assert correction.status_code == 403

    # officer may create + submit overtime but never approve it
    created = client.post(
        "/api/v1/overtime", headers=auth["headers"],
        json={"employee_id": env.employee_a["id"],
              "work_date": "2025-01-08", "requested_minutes": 45},
    )
    assert created.status_code == 201, created.text
    row_id = created.json()["id"]
    assert client.post(
        f"/api/v1/overtime/{row_id}/submit", headers=auth["headers"],
        json={},
    ).status_code == 200
    denied = client.post(
        f"/api/v1/overtime/{row_id}/approve", headers=auth["headers"],
        json={},
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "forbidden"


def test_manager_approves_but_cannot_delete(client, matrix_env):
    env = matrix_env
    auth = login(client, "manager@p4-a.co")

    submitted = client.post(
        f"/api/v1/overtime/{env.overtime['id']}/submit",
        headers=auth["headers"], json={},
    )
    assert submitted.status_code == 200, submitted.text
    approved = client.post(
        f"/api/v1/overtime/{env.overtime['id']}/approve",
        headers=auth["headers"], json={},
    )
    assert approved.status_code == 200, approved.text

    # manager corrects a closed attendance record
    corrected = client.patch(
        f"/api/v1/attendance/{env.attendance['id']}", headers=auth["headers"],
        json={"check_in": "2025-01-06T09:15:00", "reason": "late device"},
    )
    assert corrected.status_code == 200, corrected.text

    # ...but has no delete permissions in the attendance domain
    assert client.delete(
        f"/api/v1/attendance/{env.attendance['id']}", headers=auth["headers"],
        params={"reason": "x"},
    ).status_code == 403
    assert client.delete(
        f"/api/v1/work-schedules/{env.schedule_a['id']}", headers=auth["headers"]
    ).status_code == 403


def test_company_admin_manages_the_whole_domain(client, matrix_env):
    env = matrix_env
    auth = env.admin_a

    shift = client.post(
        "/api/v1/shifts", headers=auth["headers"],
        json={"company_id": env.company_a.id, "code": "ADM",
              "name_ar": "x", "name_en": "Admin Shift",
              "start_time": "08:00:00", "end_time": "16:00:00"},
    )
    assert shift.status_code == 201, shift.text
    assert client.delete(
        f"/api/v1/shifts/{shift.json()['id']}", headers=auth["headers"]
    ).status_code == 204

    removed = client.delete(
        f"/api/v1/attendance/{env.attendance['id']}", headers=auth["headers"],
        params={"reason": "cleanup"},
    )
    assert removed.status_code == 204


def test_other_company_gets_404_not_403(client, matrix_env):
    env = matrix_env
    auth = env.admin_b
    headers = {**auth["headers"], "X-Company-Id": str(env.company_b.id)}

    assert client.get(
        f"/api/v1/work-schedules/{env.schedule_a['id']}", headers=headers
    ).status_code == 404
    assert client.patch(
        f"/api/v1/work-schedules/{env.schedule_a['id']}", headers=headers,
        json={"name_en": "hijack"},
    ).status_code == 404
    assert client.get(
        f"/api/v1/attendance/{env.attendance['id']}", headers=headers
    ).status_code == 404
    assert client.get(
        f"/api/v1/overtime/{env.overtime['id']}", headers=headers
    ).status_code == 404
    assert client.post(
        f"/api/v1/overtime/{env.overtime['id']}/approve",
        headers=headers, json={},
    ).status_code == 404
    assert client.get(
        f"/api/v1/employees/{env.employee_a['id']}/work-assignments",
        headers=headers,
    ).status_code == 404
    assert client.get(
        f"/api/v1/employees/{env.employee_a['id']}/schedule",
        headers=headers, params={"date": "2025-01-06"},
    ).status_code == 404

    # company B list endpoints never leak company A rows
    listing = client.get(
        "/api/v1/attendance",
        headers=auth["headers"],
        params={"company_id": env.company_b.id},
    ).json()
    assert listing["page"]["total"] == 0


def test_custom_role_can_be_given_a_single_phase4_permission(
    client, matrix_env, db_session
):
    env = matrix_env
    admin = env.admin_a
    role = client.post(
        "/api/v1/roles", headers=admin["headers"],
        json={"company_id": env.company_a.id, "code": "att_viewer",
              "name": "Attendance Viewer"},
    )
    assert role.status_code == 201, role.text
    granted = client.put(
        f"/api/v1/roles/{role.json()['id']}/permissions",
        headers=admin["headers"],
        json={"permission_codes": ["attendance.view"]},
    )
    assert granted.status_code == 200, granted.text

    seed_user(db_session, "att-viewer@p4-a.co", env.company_a, "att_viewer")
    viewer = login(client, "att-viewer@p4-a.co")

    assert client.get(
        "/api/v1/attendance",
        headers={**viewer["headers"], "X-Company-Id": str(env.company_a.id)},
    ).status_code == 200
    # ...but no capture permission
    denied = client.post(
        "/api/v1/attendance/check-in", headers=viewer["headers"],
        json={"employee_id": env.employee_a["id"],
              "at": "2025-01-09T08:00:00"},
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "forbidden"


def test_cross_company_foreign_key_rejected_in_service(client, matrix_env):
    env = matrix_env
    # company A employee + company B schedule -> not found (never linked)
    response = client.post(
        f"/api/v1/employees/{env.employee_a['id']}/work-assignments",
        headers=env.admin_a["headers"],
        json={"schedule_id": env.schedule_b["id"],
              "effective_from": "2025-01-01"},
    )
    assert response.status_code == 404
    assert response.json()["code"] == "WORK_SCHEDULE_NOT_FOUND"


def test_raw_cross_company_insert_blocked_by_rls(client, matrix_env, db_session):
    from app.core.rls import clear_context, elevate_for_seed, set_context

    env = matrix_env
    elevate_for_seed(db_session)
    employee_id = db_session.execute(
        text("SELECT id FROM employees WHERE company_id = :c"),
        {"c": env.company_a.id},
    ).scalar_one()
    clear_context(db_session)

    set_context(
        db_session, user_id=None, company_ids=[env.company_b.id],
        is_platform_admin=False,
    )
    with pytest.raises(Exception) as excinfo:
        db_session.execute(
            text(
                "INSERT INTO attendance_records "
                "(company_id, employee_id, work_date, check_in, status, "
                " source, created_at, updated_at) VALUES "
                f"({env.company_a.id}, {employee_id}, '2025-01-06', "
                " '2025-01-06T09:00:00+03:00', 'completed', 'manual', "
                " now(), now())"
            )
        )
        db_session.flush()
    assert "row-level security" in str(excinfo.value).lower()
    db_session.rollback()
    clear_context(db_session)


def test_audit_log_is_company_isolated(client, matrix_env):
    env = matrix_env
    # company B records overtime; company A never sees it
    created = client.post(
        "/api/v1/overtime", headers=env.admin_b["headers"],
        json={"employee_id": env.employee_b["id"],
              "work_date": "2025-01-06", "requested_minutes": 90},
    )
    assert created.status_code == 201, created.text

    page_a = client.get(
        "/api/v1/audit-logs",
        headers={**env.admin_a["headers"],
                 "X-Company-Id": str(env.company_a.id)},
        params={"action": "overtime.create"},
    ).json()
    for item in page_a["items"]:
        assert item["company_id"] == env.company_a.id

    page_b = client.get(
        "/api/v1/audit-logs",
        headers={**env.admin_b["headers"],
                 "X-Company-Id": str(env.company_b.id)},
        params={"action": "overtime.create"},
    ).json()
    assert page_b["page"]["total"] >= 1
    for item in page_b["items"]:
        assert item["company_id"] == env.company_b.id
