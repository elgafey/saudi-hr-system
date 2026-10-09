from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parent.parent

TEST_PASSWORD = "Str0ng!Passw0rd"


@lru_cache
def test_database_url() -> str:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    from app.core.config import get_settings

    base = get_settings().database_url
    if base.rsplit("/", 1)[-1] == "saudi_hr_test":
        return base
    return base.rsplit("/", 1)[0] + "/saudi_hr_test"


@lru_cache
def database_is_available() -> bool:
    try:
        engine = create_engine(
            test_database_url(), connect_args={"connect_timeout": 3}
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


def pytest_collection_modifyitems(config, items):
    if database_is_available():
        return
    skip_db = pytest.mark.skip(
        reason=(
            "PostgreSQL test database unavailable (pending) - "
            "create saudi_hr_test and set TEST_DATABASE_URL/DATABASE_URL"
        )
    )
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip_db)


@pytest.fixture(scope="session")
def test_engine(db_schema):
    engine = create_engine(db_schema, future=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def db_schema():
    url = test_database_url()
    os.environ["TEST_DATABASE_URL"] = url
    engine = create_engine(url, future=True)
    with engine.begin() as conn:
        import app.audit.model  # noqa: F401
        import app.auth.models  # noqa: F401
        import app.shared.models  # noqa: F401
        from app.shared.base import Base

        for table in reversed(Base.metadata.sorted_tables):
            table.drop(bind=conn, checkfirst=True)
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        conn.execute(text("DROP SCHEMA IF EXISTS app CASCADE"))
    engine.dispose()

    from alembic.config import Config

    from alembic import command

    # 0001_phase1 (frozen) applies RLS policies for every registered table.
    # Phase 2/3/4/5/6/7/8/9 rules may already be registered at import time
    # (app.main, test modules), but at 0001's point in history those tables
    # do not exist yet - mirror that history by hiding them during the
    # upgrade (migrations 0003/0004/0005/0006/0007/0008/0010 re-register
    # and apply their own rules).
    from app.core.rls import RLS_REGISTRY
    from app.core.rls_phase2 import PHASE2_RLS_TABLES
    from app.core.rls_phase3 import PHASE3_RLS_TABLES
    from app.core.rls_phase4 import PHASE4_RLS_TABLES
    from app.core.rls_phase5 import PHASE5_RLS_TABLES
    from app.core.rls_phase6 import PHASE6_RLS_TABLES
    from app.core.rls_phase7 import PHASE7_RLS_TABLES
    from app.core.rls_phase8 import PHASE8_RLS_TABLES
    from app.core.rls_phase9 import PHASE9_RLS_TABLES

    hidden = {
        t: RLS_REGISTRY.pop(t)
        for t in (
            *PHASE2_RLS_TABLES,
            *PHASE3_RLS_TABLES,
            *PHASE4_RLS_TABLES,
            *PHASE5_RLS_TABLES,
            *PHASE6_RLS_TABLES,
            *PHASE7_RLS_TABLES,
            *PHASE8_RLS_TABLES,
            *PHASE9_RLS_TABLES,
        )
        if t in RLS_REGISTRY
    }
    try:
        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        command.upgrade(cfg, "head")
    finally:
        RLS_REGISTRY.update(hidden)
    return url


@pytest.fixture(autouse=True)
def clean_tables(request):
    if "db" not in request.keywords:
        yield
        return
    url = request.getfixturevalue("db_schema")
    engine = create_engine(url, future=True)
    tables = (
        "audit_logs, refresh_tokens, user_roles, role_permissions, "
        "users, roles, branches, companies, "
        "employees, departments, job_positions, job_grades, "
        "employee_documents, employee_contracts, "
        "employee_employment_history, employee_document_types, "
        "overtime_records, attendance_records, employee_work_assignments, "
        "break_periods, work_schedule_days, shifts, work_schedules, "
        "leave_consumptions, leave_requests, leave_allocations, "
        "leave_statutory_rules, leave_types, company_holidays, "
        "payslip_lines, payroll_run_lines, payroll_runs, "
        "payroll_adjustments, payroll_deduction_rules, payroll_periods, "
        "salary_assignment_components, employee_salary_assignments, "
        "salary_components, payroll_statutory_rules, "
        "employee_request_events, employee_requests, "
        "employee_document_visibility, "
        "salary_advance_events, salary_advances, "
        "hr_letter_events, hr_letters"
    )
    with engine.begin() as conn:
        conn.execute(
            text("SELECT set_config('app.is_platform_admin','true',true)")
        )
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    engine.dispose()
    yield


@pytest.fixture()
def db_session(db_schema):
    engine = create_engine(db_schema, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def client(db_schema):
    from fastapi.testclient import TestClient

    from app.core.database import get_db
    from app.main import create_app

    engine = create_engine(db_schema, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def test_get_db():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    application = create_app()
    application.dependency_overrides[get_db] = test_get_db
    with TestClient(application) as test_client:
        yield test_client
    application.dependency_overrides.clear()
    engine.dispose()


def seed_company(db, name: str):
    from app.companies.service import seed_default_roles
    from app.core.rls import clear_context, elevate_for_seed
    from app.shared.models import Company

    elevate_for_seed(db)
    company = Company(name=name, name_en=name, name_ar=name)
    db.add(company)
    db.flush()
    seed_default_roles(db, company)
    db.commit()
    clear_context(db)
    return company


def seed_user(db, email: str, company=None, role_code=None, *, platform=False):
    from app.core.rls import clear_context, elevate_for_seed
    from app.core.security import hash_password
    from app.shared.models import User, UserRole

    elevate_for_seed(db)
    user = User(
        email=email,
        full_name=email.split("@")[0].replace(".", " ").title(),
        password_hash=hash_password(TEST_PASSWORD),
        is_active=True,
        is_platform_admin=platform,
        company_id=company.id if company is not None else None,
    )
    db.add(user)
    db.flush()
    if company is not None and role_code is not None:
        role = db.execute(
            select_role(company.id, role_code)
        ).scalar_one_or_none()
        if role is None:
            raise AssertionError(f"role {role_code} missing in company")
        db.add(
            UserRole(user_id=user.id, role_id=role.id, company_id=company.id)
        )
    db.commit()
    clear_context(db)
    return user


def select_role(company_id: int, code: str):
    from sqlalchemy import select

    from app.shared.models import Role

    return select(Role).where(
        Role.company_id == company_id, Role.code == code
    )


def login(client, identifier: str, password: str = TEST_PASSWORD) -> dict:
    response = client.post(
        "/api/v1/auth/login",
        json={"identifier": identifier, "password": password},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    csrf = client.cookies.get("hr_csrf_token")
    return {
        "token": body["access_token"],
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
        "csrf": csrf,
        "refresh": client.cookies.get("hr_refresh_token"),
    }
