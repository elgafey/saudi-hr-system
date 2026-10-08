from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db

PDF = b"%PDF-1.4\n%leave attachment\n%%EOF\n"


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "Hessa",
        "last_name_ar": "Alshammari",
        "first_name_en": "Hessa",
        "last_name_en": "Alshammari",
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


def _request_payload(employee_id, leave_type_id, **overrides):
    payload = {
        "employee_id": employee_id,
        "leave_type_id": leave_type_id,
        "start_date": "2025-03-03",
        "end_date": "2025-03-07",
    }
    payload.update(overrides)
    return payload


@pytest.fixture()
def req_env(client, db_session):
    company = seed_company(db_session, "LV Req")
    other = seed_company(db_session, "LV Req Other")
    seed_user(db_session, "admin@req.co", company, "company_admin")
    seed_user(db_session, "manager@req.co", company, "hr_manager")
    seed_user(db_session, "officer@req.co", company, "hr_officer")
    seed_user(db_session, "auditor@req.co", company, "auditor")
    seed_user(db_session, "roleless@req.co", company)
    seed_user(db_session, "admin@req-other.co", other, "company_admin")

    admin = login(client, "admin@req.co")
    employee_a = _create_employee(client, admin, company.id)
    employee_b = _create_employee(
        client,
        admin,
        company.id,
        first_name_en="Bader",
        last_name_en="Almutairi",
        first_name_ar="Bader",
        last_name_ar="Almutairi",
    )
    annual = _create_type(client, admin, company.id)
    _create_allocation(client, admin, employee_a["id"], annual["id"])
    _create_allocation(client, admin, employee_b["id"], annual["id"])

    worker = seed_user(db_session, "worker@req.co", company, "employee")
    linked = client.post(
        f"/api/v1/employees/{employee_a['id']}/user",
        headers=admin["headers"],
        json={"user_id": worker.id},
    )
    assert linked.status_code == 200, linked.text

    return SimpleNamespace(
        company=company,
        other=other,
        admin=admin,
        manager=login(client, "manager@req.co"),
        officer=login(client, "officer@req.co"),
        auditor=login(client, "auditor@req.co"),
        roleless=login(client, "roleless@req.co"),
        worker=login(client, "worker@req.co"),
        other_admin=login(client, "admin@req-other.co"),
        employee_a=employee_a,
        employee_b=employee_b,
        annual=annual,
    )


def test_request_draft_create_update_and_recount(client, req_env):
    env = req_env
    auth = env.admin

    created = client.post(
        "/api/v1/leave-requests",
        headers=auth["headers"],
        json=_request_payload(
            env.employee_a["id"], env.annual["id"], reason="Family trip"
        ),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "draft"
    assert body["days"] == "5.00"
    assert body["count_details"]["mode"] == "working_days"
    request_id = body["id"]

    read = client.get(
        f"/api/v1/leave-requests/{request_id}", headers=auth["headers"]
    )
    assert read.status_code == 200, read.text
    assert read.json()["reason"] == "Family trip"

    # Editing a draft recounts the days (shorter range).
    updated = client.patch(
        f"/api/v1/leave-requests/{request_id}",
        headers=auth["headers"],
        json={"end_date": "2025-03-05"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["days"] == "3.00"
    assert updated.json()["status"] == "draft"

    page = client.get(
        "/api/v1/leave-requests",
        headers=auth["headers"],
        params={
            "company_id": env.company.id,
            "status": "draft",
            "date_from": "2025-03-01",
            "date_to": "2025-03-31",
            "q": "Family",
        },
    ).json()
    assert page["page"]["total"] == 1
    assert page["items"][0]["id"] == request_id

    audit = client.get(
        "/api/v1/audit-logs",
        headers=auth["headers"],
        params={"action": "leave_request.create"},
    ).json()
    assert audit["page"]["total"] >= 1
    assert all(
        item["company_id"] == env.company.id for item in audit["items"]
    )


def test_request_overlap_semantics(client, req_env):
    env = req_env
    auth = env.admin

    first = client.post(
        "/api/v1/leave-requests",
        headers=auth["headers"],
        json=_request_payload(env.employee_a["id"], env.annual["id"]),
    )
    assert first.status_code == 201, first.text

    # Two drafts may coexist (overlap is only enforced against
    # submitted/approved rows).
    second = client.post(
        "/api/v1/leave-requests",
        headers=auth["headers"],
        json=_request_payload(
            env.employee_a["id"],
            env.annual["id"],
            start_date="2025-03-05",
            end_date="2025-03-12",
        ),
    )
    assert second.status_code == 201, second.text

    submitted = client.post(
        f"/api/v1/leave-requests/{first.json()['id']}/submit",
        headers=auth["headers"],
        json={},
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "submitted"

    # Now every overlapping range is rejected - drafts included.
    clash = client.post(
        "/api/v1/leave-requests",
        headers=auth["headers"],
        json=_request_payload(
            env.employee_a["id"],
            env.annual["id"],
            start_date="2025-03-06",
            end_date="2025-03-11",
        ),
    )
    assert clash.status_code == 409, clash.text
    assert clash.json()["code"] == "LEAVE_REQUEST_OVERLAP"

    submitting_clash = client.post(
        f"/api/v1/leave-requests/{second.json()['id']}/submit",
        headers=auth["headers"],
        json={},
    )
    assert submitting_clash.status_code == 409, submitting_clash.text
    assert submitting_clash.json()["code"] == "LEAVE_REQUEST_OVERLAP"

    # The other employee's identical range is independent.
    independent = client.post(
        "/api/v1/leave-requests",
        headers=auth["headers"],
        json=_request_payload(env.employee_b["id"], env.annual["id"]),
    )
    assert independent.status_code == 201, independent.text

    # Fully adjacent ranges (next day) never overlap.
    adjacent = client.post(
        "/api/v1/leave-requests",
        headers=auth["headers"],
        json=_request_payload(
            env.employee_b["id"],
            env.annual["id"],
            start_date="2025-03-08",
            end_date="2025-03-12",
        ),
    )
    assert adjacent.status_code == 201, adjacent.text


def test_request_input_validation(client, req_env):
    env = req_env
    auth = env.admin

    inverted = client.post(
        "/api/v1/leave-requests",
        headers=auth["headers"],
        json=_request_payload(
            env.employee_a["id"],
            env.annual["id"],
            start_date="2025-03-10",
            end_date="2025-03-05",
        ),
    )
    assert inverted.status_code == 400, inverted.text
    assert inverted.json()["code"] == "LEAVE_REQUEST_INVALID_RANGE"

    half_times = client.post(
        "/api/v1/leave-requests",
        headers=auth["headers"],
        json=_request_payload(
            env.employee_a["id"],
            env.annual["id"],
            start_time="09:00:00",
        ),
    )
    assert half_times.status_code == 400, half_times.text
    assert half_times.json()["code"] == "LEAVE_REQUEST_INVALID_TIMES"

    multi_day_times = client.post(
        "/api/v1/leave-requests",
        headers=auth["headers"],
        json=_request_payload(
            env.employee_a["id"],
            env.annual["id"],
            start_time="09:00:00",
            end_time="13:00:00",
        ),
    )
    assert multi_day_times.status_code == 400, multi_day_times.text
    assert multi_day_times.json()["code"] == "LEAVE_REQUEST_INVALID_TIMES"

    long_span = client.post(
        "/api/v1/leave-requests",
        headers=auth["headers"],
        json=_request_payload(
            env.employee_a["id"],
            env.annual["id"],
            start_date="2025-01-01",
            end_date="2026-06-01",
        ),
    )
    assert long_span.status_code == 400, long_span.text
    assert long_span.json()["code"] == "LEAVE_REQUEST_INVALID_RANGE"

    inactive_employee = client.patch(
        f"/api/v1/employees/{env.employee_a['id']}",
        headers=auth["headers"],
        json={"status": "suspended"},
    )
    assert inactive_employee.status_code == 200, inactive_employee.text
    suspended = client.post(
        "/api/v1/leave-requests",
        headers=auth["headers"],
        json=_request_payload(env.employee_a["id"], env.annual["id"]),
    )
    # Leave is only available for active employees (create-time gate).
    assert suspended.status_code == 409, suspended.text
    assert suspended.json()["code"] == "LEAVE_EMPLOYEE_NOT_ACTIVE"


def test_request_min_max_reason_and_attachment_gates(client, req_env):
    env = req_env
    auth = env.admin

    bounded = _create_type(
        client,
        auth,
        env.company.id,
        code="BOUNDED",
        name_ar="محدودة",
        name_en="Bounded",
        min_request_days="2",
        max_request_days="3",
    )
    too_short = client.post(
        "/api/v1/leave-requests",
        headers=auth["headers"],
        json=_request_payload(
            env.employee_a["id"],
            bounded["id"],
            start_date="2025-04-07",
            end_date="2025-04-07",
        ),
    )
    assert too_short.status_code == 400, too_short.text
    assert too_short.json()["code"] == "LEAVE_REQUEST_INVALID_DAYS"

    too_long = client.post(
        "/api/v1/leave-requests",
        headers=auth["headers"],
        json=_request_payload(
            env.employee_a["id"],
            bounded["id"],
            start_date="2025-04-07",
            end_date="2025-04-14",
        ),
    )
    assert too_long.status_code == 400, too_long.text
    assert too_long.json()["code"] == "LEAVE_REQUEST_INVALID_DAYS"

    just_right = client.post(
        "/api/v1/leave-requests",
        headers=auth["headers"],
        json=_request_payload(
            env.employee_a["id"],
            bounded["id"],
            start_date="2025-04-07",
            end_date="2025-04-08",
        ),
    )
    assert just_right.status_code == 201, just_right.text

    reasoned = _create_type(
        client,
        auth,
        env.company.id,
        code="REASONED",
        name_ar="تتطلب سبباً",
        name_en="Needs reason",
        requires_reason=True,
    )
    no_reason = client.post(
        "/api/v1/leave-requests",
        headers=auth["headers"],
        json=_request_payload(
            env.employee_a["id"],
            reasoned["id"],
            start_date="2025-05-05",
            end_date="2025-05-06",
        ),
    )
    assert no_reason.status_code == 400, no_reason.text
    assert no_reason.json()["code"] == "LEAVE_REQUEST_REASON_REQUIRED"

    with_reason = client.post(
        "/api/v1/leave-requests",
        headers=auth["headers"],
        json=_request_payload(
            env.employee_a["id"],
            reasoned["id"],
            start_date="2025-05-05",
            end_date="2025-05-06",
            reason="Medical follow-up",
        ),
    )
    assert with_reason.status_code == 201, with_reason.text

    att_type = _create_type(
        client,
        auth,
        env.company.id,
        code="ATTACHED",
        name_ar="تتطلب مرفقاً",
        name_en="Needs attachment",
        requires_attachment=True,
        attachment_threshold_days="3",
    )
    _create_allocation(
        client, auth, env.employee_a["id"], att_type["id"],
        period_start="2025-06-01", period_end="2025-06-30",
        allocated_days="10.00",
    )
    att_request = client.post(
        "/api/v1/leave-requests",
        headers=auth["headers"],
        json=_request_payload(
            env.employee_a["id"],
            att_type["id"],
            start_date="2025-06-02",
            end_date="2025-06-04",
        ),
    )
    assert att_request.status_code == 201, att_request.text
    att_id = att_request.json()["id"]

    missing_attachment = client.post(
        f"/api/v1/leave-requests/{att_id}/submit",
        headers=auth["headers"],
        json={},
    )
    assert missing_attachment.status_code == 400, missing_attachment.text
    assert (
        missing_attachment.json()["code"]
        == "LEAVE_REQUEST_ATTACHMENT_REQUIRED"
    )

    uploaded = client.post(
        f"/api/v1/leave-requests/{att_id}/attachment",
        headers=auth["headers"],
        files={"file": ("certificate.pdf", PDF, "application/pdf")},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["attachment_name"] == "certificate.pdf"

    attachment_download = client.get(
        f"/api/v1/leave-requests/{att_id}/attachment",
        headers=auth["headers"],
    )
    assert attachment_download.status_code == 200, attachment_download.text
    assert attachment_download.content == PDF
    assert "attachment" in attachment_download.headers["content-disposition"]

    submitted = client.post(
        f"/api/v1/leave-requests/{att_id}/submit",
        headers=auth["headers"],
        json={},
    )
    assert submitted.status_code == 200, submitted.text

    removed_attachment = client.delete(
        f"/api/v1/leave-requests/{att_id}/attachment",
        headers=auth["headers"],
    )
    assert removed_attachment.status_code == 204, removed_attachment.text


def test_preview_returns_days_and_balance(client, req_env):
    env = req_env
    auth = env.admin

    preview = client.post(
        "/api/v1/leave-requests/preview",
        headers=auth["headers"],
        json={
            "employee_id": env.employee_a["id"],
            "leave_type_id": env.annual["id"],
            "start_date": "2025-03-03",
            "end_date": "2025-03-07",
        },
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["days"] == "5.00"
    assert body["day_counting_mode"] == "working_days"
    assert body["balance"]["allocated_days"] == "21.00"
    assert body["balance"]["remaining_days"] == "21.00"
    assert body["would_be_negative"] is False
    assert body["has_open_attendance_conflict"] is False
    assert body["has_approved_overtime_conflict"] is False

    overdraw = client.post(
        "/api/v1/leave-requests/preview",
        headers=auth["headers"],
        json={
            "employee_id": env.employee_a["id"],
            "leave_type_id": env.annual["id"],
            "start_date": "2025-08-04",
            "end_date": "2025-08-29",
        },
    )
    assert overdraw.status_code == 200, overdraw.text
    assert overdraw.json()["would_be_negative"] is True

    # Without leave_request.create the preview is refused (403), while a
    # user with no company membership at all cannot even resolve the
    # employee (404 - no information leak about company A).
    denied = client.post(
        "/api/v1/leave-requests/preview",
        headers=env.auditor["headers"],
        json={
            "employee_id": env.employee_a["id"],
            "leave_type_id": env.annual["id"],
            "start_date": "2025-03-03",
            "end_date": "2025-03-07",
        },
    )
    assert denied.status_code == 403, denied.text

    anonymous_member = client.post(
        "/api/v1/leave-requests/preview",
        headers=env.roleless["headers"],
        json={
            "employee_id": env.employee_a["id"],
            "leave_type_id": env.annual["id"],
            "start_date": "2025-03-03",
            "end_date": "2025-03-07",
        },
    )
    assert anonymous_member.status_code == 404, anonymous_member.text
    assert anonymous_member.json()["code"] == "LEAVE_REQUEST_NOT_FOUND"


def test_self_service_employee_scoping(client, req_env):
    env = req_env
    headers = env.worker["headers"]

    own = client.post(
        "/api/v1/leave-requests",
        headers=headers,
        json=_request_payload(
            env.employee_a["id"], env.annual["id"], reason="Personal"
        ),
    )
    assert own.status_code == 201, own.text
    own_id = own.json()["id"]

    foreign = client.post(
        "/api/v1/leave-requests",
        headers=headers,
        json=_request_payload(env.employee_b["id"], env.annual["id"]),
    )
    assert foreign.status_code == 403, foreign.text
    assert foreign.json()["code"] == "forbidden"

    listed = client.get("/api/v1/leave-requests", headers=headers).json()
    assert listed["page"]["total"] == 1
    assert listed["items"][0]["id"] == own_id

    scoped_foreign = client.get(
        "/api/v1/leave-requests",
        headers=headers,
        params={"employee_id": env.employee_b["id"]},
    )
    assert scoped_foreign.status_code == 403, scoped_foreign.text

    # An admin-created draft for employee B is invisible to the worker.
    admin_draft = client.post(
        "/api/v1/leave-requests",
        headers=env.admin["headers"],
        json=_request_payload(
            env.employee_b["id"],
            env.annual["id"],
            start_date="2025-05-12",
            end_date="2025-05-16",
        ),
    )
    assert admin_draft.status_code == 201, admin_draft.text
    assert (
        client.get(
            f"/api/v1/leave-requests/{admin_draft.json()['id']}",
            headers=headers,
        ).status_code
        == 403
    )

    assert (
        client.get(f"/api/v1/leave-requests/{own_id}", headers=headers).status_code
        == 200
    )
    patched = client.patch(
        f"/api/v1/leave-requests/{own_id}",
        headers=headers,
        json={"reason": "Personal errand"},
    )
    assert patched.status_code == 200, patched.text

    submitted = client.post(
        f"/api/v1/leave-requests/{own_id}/submit", headers=headers, json={}
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "submitted"

    # The employee may never approve, reject or delete.
    assert (
        client.post(
            f"/api/v1/leave-requests/{own_id}/approve",
            headers=headers,
            json={},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/leave-requests/{own_id}/reject",
            headers=headers,
            json={"reason": "no"},
        ).status_code
        == 403
    )
    assert (
        client.delete(f"/api/v1/leave-requests/{own_id}", headers=headers).status_code
        == 403
    )

    # Reading another company's request is 404, not 403.
    admin_only = client.get(
        f"/api/v1/leave-requests/{admin_draft.json()['id']}",
        headers=env.admin["headers"],
    )
    assert admin_only.status_code == 200, admin_only.text


def test_role_matrix_on_requests(client, req_env):
    env = req_env

    assert (
        client.get(
            "/api/v1/leave-requests", headers=env.roleless["headers"]
        ).status_code
        == 403
    )
    # A user without any company membership cannot resolve the target
    # employee at all (404, never a leak of company A's data).
    roleless_create = client.post(
        "/api/v1/leave-requests",
        headers=env.roleless["headers"],
        json=_request_payload(env.employee_a["id"], env.annual["id"]),
    )
    assert roleless_create.status_code == 404, roleless_create.text
    assert roleless_create.json()["code"] == "LEAVE_REQUEST_NOT_FOUND"

    # Auditor reads but never writes or decides.
    assert (
        client.get(
            "/api/v1/leave-requests", headers=env.auditor["headers"]
        ).status_code
        == 200
    )
    created = client.post(
        "/api/v1/leave-requests",
        headers=env.officer["headers"],
        json=_request_payload(
            env.employee_a["id"],
            env.annual["id"],
            start_date="2025-07-07",
            end_date="2025-07-11",
        ),
    )
    assert created.status_code == 201, created.text
    request_id = created.json()["id"]
    assert (
        client.post(
            f"/api/v1/leave-requests/{request_id}/submit",
            headers=env.officer["headers"],
            json={},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/leave-requests/{request_id}/approve",
            headers=env.officer["headers"],
            json={},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/leave-requests/{request_id}/reject",
            headers=env.officer["headers"],
            json={"reason": "x"},
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/api/v1/leave-requests/{request_id}", headers=env.officer["headers"]
        ).status_code
        == 403
    )

    # Only company_admin holds leave_request.delete.
    draft = client.post(
        "/api/v1/leave-requests",
        headers=env.admin["headers"],
        json=_request_payload(
            env.employee_b["id"],
            env.annual["id"],
            start_date="2025-08-04",
            end_date="2025-08-08",
        ),
    )
    assert draft.status_code == 201, draft.text
    draft_id = draft.json()["id"]
    assert (
        client.delete(
            f"/api/v1/leave-requests/{draft_id}", headers=env.manager["headers"]
        ).status_code
        == 403
    )
    removed = client.delete(
        f"/api/v1/leave-requests/{draft_id}", headers=env.admin["headers"]
    )
    assert removed.status_code == 204, removed.text


def test_delete_and_state_guards(client, req_env):
    env = req_env
    auth = env.admin

    draft = client.post(
        "/api/v1/leave-requests",
        headers=auth["headers"],
        json=_request_payload(
            env.employee_a["id"],
            env.annual["id"],
            start_date="2025-09-01",
            end_date="2025-09-05",
        ),
    )
    request_id = draft.json()["id"]

    submitted = client.post(
        f"/api/v1/leave-requests/{request_id}/submit", headers=auth["headers"], json={}
    )
    assert submitted.status_code == 200, submitted.text

    # Non-draft rows cannot be deleted or edited.
    delete_submitted = client.delete(
        f"/api/v1/leave-requests/{request_id}", headers=auth["headers"]
    )
    assert delete_submitted.status_code == 409, delete_submitted.text
    assert delete_submitted.json()["code"] == "LEAVE_REQUEST_STATE_INVALID"

    edit_submitted = client.patch(
        f"/api/v1/leave-requests/{request_id}",
        headers=auth["headers"],
        json={"reason": "changed"},
    )
    assert edit_submitted.status_code == 409, edit_submitted.text
    assert edit_submitted.json()["code"] == "LEAVE_REQUEST_STATE_INVALID"

    # Double submit is a state violation too.
    resubmit = client.post(
        f"/api/v1/leave-requests/{request_id}/submit", headers=auth["headers"], json={}
    )
    assert resubmit.status_code == 409, resubmit.text
    assert resubmit.json()["code"] == "LEAVE_REQUEST_STATE_INVALID"


def test_cross_company_request_access(client, req_env):
    env = req_env
    created = client.post(
        "/api/v1/leave-requests",
        headers=env.admin["headers"],
        json=_request_payload(env.employee_a["id"], env.annual["id"]),
    )
    request_id = created.json()["id"]
    headers = env.other_admin["headers"]

    assert (
        client.get(f"/api/v1/leave-requests/{request_id}", headers=headers).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/leave-requests/{request_id}",
            headers=headers,
            json={"reason": "hijack"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/leave-requests/{request_id}/submit",
            headers=headers,
            json={},
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/leave-requests/{request_id}", headers=headers
        ).status_code
        == 404
    )

    foreign_employee = client.post(
        "/api/v1/leave-requests",
        headers=headers,
        json=_request_payload(env.employee_a["id"], env.annual["id"]),
    )
    assert foreign_employee.status_code == 404, foreign_employee.text

    page = client.get(
        "/api/v1/leave-requests",
        headers=headers,
        params={"company_id": env.company.id},
    )
    assert page.status_code == 403, page.text
