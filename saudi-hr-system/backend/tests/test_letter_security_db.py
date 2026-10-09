"""Phase 9 HR letter security: auth, RBAC, tenant isolation, ESS redaction."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db

HR_ROUTES = [
    ("GET", "/api/v1/hr-letters"),
    ("POST", "/api/v1/hr-letters"),
    ("GET", "/api/v1/hr-letters/1"),
    ("PATCH", "/api/v1/hr-letters/1"),
    ("POST", "/api/v1/hr-letters/1/issue"),
    ("POST", "/api/v1/hr-letters/1/cancel"),
    ("POST", "/api/v1/hr-letters/1/void"),
    ("GET", "/api/v1/me/letters"),
    ("GET", "/api/v1/me/letters/1"),
]


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "سالم",
        "last_name_ar": "الرويلي",
        "first_name_en": "Salem",
        "last_name_en": "Alruwaili",
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


@pytest.fixture()
def sec_env(client, db_session):
    company_a = seed_company(db_session, "Sec Letter A")
    company_b = seed_company(db_session, "Sec Letter B")

    admin_user = seed_user(db_session, "admin@secla.co", company_a, "company_admin")
    manager_user = seed_user(db_session, "manager@secla.co", company_a, "hr_manager")
    officer_user = seed_user(db_session, "officer@secla.co", company_a, "hr_officer")
    auditor_user = seed_user(db_session, "auditor@secla.co", company_a, "auditor")
    self_user = seed_user(db_session, "self@secla.co", company_a, "employee")
    other_user = seed_user(db_session, "other@secla.co", company_a, "employee")
    admin_b_user = seed_user(db_session, "admin@secbl.co", company_b, "company_admin")
    self_b_user = seed_user(db_session, "self@secbl.co", company_b, "employee")

    admin = login(client, "admin@secla.co")
    manager = login(client, "manager@secla.co")
    officer = login(client, "officer@secla.co")
    auditor = login(client, "auditor@secla.co")
    selfauth = login(client, "self@secla.co")
    otherauth = login(client, "other@secla.co")
    admin_b = login(client, "admin@secbl.co")
    self_b = login(client, "self@secbl.co")

    emp = _create_employee(client, admin, company_a.id)
    other_emp = _create_employee(client, admin, company_a.id)
    emp_b = _create_employee(client, admin_b, company_b.id)
    _link_user(client, admin, emp["id"], self_user.id)
    _link_user(client, admin, other_emp["id"], other_user.id)
    _link_user(client, admin_b, emp_b["id"], self_b_user.id)

    return SimpleNamespace(
        client=client,
        db=db_session,
        company_a=company_a,
        company_b=company_b,
        admin=admin,
        manager=manager,
        officer=officer,
        auditor=auditor,
        selfauth=selfauth,
        otherauth=otherauth,
        admin_b=admin_b,
        self_b=self_b,
        admin_user=admin_user,
        manager_user=manager_user,
        officer_user=officer_user,
        auditor_user=auditor_user,
        self_user=self_user,
        other_user=other_user,
        admin_b_user=admin_b_user,
        self_b_user=self_b_user,
        emp=emp,
        other_emp=other_emp,
        emp_b=emp_b,
    )


def _create(env, payload=None, expect=201, auth=None):
    body = {"employee_id": env.emp["id"], "letter_type": "employment", "language": "en"}
    body.update(payload or {})
    response = env.client.post(
        "/api/v1/hr-letters",
        headers=(auth or env.admin)["headers"],
        json=body,
    )
    assert response.status_code == expect, response.text
    return response


def _action(env, letter_id, action, payload=None, expect=200, auth=None):
    response = env.client.post(
        f"/api/v1/hr-letters/{letter_id}/{action}",
        headers=(auth or env.admin)["headers"],
        json=payload if payload is not None else {},
    )
    assert response.status_code == expect, response.text
    return response


@pytest.mark.parametrize("method,route", HR_ROUTES)
def test_all_letter_routes_require_authentication(sec_env, method, route):
    env = sec_env
    if method == "GET":
        response = env.client.get(route)
    elif method == "PATCH":
        response = env.client.patch(route, json={})
    else:
        response = env.client.post(route, json={})
    assert response.status_code == 401, response.text


def test_officer_cannot_void_issued_letters(sec_env):
    env = sec_env
    issued = _create(env).json()
    _action(env, issued["id"], "issue")

    denied = _action(
        env, issued["id"], "void", {"reason": "officer tries"}, expect=403,
        auth=env.officer,
    )
    assert denied.json()["code"] == "HR_LETTER_FORBIDDEN"

    allowed = _action(
        env, issued["id"], "void", {"reason": "manager approves"}, auth=env.manager
    ).json()
    assert allowed["status"] == "void"


def test_officer_can_create_and_issue_but_auditor_cannot_edit(sec_env):
    env = sec_env
    draft = _create(env, auth=env.officer).json()
    assert draft["status"] == "draft"
    _action(env, draft["id"], "issue", auth=env.officer)

    # The manager (hr_letter.update) may edit drafts in the workflow.
    editable = _create(env).json()
    managed = env.client.patch(
        f"/api/v1/hr-letters/{editable['id']}",
        headers=env.manager["headers"],
        json={"purpose": "manager edit"},
    )
    assert managed.status_code == 200, managed.text
    assert managed.json()["purpose"] == "manager edit"

    blocked_update = env.client.patch(
        f"/api/v1/hr-letters/{editable['id']}",
        headers=env.auditor["headers"],
        json={"purpose": "auditor edit"},
    )
    assert blocked_update.status_code == 403
    assert blocked_update.json()["code"] == "HR_LETTER_FORBIDDEN"


def test_auditor_is_read_only(sec_env):
    env = sec_env
    draft = _create(env).json()
    issued = _create(env).json()
    _action(env, issued["id"], "issue")

    # Reads are allowed.
    page = env.client.get("/api/v1/hr-letters", headers=env.auditor["headers"])
    assert page.status_code == 200, page.text
    detail = env.client.get(
        f"/api/v1/hr-letters/{draft['id']}", headers=env.auditor["headers"]
    )
    assert detail.status_code == 200, detail.text

    # Every write verb is denied while the state check still passes.
    create = env.client.post(
        "/api/v1/hr-letters",
        headers=env.auditor["headers"],
        json={"employee_id": env.emp["id"], "letter_type": "employment"},
    )
    assert create.status_code == 403, create.text
    assert create.json()["code"] == "HR_LETTER_FORBIDDEN"

    update = env.client.patch(
        f"/api/v1/hr-letters/{draft['id']}",
        headers=env.auditor["headers"],
        json={"purpose": "audit edit"},
    )
    assert update.status_code == 403, update.text

    issue = env.client.post(
        f"/api/v1/hr-letters/{draft['id']}/issue",
        headers=env.auditor["headers"],
        json={},
    )
    assert issue.status_code == 403, issue.text
    assert issue.json()["code"] == "HR_LETTER_FORBIDDEN"

    cancel = env.client.post(
        f"/api/v1/hr-letters/{draft['id']}/cancel",
        headers=env.auditor["headers"],
        json={"reason": "audit"},
    )
    assert cancel.status_code == 403, cancel.text

    void = env.client.post(
        f"/api/v1/hr-letters/{issued['id']}/void",
        headers=env.auditor["headers"],
        json={"reason": "audit"},
    )
    assert void.status_code == 403, void.text
    assert void.json()["code"] == "HR_LETTER_FORBIDDEN"


def test_plain_employee_cannot_use_hr_routes(sec_env):
    env = sec_env
    letter = _create(env).json()
    issued = _create(env).json()
    _action(env, issued["id"], "issue")

    listed = env.client.get("/api/v1/hr-letters", headers=env.selfauth["headers"])
    assert listed.status_code == 403
    create = env.client.post(
        "/api/v1/hr-letters",
        headers=env.selfauth["headers"],
        json={"employee_id": env.emp["id"], "letter_type": "employment"},
    )
    assert create.status_code == 403

    # Detail reads reach the state/permission checks only for existing,
    # company-accessible rows - so the letter must exist first.
    read = env.client.get(
        f"/api/v1/hr-letters/{letter['id']}", headers=env.selfauth["headers"]
    )
    assert read.status_code == 403
    assert read.json()["code"] == "HR_LETTER_FORBIDDEN"

    update = env.client.patch(
        f"/api/v1/hr-letters/{letter['id']}",
        headers=env.selfauth["headers"],
        json={"purpose": "self edit"},
    )
    assert update.status_code == 403

    issue = env.client.post(
        f"/api/v1/hr-letters/{letter['id']}/issue",
        headers=env.selfauth["headers"],
        json={},
    )
    assert issue.status_code == 403

    # State checks still precede permission checks (Phase 8 pattern): a
    # void attempt on a DRAFT is 409, so the permission probe needs an
    # issued letter.
    void_on_draft = env.client.post(
        f"/api/v1/hr-letters/{letter['id']}/void",
        headers=env.selfauth["headers"],
        json={"reason": "self void"},
    )
    assert void_on_draft.status_code == 409
    assert void_on_draft.json()["code"] == "HR_LETTER_STATE_INVALID"

    void = env.client.post(
        f"/api/v1/hr-letters/{issued['id']}/void",
        headers=env.selfauth["headers"],
        json={"reason": "self void"},
    )
    assert void.status_code == 403
    assert void.json()["code"] == "HR_LETTER_FORBIDDEN"


def test_ess_portal_is_scoped_to_own_letters(sec_env):
    env = sec_env
    mine = _create(env).json()
    _action(env, mine["id"], "issue")

    # A second letter for a different employee in the same company.
    other_letter = _create(env, {"employee_id": env.other_emp["id"]}).json()

    page = env.client.get("/api/v1/me/letters", headers=env.selfauth["headers"])
    assert page.status_code == 200, page.text
    ids = {item["id"] for item in page.json()["items"]}
    assert mine["id"] in ids
    assert other_letter["id"] not in ids

    own = env.client.get(
        f"/api/v1/me/letters/{mine['id']}", headers=env.selfauth["headers"]
    )
    assert own.status_code == 200, own.text

    foreign = env.client.get(
        f"/api/v1/me/letters/{other_letter['id']}", headers=env.selfauth["headers"]
    )
    assert foreign.status_code == 404
    assert foreign.json()["code"] == "HR_LETTER_NOT_FOUND"

    missing = env.client.get("/api/v1/me/letters/999999", headers=env.selfauth["headers"])
    assert missing.status_code == 404


def test_ess_void_fields_and_notes_are_redacted(sec_env):
    env = sec_env
    issued = _create(env).json()
    _action(env, issued["id"], "issue")
    _action(env, issued["id"], "void", {"reason": "internal mistake"})

    hr = env.client.get(
        f"/api/v1/hr-letters/{issued['id']}", headers=env.admin["headers"]
    ).json()
    assert hr["void_reason"] == "internal mistake"
    void_events = [e for e in hr["events"] if e["action"] == "voided"]
    assert void_events and void_events[0]["note"] == "internal mistake"

    ess = env.client.get(
        f"/api/v1/me/letters/{issued['id']}", headers=env.selfauth["headers"]
    ).json()
    assert ess["void_reason"] is None
    ess_void_events = [e for e in ess["events"] if e["action"] == "voided"]
    assert ess_void_events and ess_void_events[0]["note"] is None
    # Non-void history stays visible to the employee.
    assert [e["action"] for e in ess["events"]] == ["created", "issued", "voided"]


def test_cross_company_letters_are_invisible(sec_env):
    env = sec_env
    letter_a = _create(env).json()

    # Admin B cannot read A's letter (404 - no existence leak).
    read_b = env.client.get(
        f"/api/v1/hr-letters/{letter_a['id']}", headers=env.admin_b["headers"]
    )
    assert read_b.status_code == 404
    assert read_b.json()["code"] == "HR_LETTER_NOT_FOUND"

    update_b = env.client.patch(
        f"/api/v1/hr-letters/{letter_a['id']}",
        headers=env.admin_b["headers"],
        json={"purpose": "cross tenant edit"},
    )
    assert update_b.status_code == 404

    issue_b = env.client.post(
        f"/api/v1/hr-letters/{letter_a['id']}/issue",
        headers=env.admin_b["headers"],
        json={},
    )
    assert issue_b.status_code == 404

    # Admin B cannot create a letter for A's employee.
    create_b = env.client.post(
        "/api/v1/hr-letters",
        headers=env.admin_b["headers"],
        json={"employee_id": env.emp["id"], "letter_type": "employment"},
    )
    assert create_b.status_code == 400
    assert create_b.json()["code"] == "HR_LETTER_EMPLOYEE_INVALID"

    # Admin A cannot force B's company into the list filter.
    scoped = env.client.get(
        f"/api/v1/hr-letters?company_id={env.company_b.id}",
        headers=env.admin["headers"],
    )
    assert scoped.status_code == 403

    # Admin B's list only ever contains B's rows.
    page_b = env.client.get("/api/v1/hr-letters", headers=env.admin_b["headers"])
    assert page_b.status_code == 200
    letter_b = _create(
        env, {"employee_id": env.emp_b["id"]}, auth=env.admin_b
    ).json()
    page_b = env.client.get("/api/v1/hr-letters", headers=env.admin_b["headers"])
    companies = {item["company_id"] for item in page_b.json()["items"]}
    assert companies == {env.company_b.id}
    assert letter_a["id"] not in {item["id"] for item in page_b.json()["items"]}
    assert letter_b["id"] in {item["id"] for item in page_b.json()["items"]}

    # Admin B's ESS-side employee sees only B letters.
    page_ess_b = env.client.get("/api/v1/me/letters", headers=env.self_b["headers"])
    assert page_ess_b.status_code == 200
    assert letter_a["id"] not in {i["id"] for i in page_ess_b.json()["items"]}


def test_employee_user_of_company_b_cannot_read_company_a_letter(sec_env):
    env = sec_env
    letter_a = _create(env).json()
    denied = env.client.get(
        f"/api/v1/me/letters/{letter_a['id']}", headers=env.self_b["headers"]
    )
    assert denied.status_code == 404


def test_list_responses_never_leak_content(sec_env):
    env = sec_env
    created = _create(env).json()
    page = env.client.get("/api/v1/hr-letters", headers=env.admin["headers"])
    assert page.status_code == 200
    raw = page.text
    # The list projection must never carry the content snapshot or the
    # reasons - and the detail payload of one letter is not embedded either.
    assert "content" not in page.json()["items"][0]
    assert "employee_name" not in raw
    assert "void_reason" not in raw
    assert "cancel_reason" not in raw
    assert created["id"] in {item["id"] for item in page.json()["items"]}
