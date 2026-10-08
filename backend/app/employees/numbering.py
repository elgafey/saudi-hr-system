from __future__ import annotations

import re
from collections.abc import Callable

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError
from app.shared.models import Employee

# Explicitly provided employee numbers must look like a clean identifier:
# start alphanumeric, then alphanumerics plus - _ / separators, 2-50 chars.
EMPLOYEE_NUMBER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9\-_/]{1,49}$"

_NUMBER_RE = re.compile(EMPLOYEE_NUMBER_PATTERN)

# A generation strategy returns a candidate number for the given company.
# Strategies are pluggable so per-company formats (prefixes, zero padding,
# per-company sequences) can be registered later without touching callers.
Generator = Callable[[Session, int], str]

_MAX_ATTEMPTS = 5


def _sequence_generator(db: Session, company_id: int) -> str:
    """Default strategy: shared PostgreSQL sequence rendered per company."""
    value = db.execute(text("SELECT nextval('employee_number_seq')")).scalar_one()
    return f"E{company_id}-{int(value):06d}"


_generator: Generator = _sequence_generator


def set_employee_number_generator(generator: Generator) -> None:
    global _generator
    _generator = generator


def reset_employee_number_generator() -> None:
    global _generator
    _generator = _sequence_generator


def is_valid_employee_number(value: str) -> bool:
    return _NUMBER_RE.fullmatch(value) is not None


def employee_number_available(
    db: Session, company_id: int, employee_number: str, *, exclude_id: int | None = None
) -> bool:
    stmt = select(Employee.id).where(
        Employee.company_id == company_id,
        Employee.employee_number == employee_number,
    )
    if exclude_id is not None:
        stmt = stmt.where(Employee.id != exclude_id)
    return db.execute(stmt).scalar_one_or_none() is None


def next_employee_number(db: Session, company_id: int) -> str:
    """Return a unique employee number for the company.

    The active strategy supplies candidates; duplicates and pattern
    violations are retried so custom strategies stay safe.
    """
    for _ in range(_MAX_ATTEMPTS):
        candidate = _generator(db, company_id)
        candidate = candidate.strip() if isinstance(candidate, str) else ""
        if not candidate or not is_valid_employee_number(candidate):
            raise ConflictError(
                "Employee number generator produced an invalid number"
            )
        if employee_number_available(db, company_id, candidate):
            return candidate
    raise ConflictError("Could not generate a unique employee number")
