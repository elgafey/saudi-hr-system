from __future__ import annotations

import json
import re

import pytest

from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db

_NUMBER_RE = re.compile(r"^E\d+-\d{6}$")

BASE_EMPLOYEE = {
    "first_name_ar": "نورة",
    "middle_name_ar": "محمد",
    "last_name_ar": "القحطاني",
    "first_name_en": "Noura",
    "middle_name_en": "Mohammed",
    "last_name_en": "Alqahtani",
}


def _create_employee(client, auth, company_id, **overrides):
    payload = {"company_id": company_id, **BASE_EMPLOYEE}
    payload.update(overrides)
    return client.post("/api/v1/employees", headers=auth["headers"], json=payload)


@pytest.fixture()
def emp_env(client, db_session):
    company = seed_company(db_session, "Emp Co")
    seed_user(db_session, "admin@emp.co", company, "company_admin")
    return company, login(client, "admin@emp.co")


def test_employee_auto_generated_number(client, emp_env):
    company, auth = emp_env
    created = _create_employee(client, auth, company.id)
    assert created.status_code == 201, created.text
    body = created.json()
    assert _NUMBER_RE.match(body["employee_number"]), body["employee_number"]
    assert body["employee_number"].startswith(f"E{company.id}-")
    assert body["status"] == "draft"
    assert body["employment_type"] == "full_time"
    assert body["nationality"] == "SA"

    second = _create_employee(client, auth, company.id, first_name_en="Reem")
    assert second.status_code == 201
    assert second.json()["employee_number"] != body["employee_number"]


def test_employee_explicit_number_and_duplicate(client, emp_env):
    company, auth = emp_env
    created = _create_employee(client, auth, company.id, employee_number="EMP-001")
    assert created.status_code == 201, created.text
    assert created.json()["employee_number"] == "EMP-001"

    duplicate = _create_employee(
        client, auth, company.id, employee_number="EMP-001",
        first_name_en="Other",
    )
    assert duplicate.status_code == 409
    assert "Employee number" in duplicate.json()["detail"]

    invalid = _create_employee(
        client, auth, company.id, employee_number="bad number!",
        first_name_en="Third",
    )
    assert invalid.status_code == 422


def test_same_employee_number_allowed_in_different_companies(client, db_session):
    company_a = seed_company(db_session, "Emp Num A")
    company_b = seed_company(db_session, "Emp Num B")
    seed_user(db_session, "admin@num-a.co", company_a, "company_admin")
    seed_user(db_session, "admin@num-b.co", company_b, "company_admin")

    auth_a = login(client, "admin@num-a.co")
    auth_b = login(client, "admin@num-b.co")

    first = _create_employee(client, auth_a, company_a.id, employee_number="SHARED")
    second = _create_employee(client, auth_b, company_b.id, employee_number="SHARED")
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text


def test_employee_identity_and_work_email_uniqueness(client, emp_env):
    company, auth = emp_env
    base = {
        "identity_type": "national_id",
        "identity_number": "1098765432",
        "work_email": "noura@example.com",
        "personal_email": "noura.personal@example.com",
    }
    assert _create_employee(client, auth, company.id, **base).status_code == 201

    dup_identity = _create_employee(
        client, auth, company.id, identity_type="national_id",
        identity_number="1098765432", first_name_en="Second",
        work_email="second@example.com",
    )
    assert dup_identity.status_code == 409
    assert "Identity number" in dup_identity.json()["detail"]

    dup_email = _create_employee(
        client, auth, company.id, work_email="noura@example.com",
        first_name_en="Third",
    )
    assert dup_email.status_code == 409
    assert "Work email" in dup_email.json()["detail"]


def test_identity_number_requires_identity_type(client, emp_env):
    company, auth = emp_env
    result = _create_employee(client, auth, company.id, identity_number="7654321")
    assert result.status_code == 422
    messages = json.dumps(result.json()["detail"])
    assert "identity_type" in messages


def test_identity_date_ordering_is_422(client, emp_env):
    company, auth = emp_env
    result = _create_employee(
        client,
        auth,
        company.id,
        identity_type="iqama",
        identity_number="2345678901",
        identity_issue_date="2025-05-01",
        identity_expiry_date="2024-05-01",
    )
    assert result.status_code == 422


def test_employee_enum_validation_is_422(client, emp_env):
    company, auth = emp_env
    assert _create_employee(client, auth, company.id, gender="other").status_code == 422
    assert (
        _create_employee(client, auth, company.id, status="archived").status_code
        == 422
    )
    assert (
        _create_employee(client, auth, company.id, employment_type="gig").status_code
        == 422
    )
    assert (
        _create_employee(client, auth, company.id, nationality="saudi").status_code
        == 422
    )


def test_cross_company_foreign_keys_are_404(client, db_session):
    company_a = seed_company(db_session, "Emp FK A")
    company_b = seed_company(db_session, "Emp FK B")
    seed_user(db_session, "admin@fk-a.co", company_a, "company_admin")
    seed_user(db_session, "admin@fk-b.co", company_b, "company_admin")

    auth_a = login(client, "admin@fk-a.co")
    auth_b = login(client, "admin@fk-b.co")

    branch = client.post(
        "/api/v1/branches",
        headers=auth_b["headers"],
        json={"company_id": company_b.id, "name": "B Branch", "code": "BB"},
    ).json()
    dept = client.post(
        "/api/v1/departments",
        headers=auth_b["headers"],
        json={
            "company_id": company_b.id,
            "code": "BDEPT",
            "name_ar": "قسم",
            "name_en": "B Dept",
        },
    ).json()
    position = client.post(
        "/api/v1/job-positions",
        headers=auth_b["headers"],
        json={
            "company_id": company_b.id,
            "code": "BPOS",
            "name_ar": "منصب",
            "name_en": "B Position",
        },
    ).json()
    grade = client.post(
        "/api/v1/job-grades",
        headers=auth_b["headers"],
        json={
            "company_id": company_b.id,
            "code": "BGRADE",
            "name_ar": "درجة",
            "name_en": "B Grade",
            "level": 1,
        },
    ).json()
    manager = _create_employee(client, auth_b, company_b.id)
    assert manager.status_code == 201, manager.text

    cases = {
        "branch_id": branch["id"],
        "department_id": dept["id"],
        "job_position_id": position["id"],
        "job_grade_id": grade["id"],
        "manager_id": manager.json()["id"],
    }
    for field, foreign_id in cases.items():
        result = _create_employee(
            client, auth_a, company_a.id, first_name_en=f"X{field}", **{field: foreign_id}
        )
        assert result.status_code == 404, f"{field}: {result.text}"
        assert result.json()["detail"].endswith("not found")


def test_employee_status_transitions_and_audit(client, emp_env):
    company, auth = emp_env
    employee = _create_employee(client, auth, company.id).json()
    assert employee["status"] == "draft"

    for status in ("active", "suspended", "terminated", "active"):
        response = client.patch(
            f"/api/v1/employees/{employee['id']}",
            headers=auth["headers"],
            json={"status": status},
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == status

    page = client.get(
        "/api/v1/audit-logs",
        headers=auth["headers"],
        params={"action": "employee.status_change"},
    )
    assert page.json()["page"]["total"] == 4
    latest = page.json()["items"][0]
    assert json.loads(latest["new_value"])["status"] == "active"


def test_employee_self_manager_conflict(client, emp_env):
    company, auth = emp_env
    employee = _create_employee(client, auth, company.id).json()
    response = client.patch(
        f"/api/v1/employees/{employee['id']}",
        headers=auth["headers"],
        json={"manager_id": employee["id"]},
    )
    assert response.status_code == 409
    assert "own manager" in response.json()["detail"]


def test_employee_delete_blocked_when_managing_others(client, emp_env):
    company, auth = emp_env
    manager = _create_employee(client, auth, company.id).json()
    report = _create_employee(
        client, auth, company.id, manager_id=manager["id"], first_name_en="Report"
    )
    assert report.status_code == 201, report.text

    blocked = client.delete(
        f"/api/v1/employees/{manager['id']}", headers=auth["headers"]
    )
    assert blocked.status_code == 409
    assert "manages other employees" in blocked.json()["detail"]

    # Delete the report first, then the manager can be deleted.
    assert (
        client.delete(
            f"/api/v1/employees/{report.json()['id']}", headers=auth["headers"]
        ).status_code
        == 204
    )
    assert (
        client.delete(
            f"/api/v1/employees/{manager['id']}", headers=auth["headers"]
        ).status_code
        == 204
    )


def test_employee_list_search_and_filters(client, emp_env):
    company, auth = emp_env
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
    _create_employee(
        client, auth, company.id, employee_number="EMP-A",
        first_name_en="Alice", status="active", department_id=dept["id"],
    )
    _create_employee(
        client, auth, company.id, employee_number="EMP-B",
        first_name_en="Bob", status="draft",
    )
    _create_employee(
        client, auth, company.id, employee_number="EMP-C",
        first_name_en="Carol", status="terminated",
    )

    by_number = client.get(
        "/api/v1/employees", headers=auth["headers"], params={"search": "EMP-A"}
    )
    assert by_number.json()["page"]["total"] == 1

    by_name = client.get(
        "/api/v1/employees", headers=auth["headers"], params={"search": "bob"}
    )
    assert by_name.json()["page"]["total"] == 1
    assert by_name.json()["items"][0]["first_name_en"] == "Bob"

    by_status = client.get(
        "/api/v1/employees",
        headers=auth["headers"],
        params={"status": "terminated"},
    )
    assert by_status.json()["page"]["total"] == 1

    by_dept = client.get(
        "/api/v1/employees",
        headers=auth["headers"],
        params={"department_id": dept["id"]},
    )
    assert by_dept.json()["page"]["total"] == 1

    page = client.get(
        "/api/v1/employees",
        headers=auth["headers"],
        params={"page": 2, "page_size": 2},
    )
    body = page.json()
    assert len(body["items"]) == 1
    assert body["page"] == {"page": 2, "page_size": 2, "total": 3}


def test_employee_cross_company_detail_is_404(client, db_session):
    company_a = seed_company(db_session, "Emp Iso A")
    company_b = seed_company(db_session, "Emp Iso B")
    seed_user(db_session, "admin@emp-a.co", company_a, "company_admin")
    seed_user(db_session, "admin@emp-b.co", company_b, "company_admin")

    auth_a = login(client, "admin@emp-a.co")
    employee = _create_employee(client, auth_a, company_a.id).json()

    auth_b = login(client, "admin@emp-b.co")
    assert (
        client.get(
            f"/api/v1/employees/{employee['id']}", headers=auth_b["headers"]
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/employees/{employee['id']}",
            headers=auth_b["headers"],
            json={"first_name_en": "Hijacked"},
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/employees/{employee['id']}", headers=auth_b["headers"]
        ).status_code
        == 404
    )

    client.cookies.clear()
    listing = client.get("/api/v1/employees", headers=auth_a["headers"])
    assert listing.json()["page"]["total"] == 1


def test_employee_update_audit_records_no_pii(client, emp_env):
    company, auth = emp_env
    employee = _create_employee(
        client,
        auth,
        company.id,
        employee_number="PII-1",
        work_email="pii@example.com",
    ).json()

    response = client.patch(
        f"/api/v1/employees/{employee['id']}",
        headers=auth["headers"],
        json={"first_name_en": "Renamed", "mobile_phone": "+966500000001"},
    )
    assert response.status_code == 200, response.text

    page = client.get(
        "/api/v1/audit-logs",
        headers=auth["headers"],
        params={"action": "employee.update"},
    )
    items = page.json()["items"]
    assert len(items) == 1
    new_value = json.loads(items[0]["new_value"])
    assert new_value["employee_number"] == "PII-1"
    assert sorted(new_value["fields"]) == ["first_name_en", "mobile_phone"]
    raw = items[0]["new_value"] + (items[0]["old_value"] or "")
    assert "Renamed" not in raw
    assert "Noura" not in raw
    assert "pii@example.com" not in raw
    assert "+966500000001" not in raw


def test_employee_update_duplicate_work_email_conflict(client, emp_env):
    company, auth = emp_env
    first = _create_employee(
        client, auth, company.id, work_email="first@example.com"
    ).json()
    second = _create_employee(
        client, auth, company.id, work_email="second@example.com",
        first_name_en="Second",
    ).json()

    conflict = client.patch(
        f"/api/v1/employees/{second['id']}",
        headers=auth["headers"],
        json={"work_email": "first@example.com"},
    )
    assert conflict.status_code == 409

    # Updating with the same value on the same record stays a no-op success.
    unchanged = client.patch(
        f"/api/v1/employees/{first['id']}",
        headers=auth["headers"],
        json={"work_email": "first@example.com"},
    )
    assert unchanged.status_code == 200


def test_employee_create_requires_permission(client, db_session):
    company = seed_company(db_session, "Emp Authz Co")
    seed_user(db_session, "officer@emp.co", company, "hr_officer")
    auth = login(client, "officer@emp.co")

    created = _create_employee(client, auth, company.id)
    assert created.status_code == 201, created.text

    # hr_officer cannot edit employees.
    update = client.patch(
        f"/api/v1/employees/{created.json()['id']}",
        headers=auth["headers"],
        json={"mobile_phone": "+966500000002"},
    )
    assert update.status_code == 403
