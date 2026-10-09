"""Phase 9 concurrency: one winner per state transition under races."""

from __future__ import annotations

import threading
from datetime import datetime
from datetime import timezone as dt_timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.deps import Principal, _load_company_ids, _load_permissions
from app.core.exceptions import (
    HrLetterRequestLinkedError,
    HrLetterStateError,
)
from app.core.rls import clear_context, elevate_for_seed, set_context
from app.letter.schemas import LetterCreate
from app.letter.service import create_letter, issue_letter, void_letter
from app.shared.models import EmployeeRequest, HrLetter, HrLetterEvent, User
from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "ماجد",
        "last_name_ar": "الدوسري",
        "first_name_en": "Majed",
        "last_name_en": "Aldosari",
        "status": "active",
        **overrides,
    }
    response = client.post("/api/v1/employees", headers=auth["headers"], json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def race_env(client, db_session):
    company = seed_company(db_session, "Race Letter")
    admin_user = seed_user(db_session, "admin@raceletter.co", company, "company_admin")

    admin = login(client, "admin@raceletter.co")
    emp = _create_employee(client, admin, company.id)

    def create_one(**overrides):
        body = {
            "employee_id": emp["id"],
            "letter_type": "employment",
            "language": "en",
            "purpose": "Race letter",
        }
        body.update(overrides)
        response = client.post(
            "/api/v1/hr-letters", headers=admin["headers"], json=body
        )
        assert response.status_code == 201, response.text
        return response.json()

    # Draft for the double-issue race.
    draft = create_one(purpose="Race issue")

    # Issued for the double-void race.
    issued = create_one(purpose="Race void")
    transition = client.post(
        f"/api/v1/hr-letters/{issued['id']}/issue",
        headers=admin["headers"],
        json={},
    )
    assert transition.status_code == 200, transition.text

    # Approved Phase 7 hr_letter request for the duplicate-link race.
    elevate_for_seed(db_session)
    request = EmployeeRequest(
        company_id=company.id,
        employee_id=emp["id"],
        request_type="hr_letter",
        status="approved",
        subject="Race source request",
        payload={},
        # ck_employee_request_decision_consistency needs decided_at.
        decided_at=datetime.now(dt_timezone.utc),
    )
    db_session.add(request)
    db_session.commit()
    clear_context(db_session)

    return SimpleNamespace(
        company=company,
        admin_user=admin_user,
        emp=emp,
        draft=draft,
        issued=issued,
        request_id=request.id,
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
                except (HrLetterStateError, HrLetterRequestLinkedError) as exc:
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
        assert all(not t.is_alive() for t in threads), "hr letter race deadlocked"

        assert sorted(results) == sorted(expected), results
        return factory
    finally:
        engine.dispose()


def _events(factory, letter_id) -> list[str]:
    check = factory()
    elevate_for_seed(check)
    try:
        return list(
            check.execute(
                select(HrLetterEvent.action)
                .where(HrLetterEvent.letter_id == letter_id)
                .order_by(HrLetterEvent.id)
            ).scalars()
        )
    finally:
        check.close()


def test_concurrent_issues_have_one_winner(db_schema, race_env):
    env = race_env

    def issue_one(session, principal):
        issue_letter(
            session,
            letter_id=env.draft["id"],
            principal=principal,
            ip="127.0.0.1",
        )

    factory = _race(
        db_schema,
        env,
        [issue_one, issue_one],
        ["ok", "HrLetterStateError"],
        user=env.admin_user,
    )

    check = factory()
    elevate_for_seed(check)
    try:
        row = check.get(HrLetter, env.draft["id"])
        assert row is not None
        assert row.status == "issued"
        assert row.issued_by == env.admin_user.id
        assert row.issued_at is not None
        assert row.version == 2
    finally:
        check.close()
    assert _events(factory, env.draft["id"]) == ["created", "issued"]


def test_concurrent_voids_have_one_winner(db_schema, race_env):
    env = race_env

    def void_one(session, principal):
        void_letter(
            session,
            letter_id=env.issued["id"],
            reason="race void",
            principal=principal,
            ip="127.0.0.1",
        )

    factory = _race(
        db_schema,
        env,
        [void_one, void_one],
        ["ok", "HrLetterStateError"],
        user=env.admin_user,
    )

    check = factory()
    elevate_for_seed(check)
    try:
        row = check.get(HrLetter, env.issued["id"])
        assert row is not None
        assert row.status == "void"
        assert row.voided_by == env.admin_user.id
        assert row.void_reason == "race void"
        assert row.version == 3
    finally:
        check.close()
    assert _events(factory, env.issued["id"]) == ["created", "issued", "voided"]


def test_concurrent_creates_for_same_source_request_have_one_winner(
    db_schema, race_env
):
    env = race_env

    def create_one(session, principal):
        create_letter(
            session,
            payload=LetterCreate(
                employee_id=env.emp["id"],
                letter_type="employment",
                language="en",
                purpose="Race source link",
                source_request_id=env.request_id,
            ),
            principal=principal,
            ip="127.0.0.1",
        )

    factory = _race(
        db_schema,
        env,
        [create_one, create_one],
        ["ok", "HrLetterRequestLinkedError"],
        user=env.admin_user,
    )

    check = factory()
    elevate_for_seed(check)
    try:
        rows = list(
            check.execute(
                select(HrLetter).where(
                    HrLetter.source_request_id == env.request_id
                )
            ).scalars()
        )
        active = [row for row in rows if row.status in ("draft", "issued")]
        assert len(active) == 1, rows
        assert active[0].company_id == env.company.id
        assert active[0].created_by == env.admin_user.id
    finally:
        check.close()
