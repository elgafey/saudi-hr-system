from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.payroll.engine import (
    _clip,
    _month_chunks,
    _prorate,
    blocking_warnings,
    canonical_json,
    compute_lines,
    money,
    snapshot_hash,
)
from app.payroll.statutory import (
    ENGINE_VERSION,
    WARNING_MISSING_RULE,
    WARNING_UNVERIFIED_RULE,
)

OT_RULE_STATUS = {"present": True, "verified": True, "version": 1}
OT_RULE_VALUES = {
    "overtime_rate_percent": "50",
    "days_per_month": "30",
    "hours_per_day": "8",
}
UNVERIFIED_STATUS = {"present": True, "verified": False, "version": 2}
ABSENT_STATUS = {"present": False, "verified": False, "version": None}


def _segment(
    monthly: str = "9300",
    start: str = "2025-01-01",
    end: str = "2025-01-31",
    assignment_id: int = 1,
) -> dict:
    return {
        "assignment_id": assignment_id,
        "start": start,
        "end": end,
        "monthly": monthly,
        "currency": "SAR",
    }


def _employee(**overrides) -> dict:
    payload = {
        "employee_number": "E0001",
        "segments": [_segment()],
        "overrides": [],
        "attendance": {
            "worked_minutes": 0,
            "break_minutes": 0,
            "late_minutes": 0,
            "early_leave_minutes": 0,
            "record_ids": [],
        },
        "overtime": {"approved_minutes": 0, "records": []},
        "leave": {
            "paid_days": "0.00",
            "unpaid_days": "0.00",
            "unpaid_dates": [],
            "request_ids": [],
        },
        "deduction_rules": [],
        "adjustments": [],
    }
    payload.update(overrides)
    for key in ("attendance", "overtime", "leave"):
        if key in overrides and isinstance(payload[key], dict):
            base = {
                "attendance": {
                    "worked_minutes": 0,
                    "break_minutes": 0,
                    "late_minutes": 0,
                    "early_leave_minutes": 0,
                    "record_ids": [],
                },
                "overtime": {"approved_minutes": 0, "records": []},
                "leave": {
                    "paid_days": "0.00",
                    "unpaid_days": "0.00",
                    "unpaid_dates": [],
                    "request_ids": [],
                },
            }[key]
            merged = dict(base)
            merged.update(overrides[key])
            payload[key] = merged
    return payload


def _component(**overrides) -> dict:
    component = {
        "id": 1,
        "code": "HRA",
        "category": "earning",
        "basis": "fixed",
        "default_amount": "500",
        "default_rate": None,
        "is_statutory": False,
        "statutory_key": None,
        "sort_order": 10,
    }
    component.update(overrides)
    return component


def _inputs(
    employees=None,
    components=None,
    status=None,
    values=None,
    daily_divisor: str = "30",
) -> dict:
    return {
        "engine_version": ENGINE_VERSION,
        "company_id": 1,
        "period": {
            "id": 1,
            "name": "2025-01",
            "start": "2025-01-01",
            "end": "2025-01-31",
            "currency": "SAR",
        },
        "rules": {
            "daily_divisor": daily_divisor,
            "proration_basis": "calendar_days",
            "status": (
                {"overtime": dict(OT_RULE_STATUS)} if status is None else status
            ),
            "values": (
                {"overtime": dict(OT_RULE_VALUES)} if values is None else values
            ),
        },
        "components": components if components is not None else [],
        "employees": {"1": _employee()} if employees is None else employees,
    }


def _calc(**kwargs):
    return compute_lines(_inputs(**kwargs))


# --- money -----------------------------------------------------------------


def test_money_rounds_half_up_not_even():
    assert money("1.005") == Decimal("1.01")
    assert money("2.675") == Decimal("2.68")
    assert money("0.005") == Decimal("0.01")


def test_money_negative_rounds_away_from_zero():
    assert money("-1.005") == Decimal("-1.01")


def test_money_two_decimal_places():
    assert money(Decimal("9300")) == Decimal("9300.00")
    assert money("0") == Decimal("0.00")
    assert money("1234.5") == Decimal("1234.50")


def test_money_is_decimal_addition_without_float_error():
    total = money("0.1") + money("0.2")
    assert total == Decimal("0.30")
    assert isinstance(total, Decimal)


def test_money_accepts_int_str_and_decimal():
    assert money(5) == Decimal("5.00")
    assert money("5") == Decimal("5.00")
    assert money(Decimal("5")) == Decimal("5.00")


# --- canonical json / snapshot hash ----------------------------------------


def test_canonical_json_sorts_keys():
    text = canonical_json({"b": 1, "a": 2})
    assert text == '{"a":2,"b":1}'


def test_canonical_json_is_compact():
    text = canonical_json({"a": [1, 2], "b": {"c": 3}})
    assert ", " not in text
    assert ": " not in text
    assert text == '{"a":[1,2],"b":{"c":3}}'


def test_canonical_json_keeps_unicode_unescaped():
    text = canonical_json({"label": "أجر إضافي"})
    assert "أجر" in text
    assert "\\u" not in text


def test_canonical_json_stringifies_decimal():
    text = canonical_json({"monthly": Decimal("9300")})
    assert text == '{"monthly":"9300"}'


def test_snapshot_hash_is_independent_of_key_order():
    first = {"b": 1, "a": {"y": 2, "x": 3}}
    second = {"a": {"x": 3, "y": 2}, "b": 1}
    assert snapshot_hash(first) == snapshot_hash(second)


def test_snapshot_hash_differs_on_content():
    base = {"engine_version": "1.0.0", "total": "9300.00"}
    changed = {"engine_version": "1.0.1", "total": "9300.00"}
    assert snapshot_hash(base) != snapshot_hash(changed)


def test_snapshot_hash_changes_when_engine_version_bumps():
    payload = {"engine_version": ENGINE_VERSION, "period": {"id": 1}}
    bumped = {"engine_version": f"{ENGINE_VERSION}-next", "period": {"id": 1}}
    assert snapshot_hash(payload) != snapshot_hash(bumped)


def test_snapshot_hash_is_lowercase_sha256_hex():
    digest = snapshot_hash({"a": 1})
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_snapshot_hash_is_deterministic():
    payload = {"employees": {"1": {"total": "10.00"}}, "rules": {}}
    assert snapshot_hash(payload) == snapshot_hash(payload)


# --- month chunks / proration ----------------------------------------------


def test_month_chunks_single_month():
    chunks = _month_chunks(date(2025, 1, 1), date(2025, 1, 31))
    assert chunks == [(date(2025, 1, 1), date(2025, 1, 31), 31)]


def test_month_chunks_cross_year_boundary():
    chunks = _month_chunks(date(2024, 12, 15), date(2025, 1, 2))
    assert chunks == [
        (date(2024, 12, 15), date(2024, 12, 31), 31),
        (date(2025, 1, 1), date(2025, 1, 2), 31),
    ]


def test_month_chunks_leap_february():
    chunks = _month_chunks(date(2024, 2, 1), date(2024, 2, 29))
    assert chunks == [(date(2024, 2, 1), date(2024, 2, 29), 29)]


def test_prorate_full_month_is_exact():
    assert _prorate(Decimal("9300"), date(2025, 1, 1), date(2025, 1, 31)) == (
        Decimal("9300")
    )


def test_prorate_partial_month():
    amount = _prorate(Decimal("9300"), date(2025, 1, 16), date(2025, 1, 31))
    assert amount == Decimal("4800")


def test_prorate_across_two_months():
    amount = _prorate(Decimal("9300"), date(2025, 1, 20), date(2025, 2, 10))
    assert money(amount) == Decimal("6921.43")


def test_prorate_leap_february_partial():
    amount = _prorate(Decimal("2900"), date(2024, 2, 1), date(2024, 2, 14))
    assert amount == Decimal("1400")


def test_prorate_inverted_range_is_zero():
    assert _prorate(Decimal("9300"), date(2025, 2, 1), date(2025, 1, 1)) == (
        Decimal("0")
    )


def test_clip_overlapping_ranges():
    result = _clip(
        date(2025, 1, 10), date(2025, 2, 10), date(2025, 1, 20), date(2025, 1, 25)
    )
    assert result == (date(2025, 1, 20), date(2025, 1, 25))


def test_clip_disjoint_ranges_is_none():
    assert (
        _clip(
            date(2025, 3, 1),
            date(2025, 3, 31),
            date(2025, 1, 1),
            date(2025, 1, 31),
        )
        is None
    )


def test_clip_open_ended_assignment():
    result = _clip(date(2025, 1, 5), None, date(2025, 1, 1), date(2025, 1, 31))
    assert result == (date(2025, 1, 5), date(2025, 1, 31))


# --- basic pay --------------------------------------------------------------


def test_basic_pay_full_month():
    results, warnings = _calc()
    assert warnings == []
    assert len(results) == 1
    calc = results[0]
    assert calc.basic_snapshot == Decimal("9300.00")
    assert len(calc.lines) == 1
    line = calc.lines[0]
    assert line.label_en == "Basic Pay"
    assert line.label_ar == "الأجر الأساسي"
    assert line.line_type == "earning"
    assert line.unit == "amount"
    assert line.amount == Decimal("9300.00")
    assert line.sort_group == 0
    assert calc.earnings_total == Decimal("9300.00")
    assert calc.deductions_total == Decimal("0.00")
    assert calc.net_pay == Decimal("9300.00")
    assert calc.currency == "SAR"


def test_basic_pay_prorates_partial_assignment():
    employee = _employee(segments=[_segment(start="2025-01-16")])
    results, _ = _calc(employees={"1": employee})
    calc = results[0]
    assert calc.basic_snapshot == Decimal("4800.00")
    assert calc.earnings_total == Decimal("4800.00")


def test_basic_pay_sums_assignment_segments():
    employee = _employee(
        segments=[
            _segment(start="2025-01-01", end="2025-01-15", assignment_id=5),
            _segment(start="2025-01-16", end="2025-01-31", assignment_id=9),
        ]
    )
    results, _ = _calc(employees={"1": employee})
    assert results[0].basic_snapshot == Decimal("9300.00")


def test_employee_without_segments_gets_zero_basic_line():
    employee = _employee(segments=[])
    results, warnings = _calc(employees={"1": employee})
    assert warnings == []
    calc = results[0]
    assert len(calc.lines) == 1
    assert calc.lines[0].amount == Decimal("0.00")
    assert calc.net_pay == Decimal("0.00")


def test_attendance_and_leave_fields_pass_through():
    employee = _employee(
        attendance={"worked_minutes": 4800, "late_minutes": 35},
        leave={"paid_days": "3.00", "unpaid_days": "0.00"},
    )
    results, _ = _calc(employees={"1": employee})
    calc = results[0]
    assert calc.worked_minutes == 4800
    assert calc.late_minutes == 35
    assert calc.paid_leave_days == Decimal("3.00")
    assert calc.unpaid_leave_days == Decimal("0.00")
    assert calc.absent_days == Decimal("0.00")


def test_employees_processed_in_integer_order():
    employees = {
        "10": _employee(employee_number="E0010"),
        "2": _employee(employee_number="E0002"),
    }
    results, _ = _calc(employees=employees)
    assert [r.employee_id for r in results] == [2, 10]


def test_no_employees_returns_empty_results():
    results, warnings = _calc(employees={})
    assert results == []
    assert warnings == []


# --- components -------------------------------------------------------------


def test_fixed_component_full_month():
    results, warnings = _calc(components=[_component()])
    assert warnings == []
    calc = results[0]
    assert len(calc.lines) == 2
    line = calc.lines[1]
    assert line.component_id == 1
    assert line.label_en == "HRA"
    assert line.amount == Decimal("500.00")
    assert line.unit == "amount"
    assert line.line_type == "earning"
    assert calc.earnings_total == Decimal("9800.00")


def test_fixed_component_prorates_like_basic():
    employee = _employee(segments=[_segment(start="2025-01-16")])
    results, _ = _calc(employees={"1": employee}, components=[_component()])
    line = results[0].lines[1]
    assert line.amount == Decimal("258.06")


def test_percent_of_basic_component():
    component = _component(
        basis="percent_of_basic",
        default_amount=None,
        default_rate="0.10",
        code="CAR",
    )
    results, _ = _calc(components=[component])
    line = results[0].lines[1]
    assert line.amount == Decimal("930.00")
    assert line.rate == Decimal("0.10")
    assert line.unit == "percent"
    assert results[0].earnings_total == Decimal("10230.00")


def test_override_amount_beats_component_default():
    employee = _employee(
        overrides=[
            {"assignment_id": 1, "component_id": 1, "amount": "700", "rate": None}
        ]
    )
    results, _ = _calc(employees={"1": employee}, components=[_component()])
    assert results[0].lines[1].amount == Decimal("700.00")


def test_override_rate_beats_component_default_rate():
    employee = _employee(
        overrides=[
            {"assignment_id": 1, "component_id": 1, "amount": None, "rate": "0.05"}
        ]
    )
    component = _component(
        basis="percent_of_basic", default_amount=None, default_rate="0.10"
    )
    results, _ = _calc(employees={"1": employee}, components=[component])
    line = results[0].lines[1]
    assert line.amount == Decimal("465.00")
    assert line.rate == Decimal("0.05")


def test_override_on_non_latest_assignment_is_ignored():
    employee = _employee(
        segments=[
            _segment(start="2025-01-01", end="2025-01-15", assignment_id=5),
            _segment(start="2025-01-16", end="2025-01-31", assignment_id=9),
        ],
        overrides=[
            {"assignment_id": 5, "component_id": 1, "amount": "10", "rate": None}
        ],
    )
    results, _ = _calc(employees={"1": employee}, components=[_component()])
    assert results[0].lines[1].amount == Decimal("500.00")


def test_engine_derived_component_is_skipped():
    component = _component(
        basis="engine_derived",
        default_amount="999",
        default_rate="0.5",
        code="DERIVED",
    )
    results, _ = _calc(components=[component])
    assert len(results[0].lines) == 1


def test_zero_amount_component_produces_no_line():
    component = _component(default_amount="0", code="ZERO")
    results, _ = _calc(components=[component])
    assert len(results[0].lines) == 1


def test_component_without_value_produces_no_line():
    component = _component(default_amount=None, default_rate=None, code="EMPTY")
    results, _ = _calc(components=[component])
    assert len(results[0].lines) == 1


def test_deduction_component_reduces_net_pay():
    component = _component(category="deduction", code="ADV")
    results, _ = _calc(components=[component])
    calc = results[0]
    assert calc.lines[1].line_type == "deduction"
    assert calc.deductions_total == Decimal("500.00")
    assert calc.net_pay == Decimal("8800.00")


def test_employer_contribution_excluded_from_net_pay():
    component = _component(category="employer_contribution", code="GOSI_ER")
    results, _ = _calc(components=[component])
    calc = results[0]
    assert calc.lines[1].line_type == "employer_contribution"
    assert calc.employer_total == Decimal("500.00")
    assert calc.net_pay == Decimal("9300.00")


def test_statutory_component_pays_configured_rate():
    component = _component(
        category="deduction",
        basis="engine_derived",
        default_amount=None,
        code="GOSI",
        is_statutory=True,
        statutory_key="gosi",
    )
    status = {"gosi": {"present": True, "verified": True, "version": 1}}
    values = {"gosi": {"rate": "0.0975"}}
    results, warnings = _calc(components=[component], status=status, values=values)
    assert warnings == []
    calc = results[0]
    assert len(calc.lines) == 2
    line = calc.lines[1]
    assert line.amount == Decimal("906.75")
    assert line.rate == Decimal("0.0975")
    assert calc.deductions_total == Decimal("906.75")
    assert calc.net_pay == Decimal("8393.25")


def test_statutory_component_missing_rule_warns_and_pays_nothing():
    component = _component(
        category="deduction",
        basis="engine_derived",
        default_amount=None,
        code="GOSI",
        is_statutory=True,
        statutory_key="gosi",
    )
    status = {"gosi": dict(ABSENT_STATUS)}
    results, warnings = _calc(components=[component], status=status, values={})
    calc = results[0]
    assert len(calc.lines) == 1
    assert calc.deductions_total == Decimal("0.00")
    assert len(warnings) == 2
    codes = {w["code"] for w in warnings}
    assert codes == {WARNING_MISSING_RULE}
    company = [w for w in warnings if w.get("scope") == "company"]
    employee = [w for w in warnings if w.get("employee_id") is not None]
    assert company[0]["statutory_key"] == "gosi"
    assert employee[0]["component_id"] == 1
    assert employee[0]["employee_id"] == 1
    assert len(blocking_warnings(warnings)) == 2


def test_statutory_component_unverified_still_pays_but_blocks():
    component = _component(
        category="deduction",
        basis="engine_derived",
        default_amount=None,
        code="GOSI",
        is_statutory=True,
        statutory_key="gosi",
    )
    status = {"gosi": dict(UNVERIFIED_STATUS)}
    values = {"gosi": {"rate": "0.0975"}}
    results, warnings = _calc(components=[component], status=status, values=values)
    assert results[0].deductions_total == Decimal("906.75")
    assert {w["code"] for w in warnings} == {WARNING_UNVERIFIED_RULE}
    assert len(blocking_warnings(warnings)) == 2


def test_statutory_component_without_rate_value_pays_nothing():
    component = _component(
        category="deduction",
        basis="engine_derived",
        default_amount=None,
        code="GOSI",
        is_statutory=True,
        statutory_key="gosi",
    )
    status = {"gosi": {"present": True, "verified": True, "version": 1}}
    results, warnings = _calc(components=[component], status=status, values={})
    assert results[0].deductions_total == Decimal("0.00")
    employee = [w for w in warnings if w.get("employee_id") is not None]
    assert len(employee) == 1
    assert employee[0]["code"] == WARNING_MISSING_RULE


# --- overtime ---------------------------------------------------------------


def test_overtime_uses_statutory_formula_not_hardcoded_constants():
    employee = _employee(
        overtime={
            "approved_minutes": 60,
            "records": [{"id": 7, "work_date": "2025-01-10", "minutes": 60}],
        }
    )
    results, warnings = _calc(employees={"1": employee})
    assert warnings == []
    calc = results[0]
    ot_lines = [ln for ln in calc.lines if ln.label_en == "Overtime Pay"]
    assert len(ot_lines) == 1
    line = ot_lines[0]
    assert line.amount == Decimal("58.13")
    assert line.unit == "minutes"
    assert line.quantity == Decimal("60")
    assert line.line_type == "earning"
    assert calc.overtime_minutes == 60
    assert calc.earnings_total == Decimal("9358.13")


def test_overtime_missing_rule_pays_nothing_and_blocks():
    employee = _employee(
        overtime={
            "approved_minutes": 60,
            "records": [{"id": 7, "work_date": "2025-01-10", "minutes": 60}],
        }
    )
    results, warnings = _calc(employees={"1": employee}, status={}, values={})
    calc = results[0]
    assert not [ln for ln in calc.lines if ln.label_en == "Overtime Pay"]
    assert calc.earnings_total == Decimal("9300.00")
    assert len(warnings) == 1
    assert warnings[0]["code"] == WARNING_MISSING_RULE
    assert warnings[0]["statutory_key"] == "overtime"
    assert warnings[0]["scope"] == "company"
    assert len(blocking_warnings(warnings)) == 1


def test_overtime_unverified_rule_pays_but_blocks():
    employee = _employee(
        overtime={
            "approved_minutes": 60,
            "records": [{"id": 7, "work_date": "2025-01-10", "minutes": 60}],
        }
    )
    results, warnings = _calc(
        employees={"1": employee},
        status={"overtime": dict(UNVERIFIED_STATUS)},
    )
    assert results[0].earnings_total == Decimal("9358.13")
    assert {w["code"] for w in warnings} == {WARNING_UNVERIFIED_RULE}
    assert len(blocking_warnings(warnings)) == 1


def test_overtime_with_no_rule_value_pays_nothing():
    employee = _employee(
        overtime={
            "approved_minutes": 120,
            "records": [{"id": 7, "work_date": "2025-01-10", "minutes": 120}],
        }
    )
    results, warnings = _calc(
        employees={"1": employee},
        status={"overtime": dict(OT_RULE_STATUS)},
        values={},
    )
    assert not [ln for ln in results[0].lines if ln.label_en == "Overtime Pay"]
    assert {w["code"] for w in warnings} == {WARNING_MISSING_RULE}


def test_overtime_outside_salary_segments_is_skipped():
    employee = _employee(
        overtime={
            "approved_minutes": 60,
            "records": [{"id": 7, "work_date": "2025-03-05", "minutes": 60}],
        }
    )
    results, warnings = _calc(employees={"1": employee})
    calc = results[0]
    assert not [ln for ln in calc.lines if ln.label_en == "Overtime Pay"]
    assert calc.earnings_total == Decimal("9300.00")
    assert [w["code"] for w in warnings] == ["OVERTIME_SKIPPED_NO_SALARY"]
    assert blocking_warnings(warnings) == []


def test_zero_overtime_needs_no_rule():
    results, warnings = _calc(status={}, values={})
    assert warnings == []
    assert results[0].overtime_minutes == 0


def test_overtime_sums_records_before_rounding():
    employee = _employee(
        overtime={
            "approved_minutes": 90,
            "records": [
                {"id": 7, "work_date": "2025-01-10", "minutes": 45},
                {"id": 8, "work_date": "2025-01-11", "minutes": 45},
            ],
        }
    )
    results, _ = _calc(employees={"1": employee})
    line = [ln for ln in results[0].lines if ln.label_en == "Overtime Pay"][0]
    assert line.amount == Decimal("87.19")
    assert line.quantity == Decimal("90")


# --- unpaid leave -----------------------------------------------------------


def test_unpaid_leave_deducts_daily_rate():
    employee = _employee(
        leave={
            "paid_days": "0.00",
            "unpaid_days": "1.00",
            "unpaid_dates": [("2025-01-15", "1.00")],
        }
    )
    results, _ = _calc(employees={"1": employee})
    calc = results[0]
    leave_lines = [ln for ln in calc.lines if ln.label_en == "Unpaid Leave Deduction"]
    assert len(leave_lines) == 1
    line = leave_lines[0]
    assert line.amount == Decimal("310.00")
    assert line.unit == "days"
    assert line.quantity == Decimal("1.00")
    assert line.line_type == "deduction"
    assert calc.deductions_total == Decimal("310.00")
    assert calc.net_pay == Decimal("8990.00")


def test_unpaid_leave_fractional_day():
    employee = _employee(
        leave={
            "paid_days": "0.00",
            "unpaid_days": "0.50",
            "unpaid_dates": [("2025-01-15", "0.50")],
        }
    )
    results, _ = _calc(employees={"1": employee})
    assert results[0].deductions_total == Decimal("155.00")


def test_unpaid_leave_outside_segments_is_skipped():
    employee = _employee(
        leave={
            "paid_days": "0.00",
            "unpaid_days": "1.00",
            "unpaid_dates": [("2025-02-15", "1.00")],
        }
    )
    results, _ = _calc(employees={"1": employee})
    assert results[0].deductions_total == Decimal("0.00")


def test_unpaid_leave_uses_configured_daily_divisor():
    employee = _employee(
        leave={
            "paid_days": "0.00",
            "unpaid_days": "1.00",
            "unpaid_dates": [("2025-01-15", "1.00")],
        }
    )
    results, _ = _calc(employees={"1": employee}, daily_divisor="26")
    assert results[0].deductions_total == Decimal("357.69")


# --- adjustments ------------------------------------------------------------


def test_adjustment_direction_decides_line_type():
    employee = _employee(
        adjustments=[
            {"id": 3, "component_id": 999, "amount": "100.25", "direction": "earning"},
            {"id": 4, "component_id": 999, "amount": "40.10", "direction": "deduction"},
        ]
    )
    results, _ = _calc(employees={"1": employee})
    calc = results[0]
    assert len(calc.lines) == 3
    assert calc.earnings_total == Decimal("9400.25")
    assert calc.deductions_total == Decimal("40.10")
    assert calc.net_pay == Decimal("9360.15")


def test_zero_adjustment_produces_no_line():
    employee = _employee(
        adjustments=[
            {"id": 3, "component_id": 999, "amount": "0.00", "direction": "earning"}
        ]
    )
    results, _ = _calc(employees={"1": employee})
    assert len(results[0].lines) == 1


def test_adjustment_label_falls_back_when_component_unknown():
    employee = _employee(
        adjustments=[
            {"id": 3, "component_id": 999, "amount": "10.00", "direction": "earning"}
        ]
    )
    results, _ = _calc(employees={"1": employee})
    assert results[0].lines[1].label_en == "Adjustment"
    assert results[0].lines[1].label_ar == "تسوية"


# --- deduction rules --------------------------------------------------------


def test_deduction_rule_produces_deduction_line():
    employee = _employee(
        deduction_rules=[
            {
                "id": 11,
                "component_id": 999,
                "name": "Loan Installment",
                "amount": "250.50",
                "remaining": "750.00",
                "effective_from": "2025-01-01",
            }
        ]
    )
    results, _ = _calc(employees={"1": employee})
    calc = results[0]
    assert len(calc.lines) == 2
    line = calc.lines[1]
    assert line.line_type == "deduction"
    assert line.amount == Decimal("250.50")
    assert line.label_en == "Loan Installment"
    assert calc.deductions_total == Decimal("250.50")
    assert calc.net_pay == Decimal("9049.50")


def test_deduction_rule_label_uses_component_code_when_known():
    employee = _employee(
        deduction_rules=[
            {
                "id": 11,
                "component_id": 1,
                "name": "Loan Installment",
                "amount": "100.00",
                "remaining": "900.00",
                "effective_from": "2025-01-01",
            }
        ]
    )
    results, _ = _calc(employees={"1": employee}, components=[_component()])
    assert results[0].lines[2].label_en == "HRA"


# --- warnings / blocking ----------------------------------------------------


def test_builtin_rule_defaults_do_not_warn():
    status = {
        "daily_divisor": dict(ABSENT_STATUS),
        "proration_basis": dict(ABSENT_STATUS),
    }
    results, warnings = _calc(status=status, values={})
    assert warnings == []
    assert results[0].earnings_total == Decimal("9300.00")


def test_blocking_warnings_filters_non_blocking_codes():
    warnings = [
        {"code": WARNING_MISSING_RULE, "statutory_key": "overtime"},
        {"code": "OVERTIME_SKIPPED_NO_SALARY", "employee_id": 1},
        {"code": WARNING_UNVERIFIED_RULE, "statutory_key": "gosi"},
    ]
    blocking = blocking_warnings(warnings)
    assert [w["code"] for w in blocking] == [
        WARNING_MISSING_RULE,
        WARNING_UNVERIFIED_RULE,
    ]


def test_company_warnings_deduplicated_across_employees():
    overtime = {
        "approved_minutes": 60,
        "records": [{"id": 7, "work_date": "2025-01-10", "minutes": 60}],
    }
    employees = {
        "1": _employee(employee_number="E1", overtime=dict(overtime)),
        "2": _employee(employee_number="E2", overtime=dict(overtime)),
    }
    results, warnings = _calc(employees=employees, status={}, values={})
    assert len(warnings) == 1
    assert warnings[0]["code"] == WARNING_MISSING_RULE
    for calc in results:
        assert [w for w in calc.warnings if w.get("scope") == "company"]


# --- ordering / totals ------------------------------------------------------


def test_lines_sorted_by_deterministic_groups():
    employee = _employee(
        overtime={
            "approved_minutes": 60,
            "records": [{"id": 7, "work_date": "2025-01-10", "minutes": 60}],
        },
        leave={
            "paid_days": "0.00",
            "unpaid_days": "1.00",
            "unpaid_dates": [("2025-01-15", "1.00")],
        },
        adjustments=[
            {"id": 3, "component_id": 999, "amount": "100.25", "direction": "earning"}
        ],
        deduction_rules=[
            {
                "id": 11,
                "component_id": 999,
                "name": "Loan",
                "amount": "250.50",
                "remaining": "750.00",
                "effective_from": "2025-01-01",
            }
        ],
    )
    results, warnings = _calc(employees={"1": employee}, components=[_component()])
    assert warnings == []
    calc = results[0]
    labels = [ln.label_en for ln in calc.lines]
    assert labels == [
        "Basic Pay",
        "HRA",
        "Overtime Pay",
        "Unpaid Leave Deduction",
        "Adjustment",
        "Loan",
    ]
    assert [ln.line_type for ln in calc.lines] == [
        "earning",
        "earning",
        "earning",
        "deduction",
        "earning",
        "deduction",
    ]
    assert [ln.sort_group for ln in calc.lines] == [0, 1, 2, 3, 4, 5]
    assert calc.earnings_total == Decimal("9958.38")
    assert calc.deductions_total == Decimal("560.50")
    assert calc.net_pay == Decimal("9397.88")


def test_totals_are_sums_of_rounded_lines_not_re_rounded_aggregate():
    adjustments = [
        {"id": 3, "component_id": 999, "amount": "10.005", "direction": "earning"},
        {"id": 4, "component_id": 999, "amount": "10.005", "direction": "earning"},
        {"id": 5, "component_id": 999, "amount": "10.005", "direction": "earning"},
    ]
    employee = _employee(adjustments=adjustments)
    results, _ = _calc(employees={"1": employee})
    calc = results[0]
    rounded_sum = sum(ln.amount for ln in calc.lines if ln.line_type == "earning")
    assert rounded_sum == Decimal("9330.03")
    assert calc.earnings_total == Decimal("9330.03")
    assert calc.earnings_total != money("9330.015")


def test_net_pay_equals_earnings_minus_deductions():
    employee = _employee(
        adjustments=[
            {"id": 3, "component_id": 999, "amount": "10.00", "direction": "earning"},
            {"id": 4, "component_id": 999, "amount": "25.50", "direction": "deduction"},
        ],
        deduction_rules=[
            {
                "id": 11,
                "component_id": 999,
                "name": "Loan",
                "amount": "100.00",
                "remaining": "0.00",
                "effective_from": "2025-01-01",
            }
        ],
    )
    results, _ = _calc(employees={"1": employee})
    calc = results[0]
    assert calc.net_pay == calc.earnings_total - calc.deductions_total
    assert calc.net_pay == Decimal("9184.50")


def test_every_line_amount_is_two_decimal_places():
    employee = _employee(
        overtime={
            "approved_minutes": 37,
            "records": [{"id": 7, "work_date": "2025-01-10", "minutes": 37}],
        },
        leave={
            "paid_days": "0.00",
            "unpaid_days": "1.00",
            "unpaid_dates": [("2025-01-15", "1.00")],
        },
        adjustments=[
            {"id": 3, "component_id": 999, "amount": "33.333", "direction": "earning"}
        ],
    )
    results, _ = _calc(employees={"1": employee}, components=[_component()])
    calc = results[0]
    for line in calc.lines:
        assert isinstance(line.amount, Decimal)
        assert line.amount == money(line.amount)
    assert calc.earnings_total == money(calc.earnings_total)
    assert calc.deductions_total == money(calc.deductions_total)
    assert calc.net_pay == money(calc.net_pay)


def test_computation_is_deterministic():
    overtime = {
        "approved_minutes": 60,
        "records": [{"id": 7, "work_date": "2025-01-10", "minutes": 60}],
    }
    employees = {"1": _employee(overtime=dict(overtime))}
    first, first_warnings = _calc(employees=employees, components=[_component()])
    second, second_warnings = _calc(employees=employees, components=[_component()])
    assert [ln.amount for ln in first[0].lines] == [ln.amount for ln in second[0].lines]
    assert first[0].net_pay == second[0].net_pay
    assert first_warnings == second_warnings
