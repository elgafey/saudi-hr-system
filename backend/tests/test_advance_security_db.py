from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.core.rls import clear_context, elevate_for_seed
from app.shared.models import Employee
from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


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


def _advance(client, auth, payload=None, expect=201):
    body = {
        "amount": "2500.00",
        "reason": "Security probe",
        "requested_date": date.today().isoformat(),
    }
    body.update(payload or {})
    response = client.post(
        "/api/v1/salary-advances", headers=auth["headers"], json=body
    )
    assert response.status_code == expect, response.text
    return response


def _action(client, auth, advance_id, action, payload=None, expect=200):
    response = client.post(
        f"/api/v1/salary-advances/{advance_id}/{action}",
        headers=auth["headers"],
        json=payload if payload is not None else {},
    )
    assert response.status_code == expect, response.text
    return response


@pytest.fixture()
def adv_env(client, db_session):
    company_a = seed_company(db_session, "AdvSec A")
    company_b = seed_company(db_session, "AdvSec B")

    admin_user = seed_user(db_session, "admin@advsec-a.co", company_a, "company_admin")
    seed_user(db_session, "admin@advsec-b.co", company_b, "company_admin")
    manager_user = seed_user(
        db_session, "manager@advsec-a.co", company_a, "hr_manager"
    )
    officer_user = seed_user(db_session, "officer@advsec-a.co", company_a, "hr_officer")
    auditor_user = seed_user(db_session, "auditor@advsec-a.co", company_a, "auditor")
    self_user = seed_user(db_session, "self@advsec-a.co", company_a, "employee")
    self2_user = seed_user(db_session, "self2@advsec-a.co", company_a, "employee")
    self_b_user = seed_user(db_session, "self@advsec-b.co", company_b, "employee")
    noperm_user = seed_user(db_session, "noperm@advsec-a.co", company_a)
    roleless_user = seed_user(db_session, "roleless@advsec-a.co", company_a)

    admin = login(client, "admin@advsec-a.co")
    headers_a = {**admin["headers"], "X-Company-Id": str(company_a.id)}

    # Decision-only custom role: approve + reject, without manage/view.
    role = client.post(
        "/api/v1/roles",
        headers=headers_a,
        json={
            "company_id": company_a.id,
            "code": "advance_decider",
            "name": "Advance Decider",
        },
    )
    assert role.status_code == 201, role.text
    granted = client.put(
        f"/api/v1/roles/{role.json()['id']}/permissions",
        headers=headers_a,
        json={
            "permission_codes": [
                "salary_advance.approve",
                "salary_advance.reject",
            ]
        },
    )
    assert granted.status_code == 200, granted.text
    decider_user = seed_user(
        db_session, "decider@advsec-a.co", company_a, "advance_decider"
    )

    admin_b = login(client, "admin@advsec-b.co")
    manager = login(client, "manager@advsec-a.co")
    officer = login(client, "officer@advsec-a.co")
    auditor = login(client, "auditor@advsec-a.co")
    selfauth = login(client, "self@advsec-a.co")
    self2auth = login(client, "self2@advsec-a.co")
    self_b = login(client, "self@advsec-b.co")
    decider = login(client, "decider@advsec-a.co")
    noperm = login(client, "noperm@advsec-a.co")
    roleless = login(client, "roleless@advsec-a.co")

    mgr_emp = _create_employee(
        client, admin, company_a.id, first_name_en="Mona", last_name_en="Manager"
    )
    emp_a = _create_employee(
        client,
        admin,
        company_a.id,
        manager_id=mgr_emp["id"],
        first_name_en="Self",
        last_name_en="Owner",
    )
    emp_other = _create_employee(
        client, admin, company_a.id, first_name_en="Other", last_name_en="Colleague"
    )
    decider_emp = _create_employee(
        client, admin, company_a.id, first_name_en="Approver", last_name_en="Delegate"
    )
    emp_report = _create_employee(
        client,
        admin,
        company_a.id,
        manager_id=decider_emp["id"],
        first_name_en="Report",
        last_name_en="R",
    )
    emp_roleless = _create_employee(
        client, admin, company_a.id, first_name_en="Bare", last_name_en="Roleless"
    )
    emp_b = _create_employee(
        client, admin_b, company_b.id, first_name_en="Tenant", last_name_en="B"
    )

    _link_user(client, admin, emp_a["id"], self_user.id)
    _link_user(client, admin, emp_other["id"], self2_user.id)
    _link_user(client, admin, mgr_emp["id"], manager_user.id)
    _link_user(client, admin, decider_emp["id"], decider_user.id)
    _link_user(client, admin, emp_roleless["id"], roleless_user.id)
    _link_user(client, admin_b, emp_b["id"], self_b_user.id)

    return SimpleNamespace(
        company_a=company_a,
        company_b=company_b,
        headers_a=headers_a,
        admin=admin,
        admin_b=admin_b,
        manager=manager,
        officer=officer,
        auditor=auditor,
        selfauth=selfauth,
        self2auth=self2auth,
        self_b=self_b,
        decider=decider,
        noperm=noperm,
        roleless=roleless,
        admin_user=admin_user,
        manager_user=manager_user,
        officer_user=officer_user,
        auditor_user=auditor_user,
        self_user=self_user,
        self2_user=self2_user,
        self_b_user=self_b_user,
        noperm_user=noperm_user,
        roleless_user=roleless_user,
        decider_user=decider_user,
        mgr_emp=mgr_emp,
        emp_a=emp_a,
        emp_other=emp_other,
        decider_emp=decider_emp,
        emp_report=emp_report,
        emp_roleless=emp_roleless,
        emp_b=emp_b,
    )


def _submitted_for_manager(client, env, auth=None):
    row = _advance(client, auth or env.selfauth).json()
    _action(client, auth or env.selfauth, row["id"], "submit")
    return row


def test_decision_permission_matrix(client, adv_env):
    env = adv_env
    row_mgr = _submitted_for_manager(client, env)
    row_dec = _advance(
        client,
        env.admin,
        {"reason": "delegate report", "employee_id": env.emp_report["id"]},
    ).json()
    _action(client, env.admin, row_dec["id"], "submit")

    # No decision permission: state is valid, authorization fails.
    for auth, label in (
        (env.officer, "officer"),
        (env.auditor, "auditor"),
        (env.selfauth, "owner"),
    ):
        denied = _action(
            client, auth, row_mgr["id"], "approve", expect=403
        )
        assert denied.json()["code"] == "SALARY_ADVANCE_FORBIDDEN", label

    # Without any role there is no company membership: scoped fetch 404s.
    roleless = _action(client, env.roleless, row_mgr["id"], "approve", expect=404)
    assert roleless.json()["code"] == "SALARY_ADVANCE_NOT_FOUND"

    # Decide-only holders cannot touch an assignment that is not theirs.
    wrong = _action(client, env.decider, row_mgr["id"], "approve", expect=403)
    assert wrong.json()["code"] == "SALARY_ADVANCE_FORBIDDEN"

    # ...but approve their own assignment, and the manager approves theirs.
    assigned = _action(client, env.decider, row_dec["id"], "approve").json()
    assert assigned["status"] == "approved"
    managed = _action(client, env.manager, row_mgr["id"], "approve").json()
    assert managed["status"] == "approved"


def test_finance_separation_of_duties(client, adv_env):
    env = adv_env
    row = _submitted_for_manager(client, env)
    _action(client, env.manager, row["id"], "approve")

    # Deciding and paying are separate grants: nobody without the money
    # verbs can move funds, regardless of their other permissions.
    for auth, label in (
        (env.selfauth, "owner"),
        (env.auditor, "auditor"),
        (env.decider, "decider"),
    ):
        denied = _action(client, auth, row["id"], "disburse", expect=403)
        assert denied.json()["code"] == "forbidden", label

    disbursed = _action(client, env.officer, row["id"], "disburse").json()
    assert disbursed["status"] == "disbursed"

    for auth, label in (
        (env.selfauth, "owner"),
        (env.auditor, "auditor"),
        (env.decider, "decider"),
    ):
        denied = _action(client, auth, row["id"], "settle", expect=403)
        assert denied.json()["code"] == "forbidden", label


def test_cross_employee_idor_is_blocked(client, adv_env):
    env = adv_env
    other_draft = _advance(client, env.self2auth, {"reason": "not yours"}).json()

    cross = client.get(
        f"/api/v1/salary-advances/{other_draft['id']}",
        headers=env.selfauth["headers"],
    )
    assert cross.status_code == 403
    assert cross.json()["code"] == "SALARY_ADVANCE_FORBIDDEN"

    patched = client.patch(
        f"/api/v1/salary-advances/{other_draft['id']}",
        headers=env.selfauth["headers"],
        json={"amount": "9999.00"},
    )
    assert patched.status_code == 403

    submitted = _action(
        client, env.selfauth, other_draft["id"], "submit", expect=403
    )
    assert submitted.json()["code"] == "forbidden"
    cancelled = _action(
        client, env.selfauth, other_draft["id"], "cancel", expect=403
    )
    assert cancelled.json()["code"] == "forbidden"

    # A decide-only holder without the view grant cannot read arbitrary rows.
    peek = client.get(
        f"/api/v1/salary-advances/{other_draft['id']}",
        headers=env.decider["headers"],
    )
    assert peek.status_code == 403
    assert peek.json()["code"] == "SALARY_ADVANCE_FORBIDDEN"


def test_cross_company_is_404(client, adv_env):
    env = adv_env
    foreign = _advance(client, env.self_b).json()
    _action(client, env.self_b, foreign["id"], "submit")

    read = client.get(
        f"/api/v1/salary-advances/{foreign['id']}", headers=env.admin["headers"]
    )
    assert read.status_code == 404
    assert read.json()["code"] == "SALARY_ADVANCE_NOT_FOUND"

    approved = _action(
        client, env.admin, foreign["id"], "approve", expect=404
    )
    assert approved.json()["code"] == "SALARY_ADVANCE_NOT_FOUND"
    disbursed = _action(client, env.admin, foreign["id"], "disburse", expect=404)
    assert disbursed.json()["code"] == "SALARY_ADVANCE_NOT_FOUND"

    scoped = client.get(
        "/api/v1/salary-advances",
        headers=env.admin["headers"],
        params={"company_id": env.company_b.id},
    )
    assert scoped.status_code == 403


def test_state_machine_conflicts(client, adv_env):
    env = adv_env
    draft = _advance(client, env.selfauth).json()

    _action(client, env.manager, draft["id"], "approve", expect=409)
    _action(client, env.manager, draft["id"], "reject", expect=409)
    _action(client, env.officer, draft["id"], "disburse", expect=409)
    _action(client, env.officer, draft["id"], "settle", expect=409)

    _action(client, env.selfauth, draft["id"], "submit")
    again = _action(client, env.selfauth, draft["id"], "submit", expect=409)
    assert again.json()["code"] == "SALARY_ADVANCE_STATE_INVALID"
    patched = client.patch(
        f"/api/v1/salary-advances/{draft['id']}",
        headers=env.selfauth["headers"],
        json={"amount": "100.00"},
    )
    assert patched.status_code == 409

    approved = _advance(client, env.self2auth).json()
    _action(client, env.self2auth, approved["id"], "submit")
    _action(client, env.manager, approved["id"], "approve")
    cancel_approved = _action(
        client, env.self2auth, approved["id"], "cancel", expect=409
    )
    assert cancel_approved.json()["code"] == "SALARY_ADVANCE_STATE_INVALID"
    _action(client, env.manager, approved["id"], "approve", expect=409)
    _action(client, env.manager, approved["id"], "reject", expect=409)

    decided = _advance(client, env.self2auth, {"reason": "second row"}).json()
    _action(client, env.self2auth, decided["id"], "submit")
    _action(client, env.manager, decided["id"], "reject", {"reason": "no"})
    _action(client, env.self2auth, decided["id"], "submit", expect=409)
    _action(client, env.self2auth, decided["id"], "cancel", expect=409)

    cancelled = _advance(client, env.selfauth, {"reason": "third row"}).json()
    _action(client, env.selfauth, cancelled["id"], "cancel")
    _action(client, env.selfauth, cancelled["id"], "submit", expect=409)
    _action(client, env.selfauth, cancelled["id"], "approve", expect=409)


def test_reason_and_amount_validation(client, adv_env):
    env = adv_env

    blank_reason = _advance(client, env.selfauth, {"reason": "   "}, expect=400)
    assert blank_reason.json()["code"] == "SALARY_ADVANCE_REASON_REQUIRED"

    zero = _advance(client, env.selfauth, {"amount": "0"}, expect=422)
    assert zero.status_code == 422
    negative = _advance(client, env.selfauth, {"amount": "-100.00"}, expect=422)
    assert negative.status_code == 422

    row = _advance(client, env.selfauth, {"amount": "1000.00"}).json()
    blank_update = client.patch(
        f"/api/v1/salary-advances/{row['id']}",
        headers=env.selfauth["headers"],
        json={"reason": "  "},
    )
    assert blank_update.status_code == 400
    assert blank_update.json()["code"] == "SALARY_ADVANCE_REASON_REQUIRED"

    _action(client, env.selfauth, row["id"], "submit")
    no_reason = _action(client, env.manager, row["id"], "reject", expect=400)
    assert no_reason.json()["code"] == "SALARY_ADVANCE_REASON_REQUIRED"
    ws_reason = _action(
        client, env.manager, row["id"], "reject", {"reason": "   "}, expect=400
    )
    assert ws_reason.json()["code"] == "SALARY_ADVANCE_REASON_REQUIRED"

    approved = _action(
        client, env.manager, row["id"], "approve"
    ).json()
    assert approved["status"] == "approved"
    over = _action(
        client,
        env.officer,
        row["id"],
        "disburse",
        {"installment_amount": "1000.01"},
        expect=400,
    )
    assert over.json()["code"] == "SALARY_ADVANCE_INSTALLMENT_INVALID"
    under = _action(
        client,
        env.officer,
        row["id"],
        "disburse",
        {"installment_amount": "0"},
        expect=422,
    )
    assert under.status_code == 422


def test_missing_linked_rule_is_defended(client, db_session, adv_env):
    env = adv_env
    row = _advance(client, env.selfauth, {"amount": "1200.00"}).json()
    _action(client, env.selfauth, row["id"], "submit")
    _action(client, env.manager, row["id"], "approve")
    disbursed = _action(client, env.officer, row["id"], "disburse").json()
    rule_id = disbursed["deduction_rule_id"]
    assert rule_id is not None

    # The disbursed row must never lose its repayment rule: the DB CHECK
    # rejects the FK's SET NULL cascade outright.
    elevate_for_seed(db_session)
    with pytest.raises(Exception) as excinfo:
        db_session.execute(
            text("DELETE FROM payroll_deduction_rules WHERE id = :id"),
            {"id": rule_id},
        )
        db_session.flush()
    assert "ck_salary_advance_disbursed_rule" in str(excinfo.value)
    db_session.rollback()
    clear_context(db_session)

    # The rule is still there, so the early settlement path stays usable.
    settled = _action(
        client,
        env.officer,
        row["id"],
        "settle",
        {"reason": "paid off"},
    ).json()
    assert settled["status"] == "settled"


def test_routes_require_authentication(client, adv_env):
    assert client.get("/api/v1/salary-advances").status_code == 401
    assert (
        client.post(
            "/api/v1/salary-advances",
            json={"amount": "1", "reason": "x", "requested_date": "2026-01-01"},
        ).status_code
        == 401
    )
    assert client.post("/api/v1/salary-advances/1/submit").status_code == 401
    assert client.get("/api/v1/salary-advances/1").status_code == 401


def test_unlinked_and_permissionless_clients(client, adv_env):
    env = adv_env
    unlinked = _advance(client, env.noperm, expect=403)
    assert unlinked.json()["code"] == "ESS_NOT_LINKED"

    no_list = client.get("/api/v1/salary-advances", headers=env.noperm["headers"])
    assert no_list.status_code == 403
    assert no_list.json()["code"] == "forbidden"

    # A role-less user has no company membership, so the scoped employee
    # fetch never even reaches the permission check (Phase 5 precedent).
    roleless_create = _advance(client, env.roleless, expect=404)
    assert roleless_create.json()["code"] == "SALARY_ADVANCE_NOT_FOUND"
    roleless_list = client.get(
        "/api/v1/salary-advances", headers=env.roleless["headers"]
    )
    assert roleless_list.status_code == 403
    roleless_inbox = client.get(
        "/api/v1/salary-advances",
        headers=env.roleless["headers"],
        params={"assigned_to_me": "true"},
    )
    assert roleless_inbox.status_code == 403


def test_inactive_employee_cannot_submit(client, db_session, adv_env):
    env = adv_env
    row = _advance(client, env.selfauth, {"reason": "before suspension"}).json()

    elevate_for_seed(db_session)
    db_session.expire_all()
    employee = db_session.get(Employee, env.emp_a["id"])
    employee.status = "inactive"
    db_session.commit()
    clear_context(db_session)

    denied = _action(client, env.selfauth, row["id"], "submit", expect=403)
    assert denied.json()["code"] == "forbidden"
