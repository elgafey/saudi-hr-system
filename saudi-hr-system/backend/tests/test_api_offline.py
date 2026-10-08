from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture(scope="module")
def offline_client():
    application = create_app()
    with TestClient(application) as client:
        yield client


def test_health_endpoint_reports_status(offline_client):
    response = offline_client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["phase"] == 8
    assert body["database"] in ("up", "down")
    assert "companies" in body["rls_tables"]
    assert "employees" in body["rls_tables"]
    assert "employee_documents" in body["rls_tables"]
    assert "employee_contracts" in body["rls_tables"]
    assert "employee_employment_history" in body["rls_tables"]
    assert "work_schedules" in body["rls_tables"]
    assert "attendance_records" in body["rls_tables"]
    assert "overtime_records" in body["rls_tables"]
    assert "payroll_periods" in body["rls_tables"]
    assert "payroll_runs" in body["rls_tables"]
    assert "payslip_lines" in body["rls_tables"]
    assert "employee_requests" in body["rls_tables"]
    assert "employee_request_events" in body["rls_tables"]
    assert "employee_document_visibility" in body["rls_tables"]
    assert "salary_advances" in body["rls_tables"]
    assert "salary_advance_events" in body["rls_tables"]


def test_openapi_contains_phase1_paths(offline_client):
    spec = offline_client.get("/openapi.json").json()
    for path in (
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
        "/api/v1/companies",
        "/api/v1/branches",
        "/api/v1/users",
        "/api/v1/roles",
        "/api/v1/permissions",
        "/api/v1/audit-logs",
        "/api/v1/employee-document-types",
        "/api/v1/employees/{employee_id}/contracts",
        "/api/v1/employees/{employee_id}/documents",
        "/api/v1/employees/{employee_id}/employment-history",
        "/api/v1/employees/{employee_id}/user",
        # Phase 4 - attendance domain
        "/api/v1/work-schedules",
        "/api/v1/work-schedules/{schedule_id}",
        "/api/v1/work-schedules/{schedule_id}/days",
        "/api/v1/shifts",
        "/api/v1/employees/{employee_id}/work-assignments",
        "/api/v1/employees/{employee_id}/schedule",
        "/api/v1/attendance",
        "/api/v1/attendance/check-in",
        "/api/v1/attendance/check-out",
        "/api/v1/overtime",
        "/api/v1/overtime/{overtime_id}/submit",
        "/api/v1/overtime/{overtime_id}/approve",
        "/api/v1/overtime/{overtime_id}/reject",
        "/api/v1/overtime/{overtime_id}/cancel",
        "/api/v1/overtime/{overtime_id}/correct",
        # Phase 6 - payroll domain
        "/api/v1/salary-components",
        "/api/v1/salary-assignments",
        "/api/v1/salary-assignments/{assignment_id}",
        "/api/v1/payroll-periods",
        "/api/v1/payroll-periods/{period_id}",
        "/api/v1/payroll-periods/{period_id}/calculate",
        "/api/v1/payroll-periods/{period_id}/review",
        "/api/v1/payroll-periods/{period_id}/approve",
        "/api/v1/payroll-periods/{period_id}/mark-paid",
        "/api/v1/payroll-periods/{period_id}/lock",
        "/api/v1/payroll-runs",
        "/api/v1/payroll-runs/{run_id}",
        "/api/v1/payroll-runs/{run_id}/lines",
        "/api/v1/payroll-runs/{run_id}/export",
        "/api/v1/payslips/{run_line_id}",
        "/api/v1/payroll-adjustments",
        "/api/v1/payroll-deductions",
        "/api/v1/payroll-statutory-rules",
        # Phase 7 - ESS + request/approval domain
        "/api/v1/me/profile",
        "/api/v1/me/documents",
        "/api/v1/me/documents/{document_id}/download",
        "/api/v1/me/attendance",
        "/api/v1/me/payslips",
        "/api/v1/me/payslips/{run_line_id}",
        "/api/v1/employee-requests",
        "/api/v1/employee-requests/{request_id}",
        "/api/v1/employee-requests/{request_id}/submit",
        "/api/v1/employee-requests/{request_id}/approve",
        "/api/v1/employee-requests/{request_id}/reject",
        "/api/v1/employee-requests/{request_id}/cancel",
        "/api/v1/approvals",
        "/api/v1/employee-documents/{document_id}/visibility",
        # Phase 8 - salary advances
        "/api/v1/salary-advances",
        "/api/v1/salary-advances/{advance_id}",
        "/api/v1/salary-advances/{advance_id}/submit",
        "/api/v1/salary-advances/{advance_id}/approve",
        "/api/v1/salary-advances/{advance_id}/reject",
        "/api/v1/salary-advances/{advance_id}/cancel",
        "/api/v1/salary-advances/{advance_id}/disburse",
        "/api/v1/salary-advances/{advance_id}/settle",
    ):
        assert path in spec["paths"], f"missing {path}"

    visibility = spec["paths"][
        "/api/v1/employee-documents/{document_id}/visibility"
    ]
    assert {"get", "patch"} <= set(visibility)


def test_no_future_module_paths_in_openapi(offline_client):
    # employees/documents/contracts/history, the attendance domain, the
    # leave domain and the payroll domain shipped in Phase 2/3/4/5/6; the
    # remaining markers are still future modules that must not appear.
    spec = offline_client.get("/openapi.json").json()
    for path in spec["paths"]:
        for marker in ("gosi", "/loans", "/pension"):
            assert marker not in path, f"phase 7+ path leaked: {path}"


def test_me_requires_authentication(offline_client):
    response = offline_client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_me_rejects_garbage_token(offline_client):
    response = offline_client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-token"}
    )
    assert response.status_code == 401


def test_companies_requires_authentication(offline_client):
    assert offline_client.get("/api/v1/companies").status_code == 401
    assert offline_client.post("/api/v1/companies", json={"name": "X"}).status_code == 401


def test_branches_requires_authentication(offline_client):
    assert offline_client.get("/api/v1/branches").status_code == 401


def test_users_requires_authentication(offline_client):
    assert offline_client.get("/api/v1/users").status_code == 401


def test_roles_requires_authentication(offline_client):
    assert offline_client.get("/api/v1/roles").status_code == 401


def test_audit_requires_authentication(offline_client):
    assert offline_client.get("/api/v1/audit-logs").status_code == 401


def test_refresh_get_not_allowed(offline_client):
    assert offline_client.get("/api/v1/auth/refresh").status_code == 405


def test_refresh_missing_csrf_header_forbidden(offline_client):
    offline_client.cookies.set("hr_csrf_token", "csrf-value")
    offline_client.cookies.set("hr_refresh_token", "whatever", path="/api/v1/auth")
    response = offline_client.post("/api/v1/auth/refresh")
    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]
    offline_client.cookies.delete("hr_csrf_token")
    offline_client.cookies.delete("hr_refresh_token")


def test_refresh_incorrect_csrf_forbidden(offline_client):
    offline_client.cookies.set("hr_csrf_token", "csrf-value")
    offline_client.cookies.set("hr_refresh_token", "whatever", path="/api/v1/auth")
    response = offline_client.post(
        "/api/v1/auth/refresh", headers={"X-CSRF-Token": "wrong"}
    )
    assert response.status_code == 403
    offline_client.cookies.delete("hr_csrf_token")
    offline_client.cookies.delete("hr_refresh_token")


def test_refresh_without_cookies_unauthorized(offline_client):
    offline_client.cookies.set("hr_csrf_token", "csrf-value")
    response = offline_client.post(
        "/api/v1/auth/refresh", headers={"X-CSRF-Token": "csrf-value"}
    )
    assert response.status_code == 401
    offline_client.cookies.delete("hr_csrf_token")


def test_login_with_invalid_body_is_422(offline_client):
    response = offline_client.post(
        "/api/v1/auth/login", json={"identifier": "ab", "password": ""}
    )
    assert response.status_code == 422


def test_domain_errors_have_stable_shape(offline_client):
    response = offline_client.get("/api/v1/auth/me")
    body = response.json()
    assert body == {"detail": "Authentication required", "code": "unauthorized"}
