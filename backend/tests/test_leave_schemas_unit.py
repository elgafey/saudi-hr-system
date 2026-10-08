from __future__ import annotations

from datetime import date, time
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.leave.schemas import (
    BalanceOut,
    HolidayCreate,
    HolidayUpdate,
    LeaveAllocationCreate,
    LeaveRequestCreate,
    LeaveRequestDecision,
    LeaveRequestPreview,
    LeaveTypeCreate,
    LeaveTypeOut,
    LeaveTypeUpdate,
    StatutoryRuleCreate,
)


def test_leave_type_create_defaults():
    leave_type = LeaveTypeCreate(
        company_id=1, code="ANNUAL", name_ar="سنوية", name_en="Annual"
    )
    assert leave_type.is_paid is True
    assert leave_type.requires_approval is True
    assert leave_type.allocation_requires_approval is False
    assert leave_type.day_counting_mode == "working_days"
    assert leave_type.requires_attachment is False
    assert leave_type.requires_reason is False
    assert leave_type.negative_balance_allowed is False
    assert leave_type.carry_forward_enabled is False
    assert leave_type.carry_forward_expiry == "end_of_next_year"
    assert leave_type.allowance_treatment == "continue"
    assert leave_type.is_statutory is False
    assert leave_type.status == "active"
    assert leave_type.statutory_key is None


def test_leave_type_create_rejects_bad_enums_and_bounds():
    base = dict(company_id=1, code="X", name_ar="x", name_en="x")
    with pytest.raises(ValidationError):
        LeaveTypeCreate(**base, day_counting_mode="calendar")
    with pytest.raises(ValidationError):
        LeaveTypeCreate(**base, allowance_treatment="deducted")
    with pytest.raises(ValidationError):
        LeaveTypeCreate(**base, carry_forward_expiry="forever")
    with pytest.raises(ValidationError):
        LeaveTypeCreate(**base, status="archived")
    with pytest.raises(ValidationError):
        LeaveTypeCreate(company_id=0, code="X", name_ar="x", name_en="x")
    with pytest.raises(ValidationError):
        LeaveTypeCreate(**{**base, "code": ""})
    with pytest.raises(ValidationError):
        LeaveTypeCreate(**{**base, "code": "x" * 51})
    with pytest.raises(ValidationError):
        LeaveTypeCreate(**base, min_request_days=Decimal("0"))
    with pytest.raises(ValidationError):
        LeaveTypeCreate(**base, attachment_threshold_days=Decimal("-1"))
    with pytest.raises(ValidationError):
        LeaveTypeCreate(**base, default_entitlement_days=Decimal("-0.01"))
    with pytest.raises(ValidationError):
        LeaveTypeCreate(**base, carry_forward_max_days=Decimal("-1"))


def test_leave_type_update_fields_are_all_optional():
    update = LeaveTypeUpdate()
    assert update.model_dump(exclude_none=True) == {}

    patched = LeaveTypeUpdate(name_en="Renamed", status="inactive")
    assert patched.name_en == "Renamed"
    assert patched.status == "inactive"
    assert patched.code is None

    with pytest.raises(ValidationError):
        LeaveTypeUpdate(status="paused")
    with pytest.raises(ValidationError):
        LeaveTypeUpdate(name_ar="")
    with pytest.raises(ValidationError):
        LeaveTypeUpdate(min_request_days=Decimal("0"))


def test_statutory_rule_requires_source_and_legal_verification_default():
    with pytest.raises(ValidationError):
        StatutoryRuleCreate(
            company_id=1,
            statutory_key="annual_leave",
            effective_from=date(2025, 1, 1),
        )
    with pytest.raises(ValidationError):
        StatutoryRuleCreate(
            company_id=1,
            statutory_key="annual_leave",
            effective_from=date(2025, 1, 1),
            source_reference="",
        )

    rule = StatutoryRuleCreate(
        company_id=1,
        statutory_key="annual_leave",
        effective_from=date(2025, 1, 1),
        source_reference="Ministry circular 1/2025",
    )
    # D2: legal values start flagged for verification until cleared.
    assert rule.requires_legal_verification is True
    assert rule.effective_to is None
    assert rule.rule_json == {}
    # Whitespace citations pass the schema; the service layer trims and
    # rejects them with STATUTORY_RULE_SOURCE_REQUIRED (400).
    blankish = StatutoryRuleCreate(
        company_id=1,
        statutory_key="annual_leave",
        effective_from=date(2025, 1, 1),
        source_reference="   ",
    )
    assert blankish.source_reference == "   "

    with pytest.raises(ValidationError):
        StatutoryRuleCreate(
            company_id=1,
            statutory_key="annual_leave",
            effective_from=date(2025, 1, 1),
            source_reference="x" * 501,
        )


def test_allocation_create_field_validation():
    base = dict(
        employee_id=1,
        leave_type_id=2,
        period_start=date(2025, 1, 1),
        period_end=date(2025, 6, 30),
        allocated_days=Decimal("21"),
    )
    allocation = LeaveAllocationCreate(**base)
    assert allocation.source == "manual"
    assert allocation.reason is None

    with pytest.raises(ValidationError):
        LeaveAllocationCreate(**{**base, "allocated_days": Decimal("0")})
    with pytest.raises(ValidationError):
        LeaveAllocationCreate(**{**base, "allocated_days": Decimal("-5")})
    with pytest.raises(ValidationError):
        LeaveAllocationCreate(**{**base, "employee_id": 0})
    with pytest.raises(ValidationError):
        LeaveAllocationCreate(**{**base, "source": "imported"})

    # Reversed periods pass the schema: the service layer raises
    # LEAVE_RANGE (400) and the DB CHECK backs it up.
    reversed_ok = LeaveAllocationCreate(
        **{**base, "period_start": date(2025, 6, 30), "period_end": date(2025, 1, 1)}
    )
    assert reversed_ok.period_end < reversed_ok.period_start


def test_request_create_field_validation():
    base = dict(
        employee_id=1,
        leave_type_id=2,
        start_date=date(2025, 3, 3),
        end_date=date(2025, 3, 7),
    )
    request = LeaveRequestCreate(**base)
    assert request.start_time is None
    assert request.end_time is None
    assert request.reason is None

    with pytest.raises(ValidationError):
        LeaveRequestCreate(**{**base, "employee_id": 0})
    with pytest.raises(ValidationError):
        LeaveRequestCreate(**base, reason="x" * 2001)

    # Partial-day fields may be sent together; a lone start_time is a
    # service-level LEAVE_TIMES (400), not a schema error.
    partial = LeaveRequestCreate(
        **base, start_time=time(9, 0), end_time=time(13, 0)
    )
    assert partial.start_time == time(9, 0)
    with_start_only = LeaveRequestCreate(**base, start_time=time(9, 0))
    assert with_start_only.end_time is None

    # Reversed dates are the service's job (LEAVE_RANGE).
    reversed_ok = LeaveRequestCreate(
        **{**base, "start_date": date(2025, 3, 7), "end_date": date(2025, 3, 3)}
    )
    assert reversed_ok.end_date < reversed_ok.start_date


def test_request_decision_reason_bounds():
    assert LeaveRequestDecision().reason is None
    assert LeaveRequestDecision(reason="ok").reason == "ok"
    with pytest.raises(ValidationError):
        LeaveRequestDecision(reason="x" * 501)


def test_request_preview_bounds():
    preview = LeaveRequestPreview(
        employee_id=1,
        leave_type_id=2,
        start_date=date(2025, 3, 3),
        end_date=date(2025, 3, 7),
    )
    assert preview.exclude_request_id is None

    with pytest.raises(ValidationError):
        LeaveRequestPreview(
            employee_id=1,
            leave_type_id=2,
            start_date=date(2025, 3, 3),
            end_date=date(2025, 3, 7),
            exclude_request_id=0,
        )
    with pytest.raises(ValidationError):
        LeaveRequestPreview(
            employee_id=0,
            leave_type_id=2,
            start_date=date(2025, 3, 3),
            end_date=date(2025, 3, 7),
        )


def test_holiday_create_and_update_validation():
    holiday = HolidayCreate(
        company_id=1,
        date=date(2025, 9, 23),
        name_ar="عطلة",
        name_en="Founding Day",
    )
    assert holiday.status == "active"
    assert holiday.notes is None

    with pytest.raises(ValidationError):
        HolidayCreate(
            company_id=1, date=date(2025, 9, 23), name_ar="", name_en="x"
        )
    with pytest.raises(ValidationError):
        HolidayCreate(
            company_id=1, date=date(2025, 9, 23), name_ar="x", name_en="x",
            status="holiday",
        )
    with pytest.raises(ValidationError):
        HolidayCreate(
            company_id=1, date=date(2025, 9, 23), name_ar="x", name_en="x",
            notes="n" * 1001,
        )

    update = HolidayUpdate()
    assert update.model_dump(exclude_none=True) == {}
    with pytest.raises(ValidationError):
        HolidayUpdate(status="paused")


def test_balance_out_requires_all_totals():
    balance = BalanceOut(
        leave_type_id=1,
        code="ANNUAL",
        name_ar="سنوية",
        name_en="Annual",
        is_paid=True,
        allocated_days=Decimal("21.00"),
        used_days=Decimal("5.00"),
        pending_days=Decimal("0.00"),
        remaining_days=Decimal("16.00"),
        negative_balance_allowed=False,
    )
    assert balance.remaining_days == Decimal("16.00")

    with pytest.raises(ValidationError):
        BalanceOut(
            leave_type_id=1,
            code="ANNUAL",
            name_ar="x",
            name_en="x",
            is_paid=True,
            allocated_days=Decimal("21"),
            used_days=Decimal("0"),
            pending_days=Decimal("0"),
            remaining_days=Decimal("0"),
        )


def test_out_models_are_from_attributes_ready():
    for model in (LeaveTypeOut,):
        assert model.model_config.get("from_attributes") is True
