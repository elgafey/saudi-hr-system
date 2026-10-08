from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "منيرة",
        "last_name_ar": "الشهري",
        "first_name_en": "Munira",
        "last_name_en": "Alshehri",
        **overrides,
    }
    response = client.post("/api/v1/employees", headers=auth["headers"], json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def hist_env(client, db_session):
    company = seed_company(db_session, "Hist Co")
    seed_user(db_session, "admin@hist.co", company, "company_admin")
    auth = login(client, "admin@hist.co")
    employee = _create_employee(client, auth, company.id)
    department = client.post(
        "/api/v1/departments",
        headers=auth["headers"],
        json={"company_id": company.id, "code": "OPS", "name_ar": "العمليات",
              "name_en": "Operations"},
    )
    assert department.status_code == 201, department.text
    grade = client.post(
        "/api/v1/job-grades",
        headers=auth["headers"],
        json={"company_id": company.id, "code": "G1", "name_ar": "الدرجة الأولى",
              "name_en": "Grade 1", "level": 1},
    )
    assert grade.status_code == 201, grade.text
    return SimpleNamespace(
        company=company, auth=auth, employee=employee,
        department=department.json(), grade=grade.json(),
    )


def _url(env, employee_id=None):
    emp = employee_id if employee_id is not None else env.employee["id"]
    return f"/api/v1/employees/{emp}/employment-history"


def _payload(env, **overrides):
    payload = {
        "company_id": env.company.id,
        "effective_from": "2024-01-01",
        "employment_status": "active",
        "employment_type": "full_time",
    }
    payload.update(overrides)
    return payload


def test_history_create_and_list(client, hist_env):
    env = hist_env
    created = client.post(
        _url(env), headers=env.auth["headers"],
        json=_payload(env, effective_to="2024-12-31", change_reason="hire"),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["employment_status"] == "active"
    assert body["change_reason"] == "hire"

    page = client.get(_url(env), headers=env.auth["headers"]).json()
    assert page["page"]["total"] == 1
    assert page["items"][0]["id"] == body["id"]


def test_history_apply_to_employee_updates_master(client, hist_env):
    env = hist_env
    created = client.post(
        _url(env), headers=env.auth["headers"],
        json=_payload(
            env,
            department_id=env.department["id"],
            grade_id=env.grade["id"],
            employment_type="part_time",
            apply_to_employee=True,
        ),
    )
    assert created.status_code == 201, created.text

    detail = client.get(
        f"/api/v1/employees/{env.employee['id']}", headers=env.auth["headers"]
    ).json()
    assert detail["department_id"] == env.department["id"]
    assert detail["job_grade_id"] == env.grade["id"]
    assert detail["employment_type"] == "part_time"


def test_history_without_apply_keeps_master_untouched(client, hist_env):
    env = hist_env
    created = client.post(
        _url(env), headers=env.auth["headers"],
        json=_payload(env, department_id=env.department["id"],
                      apply_to_employee=False),
    )
    assert created.status_code == 201, created.text

    detail = client.get(
        f"/api/v1/employees/{env.employee['id']}", headers=env.auth["headers"]
    ).json()
    assert detail["department_id"] is None


def test_history_overlap_rejected_with_code(client, hist_env):
    env = hist_env
    first = client.post(
        _url(env), headers=env.auth["headers"],
        json=_payload(env, effective_from="2024-01-01", effective_to="2024-06-30"),
    )
    assert first.status_code == 201, first.text

    overlapping = client.post(
        _url(env), headers=env.auth["headers"],
        json=_payload(env, effective_from="2024-03-01", effective_to="2024-05-31"),
    )
    assert overlapping.status_code == 409
    assert overlapping.json()["code"] == "EMPLOYEE_HISTORY_OVERLAP"

    touching = client.post(
        _url(env), headers=env.auth["headers"],
        json=_payload(env, effective_from="2024-06-30", effective_to="2024-07-31"),
    )
    assert touching.status_code == 409  # closed-open intervals: same day overlaps

    adjacent = client.post(
        _url(env), headers=env.auth["headers"],
        json=_payload(env, effective_from="2024-07-01", effective_to="2024-09-30"),
    )
    assert adjacent.status_code == 201, adjacent.text


def test_history_gap_between_periods_allowed(client, hist_env):
    env = hist_env
    client.post(
        _url(env), headers=env.auth["headers"],
        json=_payload(env, effective_from="2024-01-01", effective_to="2024-06-30"),
    )
    client.post(
        _url(env), headers=env.auth["headers"],
        json=_payload(env, effective_from="2025-01-01"),  # open record
    )
    gap = client.post(
        _url(env), headers=env.auth["headers"],
        json=_payload(env, effective_from="2024-07-01", effective_to="2024-09-30",
                      apply_to_employee=False),
    )
    assert gap.status_code == 201, gap.text


def test_history_new_period_auto_closes_open_record(client, hist_env):
    env = hist_env
    open_row = client.post(
        _url(env), headers=env.auth["headers"],
        json=_payload(env, effective_from="2025-01-01"),
    ).json()

    successor = client.post(
        _url(env), headers=env.auth["headers"],
        json=_payload(env, effective_from="2025-07-01"),
    )
    assert successor.status_code == 201, successor.text
    assert successor.json()["effective_from"] == "2025-07-01"
    assert successor.json()["effective_to"] is None

    page = client.get(_url(env), headers=env.auth["headers"]).json()
    assert page["page"]["total"] == 2
    by_id = {row["id"]: row for row in page["items"]}
    assert by_id[open_row["id"]]["effective_to"] == "2025-06-30"

    # A third period closes the second one too.
    third = client.post(
        _url(env), headers=env.auth["headers"],
        json=_payload(env, effective_from="2026-01-01"),
    )
    assert third.status_code == 201, third.text
    page = client.get(_url(env), headers=env.auth["headers"]).json()
    open_rows = [r for r in page["items"] if r["effective_to"] is None]
    assert len(open_rows) == 1
    assert open_rows[0]["id"] == third.json()["id"]


def test_history_same_day_open_record_rejected(client, hist_env):
    env = hist_env
    client.post(_url(env), headers=env.auth["headers"], json=_payload(env))
    duplicate = client.post(_url(env), headers=env.auth["headers"], json=_payload(env))
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "EMPLOYEE_HISTORY_OVERLAP"


def test_history_date_ordering_is_rejected(client, hist_env):
    env = hist_env
    response = client.post(
        _url(env), headers=env.auth["headers"],
        json=_payload(env, effective_from="2025-01-01", effective_to="2024-01-01"),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "EMPLOYEE_HISTORY_INVALID_DATE_RANGE"


def test_history_foreign_key_must_belong_to_company(client, hist_env, db_session):
    env = hist_env
    other = seed_company(db_session, "Hist Other Co")
    seed_user(db_session, "admin@hist-other.co", other, "company_admin")
    other_auth = login(client, "admin@hist-other.co")
    foreign_department = client.post(
        "/api/v1/departments",
        headers=other_auth["headers"],
        json={"company_id": other.id, "code": "FOPS", "name_ar": "x",
              "name_en": "Foreign Ops"},
    )
    assert foreign_department.status_code == 201, foreign_department.text

    response = client.post(
        _url(env), headers=env.auth["headers"],
        json=_payload(env, department_id=foreign_department.json()["id"]),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_employee_update_appends_history_automatically(client, hist_env):
    env = hist_env
    response = client.patch(
        f"/api/v1/employees/{env.employee['id']}",
        headers=env.auth["headers"],
        json={"department_id": env.department["id"]},
    )
    assert response.status_code == 200, response.text

    page = client.get(_url(env), headers=env.auth["headers"]).json()
    assert page["page"]["total"] == 1
    row = page["items"][0]
    assert row["department_id"] == env.department["id"]
    assert row["effective_to"] is None
    assert row["change_reason"] == "employee_update"

    # A second same-day change amends the open record instead of appending.
    response = client.patch(
        f"/api/v1/employees/{env.employee['id']}",
        headers=env.auth["headers"],
        json={"job_grade_id": env.grade["id"]},
    )
    assert response.status_code == 200, response.text
    page = client.get(_url(env), headers=env.auth["headers"]).json()
    assert page["page"]["total"] == 1
    assert page["items"][0]["grade_id"] == env.grade["id"]


def test_employee_update_splits_past_open_record(client, hist_env):
    env = hist_env
    past = client.post(
        _url(env), headers=env.auth["headers"],
        json=_payload(env, effective_from="2024-01-01", apply_to_employee=False),
    )
    assert past.status_code == 201, past.text

    response = client.patch(
        f"/api/v1/employees/{env.employee['id']}",
        headers=env.auth["headers"],
        json={"department_id": env.department["id"]},
    )
    assert response.status_code == 200, response.text

    page = client.get(_url(env), headers=env.auth["headers"]).json()
    assert page["page"]["total"] == 2
    rows = sorted(page["items"], key=lambda r: r["effective_from"])
    assert rows[0]["id"] == past.json()["id"]
    assert rows[0]["effective_to"] is not None  # closed at yesterday
    assert rows[1]["effective_to"] is None
    assert rows[1]["department_id"] == env.department["id"]


def test_employee_non_org_update_appends_nothing(client, hist_env):
    env = hist_env
    response = client.patch(
        f"/api/v1/employees/{env.employee['id']}",
        headers=env.auth["headers"],
        json={"mobile_phone": "+966500000001"},
    )
    assert response.status_code == 200, response.text
    page = client.get(_url(env), headers=env.auth["headers"]).json()
    assert page["page"]["total"] == 0


def test_history_self_manager_rejected(client, hist_env):
    env = hist_env
    response = client.post(
        _url(env), headers=env.auth["headers"],
        json=_payload(env, manager_id=env.employee["id"]),
    )
    assert response.status_code == 409


def test_history_missing_employee_is_404_with_code(client, hist_env):
    response = client.get(
        "/api/v1/employees/999999/employment-history",
        headers=hist_env.auth["headers"],
    )
    assert response.status_code == 404
    assert response.json()["code"] == "EMPLOYEE_NOT_FOUND"


def test_history_audit_actions(client, hist_env):
    env = hist_env
    client.post(_url(env), headers=env.auth["headers"], json=_payload(env))
    client.patch(
        f"/api/v1/employees/{env.employee['id']}",
        headers=env.auth["headers"],
        json={"department_id": env.department["id"]},
    )
    audit = client.get(
        "/api/v1/audit-logs", headers=env.auth["headers"],
        params={"action": "employment_history.create"},
    ).json()
    # one explicit create + one auto append from the employee PATCH
    assert audit["page"]["total"] == 2
    assert all(i["entity"] == "employee_employment_history" for i in audit["items"])
