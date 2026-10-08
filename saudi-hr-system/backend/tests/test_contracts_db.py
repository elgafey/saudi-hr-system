from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "خالد",
        "last_name_ar": "الحربي",
        "first_name_en": "Khaled",
        "last_name_en": "Alharbi",
        **overrides,
    }
    response = client.post("/api/v1/employees", headers=auth["headers"], json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def contract_env(client, db_session):
    company = seed_company(db_session, "Contract Co")
    seed_user(db_session, "admin@contract.co", company, "company_admin")
    auth = login(client, "admin@contract.co")
    employee = _create_employee(client, auth, company.id)
    return SimpleNamespace(company=company, auth=auth, employee=employee)


def _base(**overrides):
    payload = {
        "company_id": None,  # filled per test
        "contract_type": "fixed_term",
        "start_date": "2025-01-01",
    }
    payload.update(overrides)
    return payload


def _url(env, contract_id=None):
    base = f"/api/v1/employees/{env.employee['id']}/contracts"
    return base if contract_id is None else f"{base}/{contract_id}"


def test_contract_create_defaults_and_list(client, contract_env):
    env = contract_env
    payload = _base(company_id=env.company.id, contract_number="C-001")
    created = client.post(_url(env), headers=env.auth["headers"], json=payload)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "draft"
    assert body["currency"] == "SAR"
    assert body["basic_salary"] is None
    assert body["employee_id"] == env.employee["id"]

    page = client.get(_url(env), headers=env.auth["headers"]).json()
    assert page["page"]["total"] == 1
    assert page["items"][0]["id"] == body["id"]


def test_one_active_contract_per_employee(client, contract_env):
    env = contract_env
    first = client.post(
        _url(env),
        headers=env.auth["headers"],
        json=_base(company_id=env.company.id, status="active", start_date="2025-01-01"),
    )
    assert first.status_code == 201, first.text

    second = client.post(
        _url(env),
        headers=env.auth["headers"],
        json=_base(company_id=env.company.id, status="active", start_date="2025-02-01"),
    )
    assert second.status_code == 409
    assert second.json()["code"] == "CONTRACT_ACTIVE_EXISTS"

    # Drafts coexist freely alongside the active contract.
    draft = client.post(
        _url(env),
        headers=env.auth["headers"],
        json=_base(company_id=env.company.id, contract_number="C-draft"),
    )
    assert draft.status_code == 201, draft.text


def test_activating_second_contract_conflicts(client, contract_env):
    env = contract_env
    active = client.post(
        _url(env),
        headers=env.auth["headers"],
        json=_base(company_id=env.company.id, status="active"),
    )
    draft = client.post(
        _url(env),
        headers=env.auth["headers"],
        json=_base(company_id=env.company.id, contract_number="C-2"),
    )
    assert active.status_code == 201 and draft.status_code == 201

    promoted = client.patch(
        _url(env, draft.json()["id"]),
        headers=env.auth["headers"],
        json={"status": "active"},
    )
    assert promoted.status_code == 409
    assert promoted.json()["code"] == "CONTRACT_ACTIVE_EXISTS"

    # Terminating the active one frees the slot.
    terminated = client.patch(
        _url(env, active.json()["id"]),
        headers=env.auth["headers"],
        json={"status": "terminated", "termination_date": "2025-05-01"},
    )
    assert terminated.status_code == 200, terminated.text
    promoted = client.patch(
        _url(env, draft.json()["id"]),
        headers=env.auth["headers"],
        json={"status": "active"},
    )
    assert promoted.status_code == 200, promoted.text


def test_contract_date_rules(client, contract_env):
    env = contract_env
    end_before_start = client.post(
        _url(env),
        headers=env.auth["headers"],
        json=_base(company_id=env.company.id, end_date="2024-12-31"),
    )
    assert end_before_start.status_code == 400
    assert end_before_start.json()["code"] == "CONTRACT_INVALID_DATE_RANGE"

    termination_before_start = client.post(
        _url(env),
        headers=env.auth["headers"],
        json=_base(
            company_id=env.company.id, termination_date="2024-06-30",
            contract_number="C-t1",
        ),
    )
    assert termination_before_start.status_code == 400
    assert termination_before_start.json()["code"] == "CONTRACT_INVALID_DATE_RANGE"

    termination_after_end = client.post(
        _url(env),
        headers=env.auth["headers"],
        json=_base(
            company_id=env.company.id, end_date="2026-12-31",
            termination_date="2027-01-01", contract_number="C-t2",
        ),
    )
    assert termination_after_end.status_code == 400
    assert termination_after_end.json()["code"] == "CONTRACT_INVALID_DATE_RANGE"

    # Merged-state validation on update.
    valid = client.post(
        _url(env),
        headers=env.auth["headers"],
        json=_base(company_id=env.company.id, end_date="2026-12-31"),
    )
    assert valid.status_code == 201, valid.text
    broken = client.patch(
        _url(env, valid.json()["id"]),
        headers=env.auth["headers"],
        json={"end_date": "2024-06-30"},
    )
    assert broken.status_code == 400
    assert broken.json()["code"] == "CONTRACT_INVALID_DATE_RANGE"


def test_contract_number_uniqueness_scoped_to_company(client, contract_env, db_session):
    env = contract_env
    first = client.post(
        _url(env),
        headers=env.auth["headers"],
        json=_base(company_id=env.company.id, contract_number="UNIQ-1"),
    )
    assert first.status_code == 201

    duplicate = client.post(
        _url(env),
        headers=env.auth["headers"],
        json=_base(company_id=env.company.id, contract_number="UNIQ-1"),
    )
    assert duplicate.status_code == 409
    assert "Contract number" in duplicate.json()["detail"]

    other = seed_company(db_session, "Contract Other Co")
    seed_user(db_session, "admin@contract-other.co", other, "company_admin")
    other_auth = login(client, "admin@contract-other.co")
    other_employee = _create_employee(client, other_auth, other.id)
    shared = client.post(
        f"/api/v1/employees/{other_employee['id']}/contracts",
        headers=other_auth["headers"],
        json={"company_id": other.id, "contract_type": "fixed_term",
              "start_date": "2025-01-01", "contract_number": "UNIQ-1"},
    )
    assert shared.status_code == 201, shared.text


def test_contract_status_filter_and_get(client, contract_env):
    env = contract_env
    active = client.post(
        _url(env),
        headers=env.auth["headers"],
        json=_base(company_id=env.company.id, status="active"),
    ).json()
    client.post(
        _url(env),
        headers=env.auth["headers"],
        json=_base(company_id=env.company.id, contract_number="C-d"),
    )

    filtered = client.get(
        _url(env), headers=env.auth["headers"], params={"status": "active"}
    ).json()
    assert filtered["page"]["total"] == 1
    assert filtered["items"][0]["id"] == active["id"]

    detail = client.get(_url(env, active["id"]), headers=env.auth["headers"])
    assert detail.status_code == 200
    assert detail.json()["id"] == active["id"]


def test_contract_invalid_enum_is_422(client, contract_env):
    env = contract_env
    bad_type = client.post(
        _url(env),
        headers=env.auth["headers"],
        json=_base(company_id=env.company.id, contract_type="Fixed Term!"),
    )
    assert bad_type.status_code == 422

    bad_status = client.post(
        _url(env),
        headers=env.auth["headers"],
        json=_base(company_id=env.company.id, status="banana"),
    )
    assert bad_status.status_code == 422


def test_contract_delete_and_audit(client, contract_env):
    env = contract_env
    contract = client.post(
        _url(env),
        headers=env.auth["headers"],
        json=_base(company_id=env.company.id, status="active"),
    ).json()

    response = client.delete(_url(env, contract["id"]), headers=env.auth["headers"])
    assert response.status_code == 204
    assert client.get(_url(env, contract["id"]), headers=env.auth["headers"]).status_code == 404

    page = client.get(_url(env), headers=env.auth["headers"]).json()
    assert page["page"]["total"] == 0

    for action in ("contract.create", "contract.delete"):
        audit = client.get(
            "/api/v1/audit-logs", headers=env.auth["headers"],
            params={"action": action},
        ).json()
        assert audit["page"]["total"] == 1, action
        assert audit["items"][0]["entity"] == "employee_contract"


def test_contract_update_audits_field_names_only(client, contract_env):
    import json

    env = contract_env
    contract = client.post(
        _url(env),
        headers=env.auth["headers"],
        json=_base(company_id=env.company.id, basic_salary="15000.00"),
    ).json()

    updated = client.patch(
        _url(env, contract["id"]),
        headers=env.auth["headers"],
        json={"basic_salary": "16000.00", "notes": "raised"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["basic_salary"] == "16000.00"

    audit = client.get(
        "/api/v1/audit-logs", headers=env.auth["headers"],
        params={"action": "contract.update"},
    ).json()
    assert audit["page"]["total"] == 1
    new_value = json.loads(audit["items"][0]["new_value"])
    assert set(new_value["fields"]) == {"basic_salary", "notes"}


def test_contract_of_other_employee_is_404(client, contract_env):
    env = contract_env
    contract = client.post(
        _url(env),
        headers=env.auth["headers"],
        json=_base(company_id=env.company.id),
    ).json()
    other = _create_employee(client, env.auth, env.company.id, first_name_en="Other")

    response = client.get(
        f"/api/v1/employees/{other['id']}/contracts/{contract['id']}",
        headers=env.auth["headers"],
    )
    assert response.status_code == 404
    assert response.json()["code"] == "CONTRACT_NOT_FOUND"


def test_contract_missing_employee_is_404_with_code(client, contract_env):
    response = client.get(
        "/api/v1/employees/999999/contracts", headers=contract_env.auth["headers"]
    )
    assert response.status_code == 404
    assert response.json()["code"] == "EMPLOYEE_NOT_FOUND"
