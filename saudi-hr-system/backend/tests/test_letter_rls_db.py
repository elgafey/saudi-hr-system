"""Phase 9 HR letter RLS probes: forced tenant isolation on both tables."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.core.rls import clear_context, elevate_for_seed, set_context
from app.core.rls_phase9 import PHASE9_RLS_TABLES
from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db

LETTER_INSERT = (
    "INSERT INTO hr_letters (company_id, employee_id, letter_type, language, "
    "status, content, version) VALUES "
    "(:company, :employee, 'employment', 'en', 'draft', '{}'::jsonb, 1) "
    "RETURNING id"
)
EVENT_INSERT = (
    "INSERT INTO hr_letter_events (company_id, letter_id, action, "
    "to_status, actor_name) VALUES "
    "(:company, :letter, 'created', 'draft', 'probe') RETURNING id"
)

INSERTS = {
    "hr_letters": (LETTER_INSERT, "employee"),
    "hr_letter_events": (EVENT_INSERT, "letter"),
}


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "ريما",
        "last_name_ar": "الشهري",
        "first_name_en": "Reema",
        "last_name_en": "Alshehri",
        "status": "active",
        **overrides,
    }
    response = client.post("/api/v1/employees", headers=auth["headers"], json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def rls_env(client, db_session):
    company_a = seed_company(db_session, "P9RLS A")
    company_b = seed_company(db_session, "P9RLS B")
    seed_user(db_session, "admin-a@p9rls.co", company_a, "company_admin")
    seed_user(db_session, "admin-b@p9rls.co", company_b, "company_admin")
    admin_a = login(client, "admin-a@p9rls.co")
    admin_b = login(client, "admin-b@p9rls.co")

    emp_a = _create_employee(client, admin_a, company_a.id)
    emp_b = _create_employee(client, admin_b, company_b.id)

    # Letter + event rows (elevated raw inserts keep the fixture API-free).
    elevate_for_seed(db_session)
    letter_a = db_session.execute(
        text(LETTER_INSERT), {"company": company_a.id, "employee": emp_a["id"]}
    ).scalar_one()
    letter_b = db_session.execute(
        text(LETTER_INSERT), {"company": company_b.id, "employee": emp_b["id"]}
    ).scalar_one()
    event_a = db_session.execute(
        text(EVENT_INSERT), {"company": company_a.id, "letter": letter_a}
    ).scalar_one()
    event_b = db_session.execute(
        text(EVENT_INSERT), {"company": company_b.id, "letter": letter_b}
    ).scalar_one()
    db_session.commit()
    clear_context(db_session)

    # API-created rows so the API visibility check needs no raw SQL.
    api_a = client.post(
        "/api/v1/hr-letters",
        headers=admin_a["headers"],
        json={
            "employee_id": emp_a["id"],
            "letter_type": "employment",
            "language": "en",
            "purpose": "API probe A",
        },
    )
    assert api_a.status_code == 201, api_a.text
    api_b = client.post(
        "/api/v1/hr-letters",
        headers=admin_b["headers"],
        json={
            "employee_id": emp_b["id"],
            "letter_type": "employment",
            "language": "en",
            "purpose": "API probe B",
        },
    )
    assert api_b.status_code == 201, api_b.text

    return SimpleNamespace(
        company_a=company_a,
        company_b=company_b,
        employee_a=emp_a,
        employee_b=emp_b,
        letter_a=letter_a,
        letter_b=letter_b,
        event_a=event_a,
        event_b=event_b,
        api_a=api_a.json()["id"],
        api_b=api_b.json()["id"],
    )


def test_phase9_tables_have_forced_rls_at_runtime(db_session):
    elevate_for_seed(db_session)
    for table in PHASE9_RLS_TABLES:
        row = db_session.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE oid = CAST(:table AS regclass)"
            ),
            {"table": table},
        ).one()
        assert row.relrowsecurity, table
        assert row.relforcerowsecurity, table
    clear_context(db_session)


def test_select_is_scoped_to_the_context_company(db_session, rls_env):
    env = rls_env
    set_context(
        db_session,
        user_id=None,
        company_ids=[env.company_a.id],
        is_platform_admin=False,
    )
    for table in sorted(PHASE9_RLS_TABLES):
        companies = {
            row[0]
            for row in db_session.execute(
                text(f"SELECT DISTINCT company_id FROM {table}")
            ).all()
        }
        assert companies == {env.company_a.id}, table
    clear_context(db_session)

    set_context(
        db_session,
        user_id=None,
        company_ids=[env.company_b.id],
        is_platform_admin=False,
    )
    for table in sorted(PHASE9_RLS_TABLES):
        companies = {
            row[0]
            for row in db_session.execute(
                text(f"SELECT DISTINCT company_id FROM {table}")
            ).all()
        }
        assert companies == {env.company_b.id}, table
    clear_context(db_session)


@pytest.mark.parametrize("table", sorted(INSERTS))
def test_cross_company_insert_blocked(db_session, rls_env, table):
    env = rls_env
    insert_sql, fk_field = INSERTS[table]
    params = {"company": env.company_b.id}
    if fk_field == "employee":
        params["employee"] = env.employee_a["id"]
    else:
        params["letter"] = env.letter_a

    set_context(
        db_session,
        user_id=None,
        company_ids=[env.company_a.id],
        is_platform_admin=False,
    )
    with pytest.raises(Exception) as excinfo:
        db_session.execute(text(insert_sql), params)
        db_session.flush()
    assert "row-level security" in str(excinfo.value).lower()
    db_session.rollback()
    clear_context(db_session)


@pytest.mark.parametrize("table", sorted(INSERTS))
def test_cross_company_update_and_delete_blocked(db_session, rls_env, table):
    env = rls_env
    row_b = {"hr_letters": env.letter_b, "hr_letter_events": env.event_b}[table]

    set_context(
        db_session,
        user_id=None,
        company_ids=[env.company_a.id],
        is_platform_admin=False,
    )
    updated = db_session.execute(
        text(f"UPDATE {table} SET company_id = company_id WHERE id = :id"),
        {"id": row_b},
    ).rowcount
    assert updated == 0, table
    deleted = db_session.execute(
        text(f"DELETE FROM {table} WHERE id = :id"), {"id": row_b}
    ).rowcount
    assert deleted == 0, table
    clear_context(db_session)

    # the row still exists (verified with elevated context)
    elevate_for_seed(db_session)
    assert (
        db_session.execute(
            text(f"SELECT count(*) FROM {table} WHERE id = :id"), {"id": row_b}
        ).scalar_one()
        == 1
    )
    db_session.rollback()
    clear_context(db_session)


def test_company_admin_sees_only_their_rows_through_the_api(client, rls_env):
    env = rls_env
    admin_a = login(client, "admin-a@p9rls.co")

    page = client.get("/api/v1/hr-letters", headers=admin_a["headers"])
    assert page.status_code == 200, page.text
    companies = {item["company_id"] for item in page.json()["items"]}
    assert companies == {env.company_a.id}
    assert env.api_a in {item["id"] for item in page.json()["items"]}
    assert env.api_b not in {item["id"] for item in page.json()["items"]}
    assert env.letter_b not in {item["id"] for item in page.json()["items"]}


def test_phase9_policies_exist_with_standard_names(db_session):
    elevate_for_seed(db_session)
    for table in PHASE9_RLS_TABLES:
        row = db_session.execute(
            text(
                "SELECT count(*) FROM pg_policy "
                "WHERE polrelid = CAST(:table AS regclass) "
                "AND polname = :policy"
            ),
            {"table": table, "policy": f"{table}_tenant_isolation"},
        ).scalar_one()
        assert row == 1, table
    clear_context(db_session)
