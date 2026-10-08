from __future__ import annotations

import threading
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.advance.schemas import (
    AdvanceCreate,
    AdvanceDecision,
    AdvanceDisburse,
    AdvanceSettle,
)
from app.advance.service import (
    approve_advance,
    create_advance,
    disburse_advance,
    reject_advance,
    settle_advance,
    submit_advance,
)
from app.core.deps import Principal, _load_company_ids, _load_permissions
from app.core.exceptions import SalaryAdvanceStateError
from app.core.rls import clear_context, elevate_for_seed, set_context
from app.shared.models import (
    PayrollDeductionRule,
    SalaryAdvance,
    SalaryAdvanceEvent,
    User,
)
from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "فهد",
        "last_name_ar": "الحربي",
        "first_name_en": "Fahad",
        "last_name_en": "Alharbi",
        "status": "active",
        **overrides,
    }
    response = client.post("/api/v1/employees", headers=auth["headers"], json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def race_env(client, db_session):
    company = seed_company(db_session, "Race Advance")
    admin_user = seed_user(db_session, "admin@raceadv.co", company, "company_admin")
    manager_user = seed_user(db_session, "manager@raceadv.co", company, "hr_manager")
    officer_user = seed_user(db_session, "officer@raceadv.co", company, "hr_officer")
    worker_user = seed_user(db_session, "worker@raceadv.co", company, "employee")

    admin = login(client, "admin@raceadv.co")
    manager = login(client, "manager@raceadv.co")
    officer = login(client, "officer@raceadv.co")
    worker = login(client, "worker@raceadv.co")

    mgr_emp = _create_employee(client, admin, company.id)
    emp = _create_employee(client, admin, company.id, manager_id=mgr_emp["id"])
    assert (
        client.post(
            f"/api/v1/employees/{emp['id']}/user",
            headers=admin["headers"],
            json={"user_id": worker_user.id},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/employees/{mgr_emp['id']}/user",
            headers=admin["headers"],
            json={"user_id": manager_user.id},
        ).status_code
        == 200
    )

    def create_one(**overrides):
        body = {
            "amount": "2000.00",
            "reason": "Race advance",
            "requested_date": "2026-10-01",
        }
        body.update(overrides)
        response = client.post(
            "/api/v1/salary-advances", headers=worker["headers"], json=body
        )
        assert response.status_code == 201, response.text
        return response.json()

    # draft for the double-submit race
    draft = create_one(reason="Race submit draft")

    # submitted for the double-approve / approve-vs-reject races
    submitted = create_one(reason="Race approve")
    transition = client.post(
        f"/api/v1/salary-advances/{submitted['id']}/submit",
        headers=worker["headers"],
    )
    assert transition.status_code == 200, transition.text

    # approved for the double-disburse race
    approved = create_one(reason="Race disburse")
    assert (
        client.post(
            f"/api/v1/salary-advances/{approved['id']}/submit",
            headers=worker["headers"],
        ).status_code
        == 200
    )
    decision = client.post(
        f"/api/v1/salary-advances/{approved['id']}/approve",
        headers=manager["headers"],
        json={"reason": "ok"},
    )
    assert decision.status_code == 200, decision.text

    # disbursed for the double-settle race
    disbursed = create_one(reason="Race settle", amount="1500.00")
    assert (
        client.post(
            f"/api/v1/salary-advances/{disbursed['id']}/submit",
            headers=worker["headers"],
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/salary-advances/{disbursed['id']}/approve",
            headers=manager["headers"],
            json={"reason": "ok"},
        ).status_code
        == 200
    )
    paid = client.post(
        f"/api/v1/salary-advances/{disbursed['id']}/disburse",
        headers=officer["headers"],
        json={},
    )
    assert paid.status_code == 200, paid.text

    return SimpleNamespace(
        company=company,
        admin_user=admin_user,
        manager_user=manager_user,
        officer_user=officer_user,
        worker_user=worker_user,
        emp=emp,
        mgr_emp=mgr_emp,
        draft=draft,
        submitted=submitted,
        approved=approved,
        disbursed=disbursed,
        rule_id=paid.json()["deduction_rule_id"],
    )


def _build_principal(factory, user_id: int) -> Principal:
    session = factory()
    elevate_for_seed(session)
    try:
        user = session.get(User, user_id)
        assert user is not None
        company_ids = _load_company_ids(session, user_id)
        permissions, by_company = _load_permissions(session, user, company_ids)
        return Principal(
            user_id=user.id,
            email=user.email,
            is_platform_admin=user.is_platform_admin,
            company_ids=company_ids,
            permissions=permissions,
            permissions_by_company=by_company,
        )
    finally:
        clear_context(session)
        session.close()


def _race(db_schema, env, fns, expected, *, user):
    engine = create_engine(db_schema, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        principal = _build_principal(factory, user.id)
        barrier = threading.Barrier(len(fns), timeout=30)
        results: list[str] = []

        def worker(fn) -> None:
            session = factory()
            set_context(
                session,
                user_id=user.id,
                company_ids=[env.company.id],
                is_platform_admin=False,
            )
            try:
                barrier.wait()
                try:
                    fn(session, principal)
                    session.commit()
                    results.append("ok")
                except SalaryAdvanceStateError as exc:
                    session.rollback()
                    results.append(type(exc).__name__)
                except Exception as exc:  # pragma: no cover - diagnostics
                    session.rollback()
                    results.append(f"error:{type(exc).__name__}:{exc}")
            finally:
                session.close()

        threads = [threading.Thread(target=worker, args=(fn,)) for fn in fns]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        assert all(not t.is_alive() for t in threads), "salary advance race deadlocked"

        assert sorted(results) == sorted(expected), results
        return factory
    finally:
        engine.dispose()


def _events(factory, advance_id) -> list[str]:
    check = factory()
    elevate_for_seed(check)
    try:
        return list(
            check.execute(
                select(SalaryAdvanceEvent.event_type)
                .where(SalaryAdvanceEvent.advance_id == advance_id)
                .order_by(SalaryAdvanceEvent.id)
            ).scalars()
        )
    finally:
        check.close()


def test_concurrent_submits_of_same_draft_have_one_winner(db_schema, race_env):
    env = race_env

    def submit_one(session, principal):
        submit_advance(
            session,
            advance_id=env.draft["id"],
            principal=principal,
            ip="127.0.0.1",
        )

    factory = _race(
        db_schema,
        env,
        [submit_one, submit_one],
        ["ok", "SalaryAdvanceStateError"],
        user=env.worker_user,
    )

    check = factory()
    elevate_for_seed(check)
    try:
        row = check.get(SalaryAdvance, env.draft["id"])
        assert row is not None
        assert row.status == "submitted"
        assert row.submitted_by == env.worker_user.id
        assert row.approver_employee_id == env.mgr_emp["id"]
    finally:
        check.close()
    assert _events(factory, env.draft["id"]) == ["created", "submitted"]


def test_concurrent_approvals_have_one_winner(db_schema, race_env):
    env = race_env

    def approve_one(session, principal):
        approve_advance(
            session,
            advance_id=env.submitted["id"],
            payload=None,
            principal=principal,
            ip="127.0.0.1",
        )

    factory = _race(
        db_schema,
        env,
        [approve_one, approve_one],
        ["ok", "SalaryAdvanceStateError"],
        user=env.manager_user,
    )

    check = factory()
    elevate_for_seed(check)
    try:
        row = check.get(SalaryAdvance, env.submitted["id"])
        assert row is not None
        assert row.status == "approved"
        assert row.decided_by == env.manager_user.id
        assert row.decided_at is not None
    finally:
        check.close()
    assert _events(factory, env.submitted["id"]) == [
        "created",
        "submitted",
        "approved",
    ]


def test_concurrent_approve_and_reject_have_one_decision(db_schema, race_env):
    env = race_env

    def approve_one(session, principal):
        approve_advance(
            session,
            advance_id=env.submitted["id"],
            payload=None,
            principal=principal,
            ip="127.0.0.1",
        )

    def reject_one(session, principal):
        reject_advance(
            session,
            advance_id=env.submitted["id"],
            payload=AdvanceDecision(reason="budget cut"),
            principal=principal,
            ip="127.0.0.1",
        )

    factory = _race(
        db_schema,
        env,
        [approve_one, reject_one],
        ["ok", "SalaryAdvanceStateError"],
        user=env.manager_user,
    )

    check = factory()
    elevate_for_seed(check)
    try:
        row = check.get(SalaryAdvance, env.submitted["id"])
        assert row is not None
        assert row.status in ("approved", "rejected")
        assert row.decided_by == env.manager_user.id
        assert row.decided_at is not None
        status = row.status
        if status == "rejected":
            assert row.decision_reason == "budget cut"
    finally:
        check.close()

    events = _events(factory, env.submitted["id"])
    assert events == ["created", "submitted", status]
    assert events.count("approved") + events.count("rejected") == 1


def test_concurrent_disbursements_create_exactly_one_rule(db_schema, race_env):
    env = race_env

    def disburse_one(session, principal):
        disburse_advance(
            session,
            advance_id=env.approved["id"],
            payload=AdvanceDisburse(),
            principal=principal,
            ip="127.0.0.1",
        )

    factory = _race(
        db_schema,
        env,
        [disburse_one, disburse_one],
        ["ok", "SalaryAdvanceStateError"],
        user=env.officer_user,
    )

    check = factory()
    elevate_for_seed(check)
    try:
        row = check.get(SalaryAdvance, env.approved["id"])
        assert row is not None
        assert row.status == "disbursed"
        assert row.deduction_rule_id is not None
        rules = check.execute(
            select(PayrollDeductionRule).where(
                PayrollDeductionRule.employee_id == env.emp["id"],
                PayrollDeductionRule.name
                == f"Salary advance #{env.approved['id']}",
            )
        ).scalars()
        rules = list(rules)
        assert len(rules) == 1, f"expected one repayment rule, got {len(rules)}"
        rule = rules[0]
        assert rule.status == "active"
        assert row.deduction_rule_id == rule.id
        assert rule.total_amount is not None
        assert rule.remaining_amount == rule.total_amount
    finally:
        check.close()
    assert _events(factory, env.approved["id"]) == [
        "created",
        "submitted",
        "approved",
        "disbursed",
    ]


def test_concurrent_settles_have_one_winner(db_schema, race_env):
    env = race_env

    def settle_one(session, principal):
        settle_advance(
            session,
            advance_id=env.disbursed["id"],
            payload=AdvanceSettle(reason="employee repaid"),
            principal=principal,
            ip="127.0.0.1",
        )

    factory = _race(
        db_schema,
        env,
        [settle_one, settle_one],
        ["ok", "SalaryAdvanceStateError"],
        user=env.officer_user,
    )

    check = factory()
    elevate_for_seed(check)
    try:
        row = check.get(SalaryAdvance, env.disbursed["id"])
        assert row is not None
        assert row.status == "settled"
        assert row.settled_by == env.officer_user.id
        rule = check.get(PayrollDeductionRule, env.rule_id)
        assert rule is not None
        assert rule.status == "cancelled"
    finally:
        check.close()
    assert _events(factory, env.disbursed["id"]) == [
        "created",
        "submitted",
        "approved",
        "disbursed",
        "settled",
    ]


def test_concurrent_creates_both_survive(db_schema, race_env):
    # Multiple concurrent drafts are allowed by design (no open-advance
    # uniqueness lock was approved for Phase 8).
    env = race_env

    def create_one(session, principal):
        create_advance(
            session,
            payload=AdvanceCreate(
                amount=500,
                reason="Second parallel draft",
                requested_date=date(2026, 10, 2),
            ),
            principal=principal,
            ip="127.0.0.1",
        )

    factory = _race(
        db_schema,
        env,
        [create_one, create_one],
        ["ok", "ok"],
        user=env.worker_user,
    )

    check = factory()
    elevate_for_seed(check)
    try:
        rows = list(
            check.execute(
                select(SalaryAdvance).where(
                    SalaryAdvance.employee_id == env.emp["id"],
                    SalaryAdvance.reason == "Second parallel draft",
                )
            ).scalars()
        )
        assert len(rows) == 2, rows
        assert all(row.status == "draft" for row in rows)
        assert {row.created_by for row in rows} == {env.worker_user.id}
    finally:
        check.close()
