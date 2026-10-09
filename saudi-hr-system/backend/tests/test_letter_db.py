"""Phase 9 HR letter API lifecycle tests (create/update/issue/cancel/void)."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone as dt_timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.audit.model import AuditLog
from app.core.rls import clear_context, elevate_for_seed
from app.shared.models import EmployeeRequest, HrLetter, HrLetterEvent
from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "نورة",
        "last_name_ar": "القحطاني",
        "first_name_en": "Noura",
        "last_name_en": "Alqahtani",
        "status": "active",
        **overrides,
    }
    response = client.post("/api/v1/employees", headers=auth["headers"], json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _link_user(client, auth, employee_id, user_id):
    response = client.post(
        f"/api/v1/employees/{employee_id}/user",
        headers=auth["headers"],
        json={"user_id": user_id},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture()
def letter_env(client, db_session):
    company_a = seed_company(db_session, "Letter Co A")
    company_b = seed_company(db_session, "Letter Co B")

    admin_user = seed_user(db_session, "admin@lettera.co", company_a, "company_admin")
    manager_user = seed_user(db_session, "manager@lettera.co", company_a, "hr_manager")
    officer_user = seed_user(db_session, "officer@lettera.co", company_a, "hr_officer")
    auditor_user = seed_user(db_session, "auditor@lettera.co", company_a, "auditor")
    self_user = seed_user(db_session, "self@lettera.co", company_a, "employee")
    seed_user(db_session, "admin@letterb.co", company_b, "company_admin")
    self_b_user = seed_user(db_session, "self@letterb.co", company_b, "employee")

    admin = login(client, "admin@lettera.co")
    headers_a = {**admin["headers"], "X-Company-Id": str(company_a.id)}
    manager = login(client, "manager@lettera.co")
    officer = login(client, "officer@lettera.co")
    auditor = login(client, "auditor@lettera.co")
    selfauth = login(client, "self@lettera.co")
    admin_b = login(client, "admin@letterb.co")
    self_b = login(client, "self@letterb.co")

    emp = _create_employee(
        client, admin, company_a.id, first_name_en="Noura", last_name_en="Alqahtani"
    )
    emp2 = _create_employee(
        client, admin, company_a.id, first_name_en="Salem", last_name_en="Alruwaili"
    )
    emp_b = _create_employee(client, admin_b, company_b.id)

    _link_user(client, admin, emp["id"], self_user.id)
    _link_user(client, admin_b, emp_b["id"], self_b_user.id)

    assignment = client.post(
        "/api/v1/salary-assignments",
        headers=headers_a,
        json={
            "company_id": company_a.id,
            "employee_id": emp["id"],
            "effective_from": "2025-01-01",
            "basic_salary": "9300",
        },
    )
    assert assignment.status_code == 201, assignment.text

    return SimpleNamespace(
        client=client,
        db=db_session,
        company_a=company_a,
        company_b=company_b,
        admin=admin,
        headers_a=headers_a,
        manager=manager,
        officer=officer,
        auditor=auditor,
        selfauth=selfauth,
        admin_b=admin_b,
        self_b=self_b,
        emp=emp,
        emp2=emp2,
        emp_b=emp_b,
        admin_user=admin_user,
        manager_user=manager_user,
        officer_user=officer_user,
        auditor_user=auditor_user,
        self_user=self_user,
    )


def _create(env, payload=None, expect=201, auth=None):
    body = {"employee_id": env.emp["id"], "letter_type": "employment", "language": "en"}
    body.update(payload or {})
    response = env.client.post(
        "/api/v1/hr-letters",
        headers=(auth or env.admin)["headers"],
        json=body,
    )
    assert response.status_code == expect, response.text
    return response


def _action(env, letter_id, action, payload=None, expect=200, auth=None):
    response = env.client.post(
        f"/api/v1/hr-letters/{letter_id}/{action}",
        headers=(auth or env.admin)["headers"],
        json=payload if payload is not None else {},
    )
    assert response.status_code == expect, response.text
    return response


def _seed_request(env, *, status="approved", request_type="hr_letter"):
    elevate_for_seed(env.db)
    request = EmployeeRequest(
        company_id=env.company_a.id,
        employee_id=env.emp["id"],
        request_type=request_type,
        status=status,
        subject="Please issue my letter",
        payload={},
        # ck_employee_request_decision_consistency: approved/rejected rows
        # must carry a decision timestamp.
        decided_at=(
            datetime.now(dt_timezone.utc) if status in ("approved", "rejected")
            else None
        ),
    )
    env.db.add(request)
    env.db.commit()
    clear_context(env.db)
    return request.id


def test_create_draft_shape_reference_and_created_event(letter_env):
    env = letter_env
    body = _create(env).json()
    assert body["status"] == "draft"
    assert body["reference"] == f"LTR-{body['id']:06d}"
    assert body["letter_type"] == "employment"
    assert body["language"] == "en"
    assert body["version"] == 1
    assert body["issued_at"] is None
    assert body["voided_at"] is None
    assert body["content"]["employee_name"] == "Noura Alqahtani"
    assert body["content"]["company_name"]
    # Mutation responses follow the Phase 8 pattern: history comes from
    # the detail read, not from the mutation response.
    assert body["events"] == []

    detail = env.client.get(
        f"/api/v1/hr-letters/{body['id']}", headers=env.admin["headers"]
    ).json()
    assert [event["action"] for event in detail["events"]] == ["created"]
    assert detail["events"][0]["from_status"] is None
    assert detail["events"][0]["to_status"] == "draft"


@pytest.mark.parametrize(
    "letter_type",
    ["employment", "salary", "experience", "work_address"],
)
def test_create_every_letter_type_assembles_closed_content(letter_env, letter_type):
    env = letter_env
    body = _create(env, {"letter_type": letter_type, "language": "ar"}).json()
    content = body["content"]
    common = {
        "company_name",
        "company_cr",
        "company_address",
        "company_city",
        "employee_name",
        "employee_number",
        "identity_number",
        "position",
        "department",
        "branch",
        "employment_type",
        "hire_date",
    }
    assert set(content) >= common
    assert content["employee_name"] == "نورة القحطاني"
    if letter_type == "salary":
        assert content["basic_salary"] == "9300.00"
        assert content["currency"] == "SAR"
        assert content["salary_effective_from"] == "2025-01-01"
    else:
        assert "basic_salary" not in content


def test_list_excludes_content_and_supports_filters(letter_env):
    env = letter_env
    first = _create(env, {"letter_type": "employment"}).json()
    second = _create(env, {"letter_type": "salary"}).json()
    _action(env, second["id"], "issue")

    page = env.client.get("/api/v1/hr-letters", headers=env.admin["headers"])
    assert page.status_code == 200, page.text
    items = page.json()["items"]
    assert len(items) >= 2
    assert all("content" not in item for item in items)
    assert all("void_reason" not in item for item in items)

    by_status = env.client.get(
        "/api/v1/hr-letters?status=issued", headers=env.admin["headers"]
    ).json()["items"]
    assert second["id"] in {item["id"] for item in by_status}
    assert first["id"] not in {item["id"] for item in by_status}

    by_type = env.client.get(
        "/api/v1/hr-letters?letter_type=salary", headers=env.admin["headers"]
    ).json()["items"]
    assert {item["id"] for item in by_type} == {second["id"]}

    by_employee = env.client.get(
        f"/api/v1/hr-letters?employee_id={env.emp['id']}",
        headers=env.admin["headers"],
    ).json()["items"]
    assert {item["id"] for item in by_employee} >= {first["id"], second["id"]}


def test_update_purpose_and_language_rebuilds_content(letter_env):
    env = letter_env
    created = _create(env, {"language": "en"}).json()
    patched = env.client.patch(
        f"/api/v1/hr-letters/{created['id']}",
        headers=env.admin["headers"],
        json={"purpose": "Bank account opening", "language": "ar"},
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["purpose"] == "Bank account opening"
    assert body["language"] == "ar"
    assert body["version"] == created["version"] + 1
    assert body["content"]["employee_name"] == "نورة القحطاني"

    detail = env.client.get(
        f"/api/v1/hr-letters/{created['id']}", headers=env.admin["headers"]
    ).json()
    assert [event["action"] for event in detail["events"]] == ["created", "updated"]


def test_issue_freezes_content_and_records_metadata(letter_env):
    env = letter_env
    created = _create(env, {"letter_type": "salary"}).json()
    draft_content = created["content"]

    issued = _action(env, created["id"], "issue").json()
    assert issued["status"] == "issued"
    assert issued["issued_at"] is not None
    assert issued["issued_by"] == env.admin_user.id
    assert issued["content"] == draft_content  # deterministic re-assembly
    assert issued["version"] == created["version"] + 1

    detail = env.client.get(
        f"/api/v1/hr-letters/{created['id']}", headers=env.admin["headers"]
    ).json()
    actions = [event["action"] for event in detail["events"]]
    assert actions == ["created", "issued"]
    assert detail["events"][-1]["from_status"] == "draft"
    assert detail["events"][-1]["to_status"] == "issued"

    # The frozen content survives a second read.
    assert detail["content"] == draft_content


def test_cancel_draft_only(letter_env):
    env = letter_env
    draft = _create(env).json()
    cancelled = _action(
        env, draft["id"], "cancel", {"reason": "no longer needed"}
    ).json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancel_reason"] == "no longer needed"
    assert cancelled["cancelled_by"] == env.admin_user.id

    again = _action(env, draft["id"], "cancel", expect=409)
    assert again.json()["code"] == "HR_LETTER_STATE_INVALID"

    issued = _create(env).json()
    _action(env, issued["id"], "issue")
    bad = _action(env, issued["id"], "cancel", expect=409)
    assert bad.json()["code"] == "HR_LETTER_STATE_INVALID"


def test_void_issued_letter_with_reason(letter_env):
    env = letter_env
    issued = _create(env).json()
    _action(env, issued["id"], "issue")

    reasonless = _action(env, issued["id"], "void", {}, expect=400)
    assert reasonless.json()["code"] == "HR_LETTER_REASON_REQUIRED"
    blank = _action(env, issued["id"], "void", {"reason": "   "}, expect=400)
    assert blank.json()["code"] == "HR_LETTER_REASON_REQUIRED"

    voided = _action(
        env, issued["id"], "void", {"reason": "issued in error"}
    ).json()
    assert voided["status"] == "void"
    assert voided["void_reason"] == "issued in error"
    assert voided["voided_by"] == env.admin_user.id

    detail = env.client.get(
        f"/api/v1/hr-letters/{issued['id']}", headers=env.admin["headers"]
    ).json()
    actions = [event["action"] for event in detail["events"]]
    assert actions == ["created", "issued", "voided"]

    twice = _action(env, issued["id"], "void", {"reason": "again"}, expect=409)
    assert twice.json()["code"] == "HR_LETTER_STATE_INVALID"


def test_voiding_a_draft_is_state_invalid(letter_env):
    env = letter_env
    draft = _create(env).json()
    bad = _action(env, draft["id"], "void", {"reason": "x"}, expect=409)
    assert bad.json()["code"] == "HR_LETTER_STATE_INVALID"


def test_mutations_of_issued_letters_are_blocked(letter_env):
    env = letter_env
    issued = _create(env).json()
    _action(env, issued["id"], "issue")

    patched = env.client.patch(
        f"/api/v1/hr-letters/{issued['id']}",
        headers=env.admin["headers"],
        json={"purpose": "late edit"},
    )
    assert patched.status_code == 409
    assert patched.json()["code"] == "HR_LETTER_STATE_INVALID"

    reissued = _action(env, issued["id"], "issue", expect=409)
    assert reissued.json()["code"] == "HR_LETTER_STATE_INVALID"


def test_enum_validation_rejects_bad_values(letter_env):
    env = letter_env
    bad_type = env.client.post(
        "/api/v1/hr-letters",
        headers=env.admin["headers"],
        json={"employee_id": env.emp["id"], "letter_type": "gosi", "language": "en"},
    )
    assert bad_type.status_code == 422
    bad_lang = env.client.post(
        "/api/v1/hr-letters",
        headers=env.admin["headers"],
        json={"employee_id": env.emp["id"], "letter_type": "employment", "language": "fr"},
    )
    assert bad_lang.status_code == 422
    bad_status_filter = env.client.get(
        "/api/v1/hr-letters?status=deleted", headers=env.admin["headers"]
    )
    assert bad_status_filter.status_code == 422


def test_invalid_employee_targets_are_rejected(letter_env):
    env = letter_env
    unknown = _create(env, {"employee_id": 999999}, expect=400)
    assert unknown.json()["code"] == "HR_LETTER_EMPLOYEE_INVALID"

    patched = env.client.patch(
        f"/api/v1/employees/{env.emp2['id']}",
        headers=env.admin["headers"],
        json={"status": "suspended"},
    )
    assert patched.status_code == 200, patched.text
    inactive = _create(env, {"employee_id": env.emp2["id"]}, expect=400)
    assert inactive.json()["code"] == "HR_LETTER_EMPLOYEE_INVALID"


def test_source_request_link_and_duplicate_protection(letter_env):
    env = letter_env
    source_id = _seed_request(env)

    first = _create(env, {"source_request_id": source_id}).json()
    assert first["source_request_id"] == source_id

    duplicate = _create(env, {"source_request_id": source_id}, expect=409)
    assert duplicate.json()["code"] == "HR_LETTER_REQUEST_LINKED"

    # A cancelled letter frees the request again.
    _action(env, first["id"], "cancel")
    reused = _create(env, {"source_request_id": source_id}).json()
    assert reused["source_request_id"] == source_id


def test_source_request_must_be_approved_hr_letter(letter_env):
    env = letter_env
    pending_id = _seed_request(env, status="submitted")
    bad_status = _create(env, {"source_request_id": pending_id}, expect=400)
    assert bad_status.json()["code"] == "HR_LETTER_REQUEST_INVALID"

    wrong_type_id = _seed_request(env, request_type="document_request")
    bad_type = _create(env, {"source_request_id": wrong_type_id}, expect=400)
    assert bad_type.json()["code"] == "HR_LETTER_REQUEST_INVALID"

    missing = _create(env, {"source_request_id": 424242}, expect=400)
    assert missing.json()["code"] == "HR_LETTER_REQUEST_INVALID"


def test_salary_letter_requires_active_assignment(letter_env):
    env = letter_env
    body = _create(
        env,
        {"employee_id": env.emp2["id"], "letter_type": "salary"},
        expect=409,
    )
    assert body.json()["code"] == "HR_LETTER_SOURCE_MISSING"


def test_issue_fails_when_sources_disappear(letter_env):
    env = letter_env
    draft = _create(env, {"employee_id": env.emp2["id"]}).json()
    patched = env.client.patch(
        f"/api/v1/employees/{env.emp2['id']}",
        headers=env.admin["headers"],
        json={"status": "suspended"},
    )
    assert patched.status_code == 200, patched.text

    issue = _action(env, draft["id"], "issue", expect=409)
    assert issue.json()["code"] == "HR_LETTER_SOURCE_MISSING"


def test_audit_entries_never_contain_content(letter_env):
    env = letter_env
    issued = _create(env, {"letter_type": "salary"}).json()
    _action(env, issued["id"], "issue")
    _action(env, issued["id"], "void", {"reason": "wrong employee"})

    elevate_for_seed(env.db)
    entries = list(
        env.db.execute(
            select(AuditLog).where(
                AuditLog.entity == "hr_letter",
                AuditLog.company_id == env.company_a.id,
            )
        ).scalars()
    )
    clear_context(env.db)
    actions = {entry.action for entry in entries}
    assert {"hr_letter.create", "hr_letter.issue", "hr_letter.void"} <= actions
    for entry in entries:
        assert "content" not in (entry.new_value or "")
        assert "basic_salary" not in (entry.new_value or "")
        assert "9300" not in (entry.new_value or "")


def test_event_history_is_persisted_and_ordered(letter_env):
    env = letter_env
    issued = _create(env).json()
    _action(env, issued["id"], "issue")
    _action(env, issued["id"], "void", {"reason": "audit check"})

    elevate_for_seed(env.db)
    events = list(
        env.db.execute(
            select(HrLetterEvent)
            .where(HrLetterEvent.letter_id == issued["id"])
            .order_by(HrLetterEvent.id)
        ).scalars()
    )
    row = env.db.get(HrLetter, issued["id"])
    clear_context(env.db)
    assert [event.action for event in events] == ["created", "issued", "voided"]
    assert [event.to_status for event in events] == ["draft", "issued", "void"]
    assert events[-1].note == "audit check"
    assert events[-1].ip_address is not None
    assert row is not None and row.status == "void"
    assert row.reference == f"LTR-{row.id:06d}"


def test_happy_path_full_lifecycle_through_ess_portal(letter_env):
    env = letter_env
    issued = _create(env, {"letter_type": "experience"}).json()
    _action(env, issued["id"], "issue")

    page = env.client.get("/api/v1/me/letters", headers=env.selfauth["headers"])
    assert page.status_code == 200, page.text
    mine = {item["id"] for item in page.json()["items"]}
    assert issued["id"] in mine
    assert all("content" not in item for item in page.json()["items"])

    detail = env.client.get(
        f"/api/v1/me/letters/{issued['id']}", headers=env.selfauth["headers"]
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["content"]["employee_name"] == "Noura Alqahtani"
    assert [event["action"] for event in body["events"]] == ["created", "issued"]
