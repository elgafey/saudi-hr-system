from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


def _create_type(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "code": "ANNUAL",
        "name_ar": "اجازة سنوية",
        "name_en": "Annual Leave",
        **overrides,
    }
    response = client.post(
        "/api/v1/leave-types", headers=auth["headers"], json=payload
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "Nora",
        "last_name_ar": "Alharbi",
        "first_name_en": "Nora",
        "last_name_en": "Alharbi",
        "status": "active",
        **overrides,
    }
    response = client.post(
        "/api/v1/employees", headers=auth["headers"], json=payload
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def type_env(client, db_session):
    company = seed_company(db_session, "LV Types")
    other = seed_company(db_session, "LV Other")
    seed_user(db_session, "admin@lv.co", company, "company_admin")
    seed_user(db_session, "manager@lv.co", company, "hr_manager")
    seed_user(db_session, "officer@lv.co", company, "hr_officer")
    seed_user(db_session, "auditor@lv.co", company, "auditor")
    seed_user(db_session, "roleless@lv.co", company)
    seed_user(db_session, "admin@lv-other.co", other, "company_admin")

    admin = login(client, "admin@lv.co")
    annual = _create_type(client, admin, company.id)
    employee = _create_employee(client, admin, company.id)
    return SimpleNamespace(
        company=company,
        other=other,
        admin=admin,
        manager=login(client, "manager@lv.co"),
        officer=login(client, "officer@lv.co"),
        auditor=login(client, "auditor@lv.co"),
        roleless=login(client, "roleless@lv.co"),
        other_admin=login(client, "admin@lv-other.co"),
        annual=annual,
        employee=employee,
    )


def _rule_payload(company_id, **overrides):
    payload = {
        "company_id": company_id,
        "statutory_key": "annual_leave",
        "effective_from": "2025-01-01",
        "effective_to": "2025-06-30",
        "source_reference": "Ministry of HR circular 1/2025",
        "rule_json": {"days": 21},
    }
    payload.update(overrides)
    return payload


def test_leave_type_crud_lifecycle(client, type_env):
    env = type_env
    auth = env.admin

    created = env.annual
    assert created["code"] == "ANNUAL"
    assert created["status"] == "active"
    assert created["requires_approval"] is True
    assert created["day_counting_mode"] == "working_days"
    type_id = created["id"]

    read = client.get(f"/api/v1/leave-types/{type_id}", headers=auth["headers"])
    assert read.status_code == 200, read.text
    assert read.json()["name_en"] == "Annual Leave"

    updated = client.patch(
        f"/api/v1/leave-types/{type_id}",
        headers=auth["headers"],
        json={"name_en": "Annual (updated)", "sort_order": 3},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name_en"] == "Annual (updated)"
    assert updated.json()["sort_order"] == 3

    duplicate = client.post(
        "/api/v1/leave-types",
        headers=auth["headers"],
        json={
            "company_id": env.company.id,
            "code": "ANNUAL",
            "name_ar": "مكرر",
            "name_en": "Duplicate",
        },
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["code"] == "LEAVE_TYPE_CODE_EXISTS"

    bad_range = client.post(
        "/api/v1/leave-types",
        headers=auth["headers"],
        json={
            "company_id": env.company.id,
            "code": "BADRANGE",
            "name_ar": "خطأ",
            "name_en": "Bad range",
            "min_request_days": "5",
            "max_request_days": "2",
        },
    )
    assert bad_range.status_code == 400, bad_range.text
    assert bad_range.json()["code"] == "LEAVE_TYPE_INVALID_RANGE"

    page = client.get(
        "/api/v1/leave-types",
        headers=auth["headers"],
        params={"company_id": env.company.id, "status": "active"},
    ).json()
    assert page["page"]["total"] == 1
    assert page["items"][0]["code"] == "ANNUAL"

    searched = client.get(
        "/api/v1/leave-types",
        headers=auth["headers"],
        params={"company_id": env.company.id, "q": "updated"},
    ).json()
    assert searched["page"]["total"] == 1

    removed = client.delete(
        f"/api/v1/leave-types/{type_id}", headers=auth["headers"]
    )
    assert removed.status_code == 204, removed.text
    assert (
        client.get(
            f"/api/v1/leave-types/{type_id}", headers=auth["headers"]
        ).status_code
        == 404
    )


def test_leave_type_delete_blocked_when_referenced(client, type_env):
    env = type_env
    auth = env.admin
    allocation = client.post(
        "/api/v1/leave-allocations",
        headers=auth["headers"],
        json={
            "employee_id": env.employee["id"],
            "leave_type_id": env.annual["id"],
            "period_start": "2025-01-01",
            "period_end": "2025-12-31",
            "allocated_days": "21.00",
        },
    )
    assert allocation.status_code == 201, allocation.text

    blocked = client.delete(
        f"/api/v1/leave-types/{env.annual['id']}", headers=auth["headers"]
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["code"] == "LEAVE_TYPE_IN_USE"

    freed = client.delete(
        f"/api/v1/leave-allocations/{allocation.json()['id']}",
        headers=auth["headers"],
    )
    assert freed.status_code == 204, freed.text
    removed = client.delete(
        f"/api/v1/leave-types/{env.annual['id']}", headers=auth["headers"]
    )
    assert removed.status_code == 204, removed.text


def test_inactive_leave_type_blocks_new_usage(client, type_env):
    env = type_env
    auth = env.admin

    toggled = client.patch(
        f"/api/v1/leave-types/{env.annual['id']}",
        headers=auth["headers"],
        json={"status": "inactive"},
    )
    assert toggled.status_code == 200, toggled.text
    assert toggled.json()["status"] == "inactive"

    allocation = client.post(
        "/api/v1/leave-allocations",
        headers=auth["headers"],
        json={
            "employee_id": env.employee["id"],
            "leave_type_id": env.annual["id"],
            "period_start": "2025-01-01",
            "period_end": "2025-12-31",
            "allocated_days": "10.00",
        },
    )
    assert allocation.status_code == 409, allocation.text
    assert allocation.json()["code"] == "LEAVE_TYPE_INACTIVE"

    request = client.post(
        "/api/v1/leave-requests",
        headers=auth["headers"],
        json={
            "employee_id": env.employee["id"],
            "leave_type_id": env.annual["id"],
            "start_date": "2025-03-02",
            "end_date": "2025-03-06",
        },
    )
    assert request.status_code == 409, request.text
    assert request.json()["code"] == "LEAVE_TYPE_INACTIVE"


def test_role_matrix_on_leave_types(client, type_env):
    env = type_env

    assert (
        client.get(
            "/api/v1/leave-types", headers=env.roleless["headers"]
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/leave-types",
            headers=env.roleless["headers"],
            json={
                "company_id": env.company.id,
                "code": "NOPE",
                "name_ar": "x",
                "name_en": "x",
            },
        ).status_code
        == 403
    )

    assert (
        client.get(
            "/api/v1/leave-types", headers=env.auditor["headers"]
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/leave-types",
            headers=env.auditor["headers"],
            json={
                "company_id": env.company.id,
                "code": "AUDT",
                "name_ar": "x",
                "name_en": "x",
            },
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/v1/leave-types/{env.annual['id']}",
            headers=env.auditor["headers"],
            json={"name_en": "tampered"},
        ).status_code
        == 403
    )

    # hr_officer may read types but never create or edit them.
    assert (
        client.get(
            "/api/v1/leave-types", headers=env.officer["headers"]
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/leave-types",
            headers=env.officer["headers"],
            json={
                "company_id": env.company.id,
                "code": "OFFC",
                "name_ar": "x",
                "name_en": "x",
            },
        ).status_code
        == 403
    )

    # hr_manager manages types but has no delete permission.
    created = client.post(
        "/api/v1/leave-types",
        headers=env.manager["headers"],
        json={
            "company_id": env.company.id,
            "code": "MGR",
            "name_ar": "x",
            "name_en": "Manager type",
        },
    )
    assert created.status_code == 201, created.text
    assert (
        client.delete(
            f"/api/v1/leave-types/{created.json()['id']}",
            headers=env.manager["headers"],
        ).status_code
        == 403
    )


def test_statutory_rule_requires_source_and_versions_adjacent_windows(
    client, type_env
):
    env = type_env
    auth = env.admin
    base = env.company.id

    empty_source = client.post(
        "/api/v1/leave-statutory-rules",
        headers=auth["headers"],
        json=_rule_payload(base, source_reference=""),
    )
    assert empty_source.status_code == 422, empty_source.text

    blank_source = client.post(
        "/api/v1/leave-statutory-rules",
        headers=auth["headers"],
        json=_rule_payload(base, source_reference="   "),
    )
    assert blank_source.status_code == 400, blank_source.text
    assert blank_source.json()["code"] == "STATUTORY_RULE_SOURCE_REQUIRED"

    bad_dates = client.post(
        "/api/v1/leave-statutory-rules",
        headers=auth["headers"],
        json=_rule_payload(base, effective_to="2025-01-01"),
    )
    assert bad_dates.status_code == 400, bad_dates.text
    assert bad_dates.json()["code"] == "STATUTORY_RULE_INVALID_DATE_RANGE"

    v1 = client.post(
        "/api/v1/leave-statutory-rules",
        headers=auth["headers"],
        json=_rule_payload(base),
    )
    assert v1.status_code == 201, v1.text
    body = v1.json()
    assert body["version"] == 1
    assert body["jurisdiction"] == "SA"
    assert body["requires_legal_verification"] is True
    assert body["status"] == "active"

    # Adjacent window (v2 starts exactly where v1 ends) is legal.
    v2 = client.post(
        "/api/v1/leave-statutory-rules",
        headers=auth["headers"],
        json=_rule_payload(
            base, effective_from="2025-06-30", effective_to=None,
            rule_json={"days": 15},
        ),
    )
    assert v2.status_code == 201, v2.text
    assert v2.json()["version"] == 2

    overlapping = client.post(
        "/api/v1/leave-statutory-rules",
        headers=auth["headers"],
        json=_rule_payload(base, effective_from="2025-05-01"),
    )
    assert overlapping.status_code == 409, overlapping.text
    assert overlapping.json()["code"] == "STATUTORY_RULE_OVERLAP"

    second_open_ended = client.post(
        "/api/v1/leave-statutory-rules",
        headers=auth["headers"],
        json=_rule_payload(
            base,
            statutory_key="other_key",
            effective_from="2024-01-01",
            effective_to=None,
        ),
    )
    assert second_open_ended.status_code == 201, second_open_ended.text

    # Same key, open-ended version from the past would cover v1 entirely.
    covering = client.post(
        "/api/v1/leave-statutory-rules",
        headers=auth["headers"],
        json=_rule_payload(base, effective_from="2024-01-01", effective_to=None),
    )
    assert covering.status_code == 409, covering.text
    assert covering.json()["code"] == "STATUTORY_RULE_OVERLAP"

    march = client.get(
        "/api/v1/leave-statutory-rules",
        headers=auth["headers"],
        params={"statutory_key": "annual_leave", "as_of": "2025-03-01"},
    ).json()
    assert march["page"]["total"] == 1
    assert march["items"][0]["version"] == 1

    july = client.get(
        "/api/v1/leave-statutory-rules",
        headers=auth["headers"],
        params={"statutory_key": "annual_leave", "as_of": "2025-07-01"},
    ).json()
    assert july["page"]["total"] == 1
    assert july["items"][0]["version"] == 2

    read = client.get(
        f"/api/v1/leave-statutory-rules/{v1.json()['id']}",
        headers=auth["headers"],
    )
    assert read.status_code == 200, read.text

    deactivated = client.post(
        f"/api/v1/leave-statutory-rules/{v2.json()['id']}/deactivate",
        headers=auth["headers"],
        json={"reason": "superseded"},
    )
    assert deactivated.status_code == 200, deactivated.text
    assert deactivated.json()["status"] == "inactive"

    again = client.post(
        f"/api/v1/leave-statutory-rules/{v2.json()['id']}/deactivate",
        headers=auth["headers"],
        json={},
    )
    assert again.status_code == 409, again.text


def test_statutory_rule_permissions(client, type_env):
    env = type_env
    payload = _rule_payload(env.company.id, statutory_key="sick_leave")

    assert (
        client.post(
            "/api/v1/leave-statutory-rules",
            headers=env.auditor["headers"],
            json=payload,
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/api/v1/leave-statutory-rules", headers=env.auditor["headers"]
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/leave-statutory-rules",
            headers=env.officer["headers"],
            json=payload,
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/leave-statutory-rules",
            headers=env.roleless["headers"],
            json=payload,
        ).status_code
        == 403
    )


def test_cross_company_type_and_rule_access(client, type_env):
    env = type_env
    headers = env.other_admin["headers"]

    assert (
        client.get(
            f"/api/v1/leave-types/{env.annual['id']}", headers=headers
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/leave-types/{env.annual['id']}",
            headers=headers,
            json={"name_en": "hijack"},
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/leave-types/{env.annual['id']}", headers=headers
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/api/v1/leave-types",
            headers=headers,
            params={"company_id": env.company.id},
        ).status_code
        == 403
    )
