from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "Sara",
        "last_name_ar": "Alotaibi",
        "first_name_en": "Sara",
        "last_name_en": "Alotaibi",
        "status": "active",
        **overrides,
    }
    response = client.post(
        "/api/v1/employees", headers=auth["headers"], json=payload
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_type(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "code": "ANNUAL",
        "name_ar": "اجازة سنوية",
        "name_en": "Annual Leave",
        "default_entitlement_days": "21.00",
        **overrides,
    }
    response = client.post(
        "/api/v1/leave-types", headers=auth["headers"], json=payload
    )
    assert response.status_code == 201, response.text
    return response.json()


def _allocation_payload(employee_id, leave_type_id, **overrides):
    payload = {
        "employee_id": employee_id,
        "leave_type_id": leave_type_id,
        "period_start": "2025-01-01",
        "period_end": "2025-12-31",
        "allocated_days": "21.00",
    }
    payload.update(overrides)
    return payload


@pytest.fixture()
def alloc_env(client, db_session):
    company = seed_company(db_session, "LV Alloc")
    other = seed_company(db_session, "LV Alloc Other")
    seed_user(db_session, "admin@alloc.co", company, "company_admin")
    seed_user(db_session, "manager@alloc.co", company, "hr_manager")
    seed_user(db_session, "officer@alloc.co", company, "hr_officer")
    seed_user(db_session, "auditor@alloc.co", company, "auditor")
    seed_user(db_session, "roleless@alloc.co", company)
    seed_user(db_session, "admin@alloc-other.co", other, "company_admin")

    admin = login(client, "admin@alloc.co")
    employee = _create_employee(client, admin, company.id)
    employee_b = _create_employee(
        client, admin, company.id, first_name_en="Fahad",
        last_name_en="Alqahtani", first_name_ar="Fahad", last_name_ar="Alqahtani",
    )
    annual = _create_type(client, admin, company.id)
    gated = _create_type(
        client,
        admin,
        company.id,
        code="GATED",
        name_ar="مرحلتان",
        name_en="Two stage",
        allocation_requires_approval=True,
    )
    return SimpleNamespace(
        company=company,
        other=other,
        admin=admin,
        manager=login(client, "manager@alloc.co"),
        officer=login(client, "officer@alloc.co"),
        auditor=login(client, "auditor@alloc.co"),
        roleless=login(client, "roleless@alloc.co"),
        other_admin=login(client, "admin@alloc-other.co"),
        employee=employee,
        employee_b=employee_b,
        annual=annual,
        gated=gated,
    )


def _mark_used(db_session, allocation_id, days: str):
    from app.core.rls import clear_context, elevate_for_seed
    from app.shared.models import LeaveAllocation

    elevate_for_seed(db_session)
    row = db_session.get(LeaveAllocation, allocation_id)
    assert row is not None
    row.used_days = Decimal(days)
    db_session.commit()
    clear_context(db_session)


def test_allocation_create_is_auto_approved_by_default(client, alloc_env):
    env = alloc_env
    auth = env.admin

    created = client.post(
        "/api/v1/leave-allocations",
        headers=auth["headers"],
        json=_allocation_payload(env.employee["id"], env.annual["id"]),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "approved"
    assert body["used_days"] == "0.00"
    assert body["source"] == "manual"
    assert body["company_id"] == env.company.id

    read = client.get(
        f"/api/v1/leave-allocations/{body['id']}", headers=auth["headers"]
    )
    assert read.status_code == 200, read.text

    page = client.get(
        "/api/v1/leave-allocations",
        headers=auth["headers"],
        params={
            "company_id": env.company.id,
            "employee_id": env.employee["id"],
            "status": "approved",
            "period_from": "2025-06-01",
            "period_to": "2025-06-30",
        },
    ).json()
    assert page["page"]["total"] == 1
    assert page["items"][0]["id"] == body["id"]


def test_allocation_period_overlap_and_adjacency(client, alloc_env):
    env = alloc_env
    auth = env.admin

    first = client.post(
        "/api/v1/leave-allocations",
        headers=auth["headers"],
        json=_allocation_payload(
            env.employee["id"],
            env.annual["id"],
            period_end="2025-06-30",
        ),
    )
    assert first.status_code == 201, first.text

    overlapping = client.post(
        "/api/v1/leave-allocations",
        headers=auth["headers"],
        json=_allocation_payload(
            env.employee["id"],
            env.annual["id"],
            period_start="2025-06-30",
        ),
    )
    assert overlapping.status_code == 409, overlapping.text
    assert overlapping.json()["code"] == "LEAVE_ALLOCATION_OVERLAP"

    # Adjacent (touching) windows are legal: ranges are inclusive.
    adjacent = client.post(
        "/api/v1/leave-allocations",
        headers=auth["headers"],
        json=_allocation_payload(
            env.employee["id"],
            env.annual["id"],
            period_start="2025-07-01",
        ),
    )
    assert adjacent.status_code == 201, adjacent.text

    # Another employee may hold the same period.
    other_employee = client.post(
        "/api/v1/leave-allocations",
        headers=auth["headers"],
        json=_allocation_payload(env.employee_b["id"], env.annual["id"]),
    )
    assert other_employee.status_code == 201, other_employee.text

    # Different leave type on the same employee does not clash.
    other_type = client.post(
        "/api/v1/leave-allocations",
        headers=auth["headers"],
        json=_allocation_payload(env.employee["id"], env.gated["id"]),
    )
    assert other_type.status_code == 201, other_type.text


def test_allocation_requires_approval_state_machine(client, alloc_env):
    env = alloc_env
    admin = env.admin

    created = client.post(
        "/api/v1/leave-allocations",
        headers=admin["headers"],
        json=_allocation_payload(
            env.employee["id"],
            env.gated["id"],
            period_start="2025-02-01",
            period_end="2025-02-28",
        ),
    )
    assert created.status_code == 201, created.text
    allocation_id = created.json()["id"]
    assert created.json()["status"] == "submitted"

    # Idempotent submit of an already-submitted allocation.
    submitted = client.post(
        f"/api/v1/leave-allocations/{allocation_id}/submit",
        headers=admin["headers"],
        json={},
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "submitted"

    approved = client.post(
        f"/api/v1/leave-allocations/{allocation_id}/approve",
        headers=env.manager["headers"],
        json={"reason": "budget ok"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["approved_by"] is not None

    again = client.post(
        f"/api/v1/leave-allocations/{allocation_id}/approve",
        headers=admin["headers"],
        json={},
    )
    assert again.status_code == 409, again.text
    assert again.json()["code"] == "LEAVE_ALLOCATION_STATE_INVALID"

    submitted_only = client.post(
        "/api/v1/leave-allocations",
        headers=admin["headers"],
        json=_allocation_payload(
            env.employee["id"],
            env.gated["id"],
            period_start="2025-03-01",
            period_end="2025-03-31",
        ),
    )
    assert submitted_only.status_code == 201, submitted_only.text
    second_id = submitted_only.json()["id"]

    no_reason = client.post(
        f"/api/v1/leave-allocations/{second_id}/reject",
        headers=admin["headers"],
        json={},
    )
    assert no_reason.status_code == 400, no_reason.text
    assert no_reason.json()["code"] == "LEAVE_DECISION_REASON_REQUIRED"

    rejected = client.post(
        f"/api/v1/leave-allocations/{second_id}/reject",
        headers=admin["headers"],
        json={"reason": "insufficient budget"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["rejected_by"] is not None

    # A rejected allocation cannot be approved afterwards.
    late = client.post(
        f"/api/v1/leave-allocations/{second_id}/approve",
        headers=admin["headers"],
        json={},
    )
    assert late.status_code == 409, late.text


def test_allocation_update_rules(client, alloc_env):
    env = alloc_env
    auth = env.admin

    created = client.post(
        "/api/v1/leave-allocations",
        headers=auth["headers"],
        json=_allocation_payload(env.employee["id"], env.annual["id"]),
    )
    allocation_id = created.json()["id"]

    updated = client.patch(
        f"/api/v1/leave-allocations/{allocation_id}",
        headers=auth["headers"],
        json={"allocated_days": "25.00", "reason": "revised quota"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["allocated_days"] == "25.00"

    bad_period = client.patch(
        f"/api/v1/leave-allocations/{allocation_id}",
        headers=auth["headers"],
        json={"period_start": "2026-01-01", "period_end": "2025-01-01"},
    )
    assert bad_period.status_code == 400, bad_period.text
    assert bad_period.json()["code"] == "LEAVE_ALLOCATION_INVALID_DAYS"

    gated = client.post(
        "/api/v1/leave-allocations",
        headers=auth["headers"],
        json=_allocation_payload(
            env.employee["id"],
            env.gated["id"],
            period_start="2025-04-01",
            period_end="2025-04-30",
        ),
    )
    assert gated.status_code == 201, gated.text
    submitted_edit = client.patch(
        f"/api/v1/leave-allocations/{gated.json()['id']}",
        headers=auth["headers"],
        json={"allocated_days": "10.00"},
    )
    assert submitted_edit.status_code == 409, submitted_edit.text
    assert submitted_edit.json()["code"] == "LEAVE_ALLOCATION_STATE_INVALID"


def test_allocation_update_and_delete_blocked_when_used(
    client, alloc_env, db_session
):
    env = alloc_env
    auth = env.admin

    created = client.post(
        "/api/v1/leave-allocations",
        headers=auth["headers"],
        json=_allocation_payload(env.employee["id"], env.annual["id"]),
    )
    allocation_id = created.json()["id"]
    _mark_used(db_session, allocation_id, "3.00")

    update = client.patch(
        f"/api/v1/leave-allocations/{allocation_id}",
        headers=auth["headers"],
        json={"allocated_days": "18.00"},
    )
    assert update.status_code == 409, update.text
    assert update.json()["code"] == "LEAVE_ALLOCATION_IN_USE"

    delete = client.delete(
        f"/api/v1/leave-allocations/{allocation_id}", headers=auth["headers"]
    )
    assert delete.status_code == 409, delete.text
    assert delete.json()["code"] == "LEAVE_ALLOCATION_IN_USE"


def test_allocation_delete_rules(client, alloc_env):
    env = alloc_env
    auth = env.admin

    created = client.post(
        "/api/v1/leave-allocations",
        headers=auth["headers"],
        json=_allocation_payload(env.employee["id"], env.annual["id"]),
    )
    allocation_id = created.json()["id"]

    # hr_manager cannot delete allocations (no leave_allocation.delete).
    assert (
        client.delete(
            f"/api/v1/leave-allocations/{allocation_id}",
            headers=env.manager["headers"],
        ).status_code
        == 403
    )

    removed = client.delete(
        f"/api/v1/leave-allocations/{allocation_id}", headers=auth["headers"]
    )
    assert removed.status_code == 204, removed.text
    assert (
        client.get(
            f"/api/v1/leave-allocations/{allocation_id}", headers=auth["headers"]
        ).status_code
        == 404
    )


def test_generate_allocations_bulk_and_subset(client, alloc_env):
    env = alloc_env
    auth = env.admin

    generated = client.post(
        "/api/v1/leave-allocations/generate",
        headers=auth["headers"],
        json={
            "leave_type_id": env.annual["id"],
            "period_start": "2025-01-01",
            "period_end": "2025-12-31",
        },
    )
    assert generated.status_code == 201, generated.text
    rows = generated.json()
    assert len(rows) == 2
    assert all(row["source"] == "generate" for row in rows)
    assert all(row["status"] == "approved" for row in rows)
    assert all(row["allocated_days"] == "21.00" for row in rows)

    # Re-running over the same period collides with existing allocations.
    collides = client.post(
        "/api/v1/leave-allocations/generate",
        headers=auth["headers"],
        json={
            "leave_type_id": env.annual["id"],
            "period_start": "2025-01-01",
            "period_end": "2025-12-31",
        },
    )
    assert collides.status_code == 409, collides.text
    assert collides.json()["code"] == "LEAVE_ALLOCATION_OVERLAP"

    subset = client.post(
        "/api/v1/leave-allocations/generate",
        headers=auth["headers"],
        json={
            "leave_type_id": env.gated["id"],
            "period_start": "2025-01-01",
            "period_end": "2025-12-31",
            "employee_ids": [env.employee["id"]],
        },
    )
    assert subset.status_code == 201, subset.text
    assert len(subset.json()) == 1
    assert subset.json()[0]["employee_id"] == env.employee["id"]
    assert subset.json()[0]["status"] == "submitted"

    no_days = _create_type(
        client,
        auth,
        env.company.id,
        code="NODEFAULT",
        name_ar="بدون افتراضي",
        name_en="No default",
        default_entitlement_days=None,
    )
    missing_days = client.post(
        "/api/v1/leave-allocations/generate",
        headers=auth["headers"],
        json={
            "leave_type_id": no_days["id"],
            "period_start": "2026-01-01",
            "period_end": "2026-12-31",
        },
    )
    assert missing_days.status_code == 400, missing_days.text
    assert missing_days.json()["code"] == "LEAVE_ALLOCATION_INVALID_DAYS"

    bad_period = client.post(
        "/api/v1/leave-allocations/generate",
        headers=auth["headers"],
        json={
            "leave_type_id": env.gated["id"],
            "period_start": "2027-06-01",
            "period_end": "2027-01-01",
        },
    )
    assert bad_period.status_code == 400, bad_period.text
    assert bad_period.json()["code"] == "LEAVE_ALLOCATION_INVALID_DAYS"


def test_carry_forward_copies_unused_days_once(client, alloc_env):
    env = alloc_env
    auth = env.admin

    carry_type = _create_type(
        client,
        auth,
        env.company.id,
        code="CARRY",
        name_ar="قابل للترحيل",
        name_en="Carry type",
        default_entitlement_days="21.00",
        carry_forward_enabled=True,
        carry_forward_max_days="5.00",
    )
    source = client.post(
        "/api/v1/leave-allocations",
        headers=auth["headers"],
        json=_allocation_payload(
            env.employee["id"],
            carry_type["id"],
            period_start="2024-01-01",
            period_end="2024-12-31",
        ),
    )
    assert source.status_code == 201, source.text

    carried = client.post(
        "/api/v1/leave-allocations/carry-forward",
        headers=auth["headers"],
        json={
            "company_id": env.company.id,
            "period_start": "2025-01-01",
            "period_end": "2025-12-31",
        },
    )
    assert carried.status_code == 201, carried.text
    rows = carried.json()
    assert len(rows) == 1
    assert rows[0]["source"] == "carry_forward"
    assert rows[0]["status"] == "approved"
    assert rows[0]["carried_from_id"] == source.json()["id"]
    assert rows[0]["allocated_days"] == "5.00"

    # A second run over the same target period is a no-op.
    again = client.post(
        "/api/v1/leave-allocations/carry-forward",
        headers=auth["headers"],
        json={
            "company_id": env.company.id,
            "period_start": "2025-01-01",
            "period_end": "2025-12-31",
        },
    )
    assert again.status_code == 201, again.text
    assert again.json() == []

    # Expiry rules are configuration: end_of_year only carries the
    # immediately preceding calendar year.
    stale_type = _create_type(
        client,
        auth,
        env.company.id,
        code="STALE",
        name_ar="ترحيل منتهي",
        name_en="Expired carry",
        carry_forward_enabled=True,
        carry_forward_expiry="end_of_year",
    )
    stale_source = client.post(
        "/api/v1/leave-allocations",
        headers=auth["headers"],
        json=_allocation_payload(
            env.employee_b["id"],
            stale_type["id"],
            period_start="2023-01-01",
            period_end="2023-12-31",
        ),
    )
    assert stale_source.status_code == 201, stale_source.text
    stale = client.post(
        "/api/v1/leave-allocations/carry-forward",
        headers=env.admin["headers"],
        json={
            "company_id": env.company.id,
            "period_start": "2026-01-01",
            "period_end": "2026-12-31",
        },
    )
    assert stale.status_code == 201, stale.text
    # The stale 2023 entitlement never carries into 2026 under end_of_year.
    assert all(
        row["leave_type_id"] != stale_type["id"] for row in stale.json()
    )
    assert all(
        row["employee_id"] != env.employee_b["id"] for row in stale.json()
    )


def test_carry_forward_requires_permission(client, alloc_env):
    env = alloc_env
    payload = {
        "company_id": env.company.id,
        "period_start": "2025-01-01",
        "period_end": "2025-12-31",
    }
    assert (
        client.post(
            "/api/v1/leave-allocations/carry-forward",
            headers=env.officer["headers"],
            json=payload,
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/leave-allocations/carry-forward",
            headers=env.roleless["headers"],
            json=payload,
        ).status_code
        == 403
    )
    # hr_manager holds carry_forward; hr_officer does not.
    assert (
        client.post(
            "/api/v1/leave-allocations/carry-forward",
            headers=env.manager["headers"],
            json=payload,
        ).status_code
        == 201
    )


def test_allocation_role_matrix(client, alloc_env):
    env = alloc_env

    assert (
        client.get(
            "/api/v1/leave-allocations", headers=env.roleless["headers"]
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/leave-allocations",
            headers=env.roleless["headers"],
            json=_allocation_payload(env.employee["id"], env.annual["id"]),
        ).status_code
        == 403
    )

    assert (
        client.get(
            "/api/v1/leave-allocations", headers=env.auditor["headers"]
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/leave-allocations",
            headers=env.auditor["headers"],
            json=_allocation_payload(env.employee["id"], env.annual["id"]),
        ).status_code
        == 403
    )

    created = client.post(
        "/api/v1/leave-allocations",
        headers=env.officer["headers"],
        json=_allocation_payload(
            env.employee["id"],
            env.gated["id"],
            period_start="2025-05-01",
            period_end="2025-05-31",
        ),
    )
    assert created.status_code == 201, created.text
    allocation_id = created.json()["id"]
    assert (
        client.post(
            f"/api/v1/leave-allocations/{allocation_id}/approve",
            headers=env.officer["headers"],
            json={},
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/api/v1/leave-allocations/{allocation_id}",
            headers=env.officer["headers"],
        ).status_code
        == 403
    )


def test_cross_company_allocation_access(client, alloc_env):
    env = alloc_env
    created = client.post(
        "/api/v1/leave-allocations",
        headers=env.admin["headers"],
        json=_allocation_payload(env.employee["id"], env.annual["id"]),
    )
    allocation_id = created.json()["id"]
    headers = env.other_admin["headers"]

    assert (
        client.get(
            f"/api/v1/leave-allocations/{allocation_id}", headers=headers
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/leave-allocations/{allocation_id}",
            headers=headers,
            json={"allocated_days": "1.00"},
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/leave-allocations/{allocation_id}", headers=headers
        ).status_code
        == 404
    )
    # Cross-company creation is rejected before any row is written.
    foreign = client.post(
        "/api/v1/leave-allocations",
        headers=headers,
        json=_allocation_payload(env.employee["id"], env.annual["id"]),
    )
    assert foreign.status_code == 404, foreign.text
    assert foreign.json()["code"] == "LEAVE_REQUEST_NOT_FOUND"

    page = client.get(
        "/api/v1/leave-allocations",
        headers=headers,
        params={"company_id": env.company.id},
    )
    assert page.status_code == 403, page.text
