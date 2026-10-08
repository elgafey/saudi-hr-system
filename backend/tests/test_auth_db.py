from __future__ import annotations

import pytest

from tests.conftest import TEST_PASSWORD, login, seed_company, seed_user

pytestmark = pytest.mark.db


def test_full_login_success(client, db_session):
    company = seed_company(db_session, "Login Co")
    seed_user(db_session, "admin@login.co", company, "company_admin")

    response = client.post(
        "/api/v1/auth/login",
        json={"identifier": "admin@login.co", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0

    set_cookies = response.headers.get_list("set-cookie")
    refresh = next(c for c in set_cookies if "hr_refresh_token" in c)
    csrf = next(c for c in set_cookies if "hr_csrf_token" in c)
    assert "HttpOnly" in refresh
    assert "Path=/api/v1/auth" in refresh
    assert "HttpOnly" not in csrf
    assert "Path=/" in csrf or "path=/" in csrf.lower()


def test_login_wrong_password_rejected(client, db_session):
    company = seed_company(db_session, "Login Co2")
    seed_user(db_session, "admin2@login.co", company, "company_admin")

    response = client.post(
        "/api/v1/auth/login",
        json={"identifier": "admin2@login.co", "password": "WrongPassw0rd!"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


def test_login_unknown_identifier_rejected(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"identifier": "ghost@login.co", "password": "Whatever123!"},
    )
    assert response.status_code == 401


def test_login_inactive_user_rejected(client, db_session):
    company = seed_company(db_session, "Login Co3")
    user = seed_user(db_session, "inactive@login.co", company, "company_admin")
    from app.core.rls import clear_context, elevate_for_seed

    elevate_for_seed(db_session)
    user.is_active = False
    db_session.add(user)
    db_session.commit()
    clear_context(db_session)

    response = client.post(
        "/api/v1/auth/login",
        json={"identifier": "inactive@login.co", "password": TEST_PASSWORD},
    )
    assert response.status_code == 401


def test_me_returns_context(client, db_session):
    company = seed_company(db_session, "Me Co")
    seed_user(db_session, "admin@me.co", company, "company_admin")
    auth = login(client, "admin@me.co")

    response = client.get("/api/v1/auth/me", headers=auth["headers"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["email"] == "admin@me.co"
    assert company.id in body["company_ids"]
    assert "branch.create" in body["permissions"]
    assert "user.create" in body["permissions"]


def test_refresh_rotates_token(client, db_session):
    company = seed_company(db_session, "Refresh Co")
    seed_user(db_session, "admin@refresh.co", company, "company_admin")
    auth = login(client, "admin@refresh.co")
    old_refresh = auth["refresh"]
    assert old_refresh

    csrf = client.cookies.get("hr_csrf_token")
    response = client.post(
        "/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 200, response.text
    new_refresh = client.cookies.get("hr_refresh_token")
    assert new_refresh != old_refresh
    assert response.json()["access_token"]


def test_reusing_old_refresh_token_revokes_family(client, db_session):
    company = seed_company(db_session, "Reuse Co")
    seed_user(db_session, "admin@reuse.co", company, "company_admin")
    login(client, "admin@reuse.co")
    old_refresh = client.cookies.get("hr_refresh_token")
    csrf = client.cookies.get("hr_csrf_token")

    first = client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf})
    assert first.status_code == 200
    rotated = client.cookies.get("hr_refresh_token")
    rotated_csrf = client.cookies.get("hr_csrf_token")
    assert rotated and rotated != old_refresh

    client.cookies.delete("hr_refresh_token")
    client.cookies.set("hr_refresh_token", old_refresh, path="/api/v1/auth")
    reuse = client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": rotated_csrf})
    assert reuse.status_code == 401

    client.cookies.delete("hr_refresh_token")
    client.cookies.delete("hr_csrf_token")
    client.cookies.set("hr_refresh_token", rotated, path="/api/v1/auth")
    client.cookies.set("hr_csrf_token", rotated_csrf, path="/")
    after = client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": rotated_csrf})
    assert after.status_code == 401


def test_logout_revokes_session(client, db_session):
    company = seed_company(db_session, "Logout Co")
    seed_user(db_session, "admin@logout.co", company, "company_admin")
    auth = login(client, "admin@logout.co")
    csrf = client.cookies.get("hr_csrf_token")

    response = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 204

    client.cookies.delete("hr_refresh_token")
    client.cookies.delete("hr_csrf_token")
    client.cookies.set("hr_refresh_token", auth["refresh"], path="/api/v1/auth")
    client.cookies.set("hr_csrf_token", csrf, path="/")
    after = client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf})
    assert after.status_code == 401


def test_access_token_survives_only_in_memory_semantics(client, db_session):
    company = seed_company(db_session, "Token Co")
    seed_user(db_session, "admin@token.co", company, "company_admin")
    auth = login(client, "admin@token.co")

    without = client.get("/api/v1/auth/me")
    assert without.status_code == 401
    with_token = client.get("/api/v1/auth/me", headers=auth["headers"])
    assert with_token.status_code == 200


def test_change_password_and_invalidate_sessions(client, db_session):
    company = seed_company(db_session, "Pw Co")
    seed_user(db_session, "admin@pw.co", company, "company_admin")
    auth = login(client, "admin@pw.co")

    response = client.post(
        "/api/v1/auth/change-password",
        headers=auth["headers"],
        json={"current_password": TEST_PASSWORD, "new_password": "BrandNew9876!"},
    )
    assert response.status_code == 204, response.text

    client.cookies.clear()
    old = client.post(
        "/api/v1/auth/login",
        json={"identifier": "admin@pw.co", "password": TEST_PASSWORD},
    )
    assert old.status_code == 401
    new = client.post(
        "/api/v1/auth/login",
        json={"identifier": "admin@pw.co", "password": "BrandNew9876!"},
    )
    assert new.status_code == 200


def test_change_password_wrong_current_rejected(client, db_session):
    company = seed_company(db_session, "Pw2 Co")
    seed_user(db_session, "admin@pw2.co", company, "company_admin")
    auth = login(client, "admin@pw2.co")

    response = client.post(
        "/api/v1/auth/change-password",
        headers=auth["headers"],
        json={"current_password": "NotMyPass123!", "new_password": "BrandNew9876!"},
    )
    assert response.status_code == 401
