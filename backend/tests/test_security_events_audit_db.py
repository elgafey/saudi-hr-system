from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.audit.model import AuditLog
from app.core.rls import clear_context, elevate_for_seed
from tests.conftest import TEST_PASSWORD, login, seed_company, seed_user

pytestmark = pytest.mark.db


def _audit_rows(db, action: str) -> list[AuditLog]:
    elevate_for_seed(db)
    try:
        return list(
            db.execute(
                select(AuditLog).where(AuditLog.action == action)
            ).scalars()
        )
    finally:
        clear_context(db)


def test_refresh_reuse_detected_is_audited(client, db_session):
    company = seed_company(db_session, "Reuse Audit Co")
    user = seed_user(db_session, "reuse@audit.co", company, "company_admin")
    auth = login(client, "reuse@audit.co")
    original = auth["refresh"]
    csrf = auth["csrf"]
    assert original

    first = client.post(
        "/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf}
    )
    assert first.status_code == 200, first.text
    rotated = client.cookies.get("hr_refresh_token")
    assert rotated and rotated != original
    rotated_csrf = client.cookies.get("hr_csrf_token")

    client.cookies.delete("hr_refresh_token")
    client.cookies.set("hr_refresh_token", original, path="/api/v1/auth")
    reuse = client.post(
        "/api/v1/auth/refresh", headers={"X-CSRF-Token": rotated_csrf}
    )
    assert reuse.status_code == 401

    rows = _audit_rows(db_session, "auth.refresh_reuse_detected")
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_user_id == user.id
    assert row.company_id == company.id
    stored = row.new_value or ""
    assert "family_id" in stored
    # Raw token material must never be persisted to the audit trail.
    assert original not in stored
    assert rotated not in stored


def test_logout_writes_audit_event(client, db_session):
    company = seed_company(db_session, "Logout Audit Co")
    user = seed_user(db_session, "logout@audit.co", company, "company_admin")
    auth = login(client, "logout@audit.co")
    csrf = auth["csrf"]

    response = client.post(
        "/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 204

    rows = _audit_rows(db_session, "auth.logout")
    assert len(rows) == 1
    assert rows[0].actor_user_id == user.id
    assert rows[0].company_id == company.id
    assert "family_id" in (rows[0].new_value or "")


def test_failed_password_change_is_audited(client, db_session):
    company = seed_company(db_session, "Pw Audit Co")
    user = seed_user(db_session, "pw@audit.co", company, "company_admin")
    auth = login(client, "pw@audit.co")

    response = client.post(
        "/api/v1/auth/change-password",
        headers=auth["headers"],
        json={
            "current_password": "NotThePassword1!",
            "new_password": "BrandNew4567!",
        },
    )
    assert response.status_code == 401

    rows = _audit_rows(db_session, "auth.password_change_failed")
    assert len(rows) == 1
    assert rows[0].actor_user_id == user.id
    assert rows[0].company_id == company.id

    # The failed attempt must not have altered the password.
    client.cookies.clear()
    still = client.post(
        "/api/v1/auth/login",
        json={"identifier": "pw@audit.co", "password": TEST_PASSWORD},
    )
    assert still.status_code == 200, still.text


def test_login_failures_record_identifier_without_secrets(client, db_session):
    company = seed_company(db_session, "Fail Audit Co")
    user = seed_user(db_session, "fail@audit.co", company, "company_admin")

    response = client.post(
        "/api/v1/auth/login",
        json={"identifier": "fail@audit.co", "password": "BadPassword9!"},
    )
    assert response.status_code == 401

    rows = _audit_rows(db_session, "auth.login_failed")
    assert len(rows) == 1
    row = rows[0]
    assert row.record_id == str(user.id)
    assert row.actor_user_id == user.id
    payload = json.loads(row.new_value) if row.new_value else {}
    assert payload.get("identifier") == "fail@audit.co"
    # The attempted password is never persisted.
    assert "BadPassword9!" not in (row.new_value or "")

    unknown = client.post(
        "/api/v1/auth/login",
        json={"identifier": "nobody@audit.co", "password": "Whatever123!"},
    )
    assert unknown.status_code == 401
    rows = _audit_rows(db_session, "auth.login_failed")
    assert len(rows) == 2
    unknown_rows = [r for r in rows if r.actor_user_id is None]
    assert len(unknown_rows) == 1
    assert unknown_rows[0].record_id.startswith("unknown:")
    assert len(unknown_rows[0].record_id) <= 64
