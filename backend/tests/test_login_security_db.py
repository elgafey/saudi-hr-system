from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.audit.model import AuditLog
from app.core.rls import clear_context, elevate_for_seed
from tests.conftest import TEST_PASSWORD, seed_company, seed_user

pytestmark = pytest.mark.db


def _count(db, action: str, **filters) -> int:
    elevate_for_seed(db)
    try:
        stmt = select(AuditLog).where(AuditLog.action == action)
        for key, value in filters.items():
            stmt = stmt.where(getattr(AuditLog, key) == value)
        return len(db.execute(stmt).scalars().all())
    finally:
        clear_context(db)


def test_login_failure_messages_are_uniform(client, db_session):
    company = seed_company(db_session, "Uniform Co")
    seed_user(db_session, "known@uniform.co", company, "company_admin")
    inactive = seed_user(db_session, "inactive@uniform.co", company, "hr_officer")

    elevate_for_seed(db_session)
    inactive.is_active = False
    db_session.add(inactive)
    db_session.commit()
    clear_context(db_session)

    wrong_password = client.post(
        "/api/v1/auth/login",
        json={"identifier": "known@uniform.co", "password": "WrongPass9!"},
    )
    unknown = client.post(
        "/api/v1/auth/login",
        json={"identifier": "ghost@uniform.co", "password": "Whatever123!"},
    )
    disabled = client.post(
        "/api/v1/auth/login",
        json={"identifier": "inactive@uniform.co", "password": TEST_PASSWORD},
    )

    assert wrong_password.status_code == 401
    assert unknown.status_code == 401
    assert disabled.status_code == 401
    # Identical bodies: no user-existence or status disclosure.
    assert wrong_password.json() == unknown.json() == disabled.json()
    assert wrong_password.json()["detail"] == "Invalid credentials"


def test_identifier_lockout_after_repeated_failures(client, db_session):
    company = seed_company(db_session, "Lockout Co")
    user = seed_user(db_session, "lock@lockout.co", company, "company_admin")

    for _ in range(5):
        response = client.post(
            "/api/v1/auth/login",
            json={"identifier": "lock@lockout.co", "password": "Nope12345!"},
        )
        assert response.status_code == 401

    # Correct credentials are rejected while the lockout window is open.
    locked = client.post(
        "/api/v1/auth/login",
        json={"identifier": "lock@lockout.co", "password": TEST_PASSWORD},
    )
    assert locked.status_code == 401
    assert locked.json()["detail"] == "Invalid credentials"

    assert _count(db_session, "auth.login_failed") == 5
    assert (
        _count(
            db_session,
            "auth.login_blocked",
            record_id=str(user.id),
        )
        == 1
    )

    # Once the window elapses, the correct password works again.
    elevate_for_seed(db_session)
    db_session.execute(
        update(AuditLog).values(created_at=AuditLog.created_at - timedelta(minutes=16))
    )
    db_session.commit()
    clear_context(db_session)

    recovered = client.post(
        "/api/v1/auth/login",
        json={"identifier": "lock@lockout.co", "password": TEST_PASSWORD},
    )
    assert recovered.status_code == 200, recovered.text


def test_ip_lockout_blocks_unknown_identifiers(client, db_session):
    seed_company(db_session, "IP Lockout Co")

    for index in range(10):
        response = client.post(
            "/api/v1/auth/login",
            json={
                "identifier": f"unknown-{index}@lockout.co",
                "password": "Whatever123!",
            },
        )
        assert response.status_code == 401

    blocked = client.post(
        "/api/v1/auth/login",
        json={"identifier": "fresh@lockout.co", "password": "Whatever123!"},
    )
    assert blocked.status_code == 401
    assert blocked.json()["detail"] == "Invalid credentials"

    # Blocked attempts are recorded separately and do not extend the window.
    assert _count(db_session, "auth.login_failed") == 10
    assert _count(db_session, "auth.login_blocked") == 1

    # The IP budget stays exceeded: further attempts are blocked, never
    # recorded as failures (so the window cannot be extended indefinitely).
    still = client.post(
        "/api/v1/auth/login",
        json={"identifier": "another@lockout.co", "password": "Whatever123!"},
    )
    assert still.status_code == 401
    assert _count(db_session, "auth.login_blocked") == 2
    assert _count(db_session, "auth.login_failed") == 10
