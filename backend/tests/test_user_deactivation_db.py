from __future__ import annotations

import pytest
from sqlalchemy import select

from app.auth.models import RefreshToken
from app.core.rls import clear_context, elevate_for_seed
from app.shared.models import User
from tests.conftest import TEST_PASSWORD, login, seed_company, seed_user

pytestmark = pytest.mark.db


def test_deactivation_revokes_refresh_sessions(client, db_session):
    company = seed_company(db_session, "M4 Deactivate Co")
    seed_user(db_session, "admin@m4.co", company, "company_admin")
    victim = seed_user(db_session, "victim@m4.co", company, "hr_officer")

    victim_auth = login(client, "victim@m4.co")
    victim_refresh = victim_auth["refresh"]
    victim_csrf = client.cookies.get("hr_csrf_token")
    assert victim_refresh

    client.cookies.clear()
    admin_auth = login(client, "admin@m4.co")
    patched = client.patch(
        f"/api/v1/users/{victim.id}",
        headers=admin_auth["headers"],
        json={"is_active": False},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["is_active"] is False

    # The victim's active session dies immediately.
    client.cookies.set("hr_refresh_token", victim_refresh, path="/api/v1/auth")
    client.cookies.set("hr_csrf_token", victim_csrf, path="/")
    refresh = client.post(
        "/api/v1/auth/refresh", headers={"X-CSRF-Token": victim_csrf}
    )
    assert refresh.status_code == 401

    # Every refresh token of the victim is revoked in the database.
    check = db_session
    tokens = (
        check.execute(
            select(RefreshToken).where(RefreshToken.user_id == victim.id)
        )
        .scalars()
        .all()
    )
    assert tokens
    assert all(t.revoked_at is not None for t in tokens)

    # Reactivation never resurrects revoked sessions.
    reactivated = client.patch(
        f"/api/v1/users/{victim.id}",
        headers=admin_auth["headers"],
        json={"is_active": True},
    )
    assert reactivated.status_code == 200, reactivated.text
    assert reactivated.json()["is_active"] is True

    client.cookies.set("hr_refresh_token", victim_refresh, path="/api/v1/auth")
    client.cookies.set("hr_csrf_token", victim_csrf, path="/")
    again = client.post(
        "/api/v1/auth/refresh", headers={"X-CSRF-Token": victim_csrf}
    )
    assert again.status_code == 401


def test_reactivation_allows_fresh_login(client, db_session):
    company = seed_company(db_session, "M4 Reactivate Co")
    seed_user(db_session, "admin@m4r.co", company, "company_admin")
    victim = seed_user(db_session, "victim@m4r.co", company, "hr_officer")
    auth = login(client, "admin@m4r.co")

    off = client.patch(
        f"/api/v1/users/{victim.id}",
        headers=auth["headers"],
        json={"is_active": False},
    )
    assert off.status_code == 200

    blocked = client.post(
        "/api/v1/auth/login",
        json={"identifier": "victim@m4r.co", "password": TEST_PASSWORD},
    )
    assert blocked.status_code == 401

    on = client.patch(
        f"/api/v1/users/{victim.id}",
        headers=auth["headers"],
        json={"is_active": True},
    )
    assert on.status_code == 200

    allowed = client.post(
        "/api/v1/auth/login",
        json={"identifier": "victim@m4r.co", "password": TEST_PASSWORD},
    )
    assert allowed.status_code == 200, allowed.text


def test_deactivation_is_committed_before_response(client, db_session):
    company = seed_company(db_session, "M4 Durable Co")
    seed_user(db_session, "admin@m4d.co", company, "company_admin")
    victim = seed_user(db_session, "victim@m4d.co", company, "hr_officer")
    auth = login(client, "admin@m4d.co")

    patched = client.patch(
        f"/api/v1/users/{victim.id}",
        headers=auth["headers"],
        json={"is_active": False},
    )
    assert patched.status_code == 200

    # Read back from a separate session after the response was produced.
    db_session.expire_all()
    elevate_for_seed(db_session)
    fresh = db_session.get(User, victim.id)
    assert fresh is not None
    assert fresh.is_active is False
    clear_context(db_session)
