from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.audit.model import AuditLog
from app.core.rls import clear_context, elevate_for_seed
from app.shared.models import Employee, PayrollDeductionRule
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
        "reason": "School fees",
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


def _run_payroll(client, headers, period_id, expect=200):
    run = client.post(
        f"/api/v1/payroll-periods/{period_id}/calculate", headers=headers
    )
    assert run.status_code == expect, run.text
    reviewed = client.post(
        f"/api/v1/payroll-periods/{period_id}/review", headers=headers
    )
    assert reviewed.status_code == expect, reviewed.text
    approved = client.post(
        f"/api/v1/payroll-periods/{period_id}/approve", headers=headers
    )
    assert approved.status_code == expect, approved.text
    return run.json()


def _month_window(center: date) -> tuple[date, date]:
    first = center.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    return first, nxt - timedelta(days=1)


@pytest.fixture()
def adv_env(client, db_session):
    company_a = seed_company(db_session, "Advance Co A")
    company_b = seed_company(db_session, "Advance Co B")

    admin_user = seed_user(db_session, "admin@adva.co", company_a, "company_admin")
    seed_user(db_session, "admin@advb.co", company_b, "company_admin")
    manager_user = seed_user(db_session, "manager@adva.co", company_a, "hr_manager")
    officer_user = seed_user(db_session, "officer@adva.co", company_a, "hr_officer")
    auditor_user = seed_user(db_session, "auditor@adva.co", company_a, "auditor")
    self_user = seed_user(db_session, "self@adva.co", company_a, "employee")
    self2_user = seed_user(db_session, "self2@adva.co", company_a, "employee")
    self_b_user = seed_user(db_session, "self@advb.co", company_b, "employee")

    admin = login(client, "admin@adva.co")
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
        db_session, "decider@adva.co", company_a, "advance_decider"
    )

    admin_b = login(client, "admin@advb.co")
    manager = login(client, "manager@adva.co")
    officer = login(client, "officer@adva.co")
    auditor = login(client, "auditor@adva.co")
    selfauth = login(client, "self@adva.co")
    self2auth = login(client, "self2@adva.co")
    self_b = login(client, "self@advb.co")
    decider = login(client, "decider@adva.co")

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
    emp_b = _create_employee(
        client, admin_b, company_b.id, first_name_en="Tenant", last_name_en="B"
    )

    _link_user(client, admin, emp_a["id"], self_user.id)
    _link_user(client, admin, emp_other["id"], self2_user.id)
    _link_user(client, admin, mgr_emp["id"], manager_user.id)
    _link_user(client, admin, decider_emp["id"], decider_user.id)
    _link_user(client, admin_b, emp_b["id"], self_b_user.id)

    # Payroll environment: every active employee in company A needs an
    # assignment, and one period must cover the disbursement date.
    for emp in (mgr_emp, emp_a, emp_other, decider_emp, emp_report):
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

    start, end = _month_window(date.today())
    period = client.post(
        "/api/v1/payroll-periods",
        headers=headers_a,
        json={
            "company_id": company_a.id,
            "name": f"Advance {start.strftime('%b %Y')}",
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
        },
    )
    assert period.status_code == 201, period.text

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
        admin_user=admin_user,
        manager_user=manager_user,
        officer_user=officer_user,
        auditor_user=auditor_user,
        self_user=self_user,
        self2_user=self2_user,
        self_b_user=self_b_user,
        decider_user=decider_user,
        mgr_emp=mgr_emp,
        emp_a=emp_a,
        emp_other=emp_other,
        decider_emp=decider_emp,
        emp_report=emp_report,
        emp_b=emp_b,
        period_id=period.json()["id"],
    )


def _rule(db_session, rule_id) -> PayrollDeductionRule:
    elevate_for_seed(db_session)
    rule = db_session.get(PayrollDeductionRule, rule_id)
    assert rule is not None, rule_id
    db_session.refresh(rule)
    clear_context(db_session)
    return rule


def _advance_actions(db_session, advance_id) -> set[str]:
    elevate_for_seed(db_session)
    actions = set(
        db_session.execute(
            select(AuditLog.action).where(
                AuditLog.entity == "salary_advance",
                AuditLog.record_id == str(advance_id),
            )
        ).scalars()
    )
    clear_context(db_session)
    return actions


def test_full_lifecycle_repayment_and_auto_settle(client, db_session, adv_env):
    env = adv_env
    created = _advance(
        client, env.selfauth, {"amount": "2500.00", "reason": "School fees"}
    ).json()
    assert created["status"] == "draft"
    assert created["employee_id"] == env.emp_a["id"]
    assert created["approver_employee_id"] is None
    created_detail = client.get(
        f"/api/v1/salary-advances/{created['id']}", headers=env.selfauth["headers"]
    ).json()
    assert [e["event_type"] for e in created_detail["events"]] == ["created"]

    updated = client.patch(
        f"/api/v1/salary-advances/{created['id']}",
        headers=env.selfauth["headers"],
        json={"reason": "Tuition fees"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["reason"] == "Tuition fees"
    assert updated.json()["status"] == "draft"

    submitted = _action(client, env.selfauth, created["id"], "submit").json()
    assert submitted["status"] == "submitted"
    assert submitted["approver_employee_id"] == env.mgr_emp["id"]
    assert submitted["submitted_by"] == env.self_user.id
    assert submitted["submitted_at"] is not None

    inbox = client.get(
        "/api/v1/salary-advances",
        headers=env.manager["headers"],
        params={"assigned_to_me": "true", "status": "submitted"},
    )
    assert inbox.status_code == 200, inbox.text
    assert created["id"] in [item["id"] for item in inbox.json()["items"]]

    approved = _action(
        client, env.manager, created["id"], "approve", {"reason": "checked budget"}
    ).json()
    assert approved["status"] == "approved"
    assert approved["decided_by"] == env.manager_user.id
    assert approved["decision_reason"] == "checked budget"
    assert approved["decided_at"] is not None

    # HR (money role, not the decider) disburses with the default full
    # amount: a single drawdown settles the advance in one payroll run.
    disbursed = _action(client, env.officer, created["id"], "disburse").json()
    assert disbursed["status"] == "disbursed"
    assert disbursed["disbursed_by"] == env.officer_user.id
    assert Decimal(str(disbursed["installment_amount"])) == Decimal("2500.00")
    rule_id = disbursed["deduction_rule_id"]
    assert rule_id is not None

    rule = _rule(db_session, rule_id)
    assert rule.company_id == env.company_a.id
    assert rule.employee_id == env.emp_a["id"]
    assert rule.status == "active"
    assert rule.amount == Decimal("2500.00")
    assert rule.total_amount == Decimal("2500.00")
    assert rule.remaining_amount == Decimal("2500.00")

    # Frozen payroll machinery: calculate picks the rule up, approve
    # consumes exactly one installment and completes it.
    _run_payroll(client, env.headers_a, env.period_id)
    rule = _rule(db_session, rule_id)
    assert rule.status == "completed"
    assert rule.remaining_amount == Decimal("0.00")

    # Read-path reconcile auto-settles the advance (system event,
    # NULL-actor audit).
    detail = client.get(
        f"/api/v1/salary-advances/{created['id']}", headers=env.selfauth["headers"]
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["status"] == "settled"
    assert body["settled_by"] is None
    assert body["settle_note"] == "auto: deduction rule completed"
    assert body["settled_at"] is not None
    types = [e["event_type"] for e in body["events"]]
    assert types == [
        "created",
        "submitted",
        "approved",
        "disbursed",
        "settled",
    ]
    assert body["events"][-1]["actor_name"] == "system"

    actions = _advance_actions(db_session, created["id"])
    assert {
        "salary_advance.create",
        "salary_advance.update",
        "salary_advance.submit",
        "salary_advance.approve",
        "salary_advance.disburse",
        "salary_advance.settle",
    } <= actions

    elevate_for_seed(db_session)
    settle_actor = db_session.execute(
        select(AuditLog.actor_user_id).where(
            AuditLog.action == "salary_advance.settle",
            AuditLog.entity == "salary_advance",
            AuditLog.record_id == str(created["id"]),
        )
    ).scalar_one()
    rule_create = db_session.execute(
        select(AuditLog.id).where(
            AuditLog.action == "payroll_deduction.create",
            AuditLog.record_id == str(rule_id),
        )
    ).scalar_one_or_none()
    clear_context(db_session)
    assert settle_actor is None, "auto-settle must be a system audit entry"
    assert rule_create is not None, "frozen deduction create must be audited"


def test_partial_repayment_keeps_advance_disbursed(client, db_session, adv_env):
    env = adv_env
    created = _advance(
        client, env.selfauth, {"amount": "3000.00", "reason": "Home repair"}
    ).json()
    _action(client, env.selfauth, created["id"], "submit")
    _action(client, env.manager, created["id"], "approve")
    disbursed = _action(
        client,
        env.officer,
        created["id"],
        "disburse",
        {"installment_amount": "1000.00"},
    ).json()
    rule_id = disbursed["deduction_rule_id"]

    _run_payroll(client, env.headers_a, env.period_id)
    rule = _rule(db_session, rule_id)
    assert rule.status == "active"
    assert rule.remaining_amount == Decimal("2000.00")

    detail = client.get(
        f"/api/v1/salary-advances/{created['id']}", headers=env.selfauth["headers"]
    )
    assert detail.status_code == 200
    assert detail.json()["status"] == "disbursed"
    assert detail.json()["settled_at"] is None

    # The next period keeps collecting the remainder.
    start, end = _month_window(date.today() + timedelta(days=40))
    period2 = client.post(
        "/api/v1/payroll-periods",
        headers=env.headers_a,
        json={
            "company_id": env.company_a.id,
            "name": f"Advance {start.strftime('%b %Y')}",
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
        },
    )
    assert period2.status_code == 201, period2.text
    _run_payroll(client, env.headers_a, period2.json()["id"])

    rule = _rule(db_session, rule_id)
    assert rule.status == "active"
    assert rule.remaining_amount == Decimal("1000.00")
    detail = client.get(
        f"/api/v1/salary-advances/{created['id']}", headers=env.selfauth["headers"]
    )
    assert detail.json()["status"] == "disbursed"


def test_reject_flow_writes_reason_and_no_rule(client, adv_env):
    env = adv_env
    created = _advance(
        client, env.selfauth, {"amount": "1500.00", "reason": "Car repair"}
    ).json()
    _action(client, env.selfauth, created["id"], "submit")

    rejected = _action(
        client,
        env.manager,
        created["id"],
        "reject",
        {"reason": "insufficient budget"},
    ).json()
    assert rejected["status"] == "rejected"
    assert rejected["decision_reason"] == "insufficient budget"
    assert rejected["decided_by"] == env.manager_user.id
    assert rejected["deduction_rule_id"] is None

    detail = client.get(
        f"/api/v1/salary-advances/{created['id']}", headers=env.selfauth["headers"]
    ).json()
    assert [e["event_type"] for e in detail["events"]] == [
        "created",
        "submitted",
        "rejected",
    ]
    assert detail["events"][-1]["note"] == "insufficient budget"


def test_cancel_flow_draft_and_submitted(client, db_session, adv_env):
    env = adv_env
    draft = _advance(client, env.selfauth, {"reason": "abandoned plan"}).json()
    cancelled = _action(
        client, env.selfauth, draft["id"], "cancel", {"reason": "no longer needed"}
    ).json()
    assert cancelled["status"] == "cancelled"
    draft_detail = client.get(
        f"/api/v1/salary-advances/{draft['id']}", headers=env.selfauth["headers"]
    ).json()
    assert [e["event_type"] for e in draft_detail["events"]] == [
        "created",
        "cancelled",
    ]
    assert draft_detail["events"][-1]["note"] == "no longer needed"

    submitted = _advance(client, env.self2auth, {"reason": "second thoughts"}).json()
    _action(client, env.self2auth, submitted["id"], "submit")
    cancelled2 = _action(
        client,
        env.self2auth,
        submitted["id"],
        "cancel",
        {"reason": "changed my mind"},
    ).json()
    assert cancelled2["status"] == "cancelled"
    assert cancelled2["approver_employee_id"] is None  # no manager snapshot
    submitted_detail = client.get(
        f"/api/v1/salary-advances/{submitted['id']}",
        headers=env.self2auth["headers"],
    ).json()
    assert [e["event_type"] for e in submitted_detail["events"]] == [
        "created",
        "submitted",
        "cancelled",
    ]

    elevate_for_seed(db_session)
    new_value = db_session.execute(
        select(AuditLog.new_value).where(
            AuditLog.action == "salary_advance.cancel",
            AuditLog.record_id == str(submitted["id"]),
        )
    ).scalar_one()
    clear_context(db_session)
    assert json.loads(new_value)["cancel_reason"] == "changed my mind"


def test_early_settle_cancels_the_active_rule(client, db_session, adv_env):
    env = adv_env
    created = _advance(
        client, env.selfauth, {"amount": "3000.00", "reason": "Emergency"}
    ).json()
    _action(client, env.selfauth, created["id"], "submit")
    _action(client, env.manager, created["id"], "approve")
    disbursed = _action(
        client,
        env.officer,
        created["id"],
        "disburse",
        {"installment_amount": "1000.00", "note": "first drawdown"},
    ).json()
    rule_id = disbursed["deduction_rule_id"]
    assert _rule(db_session, rule_id).status == "active"

    early = _action(client, env.officer, created["id"], "settle", {}, expect=400)
    assert early.json()["code"] == "SALARY_ADVANCE_REASON_REQUIRED"

    settled = _action(
        client,
        env.officer,
        created["id"],
        "settle",
        {"reason": "employee repaid early"},
    ).json()
    assert settled["status"] == "settled"
    assert settled["settled_by"] == env.officer_user.id
    assert settled["settle_note"] == "employee repaid early"
    rule = _rule(db_session, rule_id)
    assert rule.status == "cancelled"
    detail = client.get(
        f"/api/v1/salary-advances/{created['id']}", headers=env.selfauth["headers"]
    ).json()
    assert [e["event_type"] for e in detail["events"]] == [
        "created",
        "submitted",
        "approved",
        "disbursed",
        "settled",
    ]


def test_self_scope_listing_and_viewer_reads(client, adv_env):
    env = adv_env
    own = _advance(client, env.selfauth, {"reason": "mine"}).json()
    other = _advance(client, env.self2auth, {"reason": "theirs"}).json()

    mine = client.get("/api/v1/salary-advances", headers=env.selfauth["headers"])
    assert mine.status_code == 200
    assert [item["id"] for item in mine.json()["items"]] == [own["id"]]

    cross = client.get(
        f"/api/v1/salary-advances/{other['id']}", headers=env.selfauth["headers"]
    )
    assert cross.status_code == 403
    assert cross.json()["code"] == "SALARY_ADVANCE_FORBIDDEN"

    filtered = client.get(
        "/api/v1/salary-advances",
        headers=env.selfauth["headers"],
        params={"employee_id": env.emp_other["id"]},
    )
    assert filtered.status_code == 403

    for auth in (env.admin, env.auditor, env.officer):
        page = client.get("/api/v1/salary-advances", headers=auth["headers"])
        assert page.status_code == 200, page.text
        ids = {item["id"] for item in page.json()["items"]}
        assert {own["id"], other["id"]} <= ids

    detail = client.get(
        f"/api/v1/salary-advances/{own['id']}", headers=env.selfauth["headers"]
    ).json()
    assert detail["events"][0]["event_type"] == "created"
    assert detail["events"][0]["actor_name"]
    assert detail["events"][0]["created_at"] is not None


def test_list_filters_and_decision_inbox(client, adv_env):
    env = adv_env
    draft = _advance(client, env.selfauth, {"reason": "stays draft"}).json()
    submitted_other = _advance(
        client, env.self2auth, {"reason": "no manager report"}
    ).json()
    _action(client, env.self2auth, submitted_other["id"], "submit")
    submitted = _advance(client, env.selfauth, {"reason": "manager report"}).json()
    _action(client, env.selfauth, submitted["id"], "submit")

    drafts = client.get(
        "/api/v1/salary-advances",
        headers=env.admin["headers"],
        params={"status": "draft", "page_size": 1},
    )
    assert drafts.status_code == 200
    assert drafts.json()["page"]["total"] == 1
    assert drafts.json()["items"][0]["id"] == draft["id"]

    # Manage holders see their companies' submitted rows (both reports).
    manager_inbox = client.get(
        "/api/v1/salary-advances",
        headers=env.manager["headers"],
        params={"assigned_to_me": "true", "status": "submitted"},
    )
    assert manager_inbox.status_code == 200
    assert {item["id"] for item in manager_inbox.json()["items"]} == {
        submitted_other["id"],
        submitted["id"],
    }

    # Decide-only holder sees exactly their own assignment (the report
    # whose approver snapshot is their employee).
    decider_inbox = client.get(
        "/api/v1/salary-advances",
        headers=env.decider["headers"],
        params={"assigned_to_me": "true", "status": "submitted"},
    )
    assert decider_inbox.status_code == 200
    assert [item["id"] for item in decider_inbox.json()["items"]] == []

    report = _advance(
        client,
        env.admin,
        {"reason": "delegate report", "employee_id": env.emp_report["id"]},
    ).json()
    _action(client, env.admin, report["id"], "submit")
    decider_inbox = client.get(
        "/api/v1/salary-advances",
        headers=env.decider["headers"],
        params={"assigned_to_me": "true", "status": "submitted"},
    )
    assert [item["id"] for item in decider_inbox.json()["items"]] == [report["id"]]

    # No decision permission at all: the inbox itself is denied.
    denied = client.get(
        "/api/v1/salary-advances",
        headers=env.selfauth["headers"],
        params={"assigned_to_me": "true"},
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "forbidden"

    wrong_company = client.get(
        "/api/v1/salary-advances",
        headers=env.admin_b["headers"],
        params={"company_id": env.company_a.id},
    )
    assert wrong_company.status_code == 403


def test_create_for_other_employee_markers(client, adv_env):
    env = adv_env
    by_admin = _advance(
        client,
        env.admin,
        {"reason": "admin filed", "employee_id": env.emp_other["id"]},
    ).json()
    assert by_admin["employee_id"] == env.emp_other["id"]
    assert by_admin["company_id"] == env.company_a.id

    by_officer = _advance(
        client,
        env.officer,
        {"reason": "officer filed", "employee_id": env.emp_a["id"]},
    ).json()
    assert by_officer["employee_id"] == env.emp_a["id"]

    cross = _advance(
        client,
        env.self2auth,
        {"reason": "acting for a colleague", "employee_id": env.emp_a["id"]},
        expect=403,
    )
    assert cross.json()["code"] == "forbidden"

    cross_company = _advance(
        client,
        env.admin,
        {"reason": "other tenant", "employee_id": env.emp_b["id"]},
        expect=404,
    )
    assert cross_company.json()["code"] == "SALARY_ADVANCE_NOT_FOUND"


def test_inactive_employee_cannot_receive_advances(client, db_session, adv_env):
    env = adv_env
    elevate_for_seed(db_session)
    db_session.expire_all()
    employee = db_session.get(Employee, env.emp_other["id"])
    employee.status = "inactive"
    db_session.commit()
    clear_context(db_session)

    denied = _advance(
        client,
        env.admin,
        {"reason": "inactive target", "employee_id": env.emp_other["id"]},
        expect=403,
    )
    assert denied.json()["code"] == "forbidden"
