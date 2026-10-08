from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "عبدالله",
        "last_name_ar": "الدوسري",
        "first_name_en": "Abdullah",
        "last_name_en": "Aldosari",
        **overrides,
    }
    response = client.post("/api/v1/employees", headers=auth["headers"], json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def link_env(client, db_session):
    company = seed_company(db_session, "Link Co")
    seed_user(db_session, "admin@link.co", company, "company_admin")
    auth = login(client, "admin@link.co")
    employee = _create_employee(client, auth, company.id)
    target = seed_user(db_session, "worker@link.co", company)
    other = seed_user(db_session, "other-worker@link.co", company)
    return SimpleNamespace(
        company=company, auth=auth, employee=employee, target=target, other=other
    )


def _url(env, employee_id=None):
    emp = employee_id if employee_id is not None else env.employee["id"]
    return f"/api/v1/employees/{emp}/user"


def test_link_state_starts_empty(client, link_env):
    env = link_env
    response = client.get(_url(env), headers=env.auth["headers"])
    assert response.status_code == 200
    assert response.json() == {"linked": False, "user": None}


def test_link_and_unlink_cycle(client, link_env):
    env = link_env
    linked = client.post(
        _url(env), headers=env.auth["headers"], json={"user_id": env.target.id}
    )
    assert linked.status_code == 200, linked.text
    body = linked.json()
    assert body["linked"] is True
    assert body["user"]["id"] == env.target.id
    assert body["user"]["email"] == "worker@link.co"

    state = client.get(_url(env), headers=env.auth["headers"]).json()
    assert state["linked"] is True

    audit = client.get(
        "/api/v1/audit-logs", headers=env.auth["headers"],
        params={"action": "employee_user_link.link"},
    ).json()
    assert audit["page"]["total"] == 1
    import json

    assert json.loads(audit["items"][0]["new_value"]) == {
        "user_id": env.target.id, "employee_id": env.employee["id"],
    }

    removed = client.delete(_url(env), headers=env.auth["headers"])
    assert removed.status_code == 204
    state = client.get(_url(env), headers=env.auth["headers"]).json()
    assert state["linked"] is False

    # The account itself survives the unlink untouched.
    kept = client.get(f"/api/v1/users/{env.target.id}", headers=env.auth["headers"])
    assert kept.status_code == 200
    assert kept.json()["email"] == "worker@link.co"

    audit = client.get(
        "/api/v1/audit-logs", headers=env.auth["headers"],
        params={"action": "employee_user_link.unlink"},
    ).json()
    assert audit["page"]["total"] == 1


def test_double_link_rejected(client, link_env):
    env = link_env
    first = client.post(
        _url(env), headers=env.auth["headers"], json={"user_id": env.target.id}
    )
    assert first.status_code == 200

    again_same = client.post(
        _url(env), headers=env.auth["headers"], json={"user_id": env.target.id}
    )
    assert again_same.status_code == 409
    assert again_same.json()["code"] == "EMPLOYEE_ALREADY_LINKED"

    other_employee = _create_employee(client, env.auth, env.company.id,
                                      first_name_en="Second")
    another_user = client.post(
        _url(env, other_employee["id"]),
        headers=env.auth["headers"],
        json={"user_id": env.target.id},
    )
    assert another_user.status_code == 409
    assert another_user.json()["code"] == "USER_ALREADY_LINKED"


def test_employee_with_link_rejects_second_user(client, link_env):
    env = link_env
    client.post(_url(env), headers=env.auth["headers"], json={"user_id": env.target.id})
    second = client.post(
        _url(env), headers=env.auth["headers"], json={"user_id": env.other.id}
    )
    assert second.status_code == 409
    assert second.json()["code"] == "EMPLOYEE_ALREADY_LINKED"


def test_link_unknown_user_is_404(client, link_env):
    env = link_env
    response = client.post(
        _url(env), headers=env.auth["headers"], json={"user_id": 999999}
    )
    assert response.status_code == 404
    assert response.json()["code"] == "USER_NOT_FOUND"


def test_unlink_without_link_is_404(client, link_env):
    response = client.delete(_url(link_env), headers=link_env.auth["headers"])
    assert response.status_code == 404
    assert response.json()["code"] == "USER_NOT_FOUND"


def test_cross_company_user_link_blocked(client, db_session):
    company_a = seed_company(db_session, "Link A")
    company_b = seed_company(db_session, "Link B")
    seed_user(db_session, "admin@link-a.co", company_a, "company_admin")
    seed_user(db_session, "admin@link-b.co", company_b, "company_admin")
    user_b = seed_user(db_session, "worker@link-b.co", company_b)

    auth_a = login(client, "admin@link-a.co")
    employee_a = _create_employee(client, auth_a, company_a.id)

    # Company A admin cannot even see company B's user (RLS hides it).
    hidden = client.post(
        f"/api/v1/employees/{employee_a['id']}/user",
        headers=auth_a["headers"],
        json={"user_id": user_b.id},
    )
    assert hidden.status_code == 404
    assert hidden.json()["code"] == "USER_NOT_FOUND"

    # A platform admin sees both, but the relation itself is still refused.
    seed_user(db_session, "root@platform.co", platform=True)
    root = login(client, "root@platform.co")
    blocked = client.post(
        f"/api/v1/employees/{employee_a['id']}/user",
        headers=root["headers"],
        json={"user_id": user_b.id},
    )
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "CROSS_COMPANY_RELATION"


def test_link_missing_employee_is_404_with_code(client, link_env):
    response = client.get(
        "/api/v1/employees/999999/user", headers=link_env.auth["headers"]
    )
    assert response.status_code == 404
    assert response.json()["code"] == "EMPLOYEE_NOT_FOUND"


def test_link_allows_roleless_user_in_same_company(client, link_env, db_session):
    env = link_env
    roleless = seed_user(db_session, "roleless@link.co", env.company)
    response = client.post(
        _url(env), headers=env.auth["headers"], json={"user_id": roleless.id}
    )
    assert response.status_code == 200, response.text
    assert response.json()["user"]["id"] == roleless.id
