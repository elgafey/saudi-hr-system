"""Closed payload schemas for Phase 7 employee requests.

Payloads are strictly validated per ``request_type``: unknown keys, missing
required keys and wrong JSON types raise ``EMPLOYEE_REQUEST_INVALID_PAYLOAD``;
semantically invalid attendance-correction values (bad dates, mixed
timezone awareness, inverted ranges) raise ``ATTENDANCE_CORRECTION_INVALID``.
Nothing here touches Odoo, formulas or evaluates input - only fixed field
sets with fixed types.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.core.exceptions import (
    AttendanceCorrectionError,
    EmployeeRequestPayloadError,
    EmployeeRequestTypeError,
)

ALLOWED_REQUEST_TYPES = (
    "attendance_correction",
    "hr_letter",
    "document_request",
    "other",
)

_ALLOWED_FIELDS: dict[str, set[str]] = {
    "attendance_correction": {"work_date", "check_in", "check_out"},
    "hr_letter": {"purpose", "language"},
    "document_request": {"document_name", "note"},
    "other": {"details"},
}


def validate_request_type(request_type: str) -> str:
    if request_type not in ALLOWED_REQUEST_TYPES:
        raise EmployeeRequestTypeError(
            f"Unsupported request type: {request_type}"
        )
    return request_type


def _reject_unknown(data: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(str(key) for key in set(data) - allowed)
    if unknown:
        raise EmployeeRequestPayloadError(
            f"Unknown payload fields: {', '.join(unknown)}"
        )


def _required_str(data: dict[str, Any], key: str, *, limit: int) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EmployeeRequestPayloadError(f"payload.{key} is required")
    return value.strip()[:limit]


def _optional_str(
    data: dict[str, Any], key: str, *, limit: int, required: bool = False
) -> str | None:
    value = data.get(key)
    if value is None:
        if required:
            raise EmployeeRequestPayloadError(f"payload.{key} is required")
        return None
    if not isinstance(value, str):
        raise EmployeeRequestPayloadError(f"payload.{key} must be text")
    text = value.strip()
    if not text:
        if required:
            raise EmployeeRequestPayloadError(f"payload.{key} is required")
        return None
    return text[:limit]


def parse_work_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise AttendanceCorrectionError(
        "payload.work_date must be an ISO date (YYYY-MM-DD)"
    )


def parse_timestamp(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    raise AttendanceCorrectionError(
        f"payload.{field} must be an ISO-8601 timestamp"
    )


def validate_payload(
    request_type: str, payload: dict[str, Any] | None
) -> tuple[dict, date | None]:
    """Validate and normalize one payload. Returns ``(payload, work_date)``;
    ``work_date`` is only set for ``attendance_correction``."""
    validate_request_type(request_type)
    data = dict(payload or {})
    allowed = _ALLOWED_FIELDS[request_type]
    _reject_unknown(data, allowed)

    if request_type == "attendance_correction":
        work_date = parse_work_date(data.get("work_date"))
        check_in = parse_timestamp(data.get("check_in"), "check_in")
        check_out = parse_timestamp(data.get("check_out"), "check_out")
        if (check_in.tzinfo is None) != (check_out.tzinfo is None):
            raise AttendanceCorrectionError(
                "check_in and check_out must both be timezone-aware or both naive"
            )
        if check_out <= check_in:
            raise AttendanceCorrectionError("check_out must be after check_in")
        return (
            {
                "work_date": work_date.isoformat(),
                "check_in": check_in.isoformat(),
                "check_out": check_out.isoformat(),
            },
            work_date,
        )

    if request_type == "hr_letter":
        normalized: dict[str, Any] = {
            "purpose": _required_str(data, "purpose", limit=500)
        }
        language = data.get("language")
        if language is not None:
            if language not in ("ar", "en"):
                raise EmployeeRequestPayloadError(
                    "payload.language must be 'ar' or 'en'"
                )
            normalized["language"] = language
        return normalized, None

    if request_type == "document_request":
        normalized = {
            "document_name": _required_str(data, "document_name", limit=255)
        }
        note = _optional_str(data, "note", limit=1000)
        if note is not None:
            normalized["note"] = note
        return normalized, None

    # other
    details = _optional_str(data, "details", limit=4000)
    return ({"details": details} if details is not None else {}), None
