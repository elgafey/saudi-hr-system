from __future__ import annotations

import re

import pytest

from app.core.exceptions import ConflictError
from app.employees.numbering import (
    EMPLOYEE_NUMBER_PATTERN,
    is_valid_employee_number,
    next_employee_number,
    reset_employee_number_generator,
    set_employee_number_generator,
)
from app.employees.schemas import EmployeeCreate
from tests.conftest import seed_company

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def restore_generator():
    yield
    reset_employee_number_generator()


def test_default_generator_produces_company_scoped_numbers(db_session):
    company = seed_company(db_session, "Numbering Co")

    first = next_employee_number(db_session, company.id)
    second = next_employee_number(db_session, company.id)

    pattern = re.compile(EMPLOYEE_NUMBER_PATTERN)
    assert pattern.match(first), first
    assert first.startswith(f"E{company.id}-")
    assert first != second


def test_custom_generator_is_used_and_resettable(db_session):
    company = seed_company(db_session, "Numbering Custom Co")
    calls: list[int] = []

    def custom(db, company_id: int) -> str:
        calls.append(company_id)
        return f"X-{company_id}-{len(calls):03d}"

    set_employee_number_generator(custom)
    value = next_employee_number(db_session, company.id)
    assert value == f"X-{company.id}-001"
    assert calls == [company.id]

    reset_employee_number_generator()
    default_value = next_employee_number(db_session, company.id)
    assert default_value.startswith(f"E{company.id}-")


def test_colliding_generator_retries_then_conflicts(db_session):
    from app.core.rls import clear_context, set_context
    from app.shared.models import Employee

    company = seed_company(db_session, "Numbering Collision Co")

    # Occupy a number, then hand the same one to a custom generator.
    # Keep everything in one transaction so the admin GUC stays visible.
    set_context(
        db_session, user_id=None, company_ids=[], is_platform_admin=True
    )
    db_session.add(
        Employee(
            company_id=company.id,
            employee_number="SAME-001",
            first_name_ar="أ",
            last_name_ar="ب",
            first_name_en="A",
            last_name_en="B",
        )
    )
    db_session.flush()

    def colliding(db, company_id: int) -> str:
        return "SAME-001"

    set_employee_number_generator(colliding)
    with pytest.raises(ConflictError):
        next_employee_number(db_session, company.id)
    db_session.rollback()
    clear_context(db_session)


def test_invalid_generated_number_conflicts(db_session):
    company = seed_company(db_session, "Numbering Invalid Co")

    def invalid(db, company_id: int) -> str:
        return "bad number!"

    set_employee_number_generator(invalid)
    with pytest.raises(ConflictError):
        next_employee_number(db_session, company.id)


def test_explicit_employee_number_pattern_rules():
    assert is_valid_employee_number("EMP-001")
    assert is_valid_employee_number("E1-000001")
    assert is_valid_employee_number("A1")
    assert not is_valid_employee_number("A")  # minimum length is 2
    assert not is_valid_employee_number("bad number")
    assert not is_valid_employee_number("-leading")
    assert not is_valid_employee_number("")

    with pytest.raises(Exception):
        EmployeeCreate(
            company_id=1,
            employee_number="not a number",
            first_name_ar="أ",
            last_name_ar="ب",
            first_name_en="A",
            last_name_en="B",
        )
