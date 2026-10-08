from __future__ import annotations

import threading
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.deps import Principal, _load_company_ids, _load_permissions
from app.core.exceptions import (
    PayrollAdjustmentStateError,
    PayrollPeriodExistsError,
    PayrollPeriodStateError,
    SalaryAssignmentOverlapError,
)
from app.core.rls import clear_context, elevate_for_seed, set_context
from app.payroll.schemas import (
    PayrollAdjustmentDecision,
    PayrollPeriodCreate,
    SalaryAssignmentCreate,
)
from app.payroll.service import (
    approve_payroll_period,
    calculate_payroll_period,
    create_payroll_period,
    create_salary_assignment,
    decide_payroll_adjustment,
)
from app.shared.models import (
    EmployeeSalaryAssignment,
    PayrollAdjustment,
    PayrollDeductionRule,
    PayrollPeriod,
    PayrollRun,
    PayrollRunLine,
    User,
)
from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db

EXPECTED_RACE_ERRORS = (
    PayrollAdjustmentStateError,
    PayrollPeriodExistsError,
    PayrollPeriodStateError,
    SalaryAssignmentOverlapError,
)


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "ريان",
        "last_name_ar": "الشمري",
        "first_name_en": "Rayan",
        "last_name_en": "Alshammari",
        "status": "active",
        **overrides,
    }
    response = client.post("/api/v1/employees", headers=auth["headers"], json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def pay_race_env(client, db_session):
    company = seed_company(db_session, "Race Pay")
    user = seed_user(db_session, "race@racepay.co", company, "company_admin")
    admin = login(client, "race@racepay.co")
    employee = _create_employee(client, admin, company.id)

    assignment = client.post(
        "/api/v1/salary-assignments",
        headers=admin["headers"],
        json={
            "company_id": company.id,
            "employee_id": employee["id"],
            "effective_from": "2025-01-01",
            "basic_salary": "9300",
        },
    )
    assert assignment.status_code == 201, assignment.text

    deduction = client.post(
        "/api/v1/payroll-deductions",
        headers=admin["headers"],
        json={
            "company_id": company.id,
            "employee_id": employee["id"],
            "name": "Installment Loan",
            "amount": "300",
            "total_amount": "1000",
            "effective_from": "2025-01-01",
        },
    )
    assert deduction.status_code == 201, deduction.text

    period = client.post(
        "/api/v1/payroll-periods",
        headers=admin["headers"],
        json={
            "company_id": company.id,
            "name": "Jan 2025",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
        },
    )
    assert period.status_code == 201, period.text

    adjustment = client.post(
        "/api/v1/payroll-adjustments",
        headers=admin["headers"],
        json={
            "company_id": company.id,
            "employee_id": employee["id"],
            "period_id": period.json()["id"],
            "amount": "100",
            "direction": "earning",
            "reason": "Race target",
        },
    )
    assert adjustment.status_code == 201, adjustment.text

    return SimpleNamespace(
        company=company,
        user=user,
        admin=admin,
        employee=employee,
        assignment=assignment.json(),
        deduction=deduction.json(),
        period=period.json(),
        adjustment=adjustment.json(),
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


def _race(db_schema, env, fns, expected):
    engine = create_engine(db_schema, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        principal = _build_principal(factory, env.user.id)
        barrier = threading.Barrier(len(fns), timeout=30)
        results: list[str] = []

        def worker(fn) -> None:
            session = factory()
            set_context(
                session,
                user_id=env.user.id,
                company_ids=[env.company.id],
                is_platform_admin=False,
            )
            try:
                barrier.wait()
                try:
                    fn(session, principal)
                    session.commit()
                    results.append("ok")
                except EXPECTED_RACE_ERRORS as exc:
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
        assert all(not t.is_alive() for t in threads), "payroll race deadlocked"

        assert sorted(results) == sorted(expected), results
        return factory
    finally:
        engine.dispose()


def _elevated(factory):
    session = factory()
    elevate_for_seed(session)
    return session


def test_concurrent_calculates_reuse_a_single_run(db_schema, pay_race_env):
    env = pay_race_env

    def calculate_one(session, principal):
        calculate_payroll_period(
            session,
            period_id=env.period["id"],
            principal=principal,
            ip="127.0.0.1",
        )

    def calculate_two(session, principal):
        calculate_payroll_period(
            session,
            period_id=env.period["id"],
            principal=principal,
            ip="127.0.0.1",
        )

    factory = _race(db_schema, env, [calculate_one, calculate_two], ["ok", "ok"])

    check = _elevated(factory)
    try:
        runs = (
            check.execute(
                select(PayrollRun).where(PayrollRun.period_id == env.period["id"])
            )
            .scalars()
            .all()
        )
        assert len(runs) == 1, runs
        assert runs[0].status == "active"
        assert runs[0].run_number == 1
        lines = (
            check.execute(
                select(PayrollRunLine).where(PayrollRunLine.run_id == runs[0].id)
            )
            .scalars()
            .all()
        )
        assert len(lines) == 1, lines
        period = check.get(PayrollPeriod, env.period["id"])
        assert period is not None and period.status == "calculated"
    finally:
        clear_context(check)
        check.close()


def test_concurrent_approvals_consume_installment_exactly_once(
    client, db_schema, pay_race_env
):
    env = pay_race_env

    calculated = client.post(
        f"/api/v1/payroll-periods/{env.period['id']}/calculate",
        headers=env.admin["headers"],
        json={},
    )
    assert calculated.status_code == 200, calculated.text
    reviewed = client.post(
        f"/api/v1/payroll-periods/{env.period['id']}/review",
        headers=env.admin["headers"],
        json={},
    )
    assert reviewed.status_code == 200, reviewed.text

    def approve_one(session, principal):
        approve_payroll_period(
            session, period_id=env.period["id"], principal=principal, ip="127.0.0.1"
        )

    def approve_two(session, principal):
        approve_payroll_period(
            session, period_id=env.period["id"], principal=principal, ip="127.0.0.1"
        )

    factory = _race(
        db_schema,
        env,
        [approve_one, approve_two],
        ["ok", "PayrollPeriodStateError"],
    )

    check = _elevated(factory)
    try:
        period = check.get(PayrollPeriod, env.period["id"])
        assert period is not None and period.status == "approved"
        row = check.get(PayrollDeductionRule, env.deduction["id"])
        assert row is not None
        assert row.remaining_amount == Decimal("700")
        assert row.status == "active"
    finally:
        clear_context(check)
        check.close()


def test_concurrent_period_creates_have_one_winner(db_schema, pay_race_env):
    env = pay_race_env

    def create_february_one(session, principal):
        create_payroll_period(
            session,
            payload=PayrollPeriodCreate(
                company_id=env.company.id,
                name="Feb 2025",
                period_start=date(2025, 2, 1),
                period_end=date(2025, 2, 28),
            ),
            principal=principal,
            ip="127.0.0.1",
        )

    def create_february_two(session, principal):
        create_payroll_period(
            session,
            payload=PayrollPeriodCreate(
                company_id=env.company.id,
                name="Feb 2025",
                period_start=date(2025, 2, 1),
                period_end=date(2025, 2, 28),
            ),
            principal=principal,
            ip="127.0.0.1",
        )

    factory = _race(
        db_schema,
        env,
        [create_february_one, create_february_two],
        ["ok", "PayrollPeriodExistsError"],
    )

    check = _elevated(factory)
    try:
        february = (
            check.execute(
                select(PayrollPeriod).where(
                    PayrollPeriod.company_id == env.company.id,
                    PayrollPeriod.period_start == date(2025, 2, 1),
                )
            )
            .scalars()
            .all()
        )
        assert len(february) == 1, february
        assert february[0].name == "Feb 2025"
    finally:
        clear_context(check)
        check.close()


def test_concurrent_assignment_creates_have_one_winner(db_schema, pay_race_env):
    env = pay_race_env

    def create_feb_one(session, principal):
        create_salary_assignment(
            session,
            payload=SalaryAssignmentCreate(
                company_id=env.company.id,
                employee_id=env.employee["id"],
                effective_from=date(2025, 2, 1),
                effective_to=date(2025, 2, 28),
                basic_salary=Decimal("9500"),
            ),
            principal=principal,
            ip="127.0.0.1",
        )

    def create_feb_two(session, principal):
        create_salary_assignment(
            session,
            payload=SalaryAssignmentCreate(
                company_id=env.company.id,
                employee_id=env.employee["id"],
                effective_from=date(2025, 2, 1),
                effective_to=date(2025, 2, 28),
                basic_salary=Decimal("9500"),
            ),
            principal=principal,
            ip="127.0.0.1",
        )

    factory = _race(
        db_schema,
        env,
        [create_feb_one, create_feb_two],
        ["ok", "SalaryAssignmentOverlapError"],
    )

    check = _elevated(factory)
    try:
        rows = (
            check.execute(
                select(EmployeeSalaryAssignment).where(
                    EmployeeSalaryAssignment.employee_id == env.employee["id"]
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 2, rows
        january = [r for r in rows if r.effective_from == date(2025, 1, 1)]
        assert len(january) == 1
        assert january[0].effective_to == date(2025, 1, 31)
        february = [r for r in rows if r.effective_from == date(2025, 2, 1)]
        assert len(february) == 1
        assert february[0].effective_to == date(2025, 2, 28)
    finally:
        clear_context(check)
        check.close()


def test_concurrent_adjustment_approvals_have_one_winner(db_schema, pay_race_env):
    env = pay_race_env

    def approve_one(session, principal):
        decide_payroll_adjustment(
            session,
            adjustment_id=env.adjustment["id"],
            decision="approve",
            payload=PayrollAdjustmentDecision(decision_reason="first"),
            principal=principal,
            ip="127.0.0.1",
        )

    def approve_two(session, principal):
        decide_payroll_adjustment(
            session,
            adjustment_id=env.adjustment["id"],
            decision="approve",
            payload=PayrollAdjustmentDecision(decision_reason="second"),
            principal=principal,
            ip="127.0.0.1",
        )

    factory = _race(
        db_schema,
        env,
        [approve_one, approve_two],
        ["ok", "PayrollAdjustmentStateError"],
    )

    check = _elevated(factory)
    try:
        row = check.get(PayrollAdjustment, env.adjustment["id"])
        assert row is not None and row.status == "approved"
        assert row.decision_reason in {"first", "second"}
        assert row.decided_by == env.user.id
    finally:
        clear_context(check)
        check.close()
