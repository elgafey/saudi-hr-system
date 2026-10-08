from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import text

from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "Sara",
        "last_name_ar": "Alharbi",
        "first_name_en": "Sara",
        "last_name_en": "Alharbi",
        "status": "active",
        **overrides,
    }
    response = client.post(
        "/api/v1/employees", headers=auth["headers"], json=payload
    )
    assert response.status_code == 201, response.text
    return response.json()


def _rule_payload(company_id, **overrides):
    payload = {
        "company_id": company_id,
        "statutory_key": "annual_leave",
        "effective_from": "2025-01-01",
        "source_reference": "Ministry of HR circular 1/2025",
        "rule_json": {"days": 21},
    }
    payload.update(overrides)
    return payload


@pytest.fixture()
def leave_security_env(client, db_session):
    company_a = seed_company(db_session, "LVSec A")
    company_b = seed_company(db_session, "LVSec B")
    seed_user(db_session, "admin@lvsec-a.co", company_a, "company_admin")
    seed_user(db_session, "auditor@lvsec-a.co", company_a, "auditor")
    seed_user(db_session, "officer@lvsec-a.co", company_a, "hr_officer")
    seed_user(db_session, "manager@lvsec-a.co", company_a, "hr_manager")
    seed_user(db_session, "noperm@lvsec-a.co", company_a)
    seed_user(db_session, "admin@lvsec-b.co", company_b, "company_admin")
    self_user = seed_user(db_session, "self@lvsec-a.co", company_a, "employee")

    admin_a = login(client, "admin@lvsec-a.co")
    admin_b = login(client, "admin@lvsec-b.co")
    employee_a = _create_employee(client, admin_a, company_a.id)
    employee_b = _create_employee(client, admin_b, company_b.id)

    linked = client.post(
        f"/api/v1/employees/{employee_a['id']}/user",
        headers=admin_a["headers"],
        json={"user_id": self_user.id},
    )
    assert linked.status_code == 200, linked.text

    leave_type = client.post(
        "/api/v1/leave-types",
        headers=admin_a["headers"],
        json={
            "company_id": company_a.id,
            "code": "ANNUAL",
            "name_ar": "اجازة سنوية",
            "name_en": "Annual Leave",
        },
    )
    assert leave_type.status_code == 201, leave_type.text

    casual = client.post(
        "/api/v1/leave-types",
        headers=admin_a["headers"],
        json={
            "company_id": company_a.id,
            "code": "CASUAL",
            "name_ar": "اجازة عارضة",
            "name_en": "Casual Leave",
            "allocation_requires_approval": True,
        },
    )
    assert casual.status_code == 201, casual.text

    allocation = client.post(
        "/api/v1/leave-allocations",
        headers=admin_a["headers"],
        json={
            "employee_id": employee_a["id"],
            "leave_type_id": leave_type.json()["id"],
            "period_start": "2025-01-01",
            "period_end": "2025-06-30",
            "allocated_days": "21.00",
        },
    )
    assert allocation.status_code == 201, allocation.text

    request = client.post(
        "/api/v1/leave-requests",
        headers=admin_a["headers"],
        json={
            "employee_id": employee_a["id"],
            "leave_type_id": leave_type.json()["id"],
            "start_date": "2025-03-03",
            "end_date": "2025-03-07",
        },
    )
    assert request.status_code == 201, request.text

    holiday = client.post(
        "/api/v1/company-holidays",
        headers=admin_a["headers"],
        json={
            "company_id": company_a.id,
            "date": "2025-09-23",
            "name_ar": "عطلة",
            "name_en": "Holiday",
        },
    )
    assert holiday.status_code == 201, holiday.text

    rule = client.post(
        "/api/v1/leave-statutory-rules",
        headers=admin_a["headers"],
        json=_rule_payload(company_a.id),
    )
    assert rule.status_code == 201, rule.text

    return SimpleNamespace(
        company_a=company_a,
        company_b=company_b,
        employee_a=employee_a,
        employee_b=employee_b,
        admin_a=admin_a,
        admin_b=admin_b,
        leave_type=leave_type.json(),
        casual=casual.json(),
        allocation=allocation.json(),
        request=request.json(),
        holiday=holiday.json(),
        rule=rule.json(),
    )


def test_roleless_user_denied_every_leave_route(client, leave_security_env):
    env = leave_security_env
    auth = login(client, "noperm@lvsec-a.co")
    headers = {**auth["headers"], "X-Company-Id": str(env.company_a.id)}

    # Permission-gated routes answer 403 before touching the service.
    assert client.get("/api/v1/leave-types", headers=headers).status_code == 403
    assert (
        client.get("/api/v1/leave-allocations", headers=headers).status_code
        == 403
    )
    assert (
        client.get("/api/v1/leave-balances", headers=headers).status_code == 403
    )
    assert (
        client.get("/api/v1/company-holidays", headers=headers).status_code
        == 403
    )
    assert (
        client.get("/api/v1/leave-statutory-rules", headers=headers).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/leave-types",
            headers=headers,
            json={
                "company_id": env.company_a.id,
                "code": "X",
                "name_ar": "x",
                "name_en": "x",
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/leave-allocations",
            headers=headers,
            json={
                "employee_id": env.employee_a["id"],
                "leave_type_id": env.leave_type["id"],
                "period_start": "2025-07-01",
                "period_end": "2025-12-31",
                "allocated_days": "5.00",
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/company-holidays",
            headers=headers,
            json={
                "company_id": env.company_a.id,
                "date": "2025-12-25",
                "name_ar": "x",
                "name_en": "x",
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/leave-statutory-rules",
            headers=headers,
            json=_rule_payload(env.company_a.id),
        ).status_code
        == 403
    )

    # Service-authorized routes: no membership means no visibility...
    assert (
        client.get("/api/v1/leave-requests", headers=headers).status_code == 403
    )
    assert (
        client.get(
            f"/api/v1/leave-requests/{env.request['id']}", headers=headers
        ).status_code
        == 404
    )
    # ...and service-level lookups resolve to 404, never leaking existence.
    created = client.post(
        "/api/v1/leave-requests",
        headers=headers,
        json={
            "employee_id": env.employee_a["id"],
            "leave_type_id": env.leave_type["id"],
            "start_date": "2025-03-10",
            "end_date": "2025-03-12",
        },
    )
    assert created.status_code == 404, created.text
    assert created.json()["code"] == "LEAVE_REQUEST_NOT_FOUND"
    assert (
        client.post(
            f"/api/v1/leave-requests/{env.request['id']}/submit",
            headers=headers,
            json={},
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/leave-requests/{env.request['id']}", headers=headers
        ).status_code
        == 404
    )
    # Permission-gated detail routes stop at 403 for roleless callers.
    assert (
        client.get(
            f"/api/v1/company-holidays/{env.holiday['id']}", headers=headers
        ).status_code
        == 403
    )


def test_auditor_reads_leave_but_cannot_write(client, leave_security_env):
    env = leave_security_env
    auth = login(client, "auditor@lvsec-a.co")
    headers = {**auth["headers"], "X-Company-Id": str(env.company_a.id)}

    for path, params in (
        ("/api/v1/leave-types", None),
        ("/api/v1/leave-allocations", None),
        ("/api/v1/leave-requests", None),
        ("/api/v1/leave-balances", {"employee_id": env.employee_a["id"]}),
        ("/api/v1/company-holidays", None),
        ("/api/v1/leave-statutory-rules", None),
    ):
        response = client.get(path, headers=headers, params=params)
        assert response.status_code == 200, (path, response.text)

    assert (
        client.post(
            "/api/v1/leave-types",
            headers=headers,
            json={
                "company_id": env.company_a.id,
                "code": "AUDX",
                "name_ar": "x",
                "name_en": "x",
            },
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/v1/leave-types/{env.leave_type['id']}",
            headers=headers,
            json={"name_en": "changed"},
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/api/v1/leave-types/{env.leave_type['id']}", headers=headers
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/leave-allocations",
            headers=headers,
            json={
                "employee_id": env.employee_a["id"],
                "leave_type_id": env.leave_type["id"],
                "period_start": "2025-07-01",
                "period_end": "2025-12-31",
                "allocated_days": "5.00",
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/leave-allocations/{env.allocation['id']}/approve",
            headers=headers,
            json={},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/leave-requests/{env.request['id']}/submit",
            headers=headers,
            json={},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/leave-requests/{env.request['id']}/approve",
            headers=headers,
            json={},
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/api/v1/leave-requests/{env.request['id']}", headers=headers
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/company-holidays",
            headers=headers,
            json={
                "company_id": env.company_a.id,
                "date": "2025-12-25",
                "name_ar": "x",
                "name_en": "x",
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/leave-statutory-rules/{env.rule['id']}/deactivate",
            headers=headers,
            json={},
        ).status_code
        == 403
    )


def test_hr_officer_captures_but_never_decides(client, leave_security_env):
    env = leave_security_env
    auth = login(client, "officer@lvsec-a.co")

    assert (
        client.get("/api/v1/leave-types", headers=auth["headers"]).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/leave-types",
            headers=auth["headers"],
            json={
                "company_id": env.company_a.id,
                "code": "OFFX",
                "name_ar": "x",
                "name_en": "x",
            },
        ).status_code
        == 403
    )

    # Officer may allocate on an approval-required type (lands submitted)
    # and re-submit idempotently.
    created = client.post(
        "/api/v1/leave-allocations",
        headers=auth["headers"],
        json={
            "employee_id": env.employee_a["id"],
            "leave_type_id": env.casual["id"],
            "period_start": "2025-07-01",
            "period_end": "2025-12-31",
            "allocated_days": "10.00",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "submitted"
    submitted = client.post(
        f"/api/v1/leave-allocations/{created.json()['id']}/submit",
        headers=auth["headers"],
        json={},
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "submitted"

    # ...but never approve, neither allocations nor requests.
    assert (
        client.post(
            f"/api/v1/leave-allocations/{created.json()['id']}/approve",
            headers=auth["headers"],
            json={},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/leave-requests/{env.request['id']}/approve",
            headers=auth["headers"],
            json={},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/leave-requests/{env.request['id']}/reject",
            headers=auth["headers"],
            json={"reason": "no"},
        ).status_code
        == 403
    )

    # The manager (who holds allocation.approve) completes the flow.
    manager = login(client, "manager@lvsec-a.co")
    approved = client.post(
        f"/api/v1/leave-allocations/{created.json()['id']}/approve",
        headers=manager["headers"],
        json={},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"


def test_custom_role_with_single_leave_permission(
    client, leave_security_env, db_session
):
    env = leave_security_env
    admin = env.admin_a

    role = client.post(
        "/api/v1/roles",
        headers=admin["headers"],
        json={
            "company_id": env.company_a.id,
            "code": "lv_viewer",
            "name": "Leave Request Viewer",
        },
    )
    assert role.status_code == 201, role.text
    granted = client.put(
        f"/api/v1/roles/{role.json()['id']}/permissions",
        headers=admin["headers"],
        json={"permission_codes": ["leave_request.view"]},
    )
    assert granted.status_code == 200, granted.text

    seed_user(db_session, "lvviewer@lvsec-a.co", env.company_a, "lv_viewer")
    viewer = login(client, "lvviewer@lvsec-a.co")

    listing = client.get("/api/v1/leave-requests", headers=viewer["headers"])
    assert listing.status_code == 200, listing.text
    assert listing.json()["page"]["total"] >= 1

    created = client.post(
        "/api/v1/leave-requests",
        headers=viewer["headers"],
        json={
            "employee_id": env.employee_a["id"],
            "leave_type_id": env.leave_type["id"],
            "start_date": "2025-06-09",
            "end_date": "2025-06-13",
        },
    )
    assert created.status_code == 403, created.text
    assert (
        client.get(
            "/api/v1/leave-types", headers=viewer["headers"]
        ).status_code
        == 403
    )


def test_other_company_gets_404_not_403(client, leave_security_env):
    env = leave_security_env
    auth = env.admin_b
    headers = {**auth["headers"], "X-Company-Id": str(env.company_b.id)}

    assert (
        client.get(
            f"/api/v1/leave-types/{env.leave_type['id']}", headers=headers
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/leave-types/{env.leave_type['id']}",
            headers=headers,
            json={"name_en": "hijack"},
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/leave-types/{env.leave_type['id']}", headers=headers
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/leave-allocations/{env.allocation['id']}",
            headers=headers,
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/leave-allocations/{env.allocation['id']}/approve",
            headers=headers,
            json={},
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/leave-requests/{env.request['id']}", headers=headers
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/leave-requests/{env.request['id']}/submit",
            headers=headers,
            json={},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/leave-requests/{env.request['id']}/approve",
            headers=headers,
            json={},
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/leave-requests/{env.request['id']}", headers=headers
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/company-holidays/{env.holiday['id']}", headers=headers
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/company-holidays/{env.holiday['id']}",
            headers=headers,
            json={"name_en": "hijack"},
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/company-holidays/{env.holiday['id']}", headers=headers
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/leave-statutory-rules/{env.rule['id']}/deactivate",
            headers=headers,
            json={},
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/api/v1/leave-balances",
            headers=headers,
            params={"employee_id": env.employee_a["id"]},
        ).status_code
        == 404
    )

    # Company B listings never leak company A rows.
    requests = client.get("/api/v1/leave-requests", headers=headers).json()
    assert requests["page"]["total"] == 0
    holidays = client.get("/api/v1/company-holidays", headers=headers).json()
    assert holidays["page"]["total"] == 0


def test_raw_cross_company_insert_blocked_by_rls(
    client, leave_security_env, db_session
):
    from app.core.rls import clear_context, elevate_for_seed, set_context

    env = leave_security_env
    elevate_for_seed(db_session)
    clear_context(db_session)
    set_context(
        db_session,
        user_id=None,
        company_ids=[env.company_b.id],
        is_platform_admin=False,
    )
    with pytest.raises(Exception) as excinfo:
        db_session.execute(
            text(
                "INSERT INTO company_holidays "
                "(company_id, name_ar, name_en, date, status, "
                " created_at, updated_at) VALUES "
                f"({env.company_a.id}, 'x', 'x', '2025-12-25', 'active', "
                " now(), now())"
            )
        )
        db_session.flush()
    assert "row-level security" in str(excinfo.value).lower()
    db_session.rollback()
    clear_context(db_session)


def test_employee_role_stays_inside_self_service(client, leave_security_env):
    env = leave_security_env
    auth = login(client, "self@lvsec-a.co")

    assert (
        client.get("/api/v1/leave-types", headers=auth["headers"]).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/leave-allocations",
            headers=auth["headers"],
            json={
                "employee_id": env.employee_a["id"],
                "leave_type_id": env.leave_type["id"],
                "period_start": "2025-07-01",
                "period_end": "2025-12-31",
                "allocated_days": "5.00",
            },
        ).status_code
        == 403
    )
    assert (
        client.get("/api/v1/leave-balances", headers=auth["headers"]).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/leave-statutory-rules",
            headers=auth["headers"],
            json=_rule_payload(env.company_a.id),
        ).status_code
        == 403
    )

    # Self-service surfaces stay available.
    assert (
        client.get("/api/v1/leave-balances/me", headers=auth["headers"]).status_code
        == 200
    )
    listing = client.get("/api/v1/leave-requests", headers=auth["headers"])
    assert listing.status_code == 200, listing.text

    created = client.post(
        "/api/v1/leave-requests",
        headers=auth["headers"],
        json={
            "employee_id": env.employee_a["id"],
            "leave_type_id": env.leave_type["id"],
            "start_date": "2025-06-09",
            "end_date": "2025-06-13",
        },
    )
    assert created.status_code == 201, created.text
    # ...but the employee can never decide their own request.
    assert (
        client.post(
            f"/api/v1/leave-requests/{created.json()['id']}/approve",
            headers=auth["headers"],
            json={},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/leave-requests/{created.json()['id']}/reject",
            headers=auth["headers"],
            json={"reason": "no"},
        ).status_code
        == 403
    )
