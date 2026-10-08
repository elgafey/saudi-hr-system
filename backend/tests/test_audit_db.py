from __future__ import annotations

import json

import pytest

from app.core.rls import clear_context, set_context
from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


def test_login_writes_audit_entry(client, db_session):
    company = seed_company(db_session, "Audit Co")
    seed_user(db_session, "admin@audit.co", company, "company_admin")
    login(client, "admin@audit.co")

    set_context(db_session, user_id=None, company_ids=[company.id], is_platform_admin=False)
    from sqlalchemy import select

    from app.audit.model import AuditLog

    rows = db_session.execute(
        select(AuditLog).where(AuditLog.action == "auth.login_success")
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].entity == "user"
    assert rows[0].ip_address == "testclient"
    clear_context(db_session)


def test_failed_login_writes_audit_entry(client, db_session):
    company = seed_company(db_session, "Audit Co2")
    seed_user(db_session, "admin@audit2.co", company, "company_admin")

    client.post(
        "/api/v1/auth/login",
        json={"identifier": "admin@audit2.co", "password": "BadPassword999!"},
    )
    client.post(
        "/api/v1/auth/login",
        json={"identifier": "nobody@audit2.co", "password": "BadPassword999!"},
    )

    set_context(db_session, user_id=None, company_ids=[], is_platform_admin=True)
    from sqlalchemy import select

    from app.audit.model import AuditLog

    rows = db_session.execute(
        select(AuditLog).where(AuditLog.action == "auth.login_failed")
    ).scalars().all()
    assert len(rows) == 2
    clear_context(db_session)


def test_mutations_write_audit_with_old_and_new(client, db_session):
    company = seed_company(db_session, "Audit Co3")
    seed_user(db_session, "admin@audit3.co", company, "company_admin")
    auth = login(client, "admin@audit3.co")

    client.post(
        "/api/v1/branches",
        headers=auth["headers"],
        json={"company_id": company.id, "name": "HQ", "code": "A3"},
    )

    branch = client.get("/api/v1/branches", headers=auth["headers"]).json()[0]
    client.patch(
        f"/api/v1/branches/{branch['id']}",
        headers=auth["headers"],
        json={"name": "Headquarters"},
    )

    page = client.get(
        "/api/v1/audit-logs?entity=branch", headers=auth["headers"]
    ).json()
    actions = [i["action"] for i in page["items"]]
    assert "branch.create" in actions
    assert "branch.update" in actions

    update_entry = next(
        i for i in page["items"] if i["action"] == "branch.update"
    )
    old = json.loads(update_entry["old_value"])
    new = json.loads(update_entry["new_value"])
    assert old["name"] == "HQ"
    assert new["name"] == "Headquarters"


def test_audit_pagination(client, db_session):
    company = seed_company(db_session, "Audit Page Co")
    seed_user(db_session, "admin@auditpage.co", company, "company_admin")
    auth = login(client, "admin@auditpage.co")

    for code in ("P1", "P2", "P3", "P4", "P5"):
        client.post(
            "/api/v1/branches",
            headers=auth["headers"],
            json={"company_id": company.id, "name": f"Br {code}", "code": code},
        )

    page1 = client.get(
        "/api/v1/audit-logs?page=1&page_size=3", headers=auth["headers"]
    ).json()
    assert len(page1["items"]) == 3
    assert page1["page"]["page"] == 1
    assert page1["page"]["page_size"] == 3
    assert page1["page"]["total"] >= 6

    page2 = client.get(
        "/api/v1/audit-logs?page=2&page_size=3", headers=auth["headers"]
    ).json()
    ids1 = {i["id"] for i in page1["items"]}
    ids2 = {i["id"] for i in page2["items"]}
    assert not ids1 & ids2


def test_audit_filter_by_action(client, db_session):
    company = seed_company(db_session, "Audit Filter Co")
    seed_user(db_session, "admin@auditfilter.co", company, "company_admin")
    auth = login(client, "admin@auditfilter.co")

    created = client.post(
        "/api/v1/branches",
        headers=auth["headers"],
        json={"company_id": company.id, "name": "Filter Branch", "code": "F1"},
    )
    assert created.status_code == 201, created.text

    page = client.get(
        "/api/v1/audit-logs?action=branch.create", headers=auth["headers"]
    ).json()
    assert len(page["items"]) == 1
    assert page["items"][0]["action"] == "branch.create"


def test_audit_actor_and_record_id_present(client, db_session):
    company = seed_company(db_session, "Audit Actor Co")
    admin = seed_user(db_session, "admin@auditactor.co", company, "company_admin")
    auth = login(client, "admin@auditactor.co")

    client.post(
        "/api/v1/branches",
        headers=auth["headers"],
        json={"company_id": company.id, "name": "Actor", "code": "AC1"},
    )

    page = client.get(
        "/api/v1/audit-logs?action=branch.create", headers=auth["headers"]
    ).json()
    entry = page["items"][0]
    assert entry["actor_user_id"] == admin.id
    assert entry["record_id"] not in (None, "", "0")
    assert entry["company_id"] == company.id
