from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "ماجد",
        "last_name_ar": "الدوسري",
        "first_name_en": "Majed",
        "last_name_en": "Aldosari",
        **overrides,
    }
    response = client.post("/api/v1/employees", headers=auth["headers"], json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def ot_env(client, db_session):
    company = seed_company(db_session, "Ot Co")
    seed_user(db_session, "admin@ot.co", company, "company_admin")
    auth = login(client, "admin@ot.co")
    employee = _create_employee(client, auth, company.id)
    return SimpleNamespace(company=company, auth=auth, employee=employee)


def _create(client, env, **overrides):
    payload = {
        "employee_id": env.employee["id"],
        "work_date": "2025-01-06",
        "requested_minutes": 60,
    }
    payload.update(overrides)
    response = client.post(
        "/api/v1/overtime", headers=env.auth["headers"], json=payload
    )
    return response


def _action(client, env, overtime_id, action, **payload):
    return client.post(
        f"/api/v1/overtime/{overtime_id}/{action}",
        headers=env.auth["headers"], json=payload,
    )


def test_overtime_create_list_get(client, ot_env):
    env = ot_env
    created = _create(client, env, reason="month-end close")
    assert created.status_code == 201, created.text
    row = created.json()
    assert row["status"] == "draft"
    assert row["approved_minutes"] is None

    detail = client.get(
        f"/api/v1/overtime/{row['id']}", headers=env.auth["headers"]
    )
    assert detail.status_code == 200

    page = client.get(
        "/api/v1/overtime",
        headers=env.auth["headers"],
        params={"company_id": env.company.id},
    ).json()
    assert page["page"]["total"] == 1

    # filters
    assert client.get(
        "/api/v1/overtime",
        headers=env.auth["headers"],
        params={"company_id": env.company.id, "status": "submitted"},
    ).json()["page"]["total"] == 0
    assert client.get(
        "/api/v1/overtime",
        headers=env.auth["headers"],
        params={"company_id": env.company.id, "date_from": "2025-01-01",
                "date_to": "2025-01-31"},
    ).json()["page"]["total"] == 1
    assert client.get(
        "/api/v1/overtime",
        headers=env.auth["headers"],
        params={"company_id": env.company.id, "date_from": "2025-02-01"},
    ).json()["page"]["total"] == 0
    assert client.get(
        "/api/v1/overtime",
        headers=env.auth["headers"],
        params={"company_id": env.company.id,
                "employee_id": env.employee["id"]},
    ).json()["page"]["total"] == 1


def test_overtime_full_approval_lifecycle(client, ot_env):
    env = ot_env
    created = _create(client, env)
    assert created.status_code == 201, created.text
    row_id = created.json()["id"]

    submitted = _action(client, env, row_id, "submit")
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "submitted"
    assert submitted.json()["submitted_by"] is not None
    assert submitted.json()["submitted_at"] is not None

    approved = _action(client, env, row_id, "approve", reason="ok")
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["status"] == "approved"
    assert body["approved_minutes"] == 60  # defaults to requested
    assert body["decided_by"] is not None
    assert body["decision_reason"] == "ok"

    actions = set()
    page = client.get("/api/v1/audit-logs", headers=env.auth["headers"]).json()
    for item in page["items"]:
        if item["entity"] == "overtime_record":
            actions.add(item["action"])
    assert actions == {"overtime.create", "overtime.submit", "overtime.approve"}

    entry = next(
        i for i in page["items"] if i["action"] == "overtime.approve"
    )
    old_value = json.loads(entry["old_value"])
    new_value = json.loads(entry["new_value"])
    assert old_value["status"] == "submitted"
    assert new_value["status"] == "approved"


def test_overtime_approve_with_reduced_minutes(client, ot_env):
    env = ot_env
    row_id = _create(client, env).json()["id"]
    _action(client, env, row_id, "submit")
    approved = _action(client, env, row_id, "approve", approved_minutes=30)
    assert approved.status_code == 200, approved.text
    assert approved.json()["approved_minutes"] == 30


def test_overtime_approve_exceeding_request_rejected(client, ot_env):
    env = ot_env
    row_id = _create(client, env).json()["id"]
    _action(client, env, row_id, "submit")
    response = _action(client, env, row_id, "approve", approved_minutes=90)
    assert response.status_code == 400
    assert response.json()["code"] == "OVERTIME_INVALID_MINUTES"


def test_overtime_approve_draft_requires_submission(client, ot_env):
    env = ot_env
    row_id = _create(client, env).json()["id"]
    response = _action(client, env, row_id, "approve")
    assert response.status_code == 409
    assert response.json()["code"] == "OVERTIME_APPROVAL_REQUIRED"


def test_overtime_reject_draft_requires_submission(client, ot_env):
    env = ot_env
    row_id = _create(client, env).json()["id"]
    response = _action(client, env, row_id, "reject", reason="no")
    assert response.status_code == 409
    assert response.json()["code"] == "OVERTIME_APPROVAL_REQUIRED"


def test_overtime_double_approve_rejected(client, ot_env):
    env = ot_env
    row_id = _create(client, env).json()["id"]
    _action(client, env, row_id, "submit")
    assert _action(client, env, row_id, "approve").status_code == 200
    second = _action(client, env, row_id, "approve")
    assert second.status_code == 409
    assert second.json()["code"] == "OVERTIME_ALREADY_APPROVED"


def test_overtime_reject_flow(client, ot_env):
    env = ot_env
    row_id = _create(client, env).json()["id"]
    _action(client, env, row_id, "submit")
    rejected = _action(client, env, row_id, "reject", reason="budget freeze")
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["approved_minutes"] is None
    assert rejected.json()["decision_reason"] == "budget freeze"

    # a rejected request cannot be submitted again
    resubmit = _action(client, env, row_id, "submit")
    assert resubmit.status_code == 409
    assert resubmit.json()["code"] == "OVERTIME_INVALID_STATUS_TRANSITION"


def test_overtime_cancel_paths(client, ot_env):
    env = ot_env

    draft = _create(client, env).json()["id"]
    cancelled = _action(client, env, draft, "cancel", reason="changed mind")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    submitted = _create(client, env).json()["id"]
    _action(client, env, submitted, "submit")
    assert _action(client, env, submitted, "cancel").json()["status"] == (
        "cancelled"
    )

    approved = _create(client, env).json()["id"]
    _action(client, env, approved, "submit")
    _action(client, env, approved, "approve")
    assert _action(client, env, approved, "cancel").json()["status"] == (
        "cancelled"
    )

    # cancelled records are terminal
    again = _action(client, env, approved, "submit")
    assert again.status_code == 409
    assert again.json()["code"] == "OVERTIME_INVALID_STATUS_TRANSITION"


def test_overtime_edit_only_in_draft(client, ot_env):
    env = ot_env
    row_id = _create(client, env).json()["id"]

    edited = client.patch(
        f"/api/v1/overtime/{row_id}", headers=env.auth["headers"],
        json={"requested_minutes": 90, "notes": "extended shift"},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["requested_minutes"] == 90

    _action(client, env, row_id, "submit")
    blocked = client.patch(
        f"/api/v1/overtime/{row_id}", headers=env.auth["headers"],
        json={"requested_minutes": 120},
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "OVERTIME_INVALID_STATUS_TRANSITION"

    _action(client, env, row_id, "approve")
    approved_edit = client.patch(
        f"/api/v1/overtime/{row_id}", headers=env.auth["headers"],
        json={"requested_minutes": 120},
    )
    assert approved_edit.status_code == 409
    assert approved_edit.json()["code"] == "OVERTIME_ALREADY_APPROVED"


def test_overtime_correction_of_approved_request(client, ot_env):
    env = ot_env
    row_id = _create(client, env).json()["id"]
    _action(client, env, row_id, "submit")
    _action(client, env, row_id, "approve")

    reasonless = _action(client, env, row_id, "correct", approved_minutes=45)
    assert reasonless.status_code == 400
    assert reasonless.json()["code"] == "CORRECTION_REASON_REQUIRED"

    corrected = _action(
        client, env, row_id, "correct", approved_minutes=45,
        reason="shift logged 45 minutes",
    )
    assert corrected.status_code == 200, corrected.text
    body = corrected.json()
    assert body["approved_minutes"] == 45
    assert body["correction_reason"] == "shift logged 45 minutes"
    assert body["corrected_by"] is not None

    page = client.get(
        "/api/v1/audit-logs", headers=env.auth["headers"],
        params={"action": "overtime.correct"},
    ).json()
    assert page["page"]["total"] == 1
    assert json.loads(page["items"][0]["old_value"])["approved_minutes"] == 60
    assert json.loads(page["items"][0]["new_value"])["approved_minutes"] == 45


def test_overtime_correction_needs_approved_status(client, ot_env):
    env = ot_env
    row_id = _create(client, env).json()["id"]
    response = _action(
        client, env, row_id, "correct", approved_minutes=30, reason="x"
    )
    assert response.status_code == 409
    assert response.json()["code"] == "OVERTIME_APPROVAL_REQUIRED"


def test_overtime_correction_cannot_exceed_request(client, ot_env):
    env = ot_env
    row_id = _create(client, env).json()["id"]
    _action(client, env, row_id, "submit")
    _action(client, env, row_id, "approve")
    response = _action(
        client, env, row_id, "correct", approved_minutes=120, reason="oops"
    )
    assert response.status_code == 400
    assert response.json()["code"] == "OVERTIME_INVALID_MINUTES"


@pytest.mark.parametrize("minutes", [0, -30, 1441])
def test_overtime_invalid_minutes_rejected(client, ot_env, minutes):
    env = ot_env
    response = _create(client, env, requested_minutes=minutes)
    assert response.status_code == 400
    assert response.json()["code"] == "OVERTIME_INVALID_MINUTES"


def test_overtime_update_minutes_validated(client, ot_env):
    env = ot_env
    row_id = _create(client, env).json()["id"]
    response = client.patch(
        f"/api/v1/overtime/{row_id}", headers=env.auth["headers"],
        json={"requested_minutes": 2000},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "OVERTIME_INVALID_MINUTES"


def test_overtime_attendance_link_validated(client, ot_env):
    env = ot_env
    attendance = client.post(
        "/api/v1/attendance", headers=env.auth["headers"],
        json={"employee_id": env.employee["id"],
              "check_in": "2025-01-06T09:00:00",
              "check_out": "2025-01-06T19:00:00"},
    )
    assert attendance.status_code == 201, attendance.text

    linked = _create(client, env, attendance_id=attendance.json()["id"])
    assert linked.status_code == 201, linked.text
    assert linked.json()["attendance_id"] == attendance.json()["id"]

    missing = _create(client, env, attendance_id=999999)
    assert missing.status_code == 404
    assert missing.json()["code"] == "ATTENDANCE_NOT_FOUND"


def test_overtime_pagination(client, ot_env):
    env = ot_env
    for index in range(3):
        assert _create(client, env, work_date=f"2025-01-0{index + 6}").status_code == 201

    page = client.get(
        "/api/v1/overtime",
        headers=env.auth["headers"],
        params={"company_id": env.company.id, "page": 1, "page_size": 2},
    ).json()
    assert page["page"]["total"] == 3
    assert len(page["items"]) == 2
    # newest work_date first
    assert page["items"][0]["work_date"] == "2025-01-08"


def test_overtime_cross_company_is_404(client, ot_env, db_session):
    env = ot_env
    row_id = _create(client, env).json()["id"]

    other = seed_company(db_session, "Ot Other Co")
    seed_user(db_session, "admin@ot-other.co", other, "company_admin")
    outsider = login(client, "admin@ot-other.co")

    assert client.get(
        f"/api/v1/overtime/{row_id}", headers=outsider["headers"]
    ).status_code == 404
    assert client.patch(
        f"/api/v1/overtime/{row_id}", headers=outsider["headers"],
        json={"requested_minutes": 30},
    ).status_code == 404
    assert _action(client, SimpleNamespace(auth=outsider), row_id, "submit"
                   ).status_code == 404

    listing = client.get(
        "/api/v1/overtime",
        headers=outsider["headers"],
        params={"company_id": other.id},
    ).json()
    assert listing["page"]["total"] == 0
