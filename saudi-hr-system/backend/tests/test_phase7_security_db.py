from __future__ import annotations

import json
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app.core.rls import clear_context, elevate_for_seed
from app.shared.models import AttendanceRecord, EmployeeRequest
from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db

PDF = b"%PDF-1.4\n%phase7 ess document\n%%EOF\n"


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "نورة",
        "last_name_ar": "القحطاني",
        "first_name_en": "Noura",
        "last_name_en": "Alqahtani",
        "status": "active",
        **overrides,
    }
    response = client.post("/api/v1/employees", headers=auth["headers"], json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _link_user(client, auth, employee_id, user_id):
    response = client.post(
        f"/api/v1/employees/{employee_id}/user",
        headers=auth["headers"],
        json={"user_id": user_id},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _upload_doc(client, auth, employee_id, type_id):
    response = client.post(
        f"/api/v1/employees/{employee_id}/documents",
        headers=auth["headers"],
        data={"document_type_id": str(type_id)},
        files={"file": ("nida.pdf", PDF, "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _correction(work_date, check_in, check_out, **overrides):
    payload = {
        "request_type": "attendance_correction",
        "subject": f"Fix clock for {work_date}",
        "reason": "Time clock failed",
        "payload": {
            "work_date": work_date,
            "check_in": check_in,
            "check_out": check_out,
        },
    }
    payload.update(overrides)
    return payload


def _letter(subject="Attestation letter", **overrides):
    payload = {
        "request_type": "hr_letter",
        "subject": subject,
        "payload": {"purpose": "Bank requirement", "language": "en"},
    }
    payload.update(overrides)
    return payload


def _create(client, auth, payload, expect=201):
    response = client.post(
        "/api/v1/employee-requests", headers=auth["headers"], json=payload
    )
    assert response.status_code == expect, response.text
    return response


def _action(client, auth, request_id, action, payload=None, expect=200):
    response = client.post(
        f"/api/v1/employee-requests/{request_id}/{action}",
        headers=auth["headers"],
        json=payload if payload is not None else {},
    )
    assert response.status_code == expect, response.text
    return response


@pytest.fixture()
def ess_env(client, db_session):
    company_a = seed_company(db_session, "EssSec A")
    company_b = seed_company(db_session, "EssSec B")

    admin_a_user = seed_user(db_session, "admin@essa.co", company_a, "company_admin")
    admin_b_user = seed_user(db_session, "admin@essb.co", company_b, "company_admin")
    seed_user(db_session, "auditor@essa.co", company_a, "auditor")
    seed_user(db_session, "officer@essa.co", company_a, "hr_officer")
    manager_user = seed_user(db_session, "manager@essa.co", company_a, "hr_manager")
    seed_user(db_session, "noperm@essa.co", company_a)
    self_user = seed_user(db_session, "self@essa.co", company_a, "employee")
    self2_user = seed_user(db_session, "self2@essa.co", company_a, "employee")
    self_b_user = seed_user(db_session, "self@essb.co", company_b, "employee")
    roleless_user = seed_user(db_session, "roleless@essa.co", company_a)

    admin_a = login(client, "admin@essa.co")
    headers_a = {**admin_a["headers"], "X-Company-Id": str(company_a.id)}

    # Decision-only custom role: approve + reject, without manage/view.
    role = client.post(
        "/api/v1/roles",
        headers=headers_a,
        json={
            "company_id": company_a.id,
            "code": "ess_decider",
            "name": "ESS Decider",
        },
    )
    assert role.status_code == 201, role.text
    granted = client.put(
        f"/api/v1/roles/{role.json()['id']}/permissions",
        headers=headers_a,
        json={
            "permission_codes": [
                "employee_request.approve",
                "employee_request.reject",
            ]
        },
    )
    assert granted.status_code == 200, granted.text
    decider_user = seed_user(db_session, "decider@essa.co", company_a, "ess_decider")

    admin_b = login(client, "admin@essb.co")
    manager = login(client, "manager@essa.co")
    officer = login(client, "officer@essa.co")
    auditor = login(client, "auditor@essa.co")
    selfauth = login(client, "self@essa.co")
    selfauth2 = login(client, "self2@essa.co")
    self_b = login(client, "self@essb.co")
    decider = login(client, "decider@essa.co")
    roleless = login(client, "roleless@essa.co")
    noperm = login(client, "noperm@essa.co")

    mgr_emp = _create_employee(
        client, admin_a, company_a.id, first_name_en="Mona", last_name_en="Manager"
    )
    emp_a = _create_employee(
        client,
        admin_a,
        company_a.id,
        manager_id=mgr_emp["id"],
        first_name_en="Self",
        last_name_en="Owner",
    )
    emp_other = _create_employee(
        client, admin_a, company_a.id, first_name_en="Other", last_name_en="Colleague"
    )
    decider_emp = _create_employee(
        client,
        admin_a,
        company_a.id,
        first_name_en="Approver",
        last_name_en="Delegate",
    )
    emp_c = _create_employee(
        client,
        admin_a,
        company_a.id,
        manager_id=decider_emp["id"],
        first_name_en="Report",
        last_name_en="C",
    )
    emp_roleless = _create_employee(
        client, admin_a, company_a.id, first_name_en="Bare", last_name_en="Roleless"
    )
    emp_b = _create_employee(
        client, admin_b, company_b.id, first_name_en="SelfB", last_name_en="Tenant"
    )

    _link_user(client, admin_a, emp_a["id"], self_user.id)
    _link_user(client, admin_a, emp_other["id"], self2_user.id)
    _link_user(client, admin_a, mgr_emp["id"], manager_user.id)
    _link_user(client, admin_a, decider_emp["id"], decider_user.id)
    _link_user(client, admin_a, emp_roleless["id"], roleless_user.id)
    _link_user(client, admin_b, emp_b["id"], self_b_user.id)

    contract = client.post(
        f"/api/v1/employees/{emp_a['id']}/contracts",
        headers=headers_a,
        json={
            "company_id": company_a.id,
            "contract_type": "fixed_term",
            "start_date": "2025-01-01",
            "status": "active",
            "contract_number": "C-ESS-1",
            "basic_salary": "12000",
        },
    )
    assert contract.status_code == 201, contract.text

    # Payroll: approved January run (visible) + calculated February (hidden).
    # Every active employee in the company needs an assignment to calculate.
    for emp in (mgr_emp, emp_a, emp_other, decider_emp, emp_c, emp_roleless):
        assignment = client.post(
            "/api/v1/salary-assignments",
            headers=headers_a,
            json={
                "company_id": company_a.id,
                "employee_id": emp["id"],
                "effective_from": "2025-01-01",
                "basic_salary": "9300",
            },
        )
        assert assignment.status_code == 201, assignment.text
    period = client.post(
        "/api/v1/payroll-periods",
        headers=headers_a,
        json={
            "company_id": company_a.id,
            "name": "Jan 2025",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
        },
    )
    assert period.status_code == 201, period.text
    period_id = period.json()["id"]
    run = client.post(
        f"/api/v1/payroll-periods/{period_id}/calculate", headers=headers_a
    )
    assert run.status_code == 200, run.text
    assert run.json()["warnings"] == [], run.text
    reviewed = client.post(
        f"/api/v1/payroll-periods/{period_id}/review", headers=headers_a
    )
    assert reviewed.status_code == 200, reviewed.text
    approved = client.post(
        f"/api/v1/payroll-periods/{period_id}/approve", headers=headers_a
    )
    assert approved.status_code == 200, approved.text
    lines = client.get(
        f"/api/v1/payroll-runs/{run.json()['id']}/lines", headers=headers_a
    )
    assert lines.status_code == 200, lines.text
    # emp_a's own lines (each run holds one line per employee)
    line_visible = next(
        item["id"]
        for item in lines.json()["items"]
        if item["employee_id"] == emp_a["id"]
    )

    period2 = client.post(
        "/api/v1/payroll-periods",
        headers=headers_a,
        json={
            "company_id": company_a.id,
            "name": "Feb 2025",
            "period_start": "2025-02-01",
            "period_end": "2025-02-28",
        },
    )
    assert period2.status_code == 201, period2.text
    run2 = client.post(
        f"/api/v1/payroll-periods/{period2.json()['id']}/calculate",
        headers=headers_a,
    )
    assert run2.status_code == 200, run2.text
    lines2 = client.get(
        f"/api/v1/payroll-runs/{run2.json()['id']}/lines", headers=headers_a
    )
    line_hidden = next(
        item["id"]
        for item in lines2.json()["items"]
        if item["employee_id"] == emp_a["id"]
    )

    types = client.get("/api/v1/employee-document-types", headers=headers_a)
    assert types.status_code == 200, types.text

    return SimpleNamespace(
        company_a=company_a,
        company_b=company_b,
        admin_a=admin_a,
        admin_b=admin_b,
        manager=manager,
        officer=officer,
        auditor=auditor,
        selfauth=selfauth,
        selfauth2=selfauth2,
        self_b=self_b,
        decider=decider,
        roleless=roleless,
        noperm=noperm,
        admin_a_user=admin_a_user,
        admin_b_user=admin_b_user,
        manager_user=manager_user,
        decider_user=decider_user,
        self_user=self_user,
        self_b_user=self_b_user,
        mgr_emp=mgr_emp,
        emp_a=emp_a,
        emp_other=emp_other,
        decider_emp=decider_emp,
        emp_c=emp_c,
        emp_roleless=emp_roleless,
        emp_b=emp_b,
        headers_a=headers_a,
        doc_type_id=types.json()[0]["id"],
        line_visible=line_visible,
        line_hidden=line_hidden,
    )


# ---------------------------------------------------------------------------
# /me self-service scope
# ---------------------------------------------------------------------------


def test_me_profile_is_scoped_to_linked_employee(client, ess_env):
    env = ess_env
    profile = client.get("/api/v1/me/profile", headers=env.selfauth["headers"])
    assert profile.status_code == 200, profile.text
    body = profile.json()
    assert body["id"] == env.emp_a["id"]
    assert body["company_id"] == env.company_a.id
    assert body["manager"]["id"] == env.mgr_emp["id"]
    assert body["contract"]["basic_salary"] == "12000.00"
    assert body["contract"]["currency"] == "SAR"

    other = client.get("/api/v1/me/profile", headers=env.self_b["headers"])
    assert other.status_code == 200, other.text
    assert other.json()["id"] == env.emp_b["id"]
    assert other.json()["company_id"] == env.company_b.id


def test_me_routes_require_permission_and_employee_link(client, ess_env):
    env = ess_env
    # company_admin holds ess.* but has no linked employee -> ESS_NOT_LINKED
    admin_profile = client.get("/api/v1/me/profile", headers=env.admin_a["headers"])
    assert admin_profile.status_code == 403
    assert admin_profile.json()["code"] == "ESS_NOT_LINKED"

    # roleless, unlinked user is rejected at the route gate
    for path in ("/me/profile", "/me/documents", "/me/attendance", "/me/payslips"):
        denied = client.get(f"/api/v1{path}", headers=env.noperm["headers"])
        assert denied.status_code == 403, path
        assert denied.json()["code"] == "forbidden"

    # linked but permission-less user: gate denies before the service runs
    linked = client.get("/api/v1/me/profile", headers=env.roleless["headers"])
    assert linked.status_code == 403
    assert linked.json()["code"] == "forbidden"

    # requests without the create code: ESS_NOT_LINKED beats permission (unlinked)
    unlinked = _create(
        client, env.noperm, _letter(), expect=403
    )
    assert unlinked.json()["code"] == "ESS_NOT_LINKED"
    # no company membership at all: the linked employee is scoped away as
    # not-found (same as cross-company) - never a permission oracle
    no_create = _create(client, env.roleless, _letter(), expect=404)
    assert no_create.json()["code"] == "EMPLOYEE_REQUEST_NOT_FOUND"
    # linked + membership, but the role lacks employee_request.create -> 403
    no_create = _create(client, env.decider, _letter(), expect=403)
    assert no_create.json()["code"] == "forbidden"


def test_employee_role_cannot_reach_hr_routes(client, ess_env):
    env = ess_env
    headers = env.selfauth["headers"]
    assert client.get("/api/v1/employees", headers=headers).status_code == 403
    assert (
        client.get("/api/v1/payroll-periods", headers=headers).status_code == 403
    )
    assert client.get("/api/v1/audit-logs", headers=headers).status_code == 403
    assert client.get("/api/v1/roles", headers=headers).status_code == 403
    assert (
        client.patch(
            "/api/v1/employee-documents/1/visibility",
            headers=headers,
            json={"employee_visible": True},
        ).status_code
        == 403
    )


def test_attendance_self_scope(client, ess_env):
    env = ess_env
    first = client.post(
        "/api/v1/attendance",
        headers=env.admin_a["headers"],
        json={
            "employee_id": env.emp_a["id"],
            "check_in": "2025-06-02T09:00:00",
            "check_out": "2025-06-02T17:00:00",
        },
    )
    assert first.status_code == 201, first.text
    second = client.post(
        "/api/v1/attendance",
        headers=env.admin_a["headers"],
        json={
            "employee_id": env.emp_other["id"],
            "check_in": "2025-06-03T09:00:00",
            "check_out": "2025-06-03T17:00:00",
        },
    )
    assert second.status_code == 201, second.text

    mine = client.get("/api/v1/me/attendance", headers=env.selfauth["headers"])
    assert mine.status_code == 200, mine.text
    items = mine.json()["items"]
    assert [row["employee_id"] for row in items] == [env.emp_a["id"]]
    assert items[0]["work_date"] == "2025-06-02"

    filtered = client.get(
        "/api/v1/me/attendance",
        headers=env.selfauth["headers"],
        params={"date_from": "2025-06-03", "date_to": "2025-06-03"},
    )
    assert filtered.json()["page"]["total"] == 0

    denied = client.get("/api/v1/me/attendance", headers=env.roleless["headers"])
    assert denied.status_code == 403


# ---------------------------------------------------------------------------
# Documents: default-deny sidecar + IDOR
# ---------------------------------------------------------------------------


def test_document_visibility_default_deny_and_toggle(client, ess_env):
    env = ess_env
    doc = _upload_doc(client, env.admin_a, env.emp_a["id"], env.doc_type_id)
    doc_id = doc["id"]

    # default-deny: no visibility row -> employee sees nothing
    page = client.get("/api/v1/me/documents", headers=env.selfauth["headers"])
    assert page.status_code == 200, page.text
    assert page.json()["items"] == []
    assert page.json()["page"]["total"] == 0

    # ...and HR reads the missing sidecar row as "not visible"
    default_read = client.get(
        f"/api/v1/employee-documents/{doc_id}/visibility",
        headers=env.admin_a["headers"],
    )
    assert default_read.status_code == 200, default_read.text
    assert default_read.json() == {
        "document_id": doc_id,
        "employee_visible": False,
        "updated_by": None,
    }

    # employees cannot read the flag either (route gate)
    assert (
        client.get(
            f"/api/v1/employee-documents/{doc_id}/visibility",
            headers=env.selfauth["headers"],
        ).status_code
        == 403
    )

    download = client.get(
        f"/api/v1/me/documents/{doc_id}/download", headers=env.selfauth["headers"]
    )
    assert download.status_code == 403
    assert download.json()["code"] == "ESS_DOCUMENT_NOT_SHARED"

    # the employee cannot flip their own flag
    toggle = client.patch(
        f"/api/v1/employee-documents/{doc_id}/visibility",
        headers=env.selfauth["headers"],
        json={"employee_visible": True},
    )
    assert toggle.status_code == 403

    # HR shares the document
    shared = client.patch(
        f"/api/v1/employee-documents/{doc_id}/visibility",
        headers=env.admin_a["headers"],
        json={"employee_visible": True},
    )
    assert shared.status_code == 200, shared.text
    assert shared.json() == {
        "document_id": doc_id,
        "employee_visible": True,
        "updated_by": env.admin_a_user.id,
    }

    # ...and reads the same state back
    read_back = client.get(
        f"/api/v1/employee-documents/{doc_id}/visibility",
        headers=env.admin_a["headers"],
    )
    assert read_back.status_code == 200
    assert read_back.json() == shared.json()

    page = client.get("/api/v1/me/documents", headers=env.selfauth["headers"])
    assert page.json()["page"]["total"] == 1
    assert page.json()["items"][0]["id"] == doc_id

    download = client.get(
        f"/api/v1/me/documents/{doc_id}/download", headers=env.selfauth["headers"]
    )
    assert download.status_code == 200
    assert download.content == PDF
    assert "attachment" in download.headers["content-disposition"]

    for action in ("document.download", "document.visibility"):
        audit = client.get(
            "/api/v1/audit-logs",
            headers=env.admin_a["headers"],
            params={"action": action},
        )
        assert audit.status_code == 200
        assert any(
            item["entity"] == "employee_document" and item["record_id"] == str(doc_id)
            for item in audit.json()["items"]
        ), action

    # revoking hides the document again
    revoked = client.patch(
        f"/api/v1/employee-documents/{doc_id}/visibility",
        headers=env.admin_a["headers"],
        json={"employee_visible": False},
    )
    assert revoked.status_code == 200
    page = client.get("/api/v1/me/documents", headers=env.selfauth["headers"])
    assert page.json()["page"]["total"] == 0
    download = client.get(
        f"/api/v1/me/documents/{doc_id}/download", headers=env.selfauth["headers"]
    )
    assert download.status_code == 403


def test_document_cross_employee_idor_blocked(client, ess_env):
    env = ess_env
    doc_own = _upload_doc(client, env.admin_a, env.emp_a["id"], env.doc_type_id)
    doc_other = _upload_doc(client, env.admin_a, env.emp_other["id"], env.doc_type_id)
    for doc in (doc_own, doc_other):
        toggled = client.patch(
            f"/api/v1/employee-documents/{doc['id']}/visibility",
            headers=env.admin_a["headers"],
            json={"employee_visible": True},
        )
        assert toggled.status_code == 200, toggled.text

    # each employee sees exactly their own document
    mine = client.get("/api/v1/me/documents", headers=env.selfauth["headers"])
    assert [row["id"] for row in mine.json()["items"]] == [doc_own["id"]]
    theirs = client.get("/api/v1/me/documents", headers=env.selfauth2["headers"])
    assert [row["id"] for row in theirs.json()["items"]] == [doc_other["id"]]

    # ...but downloading the other employee's document is refused
    steal = client.get(
        f"/api/v1/me/documents/{doc_other['id']}/download",
        headers=env.selfauth["headers"],
    )
    assert steal.status_code == 403
    assert steal.json()["code"] == "ESS_DOCUMENT_NOT_SHARED"
    steal_back = client.get(
        f"/api/v1/me/documents/{doc_own['id']}/download",
        headers=env.selfauth2["headers"],
    )
    assert steal_back.status_code == 403

    # cross-company HR cannot touch the flag (404, not 403 - no probing)
    cross = client.patch(
        f"/api/v1/employee-documents/{doc_own['id']}/visibility",
        headers=env.admin_b["headers"],
        json={"employee_visible": False},
    )
    assert cross.status_code == 404
    assert cross.json()["code"] == "DOCUMENT_NOT_FOUND"
    cross_read = client.get(
        f"/api/v1/employee-documents/{doc_own['id']}/visibility",
        headers=env.admin_b["headers"],
    )
    assert cross_read.status_code == 404
    assert cross_read.json()["code"] == "DOCUMENT_NOT_FOUND"


# ---------------------------------------------------------------------------
# Payslips: period gating, own-only, audit
# ---------------------------------------------------------------------------


def test_payslip_period_gating_and_audit(client, ess_env):
    env = ess_env
    page = client.get("/api/v1/me/payslips", headers=env.selfauth["headers"])
    assert page.status_code == 200, page.text
    items = page.json()["items"]
    assert [row["id"] for row in items] == [env.line_visible]
    assert items[0]["period_status"] == "approved"
    assert items[0]["net_pay"] == "9300.00"

    detail = client.get(
        f"/api/v1/me/payslips/{env.line_visible}", headers=env.selfauth["headers"]
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["period_status"] == "approved"
    assert body["net_pay"] == "9300.00"
    assert body["lines"]

    audit = client.get(
        "/api/v1/audit-logs",
        headers=env.admin_a["headers"],
        params={"action": "payslip.view"},
    )
    assert any(
        item["entity"] == "payroll_run_line"
        and item["record_id"] == str(env.line_visible)
        for item in audit.json()["items"]
    )

    # calculated period data never reaches the employee
    hidden = client.get(
        f"/api/v1/me/payslips/{env.line_hidden}", headers=env.selfauth["headers"]
    )
    assert hidden.status_code == 404
    assert hidden.json()["code"] == "not_found"


def test_payslip_idor_blocked(client, ess_env):
    env = ess_env
    # another linked employee-role user cannot read someone else's payslip
    steal = client.get(
        f"/api/v1/me/payslips/{env.line_visible}", headers=env.selfauth2["headers"]
    )
    assert steal.status_code == 403
    assert steal.json()["code"] == "PAYSLIP_NOT_OWN"

    # their list only holds their own payslip - never emp_a's line
    page = client.get("/api/v1/me/payslips", headers=env.selfauth2["headers"])
    assert page.status_code == 200
    ids = [row["id"] for row in page.json()["items"]]
    assert len(ids) == 1
    assert env.line_visible not in ids


# ---------------------------------------------------------------------------
# Request lifecycle: manager snapshot, events, audit, side effects
# ---------------------------------------------------------------------------


def test_request_lifecycle_with_manager_approval_and_audit(client, ess_env):
    env = ess_env
    created = _create(
        client,
        env.selfauth,
        _correction("2025-03-03", "2025-03-03T08:00:00", "2025-03-03T16:00:00"),
    ).json()
    assert created["status"] == "draft"
    assert created["employee_id"] == env.emp_a["id"]
    assert created["work_date"] == "2025-03-03"
    assert created["approver_employee_id"] is None
    # action responses carry the row; the event timeline is a detail read
    assert created["events"] == []

    detail = client.get(
        f"/api/v1/employee-requests/{created['id']}", headers=env.selfauth["headers"]
    )
    assert detail.status_code == 200
    assert [event["event_type"] for event in detail.json()["events"]] == ["created"]

    submitted = _action(client, env.selfauth, created["id"], "submit").json()
    assert submitted["status"] == "submitted"
    assert submitted["approver_employee_id"] == env.mgr_emp["id"]
    assert submitted["submitted_by"] == env.self_user.id
    assert submitted["submitted_at"] is not None

    inbox = client.get("/api/v1/approvals", headers=env.manager["headers"])
    assert inbox.status_code == 200, inbox.text
    assert [row["id"] for row in inbox.json()["items"]] == [created["id"]]

    approved = _action(
        client,
        env.manager,
        created["id"],
        "approve",
        {"reason": "checked against device logs"},
    ).json()
    assert approved["status"] == "approved"
    assert approved["decided_by"] == env.manager_user.id
    assert approved["decision_reason"] == "checked against device logs"
    assert approved["attendance_record_id"] is not None

    detail = client.get(
        f"/api/v1/employee-requests/{created['id']}", headers=env.selfauth["headers"]
    ).json()
    assert [event["event_type"] for event in detail["events"]] == [
        "created",
        "submitted",
        "approved",
    ]

    # the approval materialized a completed manual correction record
    records = client.get(
        "/api/v1/attendance",
        headers=env.admin_a["headers"],
        params={"employee_id": env.emp_a["id"]},
    )
    assert records.status_code == 200
    items = records.json()["items"]
    assert len(items) == 1
    record = items[0]
    assert record["id"] == approved["attendance_record_id"]
    assert record["status"] == "completed"
    assert record["source"] == "manual"
    assert record["work_date"] == "2025-03-03"
    assert record["check_in"].startswith("2025-03-03T08:00")
    assert record["check_out"].startswith("2025-03-03T16:00")
    assert record["correction_reason"]
    assert record["corrected_by"] == env.manager_user.id

    # audited end to end
    audits = client.get(
        "/api/v1/audit-logs",
        headers=env.admin_a["headers"],
        params={"entity": "employee_request"},
    ).json()
    actions = {item["action"] for item in audits["items"]}
    assert actions == {
        "employee_request.create",
        "employee_request.submit",
        "employee_request.approve",
    }
    entry = next(
        item for item in audits["items"] if item["action"] == "employee_request.approve"
    )
    assert json.loads(entry["old_value"])["status"] == "submitted"
    assert json.loads(entry["new_value"])["status"] == "approved"

    attendance_audits = client.get(
        "/api/v1/audit-logs",
        headers=env.admin_a["headers"],
        params={"entity": "attendance_record"},
    ).json()
    assert {item["action"] for item in attendance_audits["items"]} == {
        "attendance.correct"
    }


def test_assigned_approver_and_manage_scoping(client, ess_env):
    env = ess_env

    # two requests: emp_a (approver = manager employee), emp_c (approver =
    # decider employee); both submitted by the HR officer acting for them.
    req_a = _create(
        client, env.officer, _letter("Letter for Self", employee_id=env.emp_a["id"])
    ).json()
    _action(client, env.officer, req_a["id"], "submit")
    req_c = _create(
        client, env.officer, _letter("Letter for Report", employee_id=env.emp_c["id"])
    ).json()
    _action(client, env.officer, req_c["id"], "submit")
    assert req_c["id"] != req_a["id"]

    # hr_officer holds view/create/submit but no decision verb
    officer_approve = _action(
        client, env.officer, req_c["id"], "approve", expect=403
    )
    assert officer_approve.json()["code"] == "EMPLOYEE_REQUEST_FORBIDDEN"

    # decision-only decider: not assigned to req_a -> forbidden
    wrong = _action(client, env.decider, req_a["id"], "approve", expect=403)
    assert wrong.json()["code"] == "EMPLOYEE_REQUEST_FORBIDDEN"
    # ...and cannot read it either
    read = client.get(
        f"/api/v1/employee-requests/{req_a['id']}", headers=env.decider["headers"]
    )
    assert read.status_code == 403
    assert read.json()["code"] == "EMPLOYEE_REQUEST_FORBIDDEN"
    # list without manage/view/create is refused
    listing = client.get("/api/v1/employee-requests", headers=env.decider["headers"])
    assert listing.status_code == 403

    # inbox scoping: decider sees only rows assigned to them
    inbox = client.get("/api/v1/approvals", headers=env.decider["headers"])
    assert inbox.status_code == 200, inbox.text
    assert [row["id"] for row in inbox.json()["items"]] == [req_c["id"]]

    # assigned + verb (no manage) can decide
    approved = _action(client, env.decider, req_c["id"], "approve").json()
    assert approved["status"] == "approved"
    assert approved["decided_by"] == env.decider_user.id

    # manage override decides rows the caller is not assigned to
    forced = _action(client, env.admin_a, req_a["id"], "approve").json()
    assert forced["status"] == "approved"
    assert forced["decided_by"] == env.admin_a_user.id

    # hr_officer inbox entry is gone; manage holder sees everything submitted
    empty = client.get(
        "/api/v1/approvals", headers=env.officer["headers"], params={"status": ""}
    )
    assert empty.status_code == 403


def test_no_manager_falls_back_to_manage_only(client, ess_env):
    env = ess_env
    # emp_other has no manager -> approver snapshot is NULL at submit
    req = _create(
        client,
        env.officer,
        _letter("Letter without manager", employee_id=env.emp_other["id"]),
    ).json()
    submitted = _action(client, env.officer, req["id"], "submit").json()
    assert submitted["approver_employee_id"] is None

    # the decision-only decider is never auto-assigned -> forbidden
    denied = _action(client, env.decider, req["id"], "approve", expect=403)
    assert denied.json()["code"] == "EMPLOYEE_REQUEST_FORBIDDEN"

    # only employee_request.manage can decide an unassigned request
    approved = _action(client, env.admin_a, req["id"], "approve").json()
    assert approved["status"] == "approved"


def test_decision_and_owner_authorization_matrix(client, ess_env):
    env = ess_env
    req = _create(client, env.selfauth, _letter()).json()
    submitted = _action(client, env.selfauth, req["id"], "submit").json()
    assert submitted["status"] == "submitted"

    # the owner can never decide their own request
    self_approve = _action(client, env.selfauth, req["id"], "approve", expect=403)
    assert self_approve.json()["code"] == "EMPLOYEE_REQUEST_FORBIDDEN"
    self_reject = _action(
        client,
        env.selfauth,
        req["id"],
        "reject",
        {"reason": "nope"},
        expect=403,
    )
    assert self_reject.json()["code"] == "EMPLOYEE_REQUEST_FORBIDDEN"

    # auditor holds employee_request.view: reads only
    listing = client.get("/api/v1/employee-requests", headers=env.auditor["headers"])
    assert listing.status_code == 200
    assert [row["id"] for row in listing.json()["items"]] == [req["id"]]
    detail = client.get(
        f"/api/v1/employee-requests/{req['id']}", headers=env.auditor["headers"]
    )
    assert detail.status_code == 200
    auditor_create = _create(client, env.auditor, _letter(), expect=403)
    assert auditor_create.json()["code"] == "ESS_NOT_LINKED"
    auditor_approve = _action(
        client, env.auditor, req["id"], "approve", expect=403
    )
    assert auditor_approve.json()["code"] == "EMPLOYEE_REQUEST_FORBIDDEN"


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


def test_request_state_machine_enforced(client, ess_env):
    env = ess_env
    req = _create(client, env.selfauth, _letter()).json()

    # draft is mutable
    patched = client.patch(
        f"/api/v1/employee-requests/{req['id']}",
        headers=env.selfauth["headers"],
        json={"subject": "Updated subject"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["subject"] == "Updated subject"

    # approving a draft is a state error
    early = _action(client, env.manager, req["id"], "approve", expect=409)
    assert early.json()["code"] == "EMPLOYEE_REQUEST_STATE_INVALID"

    # submit once, never twice
    _action(client, env.selfauth, req["id"], "submit")
    double = _action(client, env.selfauth, req["id"], "submit", expect=409)
    assert double.json()["code"] == "EMPLOYEE_REQUEST_STATE_INVALID"

    # submitted rows are frozen for their owner
    frozen = client.patch(
        f"/api/v1/employee-requests/{req['id']}",
        headers=env.selfauth["headers"],
        json={"subject": "Too late"},
    )
    assert frozen.status_code == 409
    assert frozen.json()["code"] == "EMPLOYEE_REQUEST_STATE_INVALID"

    # submitted can be cancelled by the owner
    cancelled = _action(
        client,
        env.selfauth,
        req["id"],
        "cancel",
        {"reason": "no longer needed"},
    ).json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancel_reason"] == "no longer needed"
    assert cancelled["cancelled_by"] == env.self_user.id

    # cancelled rows are terminal
    again = _action(client, env.selfauth, req["id"], "cancel", expect=409)
    assert again.json()["code"] == "EMPLOYEE_REQUEST_STATE_INVALID"

    # approved rows can never be cancelled
    approved_req = _create(client, env.selfauth, _letter("Second letter")).json()
    _action(client, env.selfauth, approved_req["id"], "submit")
    _action(client, env.manager, approved_req["id"], "approve")
    cancel_approved = _action(
        client, env.selfauth, approved_req["id"], "cancel", expect=409
    )
    assert cancel_approved.json()["code"] == "EMPLOYEE_REQUEST_STATE_INVALID"


def test_reject_requires_reason(client, ess_env):
    env = ess_env
    req = _create(client, env.selfauth, _letter()).json()
    _action(client, env.selfauth, req["id"], "submit")

    missing = _action(client, env.manager, req["id"], "reject", expect=400)
    assert missing.json()["code"] == "EMPLOYEE_REQUEST_DECISION_REASON_REQUIRED"
    blank = _action(
        client, env.manager, req["id"], "reject", {"reason": "   "}, expect=400
    )
    assert blank.json()["code"] == "EMPLOYEE_REQUEST_DECISION_REASON_REQUIRED"

    rejected = _action(
        client,
        env.manager,
        req["id"],
        "reject",
        {"reason": "needs clarification"},
    ).json()
    assert rejected["status"] == "rejected"
    assert rejected["decision_reason"] == "needs clarification"
    assert rejected["decided_by"] == env.manager_user.id
    assert rejected["decided_at"] is not None


# ---------------------------------------------------------------------------
# Closed payload schemas
# ---------------------------------------------------------------------------


def test_payload_validation_closed_schemas(client, ess_env):
    env = ess_env
    headers = env.selfauth["headers"]

    unknown_type = client.post(
        "/api/v1/employee-requests",
        headers=headers,
        json={
            "request_type": "salary_increase",
            "subject": "Raise please",
            "payload": {},
        },
    )
    assert unknown_type.status_code == 400
    assert unknown_type.json()["code"] == "EMPLOYEE_REQUEST_TYPE_UNSUPPORTED"

    unknown_field = client.post(
        "/api/v1/employee-requests",
        headers=headers,
        json={
            "request_type": "hr_letter",
            "subject": "Letter",
            "payload": {"purpose": "x", "extra": "y"},
        },
    )
    assert unknown_field.status_code == 400
    assert unknown_field.json()["code"] == "EMPLOYEE_REQUEST_INVALID_PAYLOAD"

    missing_purpose = client.post(
        "/api/v1/employee-requests",
        headers=headers,
        json={"request_type": "hr_letter", "subject": "Letter", "payload": {}},
    )
    assert missing_purpose.status_code == 400
    assert missing_purpose.json()["code"] == "EMPLOYEE_REQUEST_INVALID_PAYLOAD"

    bad_language = client.post(
        "/api/v1/employee-requests",
        headers=headers,
        json={
            "request_type": "hr_letter",
            "subject": "Letter",
            "payload": {"purpose": "x", "language": "fr"},
        },
    )
    assert bad_language.status_code == 400
    assert bad_language.json()["code"] == "EMPLOYEE_REQUEST_INVALID_PAYLOAD"

    blank_subject = client.post(
        "/api/v1/employee-requests",
        headers=headers,
        json={"request_type": "other", "subject": "   ", "payload": {}},
    )
    assert blank_subject.status_code == 400
    assert blank_subject.json()["code"] == "EMPLOYEE_REQUEST_INVALID_PAYLOAD"

    missing_check_in = client.post(
        "/api/v1/employee-requests",
        headers=headers,
        json={
            "request_type": "attendance_correction",
            "subject": "Correction",
            "payload": {"work_date": "2025-03-10", "check_out": "2025-03-10T16:00:00"},
        },
    )
    assert missing_check_in.status_code == 400
    assert missing_check_in.json()["code"] == "ATTENDANCE_CORRECTION_INVALID"

    inverted = client.post(
        "/api/v1/employee-requests",
        headers=headers,
        json={
            "request_type": "attendance_correction",
            "subject": "Correction",
            "payload": {
                "work_date": "2025-03-10",
                "check_in": "2025-03-10T16:00:00",
                "check_out": "2025-03-10T08:00:00",
            },
        },
    )
    assert inverted.status_code == 400
    assert inverted.json()["code"] == "ATTENDANCE_CORRECTION_INVALID"

    bad_date = client.post(
        "/api/v1/employee-requests",
        headers=headers,
        json={
            "request_type": "attendance_correction",
            "subject": "Correction",
            "payload": {
                "work_date": "not-a-date",
                "check_in": "2025-03-10T08:00:00",
                "check_out": "2025-03-10T16:00:00",
            },
        },
    )
    assert bad_date.status_code == 400
    assert bad_date.json()["code"] == "ATTENDANCE_CORRECTION_INVALID"

    unknown_correction_field = client.post(
        "/api/v1/employee-requests",
        headers=headers,
        json={
            "request_type": "attendance_correction",
            "subject": "Correction",
            "payload": {
                "work_date": "2025-03-10",
                "check_in": "2025-03-10T08:00:00",
                "check_out": "2025-03-10T16:00:00",
                "extra": True,
            },
        },
    )
    assert unknown_correction_field.status_code == 400
    assert unknown_correction_field.json()["code"] == "EMPLOYEE_REQUEST_INVALID_PAYLOAD"


# ---------------------------------------------------------------------------
# Cross-employee / cross-company boundaries
# ---------------------------------------------------------------------------


def test_cross_employee_create_requires_view_marker(client, ess_env):
    env = ess_env
    # the employee role owns only itself - no acting for colleagues
    forbidden = _create(
        client,
        env.selfauth,
        _letter("Letter for colleague", employee_id=env.emp_other["id"]),
        expect=403,
    )
    assert forbidden.json()["code"] == "forbidden"

    # ...while they may always create for themselves
    own = _create(client, env.selfauth, _letter("My own letter")).json()

    # hr_officer holds employee_request.view -> may act for others
    acted = _create(
        client,
        env.officer,
        _letter("Letter for colleague", employee_id=env.emp_other["id"]),
    ).json()
    _action(client, env.officer, acted["id"], "submit")

    # the employee's list is forced to their own rows
    mine = client.get("/api/v1/employee-requests", headers=env.selfauth["headers"])
    assert mine.status_code == 200
    assert {row["employee_id"] for row in mine.json()["items"]} == {
        env.emp_a["id"]
    }
    assert {row["id"] for row in mine.json()["items"]} == {own["id"]}

    # asking for another employee's rows is refused
    cross = client.get(
        "/api/v1/employee-requests",
        headers=env.selfauth["headers"],
        params={"employee_id": env.emp_other["id"]},
    )
    assert cross.status_code == 403
    assert cross.json()["code"] == "forbidden"

    # reading the colleague's request is refused (no view, not owner)
    read = client.get(
        f"/api/v1/employee-requests/{acted['id']}", headers=env.selfauth["headers"]
    )
    assert read.status_code == 403
    assert read.json()["code"] == "EMPLOYEE_REQUEST_FORBIDDEN"
    # ...while the view holder can read it
    officer_read = client.get(
        f"/api/v1/employee-requests/{acted['id']}", headers=env.officer["headers"]
    )
    assert officer_read.status_code == 200

    # employees from another company are invisible (404, not 403)
    other_company = _create(
        client,
        env.officer,
        _letter("Letter across tenants", employee_id=env.emp_b["id"]),
        expect=404,
    )
    assert other_company.json()["code"] == "EMPLOYEE_REQUEST_NOT_FOUND"


def test_cross_company_boundaries(client, ess_env):
    env = ess_env
    req_a = _create(client, env.selfauth, _letter()).json()
    _action(client, env.selfauth, req_a["id"], "submit")

    # company B admin cannot read company A rows
    read = client.get(
        f"/api/v1/employee-requests/{req_a['id']}", headers=env.admin_b["headers"]
    )
    assert read.status_code == 404
    assert read.json()["code"] == "EMPLOYEE_REQUEST_NOT_FOUND"

    # scoping a list/inbox to a foreign company is refused
    scoped = client.get(
        "/api/v1/employee-requests",
        headers=env.admin_b["headers"],
        params={"company_id": env.company_a.id},
    )
    assert scoped.status_code == 403
    inbox_scoped = client.get(
        "/api/v1/approvals",
        headers=env.admin_b["headers"],
        params={"company_id": env.company_a.id},
    )
    assert inbox_scoped.status_code == 403

    # company B's own inbox never shows company A rows
    req_b = _create(client, env.self_b, _letter("B letter")).json()
    _action(client, env.self_b, req_b["id"], "submit")
    inbox_b = client.get("/api/v1/approvals", headers=env.admin_b["headers"])
    assert inbox_b.status_code == 200, inbox_b.text
    assert [row["id"] for row in inbox_b.json()["items"]] == [req_b["id"]]

    # company A's inbox never shows company B rows
    inbox_a = client.get("/api/v1/approvals", headers=env.admin_a["headers"])
    assert [row["id"] for row in inbox_a.json()["items"]] == [req_a["id"]]

    # company B's employee list contains only their own requests
    list_b = client.get("/api/v1/employee-requests", headers=env.self_b["headers"])
    assert {row["id"] for row in list_b.json()["items"]} == {req_b["id"]}


def test_inbox_status_filter_and_permission_gate(client, ess_env):
    env = ess_env
    draft = _create(client, env.selfauth, _letter("Draft letter")).json()
    submitted = _create(client, env.selfauth, _letter("Submitted letter")).json()
    _action(client, env.selfauth, submitted["id"], "submit")
    decided = _create(client, env.selfauth, _letter("Approved letter")).json()
    _action(client, env.selfauth, decided["id"], "submit")
    _action(client, env.manager, decided["id"], "approve")

    # default inbox status is submitted
    inbox = client.get("/api/v1/approvals", headers=env.manager["headers"])
    assert [row["id"] for row in inbox.json()["items"]] == [submitted["id"]]

    # status="" selects every status (documented inbox convention)
    everything = client.get(
        "/api/v1/approvals", headers=env.manager["headers"], params={"status": ""}
    )
    assert everything.status_code == 200, everything.text
    assert {row["id"] for row in everything.json()["items"]} == {
        draft["id"],
        submitted["id"],
        decided["id"],
    }

    approved_only = client.get(
        "/api/v1/approvals",
        headers=env.manager["headers"],
        params={"status": "approved"},
    )
    assert [row["id"] for row in approved_only.json()["items"]] == [decided["id"]]

    # invalid status values are rejected by the route pattern
    invalid = client.get(
        "/api/v1/approvals", headers=env.manager["headers"], params={"status": "wat"}
    )
    assert invalid.status_code == 422

    # no decision permission at all -> 403
    employee = client.get("/api/v1/approvals", headers=env.selfauth["headers"])
    assert employee.status_code == 403
    assert employee.json()["code"] == "forbidden"


# ---------------------------------------------------------------------------
# Attendance-correction guards
# ---------------------------------------------------------------------------


def test_duplicate_open_correction_blocked(client, ess_env):
    env = ess_env
    payload = _correction(
        "2025-04-07", "2025-04-07T08:00:00", "2025-04-07T16:00:00"
    )
    first = _create(client, env.selfauth, payload).json()

    duplicate = _create(client, env.selfauth, payload, expect=409)
    assert duplicate.json()["code"] == "EMPLOYEE_REQUEST_STATE_INVALID"
    assert "already open" in duplicate.json()["detail"]

    submitted = _action(client, env.selfauth, first["id"], "submit").json()
    assert submitted["status"] == "submitted"
    still_blocked = _create(client, env.selfauth, payload, expect=409)
    assert still_blocked.json()["code"] == "EMPLOYEE_REQUEST_STATE_INVALID"

    # cancelling frees the date again
    _action(client, env.selfauth, first["id"], "cancel", {"reason": "changed mind"})
    third = _create(client, env.selfauth, payload)
    assert third.json()["status"] == "draft"

    # a decided correction does not block a later one
    _action(client, env.selfauth, third.json()["id"], "submit")
    _action(client, env.manager, third.json()["id"], "approve")
    fourth = _create(client, env.selfauth, payload)
    assert fourth.json()["status"] == "draft"


def test_correction_stale_record_blocks_approval(client, ess_env):
    env = ess_env
    record = client.post(
        "/api/v1/attendance",
        headers=env.admin_a["headers"],
        json={
            "employee_id": env.emp_a["id"],
            "check_in": "2025-05-05T09:00:00",
            "check_out": "2025-05-05T17:00:00",
        },
    )
    assert record.status_code == 201, record.text
    record_id = record.json()["id"]

    req = _create(
        client,
        env.selfauth,
        _correction("2025-05-05", "2025-05-05T08:00:00", "2025-05-05T16:00:00"),
    ).json()
    _action(client, env.selfauth, req["id"], "submit")

    # HR edits the record after submit -> the request must be redone
    patched = client.patch(
        f"/api/v1/attendance/{record_id}",
        headers=env.admin_a["headers"],
        json={"check_out": "2025-05-05T17:30:00", "reason": "device sync"},
    )
    assert patched.status_code == 200, patched.text

    stale = _action(client, env.manager, req["id"], "approve", expect=409)
    assert stale.json()["code"] == "ATTENDANCE_CORRECTION_STALE"

    # the request stays submitted with no produced record
    detail = client.get(
        f"/api/v1/employee-requests/{req['id']}", headers=env.selfauth["headers"]
    ).json()
    assert detail["status"] == "submitted"
    assert detail["attendance_record_id"] is None

    # the stale-blocked approval was rejected outright: no approve audit and
    # no extra attendance record beyond the HR-patched original
    req_audits = client.get(
        "/api/v1/audit-logs",
        headers=env.admin_a["headers"],
        params={"entity": "employee_request"},
    ).json()
    assert "employee_request.approve" not in {
        item["action"] for item in req_audits["items"]
    }
    records = client.get(
        "/api/v1/attendance",
        headers=env.admin_a["headers"],
        params={"employee_id": env.emp_a["id"]},
    ).json()
    assert len(records["items"]) == 1
    assert records["items"][0]["id"] == record_id


def test_correction_overlap_blocks_approval(client, ess_env):
    env = ess_env
    overnight = client.post(
        "/api/v1/attendance",
        headers=env.admin_a["headers"],
        json={
            "employee_id": env.emp_a["id"],
            "check_in": "2025-05-12T22:00:00",
            "check_out": "2025-05-13T06:00:00",
        },
    )
    assert overnight.status_code == 201, overnight.text

    req = _create(
        client,
        env.selfauth,
        _correction("2025-05-13", "2025-05-13T05:00:00", "2025-05-13T09:00:00"),
    ).json()
    _action(client, env.selfauth, req["id"], "submit")

    overlap = _action(client, env.manager, req["id"], "approve", expect=409)
    assert overlap.json()["code"] == "ATTENDANCE_OVERLAP"

    detail = client.get(
        f"/api/v1/employee-requests/{req['id']}", headers=env.selfauth["headers"]
    ).json()
    assert detail["status"] == "submitted"
    assert detail["attendance_record_id"] is None


def test_correction_multiple_records_blocked(client, ess_env, db_session):
    env = ess_env
    first = client.post(
        "/api/v1/attendance",
        headers=env.admin_a["headers"],
        json={
            "employee_id": env.emp_a["id"],
            "check_in": "2025-05-19T09:00:00",
            "check_out": "2025-05-19T17:00:00",
        },
    )
    assert first.status_code == 201, first.text

    # a second row for the same date (e.g. imported later) blocks the flow
    elevate_for_seed(db_session)
    db_session.add(
        AttendanceRecord(
            company_id=env.company_a.id,
            employee_id=env.emp_a["id"],
            work_date=date(2025, 5, 19),
            check_in=datetime(2025, 5, 19, 18, 0),
            check_out=datetime(2025, 5, 19, 19, 0),
            status="completed",
            source="import",
            created_by=env.admin_a_user.id,
        )
    )
    db_session.commit()
    clear_context(db_session)

    req = _create(
        client,
        env.selfauth,
        _correction("2025-05-19", "2025-05-19T08:00:00", "2025-05-19T16:00:00"),
    ).json()
    _action(client, env.selfauth, req["id"], "submit")

    blocked = _action(client, env.manager, req["id"], "approve", expect=400)
    assert blocked.json()["code"] == "ATTENDANCE_CORRECTION_INVALID"
    assert "Multiple attendance records" in blocked.json()["detail"]


def test_correction_record_mismatch_blocks_approval(client, ess_env, db_session):
    env = ess_env
    req = _create(
        client,
        env.selfauth,
        _correction("2025-06-16", "2025-06-16T08:00:00", "2025-06-16T16:00:00"),
    ).json()
    _action(client, env.selfauth, req["id"], "submit")

    # tamper: the payload work_date diverges from the record column
    elevate_for_seed(db_session)
    row = db_session.get(EmployeeRequest, req["id"])
    row.payload = {**row.payload, "work_date": "2025-06-17"}
    db_session.commit()
    clear_context(db_session)

    mismatch = _action(client, env.manager, req["id"], "approve", expect=400)
    assert mismatch.json()["code"] == "EMPLOYEE_REQUEST_RECORD_MISMATCH"

    detail = client.get(
        f"/api/v1/employee-requests/{req['id']}", headers=env.selfauth["headers"]
    ).json()
    assert detail["status"] == "submitted"
    assert detail["attendance_record_id"] is None


def test_hr_letter_approval_has_no_attendance_side_effect(client, ess_env):
    env = ess_env
    req = _create(client, env.selfauth, _letter()).json()
    _action(client, env.selfauth, req["id"], "submit")
    approved = _action(
        client, env.manager, req["id"], "approve", {"reason": "issued"}
    ).json()
    assert approved["status"] == "approved"
    assert approved["attendance_record_id"] is None

    records = client.get(
        "/api/v1/attendance",
        headers=env.admin_a["headers"],
        params={"employee_id": env.emp_a["id"]},
    )
    assert records.json()["page"]["total"] == 0

    audits = client.get(
        "/api/v1/audit-logs",
        headers=env.admin_a["headers"],
        params={"entity": "attendance_record"},
    ).json()
    assert audits["items"] == []
