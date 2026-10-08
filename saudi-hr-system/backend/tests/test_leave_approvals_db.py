from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "Tariq",
        "last_name_ar": "Alreshoudi",
        "first_name_en": "Tariq",
        "last_name_en": "Alreshoudi",
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


@pytest.fixture()
def approve_env(client, db_session):
    company = seed_company(db_session, "LV Approve")
    seed_user(db_session, "admin@appr.co", company, "company_admin")
    seed_user(db_session, "manager@appr.co", company, "hr_manager")

    admin = login(client, "admin@appr.co")
    employee = _create_employee(client, admin, company.id)

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
        f"/api/v1/employees/{employee['id']}/work-assignments",
        headers=admin["headers"],
        json={
            "schedule_id": schedule.json()["id"],
            "effective_from": "2025-01-01",
        },
    )
    assert assignment.status_code == 201, assignment.text

    annual = _create_type(client, admin, company.id)
    auto = _create_type(
        client,
        admin,
        company.id,
        code="AUTO",
        name_ar="تلقائية",
        name_en="Auto approved",
        requires_approval=False,
    )
    allocation = client.post(
        "/api/v1/leave-allocations",
        headers=admin["headers"],
        json={
            "employee_id": employee["id"],
            "leave_type_id": annual["id"],
            "period_start": "2025-01-01",
            "period_end": "2025-12-31",
            "allocated_days": "21.00",
        },
    )
    assert allocation.status_code == 201, allocation.text
    auto_allocation = client.post(
        "/api/v1/leave-allocations",
        headers=admin["headers"],
        json={
            "employee_id": employee["id"],
            "leave_type_id": auto["id"],
            "period_start": "2025-01-01",
            "period_end": "2025-12-31",
            "allocated_days": "10.00",
        },
    )
    assert auto_allocation.status_code == 201, auto_allocation.text

    worker = seed_user(db_session, "worker@appr.co", company, "employee")
    linked = client.post(
        f"/api/v1/employees/{employee['id']}/user",
        headers=admin["headers"],
        json={"user_id": worker.id},
    )
    assert linked.status_code == 200, linked.text

    return SimpleNamespace(
        company=company,
        admin=admin,
        manager=login(client, "manager@appr.co"),
        worker=login(client, "worker@appr.co"),
        employee=employee,
        annual=annual,
        auto=auto,
    )


def test_auto_approved_on_submit_when_type_requires_no_approval(
    client, approve_env
):
    env = approve_env
    auth = env.admin

    request = _request(
        client, auth, env.employee["id"], env.auto["id"],
        start_date="2025-04-07", end_date="2025-04-11",
    )
    assert request["status"] == "draft"

    submitted = client.post(
        f"/api/v1/leave-requests/{request['id']}/submit",
        headers=auth["headers"],
        json={},
    )
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()
    assert body["status"] == "approved"
    assert body["decided_by"] is not None
    assert body["decision_reason"] == "auto"

    balance = client.get(
        "/api/v1/leave-balances",
        headers=auth["headers"],
        params={
            "employee_id": env.employee["id"],
            "leave_type_id": env.auto["id"],
            "period_start": "2025-04-01",
            "period_end": "2025-04-30",
        },
    ).json()
    line = next(item for item in balance["items"] if item["code"] == "AUTO")
    assert line["used_days"] == "5.00"
    assert line["pending_days"] == "0.00"

    # Auto-approval is audited with mode=auto.
    audit = client.get(
        "/api/v1/audit-logs",
        headers=auth["headers"],
        params={"action": "leave_request.approve"},
    ).json()
    assert audit["page"]["total"] >= 1
    new_value = json.loads(audit["items"][0]["new_value"])
    assert new_value["mode"] == "auto"


def test_manual_approval_reject_and_cancel_lifecycle(client, approve_env):
    env = approve_env
    auth = env.admin

    draft = _request(client, auth, env.employee["id"], env.annual["id"])

    # Decisions require a submitted row.
    approve_draft = client.post(
        f"/api/v1/leave-requests/{draft['id']}/approve",
        headers=auth["headers"],
        json={},
    )
    assert approve_draft.status_code == 409, approve_draft.text
    assert approve_draft.json()["code"] == "LEAVE_REQUEST_STATE_INVALID"
    reject_draft = client.post(
        f"/api/v1/leave-requests/{draft['id']}/reject",
        headers=auth["headers"],
        json={"reason": "x"},
    )
    assert reject_draft.status_code == 409, reject_draft.text

    submitted = client.post(
        f"/api/v1/leave-requests/{draft['id']}/submit",
        headers=auth["headers"],
        json={},
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "submitted"

    approved = client.post(
        f"/api/v1/leave-requests/{draft['id']}/approve",
        headers=env.manager["headers"],
        json={"reason": "approved by HR"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["decision_reason"] == "approved by HR"
    assert approved.json()["decided_by"] is not None

    # Cancelling approved leave restores the consumed balance.
    cancelled = client.post(
        f"/api/v1/leave-requests/{draft['id']}/cancel",
        headers=auth["headers"],
        json={"reason": "plans changed"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["cancel_reason"] == "plans changed"

    balance = client.get(
        "/api/v1/leave-balances",
        headers=auth["headers"],
        params={
            "employee_id": env.employee["id"],
            "leave_type_id": env.annual["id"],
            "period_start": "2025-03-01",
            "period_end": "2025-03-31",
        },
    ).json()
    line = next(item for item in balance["items"] if item["code"] == "ANNUAL")
    assert line["used_days"] == "0.00"
    assert line["pending_days"] == "0.00"
    assert line["remaining_days"] == "21.00"

    # Terminal rows cannot transition again.
    recancel = client.post(
        f"/api/v1/leave-requests/{draft['id']}/cancel",
        headers=auth["headers"],
        json={},
    )
    assert recancel.status_code == 409, recancel.text

    # Rejection requires a reason and never consumes balance.
    second = _request(
        client, auth, env.employee["id"], env.annual["id"],
        start_date="2025-03-10", end_date="2025-03-12",
    )
    client.post(
        f"/api/v1/leave-requests/{second['id']}/submit",
        headers=auth["headers"],
        json={},
    )
    no_reason = client.post(
        f"/api/v1/leave-requests/{second['id']}/reject",
        headers=auth["headers"],
        json={},
    )
    assert no_reason.status_code == 400, no_reason.text
    assert no_reason.json()["code"] == "LEAVE_DECISION_REASON_REQUIRED"

    rejected = client.post(
        f"/api/v1/leave-requests/{second['id']}/reject",
        headers=env.manager["headers"],
        json={"reason": "coverage needed"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["decision_reason"] == "coverage needed"

    late_approve = client.post(
        f"/api/v1/leave-requests/{second['id']}/approve",
        headers=auth["headers"],
        json={},
    )
    assert late_approve.status_code == 409, late_approve.text

    # A rejected request cannot be cancelled either.
    cancel_rejected = client.post(
        f"/api/v1/leave-requests/{second['id']}/cancel",
        headers=auth["headers"],
        json={},
    )
    assert cancel_rejected.status_code == 409, cancel_rejected.text

    # Draft cancel is always allowed.
    third = _request(
        client, auth, env.employee["id"], env.annual["id"],
        start_date="2025-05-05", end_date="2025-05-06",
    )
    cancelled_draft = client.post(
        f"/api/v1/leave-requests/{third['id']}/cancel",
        headers=auth["headers"],
        json={"reason": "changed my mind"},
    )
    assert cancelled_draft.status_code == 200, cancelled_draft.text
    assert cancelled_draft.json()["status"] == "cancelled"


def test_open_attendance_blocks_approval(client, approve_env):
    env = approve_env
    auth = env.admin

    request = _request(client, auth, env.employee["id"], env.annual["id"])
    client.post(
        f"/api/v1/leave-requests/{request['id']}/submit",
        headers=auth["headers"],
        json={},
    )

    check_in = client.post(
        "/api/v1/attendance/check-in",
        headers=auth["headers"],
        json={"employee_id": env.employee["id"], "at": "2025-03-03T08:00:00"},
    )
    assert check_in.status_code == 201, check_in.text

    blocked = client.post(
        f"/api/v1/leave-requests/{request['id']}/approve",
        headers=env.manager["headers"],
        json={},
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["code"] == "LEAVE_ATTENDANCE_OPEN_CONFLICT"

    # Closing the attendance record clears the conflict.
    checkout = client.patch(
        f"/api/v1/attendance/{check_in.json()['id']}",
        headers=auth["headers"],
        json={"check_out": "2025-03-03T17:00:00", "reason": "forgot to log"},
    )
    assert checkout.status_code == 200, checkout.text

    approved = client.post(
        f"/api/v1/leave-requests/{request['id']}/approve",
        headers=env.manager["headers"],
        json={},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"


def test_any_attendance_record_blocks_cancelling_approved_leave(
    client, approve_env
):
    env = approve_env
    auth = env.admin

    request = _request(client, auth, env.employee["id"], env.annual["id"])
    client.post(
        f"/api/v1/leave-requests/{request['id']}/submit",
        headers=auth["headers"],
        json={},
    )
    approved = client.post(
        f"/api/v1/leave-requests/{request['id']}/approve",
        headers=auth["headers"],
        json={},
    )
    assert approved.status_code == 200, approved.text

    attendance = client.post(
        "/api/v1/attendance",
        headers=auth["headers"],
        json={
            "employee_id": env.employee["id"],
            "check_in": "2025-03-04T09:00:00",
            "check_out": "2025-03-04T17:00:00",
        },
    )
    assert attendance.status_code == 201, attendance.text

    blocked = client.post(
        f"/api/v1/leave-requests/{request['id']}/cancel",
        headers=auth["headers"],
        json={"reason": "cannot"},
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["code"] == "LEAVE_ATTENDANCE_RECORD_EXISTS"

    # Removing the attendance record unblocks the cancellation.
    removed = client.delete(
        f"/api/v1/attendance/{attendance.json()['id']}",
        headers=auth["headers"],
        params={"reason": "wrong day"},
    )
    assert removed.status_code == 204, removed.text
    cancelled = client.post(
        f"/api/v1/leave-requests/{request['id']}/cancel",
        headers=auth["headers"],
        json={"reason": "retry"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"


def test_approved_overtime_blocks_only_full_leave_days(client, approve_env):
    env = approve_env
    auth = env.admin

    full = _request(
        client, auth, env.employee["id"], env.annual["id"],
        start_date="2025-03-10", end_date="2025-03-14",
    )
    client.post(
        f"/api/v1/leave-requests/{full['id']}/submit",
        headers=auth["headers"],
        json={},
    )

    overtime = client.post(
        "/api/v1/overtime",
        headers=auth["headers"],
        json={
            "employee_id": env.employee["id"],
            "work_date": "2025-03-10",
            "requested_minutes": 60,
        },
    )
    assert overtime.status_code == 201, overtime.text
    client.post(
        f"/api/v1/overtime/{overtime.json()['id']}/submit",
        headers=auth["headers"],
        json={},
    )
    overtime_approved = client.post(
        f"/api/v1/overtime/{overtime.json()['id']}/approve",
        headers=auth["headers"],
        json={},
    )
    assert overtime_approved.status_code == 200, overtime_approved.text

    blocked = client.post(
        f"/api/v1/leave-requests/{full['id']}/approve",
        headers=env.manager["headers"],
        json={},
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["code"] == "LEAVE_OVERTIME_CONFLICT"

    # A partial-day request on the same date is NOT a full-day conflict.
    cancel_full = client.post(
        f"/api/v1/leave-requests/{full['id']}/cancel",
        headers=auth["headers"],
        json={"reason": "switch to half day"},
    )
    assert cancel_full.status_code == 200, cancel_full.text

    partial = _request(
        client, auth, env.employee["id"], env.annual["id"],
        start_date="2025-03-10", end_date="2025-03-10",
        start_time="09:00:00", end_time="13:00:00",
    )
    assert partial["days"] == "0.50", partial
    client.post(
        f"/api/v1/leave-requests/{partial['id']}/submit",
        headers=auth["headers"],
        json={},
    )
    approved = client.post(
        f"/api/v1/leave-requests/{partial['id']}/approve",
        headers=env.manager["headers"],
        json={},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"


def test_employee_self_service_cannot_decide_but_can_cancel(
    client, approve_env
):
    env = approve_env
    headers = env.worker["headers"]

    created = client.post(
        "/api/v1/leave-requests",
        headers=headers,
        json={
            "employee_id": env.employee["id"],
            "leave_type_id": env.annual["id"],
            "start_date": "2025-06-02",
            "end_date": "2025-06-06",
        },
    )
    assert created.status_code == 201, created.text
    request_id = created.json()["id"]

    client.post(
        f"/api/v1/leave-requests/{request_id}/submit", headers=headers, json={}
    )
    assert (
        client.post(
            f"/api/v1/leave-requests/{request_id}/approve",
            headers=headers,
            json={},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/leave-requests/{request_id}/reject",
            headers=headers,
            json={"reason": "no"},
        ).status_code
        == 403
    )

    cancelled = client.post(
        f"/api/v1/leave-requests/{request_id}/cancel",
        headers=headers,
        json={"reason": "employee withdrew"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    # hr_manager holds approve/reject but not delete.
    draft = client.post(
        "/api/v1/leave-requests",
        headers=env.admin["headers"],
        json={
            "employee_id": env.employee["id"],
            "leave_type_id": env.annual["id"],
            "start_date": "2025-06-09",
            "end_date": "2025-06-13",
        },
    )
    assert draft.status_code == 201, draft.text
    assert (
        client.delete(
            f"/api/v1/leave-requests/{draft.json()['id']}",
            headers=env.manager["headers"],
        ).status_code
        == 403
    )
