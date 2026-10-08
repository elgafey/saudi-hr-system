from __future__ import annotations

import pytest

from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


def _create_position(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "code": "SE1",
        "name_ar": "مهندس برمجيات",
        "name_en": "Software Engineer",
    }
    payload.update(overrides)
    return client.post(
        "/api/v1/job-positions", headers=auth["headers"], json=payload
    )


@pytest.fixture()
def pos_env(client, db_session):
    company = seed_company(db_session, "Pos Co")
    seed_user(db_session, "admin@pos.co", company, "company_admin")
    return company, login(client, "admin@pos.co")


def test_position_create_get_and_list(client, pos_env):
    company, auth = pos_env
    created = _create_position(client, auth, company.id)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["code"] == "SE1"
    assert body["department_id"] is None

    fetched = client.get(
        f"/api/v1/job-positions/{body['id']}", headers=auth["headers"]
    )
    assert fetched.status_code == 200

    page = client.get("/api/v1/job-positions", headers=auth["headers"])
    assert page.status_code == 200
    assert page.json()["page"]["total"] == 1
    assert page.json()["items"][0]["id"] == body["id"]


def test_position_duplicate_code_conflict(client, pos_env):
    company, auth = pos_env
    assert _create_position(client, auth, company.id).status_code == 201
    again = _create_position(client, auth, company.id)
    assert again.status_code == 409


def test_position_department_must_be_visible(client, pos_env, db_session):
    company, auth = pos_env
    other = seed_company(db_session, "Pos Other Co")
    seed_user(db_session, "admin@pos-other.co", other, "company_admin")
    auth_other = login(client, "admin@pos-other.co")
    foreign_dept = client.post(
        "/api/v1/departments",
        headers=auth_other["headers"],
        json={
            "company_id": other.id,
            "code": "FDEPT",
            "name_ar": "قسم",
            "name_en": "Foreign Dept",
        },
    )
    assert foreign_dept.status_code == 201

    result = _create_position(
        client, auth, company.id, department_id=foreign_dept.json()["id"]
    )
    assert result.status_code == 404
    assert result.json()["detail"] == "Department not found"


def test_position_list_filters_by_department(client, pos_env):
    company, auth = pos_env
    dept = client.post(
        "/api/v1/departments",
        headers=auth["headers"],
        json={
            "company_id": company.id,
            "code": "ENG",
            "name_ar": "الهندسة",
            "name_en": "Engineering",
        },
    ).json()
    _create_position(client, auth, company.id, code="SE1", department_id=dept["id"])
    _create_position(client, auth, company.id, code="SA1", department_id=None)

    filtered = client.get(
        "/api/v1/job-positions",
        headers=auth["headers"],
        params={"department_id": dept["id"]},
    )
    body = filtered.json()
    assert body["page"]["total"] == 1
    assert body["items"][0]["code"] == "SE1"

    search = client.get(
        "/api/v1/job-positions", headers=auth["headers"], params={"search": "SA1"}
    )
    assert search.json()["page"]["total"] == 1


def test_position_delete_blocked_by_employees(client, pos_env, db_session):
    company, auth = pos_env
    position = _create_position(client, auth, company.id).json()
    employee = client.post(
        "/api/v1/employees",
        headers=auth["headers"],
        json={
            "company_id": company.id,
            "first_name_ar": "سارة",
            "last_name_ar": "العتيبي",
            "first_name_en": "Sarah",
            "last_name_en": "Alotaibi",
            "job_position_id": position["id"],
        },
    )
    assert employee.status_code == 201, employee.text

    blocked = client.delete(
        f"/api/v1/job-positions/{position['id']}", headers=auth["headers"]
    )
    assert blocked.status_code == 409
    assert "Employees are assigned" in blocked.json()["detail"]


def test_position_delete_success(client, pos_env):
    company, auth = pos_env
    position = _create_position(client, auth, company.id).json()
    response = client.delete(
        f"/api/v1/job-positions/{position['id']}", headers=auth["headers"]
    )
    assert response.status_code == 204
    assert (
        client.get(
            f"/api/v1/job-positions/{position['id']}", headers=auth["headers"]
        ).status_code
        == 404
    )


def test_position_cross_company_detail_is_404(client, db_session):
    company_a = seed_company(db_session, "Pos Iso A")
    company_b = seed_company(db_session, "Pos Iso B")
    seed_user(db_session, "admin@pos-a.co", company_a, "company_admin")
    seed_user(db_session, "admin@pos-b.co", company_b, "company_admin")

    auth_a = login(client, "admin@pos-a.co")
    position = _create_position(client, auth_a, company_a.id).json()

    auth_b = login(client, "admin@pos-b.co")
    assert (
        client.get(
            f"/api/v1/job-positions/{position['id']}", headers=auth_b["headers"]
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/job-positions/{position['id']}",
            headers=auth_b["headers"],
            json={"name_en": "Hijacked"},
        ).status_code
        == 404
    )


def test_position_create_requires_permission(client, db_session):
    company = seed_company(db_session, "Pos Authz Co")
    seed_user(db_session, "officer@pos.co", company, "hr_officer")
    auth = login(client, "officer@pos.co")

    result = _create_position(client, auth, company.id)
    assert result.status_code == 403

    # auditor role: read-only across organizations
    seed_user(db_session, "auditor@pos.co", company, "auditor")
    auditor = login(client, "auditor@pos.co")
    assert (
        client.get("/api/v1/job-positions", headers=auditor["headers"]).status_code
        == 200
    )
    assert _create_position(client, auditor, company.id).status_code == 403
