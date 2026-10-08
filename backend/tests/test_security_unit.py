from __future__ import annotations

import pytest

from app.core.security import (
    TokenError,
    create_access_token,
    csrf_tokens_match,
    decode_access_token,
    hash_opaque,
    hash_password,
    new_csrf_token,
    new_refresh_token,
    verify_password,
)


def test_password_hash_is_argon2_not_plaintext():
    hashed = hash_password("Sup3rSecret!")
    assert hashed != "Sup3rSecret!"
    assert hashed.startswith("$argon2")


def test_verify_password_correct():
    hashed = hash_password("Sup3rSecret!")
    assert verify_password(hashed, "Sup3rSecret!") is True


def test_verify_password_wrong():
    hashed = hash_password("Sup3rSecret!")
    assert verify_password(hashed, "wrong-password") is False


def test_password_hashes_are_salted():
    assert hash_password("same-password") != hash_password("same-password")


def test_access_token_roundtrip():
    token = create_access_token(42)
    payload = decode_access_token(token)
    assert payload["sub"] == "42"
    assert payload["type"] == "access"


def test_expired_token_rejected():
    token = create_access_token(1, expires_minutes=-1)
    with pytest.raises(TokenError):
        decode_access_token(token)


def test_token_with_wrong_type_rejected():
    import jwt as pyjwt

    from app.core.config import get_settings

    token = pyjwt.encode(
        {"sub": "1", "type": "refresh"}, get_settings().secret_key, algorithm="HS256"
    )
    with pytest.raises(TokenError):
        decode_access_token(token)


def test_token_with_wrong_signature_rejected():
    import jwt as pyjwt

    token = pyjwt.encode({"sub": "1", "type": "access"}, "other-secret", algorithm="HS256")
    with pytest.raises(TokenError):
        decode_access_token(token)


def test_csrf_match_valid():
    assert csrf_tokens_match("abc123", "abc123") is True


def test_csrf_match_missing_header():
    assert csrf_tokens_match(None, "abc123") is False


def test_csrf_match_missing_cookie():
    assert csrf_tokens_match("abc123", None) is False


def test_csrf_match_incorrect():
    assert csrf_tokens_match("wrong", "abc123") is False


def test_refresh_token_unique_and_hashed():
    raw1, hash1 = new_refresh_token()
    raw2, hash2 = new_refresh_token()
    assert raw1 != raw2
    assert hash1 != hash2
    assert hash_opaque(raw1) == hash1
    assert len(hash1) == 64


def test_csrf_token_unique():
    assert new_csrf_token() != new_csrf_token()
