from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.shared.models import PayrollStatutoryRule

# Version marker stored on every calculation snapshot (inputs_hash covers
# it, so a future engine change forces an explicit recalculation).
ENGINE_VERSION = "1.0.0"

# Approved Phase 6 defaults. These are NOT Saudi legal values: they are the
# documented fallbacks the user approved for Phase 6. Any real Saudi
# statutory value (overtime percentage, GOSI rates, ...) must come from a
# company-configured payroll_statutory_rules row with a source_reference -
# the engine NEVER stores or invents legal constants.
DEFAULT_DAILY_DIVISOR = Decimal("30")
DEFAULT_PRORATION_BASIS = "calendar_days"
PRORATION_BASES = ("calendar_days", "working_days")

# Keys with a structured rule_json schema (validated at create time).
KEY_DAILY_DIVISOR = "daily_divisor"
KEY_PRORATION_BASIS = "proration_basis"
KEY_OVERTIME = "overtime"

# Warning codes surfaced on the run; these two block period APPROVED.
WARNING_MISSING_RULE = "STATUTORY_RULE_MISSING"
WARNING_UNVERIFIED_RULE = "STATUTORY_RULE_UNVERIFIED"
BLOCKING_WARNINGS = (WARNING_MISSING_RULE, WARNING_UNVERIFIED_RULE)


def resolve_payroll_rule(
    db: Session, company_id: int, statutory_key: str, as_of: date
) -> PayrollStatutoryRule | None:
    """Effective-dated resolution: the version in force on ``as_of``.

    Same [effective_from, effective_to) semantics as the Phase 5 leave
    resolver, against the Phase 6 payroll rules table (Phase 5 is never
    modified).
    """
    stmt = (
        select(PayrollStatutoryRule)
        .where(
            PayrollStatutoryRule.company_id == company_id,
            PayrollStatutoryRule.statutory_key == statutory_key,
            PayrollStatutoryRule.status == "active",
            PayrollStatutoryRule.effective_from <= as_of,
            (PayrollStatutoryRule.effective_to.is_(None))
            | (PayrollStatutoryRule.effective_to > as_of),
        )
        .order_by(
            PayrollStatutoryRule.effective_from.desc(),
            PayrollStatutoryRule.version.desc(),
        )
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def _decimal_value(raw: object) -> Decimal | None:
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite():
        return None
    return value


class RuleSet:
    """Read-only view over the statutory rules relevant to one calculation.

    ``as_of`` is the period start: the whole period is calculated under the
    rules in force at the beginning of the period (documented Phase 6
    decision, docs/PHASE6.md).
    """

    def __init__(self, db: Session, company_id: int, as_of: date) -> None:
        self.company_id = company_id
        self.as_of = as_of
        rows = db.execute(
            select(PayrollStatutoryRule).where(
                PayrollStatutoryRule.company_id == company_id,
                PayrollStatutoryRule.status == "active",
                PayrollStatutoryRule.effective_from <= as_of,
                (PayrollStatutoryRule.effective_to.is_(None))
                | (PayrollStatutoryRule.effective_to > as_of),
            )
        ).scalars()
        # One row per key (latest effective_from/version wins - matches
        # resolve_payroll_rule's ordering for a single key).
        chosen: dict[str, PayrollStatutoryRule] = {}
        for row in sorted(
            rows,
            key=lambda r: (r.statutory_key, r.effective_from, r.version),
        ):
            chosen[row.statutory_key] = row
        self._rules = chosen

    def rule(self, key: str) -> PayrollStatutoryRule | None:
        return self._rules.get(key)

    def rule_json(self, key: str) -> dict:
        row = self._rules.get(key)
        return dict(row.rule_json) if row is not None else {}

    def verified(self, key: str) -> bool:
        row = self._rules.get(key)
        return row is not None and not row.requires_legal_verification

    # -- structured accessors ------------------------------------------------

    def daily_divisor(self) -> Decimal:
        """Configurable monthly divisor; approved Phase 6 default = 30."""
        value = _decimal_value(self.rule_json(KEY_DAILY_DIVISOR).get("divisor"))
        if value is None or value <= 0:
            return DEFAULT_DAILY_DIVISOR
        return value

    def proration_basis(self) -> str:
        raw = self.rule_json(KEY_PRORATION_BASIS).get("basis")
        if isinstance(raw, str) and raw in PRORATION_BASES:
            return raw
        return DEFAULT_PRORATION_BASIS

    def overtime_params(self) -> dict[str, Decimal] | None:
        """HRSD overtime framework: overtime hourly amount = actual hourly
        wage + ``overtime_rate_percent``% of basic hourly wage, where the
        hourly wage divides by ``days_per_month`` then ``hours_per_day``.

        All three numbers come from the configured rule - never from code.
        Returns None when the rule is absent or structurally unusable (the
        caller emits a blocking STATUTORY_RULE_MISSING warning).
        """
        row = self.rule(KEY_OVERTIME)
        if row is None:
            return None
        payload = row.rule_json
        rate = _decimal_value(payload.get("overtime_rate_percent"))
        days = _decimal_value(payload.get("days_per_month"))
        hours = _decimal_value(payload.get("hours_per_day"))
        if rate is None or days is None or hours is None:
            return None
        if rate < 0 or days <= 0 or hours <= 0:
            return None
        return {
            "overtime_rate_percent": rate,
            "days_per_month": days,
            "hours_per_day": hours,
        }

    def statutory_rate(self, key: str) -> Decimal | None:
        """Fractional rate (e.g. "0.0975") declared by a statutory rule."""
        row = self.rule(key)
        if row is None:
            return None
        rate = _decimal_value(row.rule_json.get("rate"))
        if rate is None or rate <= 0 or rate > 1:
            return None
        return rate
