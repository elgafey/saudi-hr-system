from __future__ import annotations

import re
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.advance.router import STATUS_PATTERN
from app.advance.schemas import AdvanceCreate, AdvanceDecision, AdvanceDisburse
from app.advance.service import (
    _require_state,
    _snapshot,
    _validate_amount,
    _validate_reason,
)
from app.core.exceptions import (
    SalaryAdvanceAmountError,
    SalaryAdvanceReasonRequiredError,
    SalaryAdvanceStateError,
)

PATTERN = re.compile(STATUS_PATTERN)


def test_create_schema_rejects_non_positive_amounts():
    with pytest.raises(ValidationError):
        AdvanceCreate(amount=0, reason="x", requested_date="2026-10-01")
    with pytest.raises(ValidationError):
        AdvanceCreate(amount=-100, reason="x", requested_date="2026-10-01")


def test_create_schema_rejects_blank_reason():
    with pytest.raises(ValidationError):
        AdvanceCreate(amount=100, reason="", requested_date="2026-10-01")


def test_create_schema_accepts_valid_payload_and_defaults_to_no_employee():
    payload = AdvanceCreate(
        amount="1500.50", reason="Tuition", requested_date="2026-10-01"
    )
    assert payload.amount == Decimal("1500.50")
    assert payload.employee_id is None


def test_create_schema_caps_reason_and_amount_precision():
    with pytest.raises(ValidationError):
        AdvanceCreate(amount=1, reason="x" * 4001, requested_date="2026-10-01")
    with pytest.raises(ValidationError):
        AdvanceCreate(
            amount="1000.001", reason="x", requested_date="2026-10-01"
        )


def test_disburse_schema_requires_positive_installment():
    with pytest.raises(ValidationError):
        AdvanceDisburse(installment_amount=0)
    with pytest.raises(ValidationError):
        AdvanceDisburse(installment_amount="-5")
    payload = AdvanceDisburse(installment_amount="250.00", note="ok")
    assert payload.installment_amount == Decimal("250.00")


def test_decision_schema_caps_reason_at_500():
    AdvanceDecision(reason="ok")
    with pytest.raises(ValidationError):
        AdvanceDecision(reason="x" * 501)


def test_validate_amount_allows_none_and_positive_only():
    _validate_amount(None)
    _validate_amount(Decimal("0.01"))
    with pytest.raises(SalaryAdvanceAmountError):
        _validate_amount(Decimal("0"))
    with pytest.raises(SalaryAdvanceAmountError):
        _validate_amount(Decimal("-1"))


def test_validate_reason_strips_and_requires_content():
    assert _validate_reason("  Tuition  ") == "Tuition"
    with pytest.raises(SalaryAdvanceReasonRequiredError):
        _validate_reason("   ")
    with pytest.raises(SalaryAdvanceReasonRequiredError):
        _validate_reason("\t\n")


def test_require_state_gates_transitions():
    _require_state(SimpleNamespace(status="draft"), {"draft"}, "submit")
    with pytest.raises(SalaryAdvanceStateError):
        _require_state(SimpleNamespace(status="settled"), {"draft"}, "submit")
    with pytest.raises(SalaryAdvanceStateError):
        _require_state(SimpleNamespace(status="approved"), {"submitted"}, "approve")


def test_snapshot_is_a_flat_string_snapshot():
    snapshot = _snapshot(
        SimpleNamespace(
            employee_id=7,
            approver_employee_id=3,
            status="approved",
            amount=Decimal("2500.00"),
            installment_amount=Decimal("500.00"),
            requested_date="2026-10-01",
            deduction_rule_id=None,
        )
    )
    assert snapshot == {
        "employee_id": 7,
        "approver_employee_id": 3,
        "status": "approved",
        "amount": "2500.00",
        "installment_amount": "500.00",
        "requested_date": "2026-10-01",
        "deduction_rule_id": None,
    }


def test_status_pattern_covers_the_whole_machine():
    for status in (
        "",
        "draft",
        "submitted",
        "approved",
        "rejected",
        "cancelled",
        "disbursed",
        "settled",
    ):
        assert PATTERN.fullmatch(status), status
    for bad in ("Draft", "pending", "settled ", "disbursed\n", "settledx"):
        assert not PATTERN.fullmatch(bad), bad
