from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import get_settings

_hasher = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)

JWT_ALGORITHM = "HS256"
JWT_TYPE_ACCESS = "access"


class TokenError(Exception):
    pass


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(hashed: str, password: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def create_access_token(user_id: int, expires_minutes: int | None = None) -> str:
    settings = get_settings()
    minutes = (
        expires_minutes
        if expires_minutes is not None
        else settings.access_token_expire_minutes
    )
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": JWT_TYPE_ACCESS,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[JWT_ALGORITHM]
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token has expired") from exc
    except jwt.PyJWTError as exc:
        raise TokenError("Invalid token") from exc
    if payload.get("type") != JWT_TYPE_ACCESS:
        raise TokenError("Invalid token type")
    return payload


def new_refresh_token() -> tuple[str, str]:
    """Return (raw_token, sha256_hex) - only the hash is persisted."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_opaque(raw)


def hash_opaque(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_tokens_match(header_value: str | None, cookie_value: str | None) -> bool:
    if not header_value or not cookie_value:
        return False
    return secrets.compare_digest(header_value, cookie_value)
