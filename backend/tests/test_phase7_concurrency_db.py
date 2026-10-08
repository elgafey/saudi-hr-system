from __future__ import annotations

import threading
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.deps import Principal, _load_company_ids, _load_permissions
from app.core.exceptions import EmployeeRequestStateError
from app.core.rls import clear_context, elevate_for_seed, set_context
from app.ess.schemas import RequestCreate
from app.ess.service import approve_request, create_request, submit_request
from app.shared.models import EmployeeRequest, EmployeeRequestEvent, User
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
    company = seed_company(db_session, "Race ESS")
    admin_user = seed_user(db_session, "admin@raceess.co", company, "company_admin")
    worker_user = seed_user(db_session, "worker@raceess.co", company, "employee")
    admin = login(client, "admin@raceess.co")
    worker = login(client, "worker@raceess.co")
    employee = _create_employee(client, admin, company.id)
    linked = client.post(
        f"/api/v1/employees/{employee['id']}/user",
        headers=admin["headers"],
        json={"user_id": worker_user.id},
    )
    assert linked.status_code == 200, linked.text

    # submitted correction for the double-approve race
    submitted = client.post(
        "/api/v1/employee-requests",
        headers=worker["headers"],
        json={
            "request_type": "attendance_correction",
            "subject": "Race correction 07-07",
            "reason": "device failed",
            "payload": {
                "work_date": "2025-07-07",
                "check_in": "2025-07-07T08:00:00",
                "check_out": "2025-07-07T16:00:00",
            },
        },
    )
    assert submitted.status_code == 201, submitted.text
    transition = client.post(
        f"/api/v1/employee-requests/{submitted.json()['id']}/submit",
        headers=worker["headers"],
    )
    assert transition.status_code == 200, transition.text

    # draft for the double-submit race
    draft = client.post(
        "/api/v1/employee-requests",
        headers=worker["headers"],
        json={
            "request_type": "hr_letter",
            "subject": "Race submit letter",
            "payload": {"purpose": "Bank requirement", "language": "en"},
        },
    )
    assert draft.status_code == 201, draft.text

    return SimpleNamespace(
        company=company,
        admin_user=admin_user,
        worker_user=worker_user,
        employee=employee,
        submitted=submitted.json(),
        draft=draft.json(),
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
                except EmployeeRequestStateError as exc:
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
        assert all(not t.is_alive() for t in threads), "employee request race deadlocked"

        assert sorted(results) == sorted(expected), results
        return factory
    finally:
        engine.dispose()


def test_concurrent_duplicate_open_corrections_one_wins(db_schema, race_env):
    env = race_env

    def create_one(session, principal):
        create_request(
            session,
            payload=RequestCreate(
                request_type="attendance_correction",
                subject="Race correction 07-08",
                reason="device failed",
                payload={
                    "work_date": "2025-07-08",
                    "check_in": "2025-07-08T08:00:00",
                    "check_out": "2025-07-08T16:00:00",
                },
            ),
            principal=principal,
            ip="127.0.0.1",
        )

    factory = _race(
        db_schema,
        env,
        [create_one, create_one],
        ["ok", "EmployeeRequestStateError"],
        user=env.worker_user,
    )

    # exactly one open correction survived for that date
    check = factory()
    elevate_for_seed(check)
    try:
        rows = (
            check.execute(
                select(EmployeeRequest).where(
                    EmployeeRequest.work_date == date(2025, 7, 8)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1, rows
        assert rows[0].status == "draft"
        assert rows[0].employee_id == env.employee["id"]
    finally:
        check.close()


def test_concurrent_submits_of_same_draft_have_one_winner(db_schema, race_env):
    env = race_env

    def submit_one(session, principal):
        submit_request(
            session,
            request_id=env.draft["id"],
            principal=principal,
            ip="127.0.0.1",
        )

    factory = _race(
        db_schema,
        env,
        [submit_one, submit_one],
        ["ok", "EmployeeRequestStateError"],
        user=env.worker_user,
    )

    check = factory()
    elevate_for_seed(check)
    try:
        row = check.get(EmployeeRequest, env.draft["id"])
        assert row is not None
        assert row.status == "submitted"
        assert row.submitted_by == env.worker_user.id
        events = check.execute(
            select(EmployeeRequestEvent.event_type)
            .where(EmployeeRequestEvent.request_id == env.draft["id"])
            .order_by(EmployeeRequestEvent.id)
        ).scalars()
        assert list(events) == ["created", "submitted"], list(events)
    finally:
        check.close()


def test_concurrent_approvals_have_one_winner(db_schema, race_env):
    env = race_env

    def approve_one(session, principal):
        approve_request(
            session,
            request_id=env.submitted["id"],
            payload=None,
            principal=principal,
            ip="127.0.0.1",
        )

    factory = _race(
        db_schema,
        env,
        [approve_one, approve_one],
        ["ok", "EmployeeRequestStateError"],
        user=env.admin_user,
    )

    check = factory()
    elevate_for_seed(check)
    try:
        row = check.get(EmployeeRequest, env.submitted["id"])
        assert row is not None
        assert row.status == "approved"
        assert row.decided_by == env.admin_user.id
        assert row.attendance_record_id is not None
        events = check.execute(
            select(EmployeeRequestEvent.event_type)
            .where(EmployeeRequestEvent.request_id == env.submitted["id"])
            .order_by(EmployeeRequestEvent.id)
        ).scalars()
        assert list(events) == ["created", "submitted", "approved"], list(events)

        from app.shared.models import AttendanceRecord

        records = check.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.employee_id == env.employee["id"],
                AttendanceRecord.work_date == date(2025, 7, 7),
            )
        ).scalars()
        assert len(list(records)) == 1, "exactly one attendance record"
    finally:
        check.close()
