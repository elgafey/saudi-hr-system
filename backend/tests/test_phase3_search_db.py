from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


@pytest.fixture()
def big_company(client, db_session):
    from app.core.rls import clear_context, elevate_for_seed

    company = seed_company(db_session, "Search Co")
    seed_user(db_session, "admin@search.co", company, "company_admin")

    elevate_for_seed(db_session)
    for i in range(210):
        db_session.execute(
            text(
                "INSERT INTO employees (company_id, employee_number, first_name_ar,"
                " last_name_ar, first_name_en, last_name_en, created_at, updated_at)"
                f" VALUES ({company.id}, 'SRCH-{i:04d}', 'N{i}', 'Test',"
                f" 'Search{i}', 'Employee', now(), now())"
            )
        )
        db_session.execute(
            text(
                "INSERT INTO users (email, full_name, password_hash, is_active,"
                " is_platform_admin, company_id, created_at, updated_at)"
                f" VALUES ('worker{i:04d}@search.co', 'Worker {i}', 'not-a-real-hash',"
                f" true, false, {company.id}, now(), now())"
            )
        )
    db_session.execute(
        text(
            "INSERT INTO users (email, full_name, password_hash, is_active,"
            " is_platform_admin, company_id, created_at, updated_at)"
            " VALUES ('needle@search.co', 'Hidden Needle', 'not-a-real-hash',"
            f" true, false, {company.id}, now(), now())"
        )
    )
    db_session.commit()
    clear_context(db_session)
    return company


def test_employee_search_reaches_rank_beyond_200(client, big_company):
    auth = login(client, "admin@search.co")

    # Without search, the target sits far beyond the first two pages.
    first_page = client.get(
        "/api/v1/employees",
        headers=auth["headers"],
        params={"company_id": big_company.id, "page": 1, "page_size": 50},
    ).json()
    assert first_page["page"]["total"] == 210
    assert len(first_page["items"]) == 50

    found = client.get(
        "/api/v1/employees",
        headers=auth["headers"],
        params={"company_id": big_company.id, "search": "SRCH-0205"},
    ).json()
    assert found["page"]["total"] == 1
    assert found["items"][0]["employee_number"] == "SRCH-0205"

    by_name = client.get(
        "/api/v1/employees",
        headers=auth["headers"],
        params={"company_id": big_company.id, "search": "Search205"},
    ).json()
    assert by_name["page"]["total"] == 1
    assert by_name["items"][0]["employee_number"] == "SRCH-0205"


def test_user_search_is_server_side_with_limit(client, big_company):
    auth = login(client, "admin@search.co")

    found = client.get(
        "/api/v1/users",
        headers=auth["headers"],
        params={"company_id": big_company.id, "search": "needle@search.co"},
    ).json()
    assert [u["email"] for u in found] == ["needle@search.co"]

    by_name = client.get(
        "/api/v1/users",
        headers=auth["headers"],
        params={"company_id": big_company.id, "search": "Hidden Needle"},
    ).json()
    assert [u["email"] for u in by_name] == ["needle@search.co"]

    limited = client.get(
        "/api/v1/users",
        headers=auth["headers"],
        params={"company_id": big_company.id, "search": "worker", "limit": 10},
    ).json()
    assert len(limited) == 10

    too_big = client.get(
        "/api/v1/users",
        headers=auth["headers"],
        params={"company_id": big_company.id, "limit": 101},
    )
    assert too_big.status_code == 422


def test_user_search_still_scopes_to_company(client, big_company, db_session):
    other = seed_company(db_session, "Search Other Co")
    seed_user(db_session, "outsider@search-other.co", other, "company_admin")

    auth = login(client, "admin@search.co")
    found = client.get(
        "/api/v1/users",
        headers=auth["headers"],
        params={"company_id": big_company.id, "search": "outsider"},
    ).json()
    assert found == []

    # The outsider cannot query the big company's directory at all.
    other_auth = login(client, "outsider@search-other.co")
    denied = client.get(
        "/api/v1/users",
        headers=other_auth["headers"],
        params={"company_id": big_company.id, "search": "worker"},
    )
    assert denied.status_code == 403
