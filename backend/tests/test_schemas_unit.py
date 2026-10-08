from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.auth.schemas import LoginRequest
from app.branches.schemas import BranchCreate
from app.companies.schemas import CompanyCreate
from app.core.pagination import PageParams
from app.permissions.catalog import DEFAULT_ROLES, PERMISSIONS
from app.users.schemas import UserCreate


def test_permission_codes_unique():
    codes = [c for c, _, _ in PERMISSIONS]
    assert len(codes) == len(set(codes))


def test_default_roles_reference_known_permissions():
    known = {c for c, _, _ in PERMISSIONS}
    for _code, _name, _desc, perms in DEFAULT_ROLES:
        for perm in perms:
            assert perm in known, f"unknown permission {perm}"


def test_every_phase1_permission_has_module():
    for code, name, module in PERMISSIONS:
        assert code and name and module


def test_login_identifier_min_length():
    with pytest.raises(ValidationError):
        LoginRequest(identifier="ab", password="x")


def test_company_create_defaults():
    company = CompanyCreate(name="Acme")
    assert company.country == "SA"
    assert company.default_currency == "SAR"
    assert company.timezone == "Asia/Riyadh"
    assert company.working_week == "sun-thu"


def test_user_create_password_min_length():
    with pytest.raises(ValidationError):
        UserCreate(
            email="a@b.com", full_name="A B", password="short", company_id=1
        )


def test_branch_status_pattern():
    with pytest.raises(ValidationError):
        BranchCreate(company_id=1, name="HQ", code="HQ", status="unknown")


def test_pagination_offset_math():
    params = PageParams(page=3, page_size=25)
    assert params.offset == 50
    assert params.limit == 25
