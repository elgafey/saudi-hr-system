from __future__ import annotations

import pytest
from sqlalchemy import bindparam, text

from app.core.rls import clear_context, set_context
from tests.conftest import seed_company

pytestmark = pytest.mark.db

# (insert sql with named params, dependency ids the sql consumes)
TABLES: dict[str, tuple[str, tuple[str, ...]]] = {
    "salary_components": (
        "INSERT INTO salary_components (company_id, code, name_ar, name_en, "
        "category, calculation_basis) "
        "VALUES (:company, 'RLS-C' || :company, 'مكوّن', 'RLS Component', "
        "'earning', 'fixed') RETURNING id",
        (),
    ),
    "employee_salary_assignments": (
        "INSERT INTO employee_salary_assignments (company_id, employee_id, "
        "effective_from, basic_salary) "
        "VALUES (:company, :employee, DATE '2025-06-01', 5000) RETURNING id",
        ("employee",),
    ),
    "salary_assignment_components": (
        "INSERT INTO salary_assignment_components (company_id, assignment_id, "
        "component_id, amount) "
        "VALUES (:company, :assignment, :component, 100) RETURNING id",
        ("assignment", "component"),
    ),
    "payroll_periods": (
        "INSERT INTO payroll_periods (company_id, name, period_start, period_end) "
        "VALUES (:company, 'RLS Period ' || :company, DATE '2025-06-01', "
        "DATE '2025-06-30') RETURNING id",
        (),
    ),
    "payroll_runs": (
        "INSERT INTO payroll_runs (company_id, period_id, run_number) "
        "VALUES (:company, :period, 1) RETURNING id",
        ("period",),
    ),
    "payroll_run_lines": (
        "INSERT INTO payroll_run_lines (company_id, run_id, employee_id, "
        "basic_snapshot, currency) "
        "VALUES (:company, :run, :employee, 5000, 'SAR') RETURNING id",
        ("run", "employee"),
    ),
    "payslip_lines": (
        "INSERT INTO payslip_lines (company_id, run_line_id, component_id, "
        "line_type, label_ar, label_en, unit, amount) "
        "VALUES (:company, :run_line, :component, 'earning', 'الأساس', "
        "'Basic', 'amount', 100) RETURNING id",
        ("run_line", "component"),
    ),
    "payroll_deduction_rules": (
        "INSERT INTO payroll_deduction_rules (company_id, employee_id, name, "
        "amount, effective_from) "
        "VALUES (:company, :employee, 'RLS Deduction', 100, DATE '2025-06-01') "
        "RETURNING id",
        ("employee",),
    ),
    "payroll_adjustments": (
        "INSERT INTO payroll_adjustments (company_id, employee_id, period_id, "
        "amount, direction, reason) "
        "VALUES (:company, :employee, :period, 100, 'earning', "
        "'RLS adjustment') RETURNING id",
        ("employee", "period"),
    ),
    "payroll_statutory_rules": (
        "INSERT INTO payroll_statutory_rules (company_id, statutory_key, "
        "effective_from, rule_json, source_reference) "
        "VALUES (:company, 'overtime', DATE '2025-06-01', "
        "'{\"overtime_rate_percent\": 50}'::jsonb, 'REF-RLS') RETURNING id",
        (),
    ),
}

# Tables whose insert produces a dependency id other tables consume.
KEY_OF = {
    "salary_components": "component",
    "employee_salary_assignments": "assignment",
    "payroll_periods": "period",
    "payroll_runs": "run",
    "payroll_run_lines": "run_line",
}


@pytest.fixture()
def two_companies(db_session):
    a = seed_company(db_session, "RLS Pay A")
    b = seed_company(db_session, "RLS Pay B")
    clear_context(db_session)
    return a, b


def _elevate(db_session) -> None:
    set_context(db_session, user_id=None, company_ids=[], is_platform_admin=True)


def _as_member(db_session, company_id: int) -> None:
    set_context(
        db_session,
        user_id=None,
        company_ids=[company_id],
        is_platform_admin=False,
    )


def _seed_rows(db_session, company_id: int) -> dict[str, int]:
    """Insert one row per phase 6 table for a company (elevated context)."""
    ids: dict[str, int] = {}
    ids["employee"] = db_session.execute(
        text(
            "INSERT INTO employees (company_id, employee_number, first_name_ar, "
            "last_name_ar, first_name_en, last_name_en, status) "
            "VALUES (:c, 'RLS-E-' || :c, 'أ', 'ب', 'RLS', 'Employee', 'draft') "
            "RETURNING id"
        ),
        {"c": company_id},
    ).scalar_one()
    for table, (sql, _deps) in TABLES.items():
        params: dict[str, object] = {"company": company_id}
        params.update({k: v for k, v in ids.items() if f":{k}" in sql})
        row_id = db_session.execute(text(sql), params).scalar_one()
        key = KEY_OF.get(table)
        if key is not None:
            ids[key] = row_id
    return ids


def _count(db_session, table: str) -> int:
    return db_session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


@pytest.mark.parametrize("table", sorted(TABLES))
def test_no_context_means_zero_rows(db_session, two_companies, table):
    company_a, company_b = two_companies

    _elevate(db_session)
    for company in (company_a, company_b):
        _seed_rows(db_session, company.id)
    db_session.flush()
    clear_context(db_session)

    assert _count(db_session, table) == 0


@pytest.mark.parametrize("table", sorted(TABLES))
def test_member_context_scopes_reads(db_session, two_companies, table):
    company_a, company_b = two_companies

    _elevate(db_session)
    _seed_rows(db_session, company_a.id)
    _seed_rows(db_session, company_b.id)
    db_session.flush()

    _as_member(db_session, company_a.id)
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
    assert _count(db_session, table) == 1
    clear_context(db_session)


@pytest.mark.parametrize("table", sorted(TABLES))
def test_cross_company_insert_blocked(db_session, two_companies, table):
    insert_sql, deps = TABLES[table]
    company_a, company_b = two_companies

    _elevate(db_session)
    ids = _seed_rows(db_session, company_a.id)
    db_session.flush()

    _as_member(db_session, company_a.id)
    params: dict[str, object] = {"company": company_b.id}
    params.update({dep: ids[dep] for dep in deps})
    with pytest.raises(Exception) as excinfo:
        db_session.execute(text(insert_sql), params)
        db_session.flush()
    assert "row-level security" in str(excinfo.value).lower()
    db_session.rollback()
    clear_context(db_session)


@pytest.mark.parametrize("table", sorted(TABLES))
def test_cross_company_update_and_delete_blocked(db_session, two_companies, table):
    company_a, company_b = two_companies

    _elevate(db_session)
    _seed_rows(db_session, company_a.id)
    _seed_rows(db_session, company_b.id)
    db_session.flush()
    row_b = db_session.execute(
        text(f"SELECT id FROM {table} WHERE company_id = :c"),
        {"c": company_b.id},
    ).scalar_one()
    assert row_b > 0

    _as_member(db_session, company_a.id)
    updated = db_session.execute(
        text(f"UPDATE {table} SET company_id = :a WHERE id = :id"),
        {"a": company_a.id, "id": row_b},
    ).rowcount
    assert updated == 0

    deleted = db_session.execute(
        text(f"DELETE FROM {table} WHERE id = :id"), {"id": row_b}
    ).rowcount
    assert deleted == 0
    clear_context(db_session)

    _elevate(db_session)
    assert (
        db_session.execute(
            text(f"SELECT count(*) FROM {table} WHERE id = :id"),
            {"id": row_b},
        ).scalar_one()
        == 1
    )
    clear_context(db_session)


@pytest.mark.parametrize("table", sorted(TABLES))
def test_platform_admin_context_bypasses_tenant_scope(db_session, two_companies, table):
    company_a, company_b = two_companies

    _elevate(db_session)
    _seed_rows(db_session, company_a.id)
    _seed_rows(db_session, company_b.id)
    db_session.flush()

    assert _count(db_session, table) == 2
    clear_context(db_session)


def test_phase6_tables_have_forced_rls(db_session):
    rows = db_session.execute(
        text(
            "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relname IN :names"
        ).bindparams(bindparam("names", expanding=True)),
        {"names": sorted(TABLES)},
    ).all()
    assert len(rows) == len(TABLES)
    for name, enabled, forced in rows:
        assert enabled, f"{name} RLS not enabled"
        assert forced, f"{name} FORCE RLS not set"


def test_phase6_policies_use_tenant_clauses(db_session):
    rows = db_session.execute(
        text(
            "SELECT tablename, qual, with_check FROM pg_policies "
            "WHERE schemaname = 'public' AND tablename IN "
            "('salary_components','employee_salary_assignments',"
            "'salary_assignment_components','payroll_periods','payroll_runs',"
            "'payroll_run_lines','payslip_lines','payroll_deduction_rules',"
            "'payroll_adjustments','payroll_statutory_rules')"
        )
    ).all()
    assert len(rows) == len(TABLES)
    for _name, qual, with_check in rows:
        assert qual is not None and "app.is_platform_admin()" in qual
        assert qual is not None and "app.current_company_ids()" in qual
        assert with_check is not None
        assert "app.is_platform_admin()" in with_check
        assert "app.current_company_ids()" in with_check
