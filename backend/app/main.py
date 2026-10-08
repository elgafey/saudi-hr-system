from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.advance.router import salary_advances_router
from app.attendance.router import router as attendance_router
from app.audit.router import router as audit_router
from app.auth.router import router as auth_router
from app.branches.router import router as branches_router
from app.companies.router import router as companies_router
from app.core.config import get_settings
from app.core.exceptions import DomainError
from app.core.rls import RLS_REGISTRY
from app.core.rls_phase2 import register_phase2_rls
from app.core.rls_phase3 import register_phase3_rls
from app.core.rls_phase4 import register_phase4_rls
from app.core.rls_phase5 import register_phase5_rls
from app.core.rls_phase6 import register_phase6_rls
from app.core.rls_phase7 import register_phase7_rls
from app.core.rls_phase8 import register_phase8_rls
from app.departments.router import router as departments_router
from app.employee_contracts.router import router as contracts_router
from app.employee_documents.router import router as documents_router
from app.employee_documents.router import types_router as document_types_router
from app.employee_work_assignments.router import (
    router as work_assignments_router,
)
from app.employees.router import router as employees_router
from app.employment_history.router import router as history_router
from app.ess.router import approvals_router, me_router
from app.ess.router import requests_router as employee_requests_router
from app.ess.router import visibility_router as document_visibility_router
from app.job_grades.router import router as job_grades_router
from app.job_positions.router import router as job_positions_router
from app.leave.router import allocations_router as leave_allocations_router
from app.leave.router import balances_router as leave_balances_router
from app.leave.router import holidays_router as company_holidays_router
from app.leave.router import leave_types_router
from app.leave.router import requests_router as leave_requests_router
from app.leave.router import statutory_router as leave_statutory_router
from app.overtime.router import router as overtime_router
from app.payroll.router import adjustments_router as payroll_adjustments_router
from app.payroll.router import deductions_router as payroll_deductions_router
from app.payroll.router import payslips_router as payroll_payslips_router
from app.payroll.router import periods_router as payroll_periods_router
from app.payroll.router import runs_router as payroll_runs_router
from app.payroll.router import salary_assignments_router, salary_components_router
from app.payroll.router import statutory_router as payroll_statutory_router
from app.roles.router import router as roles_router
from app.shifts.router import router as shifts_router
from app.users.router import router as users_router
from app.work_schedules.router import resolve_router as schedule_resolve_router
from app.work_schedules.router import router as work_schedules_router

# Later-phase tables must be part of the runtime registry (health endpoint,
# apply-rls CLI). Alembic never imports this module, so migration 0001 keeps
# running against the Phase 1-only registry.
register_phase2_rls()
register_phase3_rls()
register_phase4_rls()
register_phase5_rls()
register_phase6_rls()
register_phase7_rls()
register_phase8_rls()

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.core.database import database_available

    app.state.database_available = database_available()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    # M6: interactive API documentation is a development/test aid; it is
    # disabled by default whenever ENVIRONMENT=production.
    docs = None if settings.is_production else "/docs"
    redoc = None if settings.is_production else "/redoc"
    openapi_url = None if settings.is_production else "/openapi.json"
    app = FastAPI(
        title="Saudi HR Management System API",
        version="0.1.0",
        description=(
            "Multi-company Saudi HR platform. Phase 1: foundation, "
            "authentication, RBAC, companies, branches, audit. "
            "Phase 2: departments, job positions, job grades, employees. "
            "Phase 3: employee documents, contracts, employment history, "
            "employee-account links. Phase 4: work schedules, shifts, "
            "employee assignments, attendance and overtime. "
            "Phase 5: leave types, statutory rules, allocations, "
            "requests, balances and company holidays. "
            "Phase 6: salary components, effective-dated assignments, "
            "payroll periods and runs, payslips, adjustments, deduction "
            "rules and statutory payroll rules. Phase 7: employee "
            "self-service (/me), generic request & approval workflow and "
            "the manager approvals inbox. Phase 8: salary advances "
            "(apply, approve, disburse, repay through payroll)."
        ),
        lifespan=lifespan,
        docs_url=docs,
        redoc_url=redoc,
        openapi_url=openapi_url,
    )
    app.state.database_available = False

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(DomainError)
    async def domain_error_handler(
        request: Request, exc: DomainError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "code": exc.code},
        )

    @app.get("/health", tags=["system"])
    def health(request: Request) -> dict:
        return {
            "status": "ok",
            "phase": 8,
            "database": "up" if request.app.state.database_available else "down",
            "rls_tables": sorted(RLS_REGISTRY.keys()),
        }

    app.include_router(auth_router, prefix=API_PREFIX)
    app.include_router(companies_router, prefix=API_PREFIX)
    app.include_router(branches_router, prefix=API_PREFIX)
    app.include_router(users_router, prefix=API_PREFIX)
    app.include_router(roles_router, prefix=API_PREFIX)
    app.include_router(audit_router, prefix=API_PREFIX)
    app.include_router(departments_router, prefix=API_PREFIX)
    app.include_router(job_positions_router, prefix=API_PREFIX)
    app.include_router(job_grades_router, prefix=API_PREFIX)
    app.include_router(employees_router, prefix=API_PREFIX)
    app.include_router(documents_router, prefix=API_PREFIX)
    app.include_router(document_types_router, prefix=API_PREFIX)
    app.include_router(contracts_router, prefix=API_PREFIX)
    app.include_router(history_router, prefix=API_PREFIX)
    app.include_router(work_schedules_router, prefix=API_PREFIX)
    app.include_router(schedule_resolve_router, prefix=API_PREFIX)
    app.include_router(shifts_router, prefix=API_PREFIX)
    app.include_router(work_assignments_router, prefix=API_PREFIX)
    app.include_router(attendance_router, prefix=API_PREFIX)
    app.include_router(overtime_router, prefix=API_PREFIX)
    app.include_router(leave_types_router, prefix=API_PREFIX)
    app.include_router(leave_statutory_router, prefix=API_PREFIX)
    app.include_router(leave_allocations_router, prefix=API_PREFIX)
    app.include_router(leave_requests_router, prefix=API_PREFIX)
    app.include_router(leave_balances_router, prefix=API_PREFIX)
    app.include_router(company_holidays_router, prefix=API_PREFIX)
    app.include_router(salary_components_router, prefix=API_PREFIX)
    app.include_router(salary_assignments_router, prefix=API_PREFIX)
    app.include_router(payroll_periods_router, prefix=API_PREFIX)
    app.include_router(payroll_runs_router, prefix=API_PREFIX)
    app.include_router(payroll_payslips_router, prefix=API_PREFIX)
    app.include_router(payroll_adjustments_router, prefix=API_PREFIX)
    app.include_router(payroll_deductions_router, prefix=API_PREFIX)
    app.include_router(payroll_statutory_router, prefix=API_PREFIX)
    app.include_router(me_router, prefix=API_PREFIX)
    app.include_router(employee_requests_router, prefix=API_PREFIX)
    app.include_router(approvals_router, prefix=API_PREFIX)
    app.include_router(document_visibility_router, prefix=API_PREFIX)
    app.include_router(salary_advances_router, prefix=API_PREFIX)
    return app


app = create_app()
