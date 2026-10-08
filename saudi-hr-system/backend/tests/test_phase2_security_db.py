from __future__ import annotations

import pytest

from app.core.rls import clear_context, elevate_for_seed
from app.shared.models import UserRole
from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db

BASE_EMPLOYEE = {
    "first_name_ar": "سعد",
    "last_name_ar": "الدوسري",
    "first_name_en": "Saad",
    "last_name_en": "Aldosari",
}


def _grant_role(db, user, company, role_code):
    """Attach an additional company-scoped role to an existing user."""
    from tests.conftest import select_role

    elevate_for_seed(db)
    role = db.execute(
        select_role(company.id, role_code)
    ).scalar_one_or_none()
    assert role is not None, f"missing role {role_code}"
    db.add(UserRole(user_id=user.id, role_id=role.id, company_id=company.id))
    db.commit()
    clear_context(db)


def _create(client, auth, path, payload):
    return client.post(f"/api/v1/{path}", headers=auth["headers"], json=payload)


@pytest.fixture()
def dual_user(client, db_session):
    """hr_manager in company A, auditor in company B."""
    company_a = seed_company(db_session, "Dual A")
    company_b = seed_company(db_session, "Dual B")
    user = seed_user(db_session, "dual@example.com", company_a, "hr_manager")
    _grant_role(db_session, user, company_b, "auditor")
    return company_a, company_b, login(client, "dual@example.com")


def test_asymmetric_hr_manager_and_auditor_matrix(client, dual_user):
    company_a, company_b, auth = dual_user
    headers = auth["headers"]

    # Company A (hr_manager): may create and update, may not delete.
    dept = _create(
        client, auth, "departments",
        {"company_id": company_a.id, "code": "HR", "name_ar": "الموارد",
         "name_en": "HR"},
    )
    assert dept.status_code == 201, dept.text
    position = _create(
        client, auth, "job-positions",
        {"company_id": company_a.id, "code": "MGR", "name_ar": "مدير",
         "name_en": "Manager"},
    )
    assert position.status_code == 201, position.text
    grade = _create(
        client, auth, "job-grades",
        {"company_id": company_a.id, "code": "L5", "name_ar": "درجة 5",
         "name_en": "Level 5", "level": 5},
    )
    assert grade.status_code == 201, grade.text
    employee = _create(
        client, auth, "employees", {**BASE_EMPLOYEE, "company_id": company_a.id}
    )
    assert employee.status_code == 201, employee.text

    patched = client.patch(
        f"/api/v1/departments/{dept.json()['id']}",
        headers=headers,
        json={"description": "updated by hr manager"},
    )
    assert patched.status_code == 200

    assert (
        client.delete(
            f"/api/v1/employees/{employee.json()['id']}", headers=headers
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/api/v1/departments/{dept.json()['id']}", headers=headers
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/api/v1/job-positions/{position.json()['id']}", headers=headers
        ).status_code
        == 403
    )

    # Company B (auditor): read-only - no creates, no updates, no deletes.
    assert client.get("/api/v1/departments", headers=headers).status_code == 200
    assert client.get("/api/v1/job-positions", headers=headers).status_code == 200
    assert client.get("/api/v1/job-grades", headers=headers).status_code == 200
    assert client.get("/api/v1/employees", headers=headers).status_code == 200

    assert _create(
        client, auth, "departments",
        {"company_id": company_b.id, "code": "X", "name_ar": "قسم",
         "name_en": "X"},
    ).status_code == 403
    assert _create(
        client, auth, "job-positions",
        {"company_id": company_b.id, "code": "X", "name_ar": "منصب",
         "name_en": "X"},
    ).status_code == 403
    assert _create(
        client, auth, "job-grades",
        {"company_id": company_b.id, "code": "X", "name_ar": "درجة",
         "name_en": "X", "level": 1},
    ).status_code == 403
    assert _create(
        client, auth, "employees", {**BASE_EMPLOYEE, "company_id": company_b.id}
    ).status_code == 403

    # Reads stay scoped: company A rows must not leak into company B scope.
    scoped_b = client.get(
        "/api/v1/employees", headers=headers, params={"company_id": company_b.id}
    )
    assert scoped_b.status_code == 200
    assert scoped_b.json()["page"]["total"] == 0

    scoped_a = client.get(
        "/api/v1/employees", headers=headers, params={"company_id": company_a.id}
    )
    assert scoped_a.json()["page"]["total"] == 1


def test_auditor_only_user_is_read_only_everywhere(client, db_session):
    company = seed_company(db_session, "Auditor Matrix Co")
    seed_user(db_session, "auditor2@matrix.co", company, "auditor")
    auth = login(client, "auditor2@matrix.co")

    for path, payload in (
        ("departments", {"company_id": company.id, "code": "D",
                         "name_ar": "قسم", "name_en": "D"}),
        ("job-positions", {"company_id": company.id, "code": "P",
                           "name_ar": "منصب", "name_en": "P"}),
        ("job-grades", {"company_id": company.id, "code": "G",
                        "name_ar": "درجة", "name_en": "G", "level": 1}),
        ("employees", {**BASE_EMPLOYEE, "company_id": company.id}),
    ):
        assert _create(client, auth, path, payload).status_code == 403, path
        assert (
            client.get(f"/api/v1/{path}", headers=auth["headers"]).status_code
            == 200
        ), path


def test_platform_admin_accesses_all_companies(client, db_session):
    company_a = seed_company(db_session, "Admin Matrix A")
    company_b = seed_company(db_session, "Admin Matrix B")
    seed_user(db_session, "root@matrix.co", platform=True)
    auth = login(client, "root@matrix.co")

    created = _create(
        client, auth, "departments",
        {"company_id": company_b.id, "code": "ROOTDEPT", "name_ar": "قسم",
         "name_en": "Root Dept"},
    )
    assert created.status_code == 201, created.text

    for company in (company_a, company_b):
        page = client.get(
            "/api/v1/departments",
            headers=auth["headers"],
            params={"company_id": company.id},
        )
        assert page.status_code == 200


def test_user_without_roles_cannot_reach_phase2_endpoints(client, db_session):
    company = seed_company(db_session, "No Role Co")
    seed_user(db_session, "norole@matrix.co", company)
    auth = login(client, "norole@matrix.co")

    for path in (
        "departments",
        "job-positions",
        "job-grades",
        "employees",
    ):
        assert (
            client.get(f"/api/v1/{path}", headers=auth["headers"]).status_code
            == 403
        ), path
