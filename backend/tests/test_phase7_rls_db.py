from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.core.rls import clear_context, elevate_for_seed, set_context
from app.core.rls_phase7 import PHASE7_RLS_TABLES
from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db

PDF = b"%PDF-1.4\n%phase7 rls probe\n%%EOF\n"

REQUEST_INSERT = (
    "INSERT INTO employee_requests (company_id, employee_id, request_type, "
    "status, subject, payload) VALUES "
    "(:company, :employee, 'other', 'draft', 'rls probe', '{}') RETURNING id"
)
EVENT_INSERT = (
    "INSERT INTO employee_request_events (company_id, request_id, event_type, "
    "actor_name) VALUES (:company, :request, 'created', 'probe') RETURNING id"
)
VISIBILITY_INSERT = (
    "INSERT INTO employee_document_visibility (company_id, document_id, "
    "employee_visible) VALUES (:company, :document, false) RETURNING id"
)

INSERTS = {
    "employee_requests": (REQUEST_INSERT, "employee"),
    "employee_request_events": (EVENT_INSERT, "request"),
    "employee_document_visibility": (VISIBILITY_INSERT, "document"),
}


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "سالم",
        "last_name_ar": "الرويلي",
        "first_name_en": "Salem",
        "last_name_en": "Alruwaili",
        "status": "active",
        **overrides,
    }
    response = client.post("/api/v1/employees", headers=auth["headers"], json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def rls_env(client, db_session):
    company_a = seed_company(db_session, "P7RLS A")
    company_b = seed_company(db_session, "P7RLS B")
    seed_user(db_session, "admin-a@p7rls.co", company_a, "company_admin")
    seed_user(db_session, "admin-b@p7rls.co", company_b, "company_admin")
    admin_a = login(client, "admin-a@p7rls.co")
    admin_b = login(client, "admin-b@p7rls.co")

    emp_a = _create_employee(client, admin_a, company_a.id)
    emp_b = _create_employee(client, admin_b, company_b.id)

    types_a = client.get("/api/v1/employee-document-types", headers=admin_a["headers"])
    assert types_a.status_code == 200, types_a.text
    types_b = client.get("/api/v1/employee-document-types", headers=admin_b["headers"])
    assert types_b.status_code == 200, types_b.text

    doc_a = client.post(
        f"/api/v1/employees/{emp_a['id']}/documents",
        headers=admin_a["headers"],
        data={"document_type_id": str(types_a.json()[0]["id"])},
        files={"file": ("a.pdf", PDF, "application/pdf")},
    )
    assert doc_a.status_code == 201, doc_a.text
    doc_b = client.post(
        f"/api/v1/employees/{emp_b['id']}/documents",
        headers=admin_b["headers"],
        data={"document_type_id": str(types_b.json()[0]["id"])},
        files={"file": ("b.pdf", PDF, "application/pdf")},
    )
    assert doc_b.status_code == 201, doc_b.text

    # visibility rows (one per company, created through the API)
    vis_a = client.patch(
        f"/api/v1/employee-documents/{doc_a.json()['id']}/visibility",
        headers=admin_a["headers"],
        json={"employee_visible": True},
    )
    assert vis_a.status_code == 200, vis_a.text
    vis_b = client.patch(
        f"/api/v1/employee-documents/{doc_b.json()['id']}/visibility",
        headers=admin_b["headers"],
        json={"employee_visible": True},
    )
    assert vis_b.status_code == 200, vis_b.text

    # request + event rows (elevated raw inserts keep the fixture API-free)
    elevate_for_seed(db_session)
    request_a = db_session.execute(
        text(REQUEST_INSERT), {"company": company_a.id, "employee": emp_a["id"]}
    ).scalar_one()
    request_b = db_session.execute(
        text(REQUEST_INSERT), {"company": company_b.id, "employee": emp_b["id"]}
    ).scalar_one()
    event_a = db_session.execute(
        text(EVENT_INSERT), {"company": company_a.id, "request": request_a}
    ).scalar_one()
    event_b = db_session.execute(
        text(EVENT_INSERT), {"company": company_b.id, "request": request_b}
    ).scalar_one()
    db_session.commit()
    clear_context(db_session)

    return SimpleNamespace(
        company_a=company_a,
        company_b=company_b,
        employee_a=emp_a,
        employee_b=emp_b,
        document_a=doc_a.json()["id"],
        document_b=doc_b.json()["id"],
        request_a=request_a,
        request_b=request_b,
        event_a=event_a,
        event_b=event_b,
    )


def test_phase7_tables_have_forced_rls_at_runtime(db_session):
    elevate_for_seed(db_session)
    for table in PHASE7_RLS_TABLES:
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
    for table in sorted(PHASE7_RLS_TABLES):
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
    for table in sorted(PHASE7_RLS_TABLES):
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
    elif fk_field == "request":
        params["request"] = env.request_a
    else:
        params["document"] = env.document_a

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
    row_b = {
        "employee_requests": env.request_b,
        "employee_request_events": env.event_b,
        "employee_document_visibility": None,
    }[table]
    if row_b is None:
        elevate_for_seed(db_session)
        row_b = db_session.execute(
            text(
                "SELECT id FROM employee_document_visibility "
                "WHERE company_id = :company"
            ),
            {"company": env.company_b.id},
        ).scalar_one()
        clear_context(db_session)

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
    assert db_session.execute(
        text(f"SELECT count(*) FROM {table} WHERE id = :id"), {"id": row_b}
    ).scalar_one() == 1
    db_session.rollback()
    clear_context(db_session)


def test_company_admin_sees_only_their_rows_through_the_api(client, db_session, rls_env):
    env = rls_env
    admin_a = login(client, "admin-a@p7rls.co")

    # audit rows are service+RLS scoped to the caller's company
    page = client.get("/api/v1/audit-logs", headers=admin_a["headers"])
    assert page.status_code == 200
    companies = {
        item["company_id"]
        for item in page.json()["items"]
        if item["company_id"] is not None
    }
    assert companies <= {env.company_a.id}
