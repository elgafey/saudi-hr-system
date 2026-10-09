"""Phase 9 HR letter unit tests (no database)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core import exceptions
from app.letter.schemas import (
    CONTENT_MODELS,
    LetterCreate,
    LetterUpdate,
    LetterVoid,
)
from app.permissions.catalog import DEFAULT_ROLES, PERMISSIONS
from app.shared.models import HrLetter

LETTER_MODULES = ("hr_letter.view", "hr_letter.create", "hr_letter.update",
                  "hr_letter.issue", "hr_letter.void", "ess.letter.view")

EXPECTED_ROLE_TOTALS = {
    "company_admin": 149,
    "hr_manager": 130,
    "hr_officer": 79,
    "auditor": 36,
    "employee": 17,
}

EXPECTED_ROLE_LETTER_GRANTS = {
    "company_admin": set(LETTER_MODULES),
    "hr_manager": set(LETTER_MODULES),
    "hr_officer": set(LETTER_MODULES) - {"hr_letter.void"},
    "auditor": {"hr_letter.view"},
    "employee": {"ess.letter.view"},
}


def _role_perms() -> dict[str, list[str]]:
    return {code: perms for code, _n, _d, perms in DEFAULT_ROLES}


def test_permission_catalog_has_six_phase9_codes():
    codes = [code for code, _name, _module in PERMISSIONS]
    assert len(codes) == 150
    assert len(set(codes)) == 150
    for code in LETTER_MODULES:
        assert code in codes, code
    by_code = {code: module for code, _name, module in PERMISSIONS}
    assert all(by_code[c] == "hr_letters" for c in LETTER_MODULES[:5])
    assert by_code["ess.letter.view"] == "ess"


def test_default_role_totals_and_letter_grants_match_plan():
    roles = _role_perms()
    for role_code, expected_total in EXPECTED_ROLE_TOTALS.items():
        assert len(roles[role_code]) == expected_total, role_code
    for role_code, expected in EXPECTED_ROLE_LETTER_GRANTS.items():
        granted = set(roles[role_code]) & set(LETTER_MODULES)
        assert granted == expected, role_code


def test_content_models_cover_exactly_the_four_letter_types():
    assert set(CONTENT_MODELS) == {
        "employment",
        "salary",
        "experience",
        "work_address",
    }


def test_content_models_reject_extra_fields():
    base = {
        "company_name": "Acme",
        "employee_name": "Noura Alqahtani",
        "employee_number": "E-1",
        "employment_type": "full_time",
    }
    for letter_type, model in CONTENT_MODELS.items():
        data = dict(base)
        if letter_type == "employment":
            data["employment_status"] = "active"
        elif letter_type == "experience":
            data["employment_status"] = "active"
        elif letter_type == "salary":
            data.update(
                basic_salary="9000.00", currency="SAR",
                salary_effective_from="2025-01-01",
            )
        model(**data)  # valid construction
        with pytest.raises(ValidationError):
            model(**{**data, "client_supplied_note": "hack"})


def test_content_models_require_type_specific_fields():
    base = {
        "company_name": "Acme",
        "employee_name": "Noura Alqahtani",
        "employee_number": "E-1",
        "employment_type": "full_time",
    }
    with pytest.raises(ValidationError):
        CONTENT_MODELS["salary"](**base)
    with pytest.raises(ValidationError):
        CONTENT_MODELS["employment"](**base)


def test_client_payloads_never_accept_content():
    with pytest.raises(ValidationError):
        LetterCreate(
            employee_id=1,
            letter_type="employment",
            content={"salary": "anything"},
        )
    with pytest.raises(ValidationError):
        LetterUpdate(content={"purpose": "hack"})
    with pytest.raises(ValidationError):
        LetterVoid(reason="audit trail", content={})


def test_reference_is_derived_from_the_id():
    row = HrLetter(id=7)
    assert row.reference == "LTR-000007"
    assert HrLetter(id=123456).reference == "LTR-123456"


def test_letter_exceptions_carry_stable_codes():
    expected = {
        exceptions.HrLetterNotFoundError: ("HR_LETTER_NOT_FOUND", 404),
        exceptions.HrLetterForbiddenError: ("HR_LETTER_FORBIDDEN", 403),
        exceptions.HrLetterStateError: ("HR_LETTER_STATE_INVALID", 409),
        exceptions.HrLetterReasonRequiredError: (
            "HR_LETTER_REASON_REQUIRED", 400
        ),
        exceptions.HrLetterTypeError: ("HR_LETTER_TYPE_INVALID", 400),
        exceptions.HrLetterRequestError: ("HR_LETTER_REQUEST_INVALID", 400),
        exceptions.HrLetterRequestLinkedError: (
            "HR_LETTER_REQUEST_LINKED", 409
        ),
        exceptions.HrLetterEmployeeInvalidError: (
            "HR_LETTER_EMPLOYEE_INVALID", 400
        ),
        exceptions.HrLetterSourceMissingError: (
            "HR_LETTER_SOURCE_MISSING", 409
        ),
    }
    codes = []
    for cls, (code, status) in expected.items():
        exc = cls("boom")
        assert exc.code == code, cls.__name__
        assert exc.status_code == status, cls.__name__
        codes.append(exc.code)
    assert len(codes) == len(set(codes))


def test_letter_source_contains_no_role_names():
    backend = Path(__file__).resolve().parent.parent
    pattern = re.compile(r"['\"](company_admin|hr_manager|hr_officer|auditor)['\"]")
    for path in sorted((backend / "app" / "letter").glob("*.py")):
        assert not pattern.search(path.read_text()), path.name


def test_letter_tables_declare_the_phase9_checks():
    constraint_names = {
        c.name for c in HrLetter.__table__.constraints if c.name
    }
    assert {
        "ck_hr_letter_type",
        "ck_hr_letter_language",
        "ck_hr_letter_status",
        "ck_hr_letter_issued_consistency",
        "ck_hr_letter_cancelled_consistency",
        "ck_hr_letter_void_consistency",
        "ck_hr_letter_void_reason",
    } <= constraint_names
