from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import text

from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db

PDF = b"%PDF-1.4\n%security matrix pdf\n%%EOF\n"


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "ريما",
        "last_name_ar": "الغامدي",
        "first_name_en": "Reema",
        "last_name_en": "Alghamdi",
        **overrides,
    }
    response = client.post("/api/v1/employees", headers=auth["headers"], json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def matrix_env(client, db_session):
    company_a = seed_company(db_session, "Matrix A")
    company_b = seed_company(db_session, "Matrix B")
    seed_user(db_session, "admin@matrix-a.co", company_a, "company_admin")
    seed_user(db_session, "auditor@matrix-a.co", company_a, "auditor")
    seed_user(db_session, "manager@matrix-a.co", company_a, "hr_manager")
    seed_user(db_session, "officer@matrix-a.co", company_a, "hr_officer")
    seed_user(db_session, "noperm@matrix-a.co", company_a)
    seed_user(db_session, "admin@matrix-b.co", company_b, "company_admin")
    seed_user(db_session, "root@matrix.co", platform=True)

    admin_a = login(client, "admin@matrix-a.co")
    employee_a = _create_employee(client, admin_a, company_a.id)
    type_ids = client.get(
        "/api/v1/employee-document-types",
        headers={**admin_a["headers"], "X-Company-Id": str(company_a.id)},
    ).json()
    document = client.post(
        f"/api/v1/employees/{employee_a['id']}/documents",
        headers={**admin_a["headers"], "X-Company-Id": str(company_a.id)},
        data={"document_type_id": str(type_ids[0]["id"])},
        files={"file": ("matrix.pdf", PDF, "application/pdf")},
    )
    assert document.status_code == 201, document.text

    contract = client.post(
        f"/api/v1/employees/{employee_a['id']}/contracts",
        headers=admin_a["headers"],
        json={"company_id": company_a.id, "contract_type": "fixed_term",
              "start_date": "2025-01-01"},
    )
    assert contract.status_code == 201, contract.text

    return SimpleNamespace(
        company_a=company_a, company_b=company_b, employee=employee_a,
        document=document.json(), contract=contract.json(), type_id=type_ids[0]["id"],
    )


def test_company_admin_can_manage_documents(client, matrix_env):
    response = client.post(
        f"/api/v1/employees/{matrix_env.employee['id']}/documents",
        headers=login(client, "admin@matrix-a.co")["headers"],
        data={"document_type_id": str(matrix_env.type_id)},
        files={"file": ("admin.pdf", PDF, "application/pdf")},
    )
    assert response.status_code == 201


def test_auditor_reads_but_cannot_upload_or_delete(client, matrix_env):
    env = matrix_env
    auth = login(client, "auditor@matrix-a.co")
    url = f"/api/v1/employees/{env.employee['id']}/documents"

    assert client.get(url, headers=auth["headers"]).status_code == 200

    upload = client.post(
        url, headers=auth["headers"],
        data={"document_type_id": str(env.type_id)},
        files={"file": ("a.pdf", PDF, "application/pdf")},
    )
    assert upload.status_code == 403
    assert upload.json()["code"] == "forbidden"

    removed = client.delete(f"{url}/{env.document['id']}", headers=auth["headers"])
    assert removed.status_code == 403


def test_hr_officer_uploads_but_cannot_delete(client, matrix_env):
    env = matrix_env
    auth = login(client, "officer@matrix-a.co")

    upload = client.post(
        f"/api/v1/employees/{env.employee['id']}/documents",
        headers=auth["headers"],
        data={"document_type_id": str(env.type_id)},
        files={"file": ("o.pdf", PDF, "application/pdf")},
    )
    assert upload.status_code == 201, upload.text

    removed = client.delete(
        f"/api/v1/employees/{env.employee['id']}/documents/{env.document['id']}",
        headers=auth["headers"],
    )
    assert removed.status_code == 403


def test_hr_manager_updates_contract_but_cannot_delete(client, matrix_env):
    env = matrix_env
    auth = login(client, "manager@matrix-a.co")
    url = f"/api/v1/employees/{env.employee['id']}/contracts/{env.contract['id']}"

    updated = client.patch(url, headers=auth["headers"], json={"notes": "reviewed"})
    assert updated.status_code == 200, updated.text

    removed = client.delete(url, headers=auth["headers"])
    assert removed.status_code == 403


def test_roleless_user_is_denied_every_phase3_route(client, matrix_env):
    env = matrix_env
    auth = login(client, "noperm@matrix-a.co")
    headers = {**auth["headers"], "X-Company-Id": str(env.company_a.id)}

    assert client.get(
        f"/api/v1/employees/{env.employee['id']}/documents", headers=headers
    ).status_code == 403
    assert client.get(
        f"/api/v1/employees/{env.employee['id']}/contracts", headers=headers
    ).status_code == 403
    assert client.get(
        f"/api/v1/employees/{env.employee['id']}/employment-history", headers=headers
    ).status_code == 403
    assert client.get(
        f"/api/v1/employees/{env.employee['id']}/user", headers=headers
    ).status_code == 403


def test_other_company_sees_404_not_403(client, matrix_env):
    env = matrix_env
    auth_b = login(client, "admin@matrix-b.co")
    headers_b = {**auth_b["headers"], "X-Company-Id": str(env.company_b.id)}

    documents = client.get(
        f"/api/v1/employees/{env.employee['id']}/documents", headers=headers_b
    )
    assert documents.status_code == 404
    assert documents.json()["code"] == "EMPLOYEE_NOT_FOUND"

    contracts = client.get(
        f"/api/v1/employees/{env.employee['id']}/contracts", headers=headers_b
    )
    assert contracts.status_code == 404

    history = client.get(
        f"/api/v1/employees/{env.employee['id']}/employment-history",
        headers=headers_b,
    )
    assert history.status_code == 404

    detail_document = client.get(
        f"/api/v1/employees/{env.employee['id']}/documents/{env.document['id']}",
        headers=headers_b,
    )
    assert detail_document.status_code == 404


def test_download_requires_its_own_permission(client, matrix_env, db_session):
    env = matrix_env
    # Custom role: list-only, no download permission.
    role = client.post(
        "/api/v1/roles",
        headers=login(client, "admin@matrix-a.co")["headers"],
        json={"company_id": env.company_a.id, "code": "doc_viewer",
              "name": "Document Viewer"},
    )
    assert role.status_code == 201, role.text
    granted = client.put(
        f"/api/v1/roles/{role.json()['id']}/permissions",
        headers=login(client, "admin@matrix-a.co")["headers"],
        json={"permission_codes": [
            "employee.read",
            "employee_document.view",
        ]},
    )
    assert granted.status_code == 200, granted.text

    seed_user(db_session, "viewer@matrix-a.co", env.company_a, "doc_viewer")
    viewer = login(client, "viewer@matrix-a.co")
    url = f"/api/v1/employees/{env.employee['id']}/documents/{env.document['id']}"

    assert client.get(url, headers=viewer["headers"]).status_code == 200
    download = client.get(f"{url}/download", headers=viewer["headers"])
    assert download.status_code == 403
    assert download.json()["code"] == "forbidden"


def test_history_create_is_denied_for_auditor_and_allowed_for_manager(
    client, matrix_env
):
    env = matrix_env
    url = f"/api/v1/employees/{env.employee['id']}/employment-history"
    payload = {
        "company_id": env.company_a.id, "effective_from": "2025-01-01",
        "employment_status": "active", "employment_type": "full_time",
    }

    auditor = login(client, "auditor@matrix-a.co")
    assert client.get(url, headers=auditor["headers"]).status_code == 200
    denied = client.post(url, headers=auditor["headers"], json=payload)
    assert denied.status_code == 403

    manager = login(client, "manager@matrix-a.co")
    allowed = client.post(url, headers=manager["headers"], json=payload)
    assert allowed.status_code == 201, allowed.text


def test_link_manage_allowed_for_hr_manager(client, matrix_env, db_session):
    env = matrix_env
    target = seed_user(db_session, "link-matrix@matrix-a.co", env.company_a)
    manager = login(client, "manager@matrix-a.co")
    url = f"/api/v1/employees/{env.employee['id']}/user"

    linked = client.post(
        url, headers=manager["headers"], json={"user_id": target.id}
    )
    assert linked.status_code == 200, linked.text

    officer = login(client, "officer@matrix-a.co")
    denied = client.delete(url, headers=officer["headers"])
    assert denied.status_code == 403  # hr_officer has link.view only


def test_raw_cross_company_insert_blocked_by_rls(client, matrix_env, db_session):
    from app.core.rls import clear_context, elevate_for_seed, set_context

    env = matrix_env
    elevate_for_seed(db_session)
    employee_id = db_session.execute(
        text("SELECT id FROM employees LIMIT 1")
    ).scalar_one()
    type_id = db_session.execute(
        text("SELECT id FROM employee_document_types LIMIT 1")
    ).scalar_one()
    clear_context(db_session)

    set_context(
        db_session, user_id=None, company_ids=[env.company_b.id],
        is_platform_admin=False,
    )
    with pytest.raises(Exception) as excinfo:
        db_session.execute(
            text(
                "INSERT INTO employee_documents "
                "(company_id, employee_id, document_type_id, file_name, "
                " mime_type, file_size, storage_key, created_at, updated_at) "
                f"VALUES ({env.company_a.id}, {employee_id}, {type_id}, "
                "'x.pdf', 'application/pdf', 1, "
                "'company_1/employee_1/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.pdf', "
                "now(), now())"
            )
        )
        db_session.flush()
    assert "row-level security" in str(excinfo.value).lower()
    db_session.rollback()
    clear_context(db_session)
