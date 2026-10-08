from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.rls import clear_context, elevate_for_seed, set_context
from app.shared.models import User
from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


def _as_member(db, *, user_id, company_id):
    set_context(
        db, user_id=user_id, company_ids=[company_id], is_platform_admin=False
    )


def test_direct_sql_cannot_self_escalate(db_session):
    company = seed_company(db_session, "M1 Escalate Co")
    victim = seed_user(db_session, "victim@m1.co", company, "hr_officer")

    _as_member(db_session, user_id=victim.id, company_id=company.id)
    with pytest.raises(DBAPIError, match="security-sensitive"):
        db_session.execute(
            text("UPDATE users SET is_platform_admin = true WHERE id = :uid"),
            {"uid": victim.id},
        )
    db_session.rollback()
    clear_context(db_session)

    db_session.expire_all()
    elevate_for_seed(db_session)
    fresh = db_session.get(User, victim.id)
    assert fresh.is_platform_admin is False


def test_direct_sql_cannot_reactivate_own_account(db_session):
    company = seed_company(db_session, "M1 Reactivate Co")
    victim = seed_user(db_session, "sleeper@m1.co", company, "hr_officer")

    elevate_for_seed(db_session)
    db_session.execute(
        text("UPDATE users SET is_active = false WHERE id = :uid"),
        {"uid": victim.id},
    )
    db_session.commit()
    clear_context(db_session)

    _as_member(db_session, user_id=victim.id, company_id=company.id)
    with pytest.raises(DBAPIError, match="own active state"):
        db_session.execute(
            text("UPDATE users SET is_active = true WHERE id = :uid"),
            {"uid": victim.id},
        )
    db_session.rollback()
    clear_context(db_session)

    db_session.expire_all()
    elevate_for_seed(db_session)
    fresh = db_session.get(User, victim.id)
    assert fresh.is_active is False


def test_direct_sql_cannot_reset_other_users_password(db_session):
    company = seed_company(db_session, "M1 Password Co")
    actor = seed_user(db_session, "actor@m1.co", company, "hr_officer")
    target = seed_user(db_session, "target@m1.co", company, "hr_officer")

    _as_member(
        db_session, user_id=actor.id, company_id=company.id
    )
    with pytest.raises(DBAPIError, match="password changes on other accounts"):
        db_session.execute(
            text("UPDATE users SET password_hash = 'pwned' WHERE id = :uid"),
            {"uid": target.id},
        )
    db_session.rollback()
    clear_context(db_session)

    db_session.expire_all()
    elevate_for_seed(db_session)
    fresh = db_session.get(User, target.id)
    assert fresh.password_hash != "pwned"


def test_direct_sql_cannot_create_platform_admin(db_session):
    company = seed_company(db_session, "M1 Insert Co")
    actor = seed_user(db_session, "creator@m1.co", company, "hr_officer")

    _as_member(db_session, user_id=actor.id, company_id=company.id)
    with pytest.raises(
        DBAPIError, match="platform administrators can only be created"
    ):
        db_session.execute(
            text(
                "INSERT INTO users (email, full_name, password_hash, "
                "is_active, is_platform_admin, company_id) "
                "VALUES ('evil@m1.co', 'Evil', 'x', true, true, :cid)"
            ),
            {"cid": company.id},
        )
    db_session.rollback()
    clear_context(db_session)

    db_session.expire_all()
    elevate_for_seed(db_session)
    assert (
        db_session.execute(
            text("SELECT count(*) FROM users WHERE email = 'evil@m1.co'")
        ).scalar_one()
        == 0
    )
    clear_context(db_session)


def test_platform_admin_context_can_still_manage_users(db_session):
    company = seed_company(db_session, "M1 Admin Co")
    user = seed_user(db_session, "managed@m1.co", company, "hr_officer")

    elevate_for_seed(db_session)
    db_session.execute(
        text("UPDATE users SET is_platform_admin = true WHERE id = :uid"),
        {"uid": user.id},
    )
    db_session.execute(
        text("UPDATE users SET is_platform_admin = false WHERE id = :uid"),
        {"uid": user.id},
    )
    db_session.commit()
    clear_context(db_session)

    db_session.expire_all()
    elevate_for_seed(db_session)
    fresh = db_session.get(User, user.id)
    assert fresh.is_platform_admin is False

    # Users may still change their own password (matches change_own_password).
    _as_member(db_session, user_id=user.id, company_id=company.id)
    db_session.execute(
        text("UPDATE users SET password_hash = 'self-set-hash' WHERE id = :uid"),
        {"uid": user.id},
    )
    db_session.commit()
    clear_context(db_session)

    db_session.expire_all()
    elevate_for_seed(db_session)
    assert db_session.get(User, user.id).password_hash == "self-set-hash"


def test_api_self_deactivation_forbidden(client, db_session):
    company = seed_company(db_session, "M1 Self Api Co")
    admin = seed_user(db_session, "admin@m1.co", company, "company_admin")
    auth = login(client, "admin@m1.co")

    response = client.patch(
        f"/api/v1/users/{admin.id}",
        headers=auth["headers"],
        json={"is_active": False},
    )
    assert response.status_code == 403

    db_session.expire_all()
    elevate_for_seed(db_session)
    assert db_session.get(User, admin.id).is_active is True
    clear_context(db_session)
