from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.rls import clear_context, elevate_for_seed
from app.shared.models import (
    Branch,
    Company,
    Permission,
    Role,
    RolePermission,
    UserRole,
)
from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


def _grant_role(db, *, company, user, code, name, permission_codes):
    elevate_for_seed(db)
    role = Role(company_id=company.id, code=code, name=name)
    db.add(role)
    db.flush()
    for pcode in permission_codes:
        perm = db.execute(
            select(Permission).where(Permission.code == pcode)
        ).scalar_one()
        db.add(
            RolePermission(
                role_id=role.id, permission_id=perm.id, company_id=company.id
            )
        )
    db.add(UserRole(user_id=user.id, role_id=role.id, company_id=company.id))
    db.commit()
    clear_context(db)
    return role


def _seed_branch(db, *, company, code):
    elevate_for_seed(db)
    branch = Branch(company_id=company.id, name=f"Branch {code}", code=code)
    db.add(branch)
    db.commit()
    clear_context(db)
    return branch


def test_permissions_are_checked_per_company(client, db_session):
    tenant_a = seed_company(db_session, "Scope A")
    tenant_b = seed_company(db_session, "Scope B")
    a_admin = seed_user(db_session, "admin@scope-a.co", tenant_a, "company_admin")
    b_admin = seed_user(db_session, "admin@scope-b.co", tenant_b, "company_admin")
    b_officer = seed_user(db_session, "officer@scope-b.co", tenant_b, "hr_officer")
    a_branch = _seed_branch(db_session, company=tenant_a, code="SAA")
    b_branch = _seed_branch(db_session, company=tenant_b, code="SBB")

    # Sign in as B's admin first so company-B audit rows exist.
    login(client, "admin@scope-b.co")
    client.cookies.clear()

    # A's admin gains ONLY branch.read inside company B.
    _grant_role(
        db_session,
        company=tenant_b,
        user=a_admin,
        code="branch_reader",
        name="Branch Reader",
        permission_codes=["branch.read"],
    )

    auth = login(client, "admin@scope-a.co")
    headers = auth["headers"]

    # Strict per-company denial: user.read is not granted in B.
    assert (
        client.get(
            f"/api/v1/users?company_id={tenant_b.id}", headers=headers
        ).status_code
        == 403
    )
    assert (
        client.get(f"/api/v1/users/{b_officer.id}", headers=headers).status_code
        == 403
    )
    assert (
        client.get(
            f"/api/v1/roles?company_id={tenant_b.id}", headers=headers
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"/api/v1/audit-logs?company_id={tenant_b.id}", headers=headers
        ).status_code
        == 403
    )

    # Unfiltered user listing is limited to companies where user.read holds.
    users = client.get("/api/v1/users", headers=headers).json()
    assert {u["email"] for u in users} == {"admin@scope-a.co"}

    # branch.read in B: B-scoped branch listing works and returns only B rows.
    scoped = client.get(
        f"/api/v1/branches?company_id={tenant_b.id}", headers=headers
    )
    assert scoped.status_code == 200, scoped.text
    rows = scoped.json()
    assert rows and {b["company_id"] for b in rows} == {tenant_b.id}
    assert b_branch.id in {b["id"] for b in rows}

    # List without filter = union over permitted companies only.
    all_branches = client.get("/api/v1/branches", headers=headers).json()
    branch_ids = {b["id"] for b in all_branches}
    assert a_branch.id in branch_ids and b_branch.id in branch_ids

    # Audit listing hides other companies' rows (actor=self rows are allowed).
    audit = client.get("/api/v1/audit-logs?page_size=100", headers=headers)
    assert audit.status_code == 200
    items = audit.json()["items"]
    assert items, "expected audit rows from logins and role grants"
    for item in items:
        assert (
            item["company_id"] in (tenant_a.id, None)
            or item["actor_user_id"] == a_admin.id
        ), item
    # Company B's admin activity must never surface for A's admin.
    assert all(i["actor_user_id"] != b_admin.id for i in items)


def test_company_update_enforces_company_update_permission(client, db_session):
    company = seed_company(db_session, "H2 Tenant")
    seed_user(db_session, "admin@h2.co", company, "company_admin")
    seed_user(db_session, "auditor@h2.co", company, "auditor")
    seed_user(db_session, "manager@h2.co", company, "hr_manager")

    admin = login(client, "admin@h2.co")
    ok = client.patch(
        f"/api/v1/companies/{company.id}",
        headers=admin["headers"],
        json={"city": "Jeddah"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["city"] == "Jeddah"

    client.cookies.clear()
    auditor = login(client, "auditor@h2.co")
    read = client.get(
        f"/api/v1/companies/{company.id}", headers=auditor["headers"]
    )
    assert read.status_code == 200, read.text
    denied = client.patch(
        f"/api/v1/companies/{company.id}",
        headers=auditor["headers"],
        json={"city": "Makkah"},
    )
    assert denied.status_code == 403

    client.cookies.clear()
    manager = login(client, "manager@h2.co")
    denied_manager = client.patch(
        f"/api/v1/companies/{company.id}",
        headers=manager["headers"],
        json={"city": "Makkah"},
    )
    assert denied_manager.status_code == 403

    # Company stays with the admin's edit.
    db_session.expire_all()
    elevate_for_seed(db_session)
    fresh = db_session.get(Company, company.id)
    assert fresh.city == "Jeddah"
    clear_context(db_session)


def test_role_without_permissions_gets_no_data_access(client, db_session):
    company = seed_company(db_session, "Empty Role Co")
    user = seed_user(db_session, "ghost@empty.co", company)
    _grant_role(
        db_session,
        company=company,
        user=user,
        code="ghost",
        name="Ghost",
        permission_codes=[],
    )

    auth = login(client, "ghost@empty.co")

    me = client.get("/api/v1/auth/me", headers=auth["headers"])
    assert me.status_code == 200
    assert me.json()["permissions"] == []
    assert company.id in me.json()["company_ids"]

    assert (
        client.get("/api/v1/users", headers=auth["headers"]).status_code == 403
    )
    assert (
        client.get("/api/v1/branches", headers=auth["headers"]).status_code == 403
    )
    assert (
        client.get("/api/v1/audit-logs", headers=auth["headers"]).status_code
        == 403
    )
    assert (
        client.get("/api/v1/roles", headers=auth["headers"]).status_code == 403
    )

    companies = client.get("/api/v1/companies", headers=auth["headers"])
    assert companies.status_code == 200
    assert companies.json() == []
