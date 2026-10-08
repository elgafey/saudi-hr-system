from __future__ import annotations

import pytest
from sqlalchemy import text

from app.core.rls import clear_context, set_context
from tests.conftest import seed_company

pytestmark = pytest.mark.db

# (table, insert sql with :company bind param, search marker)
TABLES = {
    "departments": (
        "INSERT INTO departments (company_id, code, name_ar, name_en, status) "
        "VALUES (:company, 'RLS-D', 'قسم', 'RLS Dept', 'active') "
        "RETURNING id",
        "RLS-D",
    ),
    "job_positions": (
        "INSERT INTO job_positions (company_id, code, name_ar, name_en, status) "
        "VALUES (:company, 'RLS-P', 'منصب', 'RLS Position', 'active') "
        "RETURNING id",
        "RLS-P",
    ),
    "job_grades": (
        "INSERT INTO job_grades (company_id, code, name_ar, name_en, level, status) "
        "VALUES (:company, 'RLS-G', 'درجة', 'RLS Grade', 1, 'active') "
        "RETURNING id",
        "RLS-G",
    ),
    "employees": (
        "INSERT INTO employees (company_id, employee_number, first_name_ar, "
        "last_name_ar, first_name_en, last_name_en, status) "
        "VALUES (:company, 'RLS-E-' || :company, 'أ', 'ب', 'RLS', 'Employee', 'draft') "
        "RETURNING id",
        "RLS",
    ),
}


@pytest.fixture()
def two_companies(db_session):
    a = seed_company(db_session, "RLS A")
    b = seed_company(db_session, "RLS B")
    clear_context(db_session)
    return a, b


def _rows(db_session, table, column="code"):
    return db_session.execute(
        text(f"SELECT count(*) FROM {table}")
    ).scalar_one()


@pytest.mark.parametrize("table", sorted(TABLES))
def test_no_context_means_zero_rows(db_session, two_companies, table):
    insert_sql, _ = TABLES[table]
    company_a, company_b = two_companies

    set_context(
        db_session, user_id=None, company_ids=[], is_platform_admin=True
    )
    for company in (company_a, company_b):
        db_session.execute(text(insert_sql), {"company": company.id})
    db_session.flush()
    clear_context(db_session)

    assert _rows(db_session, table) == 0


@pytest.mark.parametrize("table", sorted(TABLES))
def test_member_context_scopes_reads(db_session, two_companies, table):
    insert_sql, _ = TABLES[table]
    company_a, company_b = two_companies

    set_context(
        db_session, user_id=None, company_ids=[], is_platform_admin=True
    )
    db_session.execute(text(insert_sql), {"company": company_a.id})
    db_session.execute(text(insert_sql), {"company": company_b.id})
    db_session.flush()

    set_context(
        db_session, user_id=None, company_ids=[company_a.id],
        is_platform_admin=False,
    )
    visible = db_session.execute(
        text(f"SELECT count(*) FROM {table} WHERE company_id = :c"),
        {"c": company_a.id},
    ).scalar_one()
    assert visible == 1

    from_other = db_session.execute(
        text(f"SELECT count(*) FROM {table} WHERE company_id = :c"),
        {"c": company_b.id},
    ).scalar_one()
    assert from_other == 0
    clear_context(db_session)


@pytest.mark.parametrize("table", sorted(TABLES))
def test_cross_company_insert_blocked(db_session, two_companies, table):
    insert_sql, _ = TABLES[table]
    company_a, company_b = two_companies

    set_context(
        db_session, user_id=None, company_ids=[company_a.id],
        is_platform_admin=False,
    )
    with pytest.raises(Exception) as excinfo:
        db_session.execute(text(insert_sql), {"company": company_b.id})
        db_session.flush()
    assert "row-level security" in str(excinfo.value).lower()
    db_session.rollback()
    clear_context(db_session)


@pytest.mark.parametrize("table", sorted(TABLES))
def test_cross_company_update_and_delete_blocked(db_session, two_companies, table):
    insert_sql, marker = TABLES[table]
    company_a, company_b = two_companies

    set_context(
        db_session, user_id=None, company_ids=[], is_platform_admin=True
    )
    id_b = db_session.execute(
        text(insert_sql), {"company": company_b.id}
    ).scalar_one()
    db_session.flush()

    set_context(
        db_session, user_id=None, company_ids=[company_a.id],
        is_platform_admin=False,
    )
    updated = db_session.execute(
        text(f"UPDATE {table} SET status = 'inactive' WHERE id = :id"),
        {"id": id_b},
    ).rowcount
    assert updated == 0

    deleted = db_session.execute(
        text(f"DELETE FROM {table} WHERE id = :id"), {"id": id_b}
    ).rowcount
    assert deleted == 0
    clear_context(db_session)

    # Row still exists (verified with elevated context).
    set_context(
        db_session, user_id=None, company_ids=[], is_platform_admin=True
    )
    assert db_session.execute(
        text(f"SELECT count(*) FROM {table} WHERE id = :id"), {"id": id_b}
    ).scalar_one() == 1
    clear_context(db_session)


@pytest.mark.parametrize("table", sorted(TABLES))
def test_platform_admin_context_bypasses_tenant_scope(
    db_session, two_companies, table
):
    insert_sql, _ = TABLES[table]
    company_a, company_b = two_companies

    set_context(
        db_session, user_id=None, company_ids=[], is_platform_admin=True
    )
    db_session.execute(text(insert_sql), {"company": company_a.id})
    db_session.execute(text(insert_sql), {"company": company_b.id})
    db_session.flush()

    assert _rows(db_session, table) == 2
    clear_context(db_session)


def test_phase2_tables_have_forced_rls(db_session):
    rows = db_session.execute(
        text(
            "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relname IN "
            "('departments','job_positions','job_grades','employees')"
        )
    ).all()
    assert len(rows) == 4
    for name, enabled, forced in rows:
        assert enabled, f"{name} RLS not enabled"
        assert forced, f"{name} FORCE RLS not set"


def test_phase2_policies_use_tenant_clauses(db_session):
    rows = db_session.execute(
        text(
            "SELECT tablename, qual, with_check FROM pg_policies "
            "WHERE schemaname = 'public' AND tablename IN "
            "('departments','job_positions','job_grades','employees')"
        )
    ).all()
    assert len(rows) == 4
    for _name, qual, with_check in rows:
        assert "app.is_platform_admin()" in qual
        assert "app.current_company_ids()" in qual
        assert "app.is_platform_admin()" in with_check
        assert "app.current_company_ids()" in with_check
