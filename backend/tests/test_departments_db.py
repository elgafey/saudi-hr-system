from __future__ import annotations

import pytest

from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


def _create_department(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "code": "ENG",
        "name_ar": "الهندسة",
        "name_en": "Engineering",
    }
    payload.update(overrides)
    return client.post("/api/v1/departments", headers=auth["headers"], json=payload)


@pytest.fixture()
def dept_env(client, db_session):
    company = seed_company(db_session, "Dept Co")
    admin = seed_user(db_session, "admin@dept.co", company, "company_admin")
    return company, login(client, "admin@dept.co"), admin


def test_department_create_and_get(client, dept_env):
    company, auth, _ = dept_env
    created = _create_department(client, auth, company.id)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["code"] == "ENG"
    assert body["status"] == "active"
    assert body["parent_id"] is None

    fetched = client.get(
        f"/api/v1/departments/{body['id']}", headers=auth["headers"]
    )
    assert fetched.status_code == 200
    assert fetched.json()["name_en"] == "Engineering"


def test_department_list_pagination_search_and_status(client, dept_env):
    company, auth, _ = dept_env
    _create_department(client, auth, company.id, code="ENG", name_en="Engineering")
    _create_department(
        client, auth, company.id, code="SALES", name_en="Sales", name_ar="المبيعات"
    )
    _create_department(
        client, auth, company.id, code="HR", name_en="Human Resources",
        name_ar="الموارد البشرية", status="inactive",
    )

    page1 = client.get(
        "/api/v1/departments",
        headers=auth["headers"],
        params={"page": 1, "page_size": 2},
    )
    assert page1.status_code == 200
    body = page1.json()
    assert len(body["items"]) == 2
    assert body["page"] == {"page": 1, "page_size": 2, "total": 3}

    page2 = client.get(
        "/api/v1/departments",
        headers=auth["headers"],
        params={"page": 2, "page_size": 2},
    )
    assert len(page2.json()["items"]) == 1

    search = client.get(
        "/api/v1/departments", headers=auth["headers"], params={"search": "sales"}
    )
    assert search.json()["page"]["total"] == 1
    assert search.json()["items"][0]["code"] == "SALES"

    filtered = client.get(
        "/api/v1/departments",
        headers=auth["headers"],
        params={"status": "inactive"},
    )
    assert filtered.json()["page"]["total"] == 1
    assert filtered.json()["items"][0]["code"] == "HR"


def test_duplicate_department_code_conflict(client, dept_env):
    company, auth, _ = dept_env
    assert _create_department(client, auth, company.id).status_code == 201
    again = _create_department(client, auth, company.id)
    assert again.status_code == 409
    assert "already exists" in again.json()["detail"]


def test_department_validation_errors_are_422(client, dept_env):
    company, auth, _ = dept_env
    empty_name = _create_department(client, auth, company.id, name_en="")
    assert empty_name.status_code == 422

    bad_status = _create_department(client, auth, company.id, status="archived")
    assert bad_status.status_code == 422

    bad_parent = _create_department(client, auth, company.id, parent_id=0)
    assert bad_parent.status_code == 422


def test_cross_company_department_detail_is_404(client, db_session):
    company_a = seed_company(db_session, "Dept Iso A")
    company_b = seed_company(db_session, "Dept Iso B")
    seed_user(db_session, "admin@a-dept.co", company_a, "company_admin")
    seed_user(db_session, "admin@b-dept.co", company_b, "company_admin")

    auth_a = login(client, "admin@a-dept.co")
    created = _create_department(client, auth_a, company_a.id)
    assert created.status_code == 201
    dept_id = created.json()["id"]

    auth_b = login(client, "admin@b-dept.co")
    assert (
        client.get(f"/api/v1/departments/{dept_id}", headers=auth_b["headers"]).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/departments/{dept_id}",
            headers=auth_b["headers"],
            json={"name_en": "Hijacked"},
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/departments/{dept_id}", headers=auth_b["headers"]
        ).status_code
        == 404
    )

    client.cookies.clear()
    listing = client.get("/api/v1/departments", headers=auth_a["headers"])
    assert listing.json()["page"]["total"] == 1


def test_parent_department_must_be_visible_in_company(client, dept_env, db_session):
    company, auth, _ = dept_env
    other = seed_company(db_session, "Dept Parent Other")
    seed_user(db_session, "admin@parent-other.co", other, "company_admin")
    auth_other = login(client, "admin@parent-other.co")
    foreign = _create_department(client, auth_other, other.id, code="FOREIGN")
    assert foreign.status_code == 201

    result = _create_department(
        client, auth, company.id, parent_id=foreign.json()["id"]
    )
    assert result.status_code == 404
    assert "Parent department" in result.json()["detail"]


def test_department_cycle_detection(client, dept_env):
    company, auth, _ = dept_env
    parent = _create_department(client, auth, company.id, code="ROOT").json()
    child = _create_department(
        client, auth, company.id, code="CHILD", parent_id=parent["id"]
    ).json()

    self_parent = client.patch(
        f"/api/v1/departments/{parent['id']}",
        headers=auth["headers"],
        json={"parent_id": parent["id"]},
    )
    assert self_parent.status_code == 409

    cycle = client.patch(
        f"/api/v1/departments/{parent['id']}",
        headers=auth["headers"],
        json={"parent_id": child["id"]},
    )
    assert cycle.status_code == 409
    assert "cycle" in cycle.json()["detail"]


def test_department_delete_blocked_by_children(client, dept_env):
    company, auth, _ = dept_env
    parent = _create_department(client, auth, company.id, code="ROOT").json()
    _create_department(
        client, auth, company.id, code="CHILD", parent_id=parent["id"]
    )
    blocked = client.delete(
        f"/api/v1/departments/{parent['id']}", headers=auth["headers"]
    )
    assert blocked.status_code == 409
    assert "sub-departments" in blocked.json()["detail"]


def test_department_delete_writes_audit(client, dept_env):
    company, auth, _ = dept_env
    created = _create_department(client, auth, company.id).json()

    response = client.delete(
        f"/api/v1/departments/{created['id']}", headers=auth["headers"]
    )
    assert response.status_code == 204

    gone = client.get(
        f"/api/v1/departments/{created['id']}", headers=auth["headers"]
    )
    assert gone.status_code == 404

    page = client.get(
        "/api/v1/audit-logs",
        headers=auth["headers"],
        params={"action": "department.delete"},
    )
    assert page.status_code == 200
    items = page.json()["items"]
    assert len(items) == 1
    assert items[0]["company_id"] == company.id
    assert "ENG" in items[0]["old_value"]


def test_department_create_requires_permission(client, db_session):
    company = seed_company(db_session, "Dept Authz Co")
    seed_user(db_session, "officer@dept-authz.co", company, "hr_officer")
    auth = login(client, "officer@dept-authz.co")

    result = _create_department(client, auth, company.id)
    assert result.status_code == 403
    assert result.json()["code"] == "forbidden"

    officer_read = client.get("/api/v1/departments", headers=auth["headers"])
    assert officer_read.status_code == 200


def test_department_read_requires_permission(client, db_session):
    company = seed_company(db_session, "Dept Read Co")
    seed_user(db_session, "noread@dept.co", company)  # no role assigned
    auth = login(client, "noread@dept.co")

    response = client.get("/api/v1/departments", headers=auth["headers"])
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
