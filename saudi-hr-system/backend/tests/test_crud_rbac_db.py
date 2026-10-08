from __future__ import annotations

import pytest

from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


def test_platform_admin_creates_company_with_default_roles(client, db_session):
    seed_user(db_session, "root@platform.co", platform=True)
    auth = login(client, "root@platform.co")

    response = client.post(
        "/api/v1/companies",
        headers=auth["headers"],
        json={
            "name": "Acme Saudi",
            "name_en": "Acme Saudi",
            "name_ar": "أكمي السعودية",
            "city": "Riyadh",
        },
    )
    assert response.status_code == 201, response.text
    company = response.json()
    assert company["country"] == "SA"
    assert company["default_currency"] == "SAR"
    assert company["timezone"] == "Asia/Riyadh"

    roles = client.get(
        f"/api/v1/roles?company_id={company['id']}", headers=auth["headers"]
    ).json()
    codes = {r["code"] for r in roles}
    assert codes == {
        "company_admin",
        "hr_manager",
        "hr_officer",
        "auditor",
        "employee",
    }

    admin_role = next(r for r in roles if r["code"] == "company_admin")
    perms = client.get(
        f"/api/v1/roles/{admin_role['id']}", headers=auth["headers"]
    ).json()["permission_codes"]
    assert "user.create" in perms
    assert "audit.read" in perms
    assert "company.create" not in perms


def test_non_platform_admin_cannot_create_company(client, db_session):
    company = seed_company(db_session, "Tenant A")
    seed_user(db_session, "admin@a.co", company, "company_admin")
    auth = login(client, "admin@a.co")

    response = client.post(
        "/api/v1/companies", headers=auth["headers"], json={"name": "Sneaky Inc"}
    )
    assert response.status_code == 403


def test_branch_crud_within_company(client, db_session):
    company = seed_company(db_session, "Tenant B")
    seed_user(db_session, "admin@b.co", company, "company_admin")
    auth = login(client, "admin@b.co")

    created = client.post(
        "/api/v1/branches",
        headers=auth["headers"],
        json={"company_id": company.id, "name": "Riyadh HQ", "code": "RUH"},
    )
    assert created.status_code == 201, created.text
    branch_id = created.json()["id"]

    listed = client.get("/api/v1/branches", headers=auth["headers"]).json()
    assert [b["id"] for b in listed] == [branch_id]

    patched = client.patch(
        f"/api/v1/branches/{branch_id}",
        headers=auth["headers"],
        json={"name": "Riyadh Headquarters"},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Riyadh Headquarters"


def test_branch_duplicate_code_conflict(client, db_session):
    company = seed_company(db_session, "Tenant C")
    seed_user(db_session, "admin@c.co", company, "company_admin")
    auth = login(client, "admin@c.co")

    payload = {"company_id": company.id, "name": "HQ", "code": "HQ1"}
    assert client.post(
        "/api/v1/branches", headers=auth["headers"], json=payload
    ).status_code == 201
    duplicate = client.post(
        "/api/v1/branches", headers=auth["headers"], json=payload
    )
    assert duplicate.status_code == 409


def test_same_branch_code_allowed_in_different_companies(client, db_session):
    seed_user(db_session, "root2@platform.co", platform=True)
    auth = login(client, "root2@platform.co")
    company_a = seed_company(db_session, "Multi A")
    company_b = seed_company(db_session, "Multi B")

    for cid in (company_a.id, company_b.id):
        response = client.post(
            "/api/v1/branches",
            headers=auth["headers"],
            json={"company_id": cid, "name": "Branch", "code": "SAME"},
        )
        assert response.status_code == 201, response.text


def test_user_create_with_role_assignment(client, db_session):
    company = seed_company(db_session, "Tenant D")
    seed_user(db_session, "admin@d.co", company, "company_admin")
    auth = login(client, "admin@d.co")

    roles = client.get(
        f"/api/v1/roles?company_id={company.id}", headers=auth["headers"]
    ).json()
    officer = next(r for r in roles if r["code"] == "hr_officer")

    created = client.post(
        "/api/v1/users",
        headers=auth["headers"],
        json={
            "email": "officer@d.co",
            "full_name": "HR Officer",
            "password": "OfficerPass123!",
            "company_id": company.id,
            "role_ids": [officer["id"]],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["email"] == "officer@d.co"
    assert body["is_platform_admin"] is False
    assert [r["code"] for r in body["roles"]] == ["hr_officer"]


def test_duplicate_email_conflict(client, db_session):
    company = seed_company(db_session, "Tenant E")
    seed_user(db_session, "admin@e.co", company, "company_admin")
    auth = login(client, "admin@e.co")

    payload = {
        "email": "dup@e.co",
        "full_name": "First",
        "password": "DupPass12345!",
        "company_id": company.id,
    }
    assert client.post(
        "/api/v1/users", headers=auth["headers"], json=payload
    ).status_code == 201
    duplicate = client.post(
        "/api/v1/users", headers=auth["headers"], json=payload
    )
    assert duplicate.status_code == 409


def test_non_admin_cannot_grant_platform_admin(client, db_session):
    company = seed_company(db_session, "Tenant F")
    seed_user(db_session, "admin@f.co", company, "company_admin")
    victim = seed_user(db_session, "victim@f.co", company, "hr_officer")
    auth = login(client, "admin@f.co")

    response = client.patch(
        f"/api/v1/users/{victim.id}",
        headers=auth["headers"],
        json={"is_platform_admin": True},
    )
    assert response.status_code == 403


def test_permissions_catalog_requires_permission(client, db_session):
    company = seed_company(db_session, "Tenant G")
    seed_user(db_session, "admin@g.co", company, "company_admin")
    auth = login(client, "admin@g.co")

    response = client.get("/api/v1/permissions", headers=auth["headers"])
    assert response.status_code == 200
    codes = {p["code"] for p in response.json()}
    assert "user.create" in codes
    assert "audit.read" in codes


def test_role_permission_update_roundtrip(client, db_session):
    company = seed_company(db_session, "Tenant H")
    seed_user(db_session, "admin@h.co", company, "company_admin")
    auth = login(client, "admin@h.co")

    roles = client.get(
        f"/api/v1/roles?company_id={company.id}", headers=auth["headers"]
    ).json()
    officer = next(r for r in roles if r["code"] == "hr_officer")

    updated = client.put(
        f"/api/v1/roles/{officer['id']}/permissions",
        headers=auth["headers"],
        json={"permission_codes": ["company.read", "branch.read"]},
    )
    assert updated.status_code == 200
    assert sorted(updated.json()["permission_codes"]) == [
        "branch.read",
        "company.read",
    ]

    unknown = client.put(
        f"/api/v1/roles/{officer['id']}/permissions",
        headers=auth["headers"],
        json={"permission_codes": ["not.a.permission"]},
    )
    assert unknown.status_code == 404


def test_user_without_permission_gets_403(client, db_session):
    company = seed_company(db_session, "Tenant I")
    seed_user(db_session, "admin@i.co", company, "company_admin")
    seed_user(db_session, "auditor@i.co", company, "auditor")
    auth = login(client, "auditor@i.co")

    create_branch = client.post(
        "/api/v1/branches",
        headers=auth["headers"],
        json={"company_id": company.id, "name": "Nope", "code": "N1"},
    )
    assert create_branch.status_code == 403

    create_company = client.post(
        "/api/v1/companies", headers=auth["headers"], json={"name": "Nope Inc"}
    )
    assert create_company.status_code == 403

    read_audit = client.get("/api/v1/audit-logs", headers=auth["headers"])
    assert read_audit.status_code == 200
