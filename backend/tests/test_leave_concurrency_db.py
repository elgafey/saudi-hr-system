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
    LeaveAllocationOverlapError,
    LeaveRequestOverlapError,
    LeaveRequestStateError,
)
from app.core.rls import clear_context, elevate_for_seed, set_context
from app.leave.schemas import LeaveAllocationCreate, LeaveRequestDecision
from app.leave.service import (
    approve_leave_request,
    create_leave_allocation,
    submit_leave_request,
)
from app.shared.models import (
    LeaveAllocation,
    LeaveConsumption,
    LeaveRequest,
    User,
)
from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "Fahad",
        "last_name_ar": "Alqahtani",
        "first_name_en": "Fahad",
        "last_name_en": "Alqahtani",
        "status": "active",
        **overrides,
    }
    response = client.post(
        "/api/v1/employees", headers=auth["headers"], json=payload
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def race_env(client, db_session):
    company = seed_company(db_session, "Race Leave")
    user = seed_user(db_session, "race@raceleave.co", company, "company_admin")
    admin = login(client, "race@raceleave.co")
    employee = _create_employee(client, admin, company.id)

    leave_type = client.post(
        "/api/v1/leave-types",
        headers=admin["headers"],
        json={
            "company_id": company.id,
            "code": "RACE",
            "name_ar": "اجازة سباق",
            "name_en": "Race Leave",
            "requires_approval": True,
        },
    )
    assert leave_type.status_code == 201, leave_type.text

    allocation = client.post(
        "/api/v1/leave-allocations",
        headers=admin["headers"],
        json={
            "employee_id": employee["id"],
            "leave_type_id": leave_type.json()["id"],
            "period_start": "2025-01-01",
            "period_end": "2025-06-30",
            "allocated_days": "21.00",
        },
    )
    assert allocation.status_code == 201, allocation.text

    # Two OVERLAPPING drafts may coexist (the exclusion constraint only
    # fires for submitted/approved rows) - they race at submit time.
    draft_a = client.post(
        "/api/v1/leave-requests",
        headers=admin["headers"],
        json={
            "employee_id": employee["id"],
            "leave_type_id": leave_type.json()["id"],
            "start_date": "2025-03-10",
            "end_date": "2025-03-14",
        },
    )
    assert draft_a.status_code == 201, draft_a.text
    draft_b = client.post(
        "/api/v1/leave-requests",
        headers=admin["headers"],
        json={
            "employee_id": employee["id"],
            "leave_type_id": leave_type.json()["id"],
            "start_date": "2025-03-12",
            "end_date": "2025-03-16",
        },
    )
    assert draft_b.status_code == 201, draft_b.text

    # One already-submitted request for the double-approve race.
    submitted = client.post(
        "/api/v1/leave-requests",
        headers=admin["headers"],
        json={
            "employee_id": employee["id"],
            "leave_type_id": leave_type.json()["id"],
            "start_date": "2025-04-07",
            "end_date": "2025-04-11",
        },
    )
    assert submitted.status_code == 201, submitted.text
    submitted_transition = client.post(
        f"/api/v1/leave-requests/{submitted.json()['id']}/submit",
        headers=admin["headers"],
        json={},
    )
    assert submitted_transition.status_code == 200, submitted_transition.text

    return SimpleNamespace(
        company=company,
        user=user,
        employee=employee,
        leave_type=leave_type.json(),
        draft_a=draft_a.json(),
        draft_b=draft_b.json(),
        submitted=submitted.json(),
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
                except (
                    LeaveRequestOverlapError,
                    LeaveAllocationOverlapError,
                    LeaveRequestStateError,
                ) as exc:
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
        assert all(not t.is_alive() for t in threads), "leave race deadlocked"

        assert sorted(results) == sorted(expected), results
        return factory
    finally:
        engine.dispose()


def test_concurrent_submits_of_overlapping_requests_have_one_winner(
    db_schema, race_env
):
    env = race_env

    def submit_a(session, principal):
        submit_leave_request(
            session,
            request_id=env.draft_a["id"],
            principal=principal,
            ip="127.0.0.1",
        )

    def submit_b(session, principal):
        submit_leave_request(
            session,
            request_id=env.draft_b["id"],
            principal=principal,
            ip="127.0.0.1",
        )

    factory = _race(
        db_schema, env, [submit_a, submit_b],
        ["ok", "LeaveRequestOverlapError"],
    )

    # Exactly one of the two overlapping requests reached "submitted".
    check = factory()
    elevate_for_seed(check)
    try:
        rows = (
            check.execute(
                select(LeaveRequest.status).where(
                    LeaveRequest.id.in_(
                        [env.draft_a["id"], env.draft_b["id"]]
                    )
                )
            )
            .scalars()
            .all()
        )
        assert sorted(rows) == ["draft", "submitted"], rows
    finally:
        clear_context(check)
        check.close()


def test_concurrent_approvals_of_same_request_have_one_winner(
    db_schema, race_env
):
    env = race_env

    def approve_one(session, principal):
        approve_leave_request(
            session,
            request_id=env.submitted["id"],
            payload=LeaveRequestDecision(reason="first wins"),
            principal=principal,
            ip="127.0.0.1",
        )

    def approve_two(session, principal):
        approve_leave_request(
            session,
            request_id=env.submitted["id"],
            payload=LeaveRequestDecision(reason="second wins"),
            principal=principal,
            ip="127.0.0.1",
        )

    factory = _race(
        db_schema, env, [approve_one, approve_two],
        ["ok", "LeaveRequestStateError"],
    )

    # The single winner consumed the balance exactly once.
    check = factory()
    elevate_for_seed(check)
    try:
        request_id = env.submitted["id"]
        row = check.get(LeaveRequest, request_id)
        assert row is not None and row.status == "approved", row.status
        assert row.decision_reason in {"first wins", "second wins"}
        consumptions = (
            check.execute(
                select(LeaveConsumption).where(
                    LeaveConsumption.leave_request_id == request_id
                )
            )
            .scalars()
            .all()
        )
        assert len(consumptions) == 1, consumptions
    finally:
        clear_context(check)
        check.close()


def test_concurrent_overlapping_allocation_creates_have_one_winner(
    db_schema, race_env
):
    env = race_env

    def create_july(session, principal):
        create_leave_allocation(
            session,
            payload=LeaveAllocationCreate(
                employee_id=env.employee["id"],
                leave_type_id=env.leave_type["id"],
                period_start=date(2025, 7, 1),
                period_end=date(2025, 7, 31),
                allocated_days=Decimal("5.00"),
            ),
            principal=principal,
            ip="127.0.0.1",
        )

    def create_august(session, principal):
        create_leave_allocation(
            session,
            payload=LeaveAllocationCreate(
                employee_id=env.employee["id"],
                leave_type_id=env.leave_type["id"],
                period_start=date(2025, 7, 15),
                period_end=date(2025, 8, 15),
                allocated_days=Decimal("5.00"),
            ),
            principal=principal,
            ip="127.0.0.1",
        )

    factory = _race(
        db_schema, env, [create_july, create_august],
        ["ok", "LeaveAllocationOverlapError"],
    )

    check = factory()
    elevate_for_seed(check)
    try:
        rows = (
            check.execute(
                select(LeaveAllocation).where(
                    LeaveAllocation.employee_id == env.employee["id"],
                    LeaveAllocation.period_start >= date(2025, 7, 1),
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1, rows
    finally:
        clear_context(check)
        check.close()
