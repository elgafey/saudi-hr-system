from __future__ import annotations

import pytest

from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


def _create_grade(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "code": "G3",
        "name_ar": "الدرجة الثالثة",
        "name_en": "Grade III",
        "level": 3,
    }
    payload.update(overrides)
    return client.post("/api/v1/job-grades", headers=auth["headers"], json=payload)


@pytest.fixture()
def grade_env(client, db_session):
    company = seed_company(db_session, "Grade Co")
    seed_user(db_session, "admin@grade.co", company, "company_admin")
    return company, login(client, "admin@grade.co")


def test_grade_create_get_and_ordering(client, grade_env):
    company, auth = grade_env
    for level, code in ((5, "G5"), (1, "G1"), (3, "G3")):
        response = _create_grade(client, auth, company.id, code=code, level=level)
        assert response.status_code == 201, response.text

    page = client.get("/api/v1/job-grades", headers=auth["headers"])
    body = page.json()
    assert body["page"]["total"] == 3
    assert [g["level"] for g in body["items"]] == [1, 3, 5]

    fetched = client.get(
        f"/api/v1/job-grades/{body['items'][1]['id']}", headers=auth["headers"]
    )
    assert fetched.status_code == 200
    assert fetched.json()["code"] == "G3"


def test_grade_duplicate_code_and_level_conflict(client, grade_env):
    company, auth = grade_env
    assert _create_grade(client, auth, company.id).status_code == 201

    dup_code = _create_grade(client, auth, company.id, level=9)
    assert dup_code.status_code == 409
    assert "code" in dup_code.json()["detail"]

    dup_level = _create_grade(client, auth, company.id, code="OTHER")
    assert dup_level.status_code == 409
    assert "level" in dup_level.json()["detail"]


def test_grade_level_validation_is_422(client, grade_env):
    company, auth = grade_env
    assert _create_grade(client, auth, company.id, level=0).status_code == 422
    assert _create_grade(client, auth, company.id, level=1000).status_code == 422


def test_grade_update_changes_level_and_status(client, grade_env):
    company, auth = grade_env
    grade = _create_grade(client, auth, company.id).json()

    updated = client.patch(
        f"/api/v1/job-grades/{grade['id']}",
        headers=auth["headers"],
        json={"level": 7, "status": "inactive"},
    )
    assert updated.status_code == 200
    assert updated.json()["level"] == 7
    assert updated.json()["status"] == "inactive"


def test_grade_cross_company_detail_is_404(client, db_session):
    company_a = seed_company(db_session, "Grade Iso A")
    company_b = seed_company(db_session, "Grade Iso B")
    seed_user(db_session, "admin@grade-a.co", company_a, "company_admin")
    seed_user(db_session, "admin@grade-b.co", company_b, "company_admin")

    auth_a = login(client, "admin@grade-a.co")
    grade = _create_grade(client, auth_a, company_a.id).json()

    auth_b = login(client, "admin@grade-b.co")
    assert (
        client.get(
            f"/api/v1/job-grades/{grade['id']}", headers=auth_b["headers"]
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/job-grades/{grade['id']}",
            headers=auth_b["headers"],
            json={"name_en": "Hijacked"},
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/job-grades/{grade['id']}", headers=auth_b["headers"]
        ).status_code
        == 404
    )


def test_grade_delete_blocked_by_employees_then_succeeds(client, grade_env):
    company, auth = grade_env
    grade = _create_grade(client, auth, company.id).json()

    employee = client.post(
        "/api/v1/employees",
        headers=auth["headers"],
        json={
            "company_id": company.id,
            "first_name_ar": "خالد",
            "last_name_ar": "الشمري",
            "first_name_en": "Khaled",
            "last_name_en": "Alshammari",
            "job_grade_id": grade["id"],
        },
    )
    assert employee.status_code == 201, employee.text

    blocked = client.delete(
        f"/api/v1/job-grades/{grade['id']}", headers=auth["headers"]
    )
    assert blocked.status_code == 409
    assert "Employees are assigned" in blocked.json()["detail"]

    # Remove the employee, then the grade can be deleted.
    removed = client.delete(
        f"/api/v1/employees/{employee.json()['id']}", headers=auth["headers"]
    )
    assert removed.status_code == 204
    assert (
        client.delete(
            f"/api/v1/job-grades/{grade['id']}", headers=auth["headers"]
        ).status_code
        == 204
    )


def test_grade_create_requires_permission(client, db_session):
    company = seed_company(db_session, "Grade Authz Co")
    seed_user(db_session, "officer@grade.co", company, "hr_officer")
    auth = login(client, "officer@grade.co")

    # hr_officer can read grades but not create them.
    assert (
        client.get("/api/v1/job-grades", headers=auth["headers"]).status_code
        == 200
    )
    assert _create_grade(client, auth, company.id).status_code == 403
