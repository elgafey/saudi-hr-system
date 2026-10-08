from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.conftest import login, seed_company, seed_user

pytestmark = pytest.mark.db

PDF = b"%PDF-1.4\n%minimal test pdf\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def _create_employee(client, auth, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "first_name_ar": "سارة",
        "last_name_ar": "العلي",
        "first_name_en": "Sara",
        "last_name_en": "Alali",
        **overrides,
    }
    return client.post("/api/v1/employees", headers=auth["headers"], json=payload)


def _doc_env(client, db_session):
    company = seed_company(db_session, "Doc Co")
    seed_user(db_session, "admin@doc.co", company, "company_admin")
    auth = login(client, "admin@doc.co")
    headers = {**auth["headers"], "X-Company-Id": str(company.id)}
    created = _create_employee(client, auth, company.id)
    assert created.status_code == 201, created.text
    types = client.get("/api/v1/employee-document-types", headers=headers)
    assert types.status_code == 200, types.text
    assert len(types.json()) == 8
    return SimpleNamespace(
        company=company, auth=auth, headers=headers, employee=created.json(),
        types=types.json(),
    )


def _upload(env, client, **kwargs):
    files = {
        "file": (
            kwargs.pop("filename", "nida.pdf"),
            kwargs.pop("data", PDF),
            kwargs.pop("content_type", "application/pdf"),
        )
    }
    data = {"document_type_id": str(kwargs.pop("type_id", env.types[0]["id"]))}
    data.update({k: v for k, v in kwargs.items() if v is not None})
    return client.post(
        f"/api/v1/employees/{env.employee['id']}/documents",
        headers=env.headers,
        data=data,
        files=files,
    )


def _doc_key(db, document_id):
    from app.core.rls import clear_context, elevate_for_seed
    from app.shared.models import EmployeeDocument

    elevate_for_seed(db)
    try:
        row = db.get(EmployeeDocument, document_id)
        assert row is not None
        return row.storage_key, row.file_name, row.mime_type
    finally:
        clear_context(db)


def test_document_type_defaults_are_seeded_lazily(client, db_session):
    company = seed_company(db_session, "Type Co")
    seed_user(db_session, "admin@type.co", company, "company_admin")
    auth = login(client, "admin@type.co")
    headers = {**auth["headers"], "X-Company-Id": str(company.id)}

    first = client.get("/api/v1/employee-document-types", headers=headers)
    assert first.status_code == 200
    rows = first.json()
    assert len(rows) == 8
    assert {r["code"] for r in rows} == {
        "national_id", "passport", "iqama", "driving_license",
        "qualification", "certificate", "medical", "other",
    }
    assert all(r["is_default"] for r in rows)
    assert rows[0]["name_ar"] and rows[0]["name_en"]

    second = client.get("/api/v1/employee-document-types", headers=headers)
    assert len(second.json()) == 8  # idempotent, no duplicates


def test_custom_document_type_create_and_duplicate(client, db_session):
    company = seed_company(db_session, "Type2 Co")
    seed_user(db_session, "admin@type2.co", company, "company_admin")
    auth = login(client, "admin@type2.co")
    headers = {**auth["headers"], "X-Company-Id": str(company.id)}

    created = client.post(
        "/api/v1/employee-document-types",
        headers=headers,
        json={
            "company_id": company.id,
            "code": "offer_letter",
            "name_ar": "خطاب عرض العمل",
            "name_en": "Offer Letter",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["code"] == "offer_letter"
    assert created.json()["is_default"] is False

    duplicate = client.post(
        "/api/v1/employee-document-types",
        headers=headers,
        json={
            "company_id": company.id,
            "code": "offer_letter",
            "name_ar": "x",
            "name_en": "y",
        },
    )
    assert duplicate.status_code == 409


def test_document_upload_stores_bytes_and_metadata(client, db_session):
    env = _doc_env(client, db_session)
    response = _upload(
        env, client, filename="../../evil name.pdf", data=PDF,
        document_number="7654321098",
        issue_date="2025-01-15", expiry_date="2035-01-15",
        notes="National ID card",
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["file_name"] == "evil name.pdf"  # basename only, sanitized
    assert body["mime_type"] == "application/pdf"
    assert body["file_size"] == len(PDF)
    assert body["document_number"] == "7654321098"
    assert "storage_key" not in body  # never exposed

    key, _name, _mime = _doc_key(db_session, body["id"])
    from app.core.storage import get_storage

    assert get_storage().load(key) == PDF

    page = client.get(
        f"/api/v1/employees/{env.employee['id']}/documents",
        headers=env.headers,
    ).json()
    assert page["page"]["total"] == 1
    assert page["items"][0]["id"] == body["id"]


def test_document_download_returns_bytes_and_headers(client, db_session):
    env = _doc_env(client, db_session)
    uploaded = _upload(env, client, filename="passport.pdf", data=PDF)
    document_id = uploaded.json()["id"]

    response = client.get(
        f"/api/v1/employees/{env.employee['id']}/documents/{document_id}/download",
        headers=env.headers,
    )
    assert response.status_code == 200
    assert response.content == PDF
    assert response.headers["content-type"].startswith("application/pdf")
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "passport.pdf" in disposition
    assert response.headers["x-content-type-options"] == "nosniff"

    audit = client.get(
        "/api/v1/audit-logs", headers=env.headers, params={"action": "document.download"}
    ).json()
    assert audit["page"]["total"] == 1
    assert audit["items"][0]["entity"] == "employee_document"


def test_document_empty_file_rejected(client, db_session):
    env = _doc_env(client, db_session)
    response = _upload(env, client, data=b"")
    assert response.status_code == 400
    assert response.json()["code"] == "DOCUMENT_EMPTY_FILE"


def test_document_oversize_file_rejected(client, db_session):
    env = _doc_env(client, db_session)
    response = _upload(env, client, data=b"x" * (10 * 1024 * 1024 + 1))
    assert response.status_code == 413
    assert response.json()["code"] == "DOCUMENT_FILE_TOO_LARGE"


def test_document_disallowed_content_rejected(client, db_session):
    env = _doc_env(client, db_session)
    response = _upload(env, client, filename="evil.txt", data=b"just some text")
    assert response.status_code == 415
    assert response.json()["code"] == "DOCUMENT_INVALID_MIME_TYPE"


def test_document_spoofed_mime_rejected(client, db_session):
    env = _doc_env(client, db_session)
    response = _upload(
        env, client, filename="fake.png", data=PDF, content_type="image/png"
    )
    assert response.status_code == 415
    assert response.json()["code"] == "DOCUMENT_INVALID_MIME_TYPE"


def test_document_date_ordering_rejected(client, db_session):
    env = _doc_env(client, db_session)
    response = _upload(
        env, client, issue_date="2025-06-01", expiry_date="2025-01-01"
    )
    assert response.status_code == 400
    assert response.json()["code"] == "DOCUMENT_INVALID_DATE_RANGE"


def test_document_type_must_belong_to_company(client, db_session):
    env = _doc_env(client, db_session)
    other = seed_company(db_session, "Doc Other Co")
    seed_user(db_session, "admin@doc-other.co", other, "company_admin")
    other_auth = login(client, "admin@doc-other.co")
    other_headers = {**other_auth["headers"], "X-Company-Id": str(other.id)}
    other_types = client.get(
        "/api/v1/employee-document-types", headers=other_headers
    ).json()

    response = _upload(env, client, type_id=other_types[0]["id"])
    assert response.status_code == 404
    assert response.json()["code"] == "DOCUMENT_TYPE_NOT_FOUND"


def test_document_update_metadata_and_audit(client, db_session):
    import json

    env = _doc_env(client, db_session)
    document_id = _upload(env, client).json()["id"]
    passport_type = next(t for t in env.types if t["code"] == "passport")

    response = client.patch(
        f"/api/v1/employees/{env.employee['id']}/documents/{document_id}",
        headers=env.headers,
        json={"document_type_id": passport_type["id"], "notes": "renewed"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["document_type_id"] == passport_type["id"]
    assert body["notes"] == "renewed"

    audit = client.get(
        "/api/v1/audit-logs", headers=env.headers, params={"action": "document.update"}
    ).json()
    assert audit["page"]["total"] == 1
    new_value = json.loads(audit["items"][0]["new_value"])
    assert set(new_value["fields"]) == {"document_type_id", "notes"}


def test_document_delete_removes_row_and_file(client, db_session):
    env = _doc_env(client, db_session)
    document_id = _upload(env, client).json()["id"]
    key, _name, _mime = _doc_key(db_session, document_id)

    response = client.delete(
        f"/api/v1/employees/{env.employee['id']}/documents/{document_id}",
        headers=env.headers,
    )
    assert response.status_code == 204

    from app.core.exceptions import DocumentNotFoundError
    from app.core.storage import get_storage

    with pytest.raises(DocumentNotFoundError):
        get_storage().load(key)

    page = client.get(
        f"/api/v1/employees/{env.employee['id']}/documents",
        headers=env.headers,
    ).json()
    assert page["page"]["total"] == 0

    audit = client.get(
        "/api/v1/audit-logs", headers=env.headers, params={"action": "document.delete"}
    ).json()
    assert audit["page"]["total"] == 1


def test_document_pagination(client, db_session):
    env = _doc_env(client, db_session)
    for i in range(3):
        assert _upload(env, client, filename=f"doc{i}.pdf").status_code == 201

    page = client.get(
        f"/api/v1/employees/{env.employee['id']}/documents",
        headers=env.headers,
        params={"page": 2, "page_size": 2},
    ).json()
    assert page["page"]["total"] == 3
    assert len(page["items"]) == 1

    filtered = client.get(
        f"/api/v1/employees/{env.employee['id']}/documents",
        headers=env.headers,
        params={"document_type_id": env.types[1]["id"]},
    ).json()
    assert filtered["page"]["total"] == 0


def test_document_missing_employee_is_404_with_code(client, db_session):
    env = _doc_env(client, db_session)
    response = client.get("/api/v1/employees/999999/documents", headers=env.headers)
    assert response.status_code == 404
    assert response.json()["code"] == "EMPLOYEE_NOT_FOUND"


def test_document_cannot_be_fetched_under_wrong_employee(client, db_session):
    env = _doc_env(client, db_session)
    document_id = _upload(env, client).json()["id"]
    other = _create_employee(client, env.auth, env.company.id, first_name_en="Other")
    assert other.status_code == 201

    response = client.get(
        f"/api/v1/employees/{other.json()['id']}/documents/{document_id}",
        headers=env.headers,
    )
    assert response.status_code == 404
    assert response.json()["code"] == "DOCUMENT_NOT_FOUND"


def test_png_upload_uses_sniffed_mime(client, db_session):
    env = _doc_env(client, db_session)
    response = _upload(
        env, client, filename="photo.png", data=PNG, content_type="image/png"
    )
    assert response.status_code == 201, response.text
    assert response.json()["mime_type"] == "image/png"
