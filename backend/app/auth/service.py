from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.audit.model import AuditLog
from app.audit.service import record_audit
from app.auth.models import RefreshToken
from app.core.config import get_settings
from app.core.exceptions import UnauthorizedError
from app.core.rls import set_context
from app.core.security import (
    create_access_token,
    hash_opaque,
    hash_password,
    new_refresh_token,
    verify_password,
)
from app.shared.models import User, UserRole

# M5: PostgreSQL-backed login throttling (audit-derived, no extra service).
LOGIN_WINDOW_MINUTES = 15
LOGIN_MAX_FAILURES_PER_IDENTIFIER = 5
LOGIN_MAX_FAILURES_PER_IP = 10

_dummy_hash: str | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _elevated(db: Session, active: bool) -> None:
    set_context(db, user_id=None, company_ids=[], is_platform_admin=active)


def _get_dummy_hash() -> str:
    """Constant-work hash for non-existent accounts (timing equalization)."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password(new_refresh_token()[0])
    return _dummy_hash


def _failure_key(user: User | None, identifier: str) -> str:
    """Stable audit record_id key for login failures (fits varchar(64))."""
    if user is not None:
        return str(user.id)
    return ("unknown:" + identifier)[:64]


def find_user_by_identifier(db: Session, identifier: str) -> User | None:
    """Resolve the login identifier.

    Phase 1: email only. Phase 2 will extend this to employee-number lookup
    through users.employee_id -> employees.id without changing the API.
    """
    _elevated(db, True)
    try:
        return db.execute(
            select(User).where(User.email == identifier.strip().lower())
        ).scalar_one_or_none()
    finally:
        _elevated(db, False)


def _is_locked_out(db: Session, *, failure_key: str, ip_address: str | None) -> bool:
    """True when this identifier or source IP exceeded the failure budget."""
    _elevated(db, True)
    try:
        since = _utcnow() - timedelta(minutes=LOGIN_WINDOW_MINUTES)
        ident_failures = db.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.action == "auth.login_failed",
                AuditLog.record_id == failure_key,
                AuditLog.created_at >= since,
            )
        ).scalar_one()
        if ident_failures >= LOGIN_MAX_FAILURES_PER_IDENTIFIER:
            return True
        if ip_address:
            ip_failures = db.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.action == "auth.login_failed",
                    AuditLog.ip_address == ip_address,
                    AuditLog.created_at >= since,
                )
            ).scalar_one()
            if ip_failures >= LOGIN_MAX_FAILURES_PER_IP:
                return True
        return False
    finally:
        _elevated(db, False)


def _user_context(db: Session, user: User) -> list[int]:
    set_context(db, user_id=user.id, company_ids=[], is_platform_admin=False)
    rows = db.execute(
        select(UserRole.company_id).where(UserRole.user_id == user.id).distinct()
    ).scalars()
    return sorted({int(r) for r in rows})


def _audit_auth_event(
    db: Session,
    *,
    user: User | None,
    success: bool,
    attempted_identifier: str,
    ip_address: str | None,
) -> None:
    _elevated(db, True)
    try:
        record_audit(
            db,
            action="auth.login_success" if success else "auth.login_failed",
            entity="user",
            record_id=_failure_key(user, attempted_identifier),
            actor_user_id=user.id if user else None,
            company_id=user.company_id if user else None,
            new_value={"identifier": attempted_identifier} if not success else None,
            ip_address=ip_address,
        )
        db.commit()
    finally:
        _elevated(db, False)


def _audit_login_blocked(
    db: Session,
    *,
    user: User | None,
    attempted_identifier: str,
    ip_address: str | None,
) -> None:
    """Record a throttled attempt. Deliberately NOT 'auth.login_failed' so
    blocked requests cannot extend the lockout window."""
    _elevated(db, True)
    try:
        record_audit(
            db,
            action="auth.login_blocked",
            entity="user",
            record_id=_failure_key(user, attempted_identifier),
            actor_user_id=user.id if user else None,
            company_id=user.company_id if user else None,
            new_value={"identifier": attempted_identifier},
            ip_address=ip_address,
        )
        db.commit()
    finally:
        _elevated(db, False)


def login(
    db: Session,
    *,
    identifier: str,
    password: str,
    ip_address: str | None,
) -> tuple[User, list[int], str]:
    ident = identifier.strip()
    user = find_user_by_identifier(db, ident)
    failure_key = _failure_key(user, ident)

    if _is_locked_out(db, failure_key=failure_key, ip_address=ip_address):
        _audit_login_blocked(
            db, user=user, attempted_identifier=ident, ip_address=ip_address
        )
        raise UnauthorizedError("Invalid credentials")

    # Always run one Argon2 verification (real or dummy) so a non-existent
    # account and a wrong password cost the same (timing equalization).
    if user is not None:
        password_ok = verify_password(user.password_hash, password)
    else:
        verify_password(_get_dummy_hash(), password)
        password_ok = False

    if user is None or not password_ok:
        _audit_auth_event(
            db, user=user, success=False, attempted_identifier=ident,
            ip_address=ip_address,
        )
        raise UnauthorizedError("Invalid credentials")

    if not user.is_active:
        _audit_auth_event(
            db, user=user, success=False, attempted_identifier=ident,
            ip_address=ip_address,
        )
        raise UnauthorizedError("Invalid credentials")

    company_ids = _user_context(db, user)
    set_context(
        db,
        user_id=user.id,
        company_ids=company_ids,
        is_platform_admin=user.is_platform_admin,
    )

    user.last_login_at = _utcnow()
    db.add(user)
    record_audit(
        db,
        action="auth.login_success",
        entity="user",
        record_id=user.id,
        actor_user_id=user.id,
        company_id=user.company_id,
        ip_address=ip_address,
    )

    access_token = create_access_token(user.id)
    return user, company_ids, access_token


def issue_refresh_token(
    db: Session, user: User, ip_address: str | None
) -> tuple[str, RefreshToken]:
    settings = get_settings()
    raw, token_hash = new_refresh_token()
    row = RefreshToken(
        user_id=user.id,
        family_id=str(uuid.uuid4()),
        token_hash=token_hash,
        expires_at=_utcnow() + timedelta(days=settings.refresh_token_expire_days),
        created_ip=ip_address,
    )
    db.add(row)
    db.flush()
    return raw, row


def _revoke_family(db: Session, family_id: str) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_utcnow())
    )


def _audit_reuse_or_revoke(
    db: Session,
    *,
    row: RefreshToken,
    action: str,
    ip_address: str | None,
) -> None:
    """Elevated audit write for session-security events (M3). Never records
    token material - only the opaque family identifier."""
    _elevated(db, True)
    try:
        user = db.get(User, row.user_id)
        record_audit(
            db,
            action=action,
            entity="user",
            record_id=row.user_id,
            actor_user_id=row.user_id,
            company_id=user.company_id if user is not None else None,
            new_value={"family_id": row.family_id},
            ip_address=ip_address,
        )
        db.commit()
    finally:
        _elevated(db, False)


def rotate_refresh_token(
    db: Session, *, raw_token: str, ip_address: str | None
) -> tuple[User, str, str, RefreshToken]:
    token_hash = hash_opaque(raw_token)
    now = _utcnow()

    # M2: atomic claim. The conditional UPDATE + row lock guarantees that
    # exactly one concurrent request can move the token to revoked state;
    # a second one either blocks then observes revocation (reuse path) or
    # fails outright - never two successful rotations.
    claimed = db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
        .values(revoked_at=now)
        .returning(
            RefreshToken.id, RefreshToken.family_id, RefreshToken.user_id
        )
    ).first()

    if claimed is None:
        row = db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        ).scalar_one_or_none()
        if row is None:
            raise UnauthorizedError("Invalid refresh token")
        if row.revoked_at is not None:
            # Reuse detection: revoke the whole family, audit, COMMIT so the
            # revocation cannot be lost when the request fails (M3/M4).
            _revoke_family(db, row.family_id)
            _audit_reuse_or_revoke(
                db, row=row, action="auth.refresh_reuse_detected",
                ip_address=ip_address,
            )
            raise UnauthorizedError(
                "Refresh token reuse detected; session revoked"
            )
        raise UnauthorizedError("Refresh token expired")

    family_id = claimed.family_id
    user_id = claimed.user_id

    set_context(db, user_id=user_id, company_ids=[], is_platform_admin=False)
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        _revoke_family(db, family_id)
        # Persist the revocation before raising: a rollback on the error
        # path must not resurrect the sessions of an inactive account (M4).
        db.commit()
        raise UnauthorizedError("Account is inactive")

    set_context(db, user_id=user.id, company_ids=[], is_platform_admin=False)
    row = db.get(RefreshToken, claimed.id)
    new_raw, new_hash = new_refresh_token()
    replacement = RefreshToken(
        user_id=user.id,
        family_id=family_id,
        token_hash=new_hash,
        expires_at=_utcnow() + timedelta(days=get_settings().refresh_token_expire_days),
        created_ip=ip_address,
    )
    db.add(replacement)
    db.flush()
    if row is not None:
        row.replaced_by_id = replacement.id
    db.flush()

    company_ids = _user_context(db, user)
    set_context(
        db,
        user_id=user.id,
        company_ids=company_ids,
        is_platform_admin=user.is_platform_admin,
    )
    access_token = create_access_token(user.id)
    return user, access_token, new_raw, replacement


def revoke_session_family(
    db: Session, raw_token: str, ip_address: str | None = None
) -> None:
    row = db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_opaque(raw_token)
        )
    ).scalar_one_or_none()
    if row is not None:
        _revoke_family(db, row.family_id)
        # M3: audit the revocation (logout) in the same transaction.
        _elevated(db, True)
        try:
            user = db.get(User, row.user_id)
            record_audit(
                db,
                action="auth.logout",
                entity="user",
                record_id=row.user_id,
                actor_user_id=row.user_id,
                company_id=user.company_id if user is not None else None,
                new_value={"family_id": row.family_id},
                ip_address=ip_address,
            )
        finally:
            _elevated(db, False)


def change_own_password(
    db: Session,
    *,
    user: User,
    current_password: str,
    new_password: str,
    ip_address: str | None,
) -> None:
    if not verify_password(user.password_hash, current_password):
        # M3: audit the failed attempt and COMMIT before raising so the
        # record survives the request rollback. No secrets are recorded.
        record_audit(
            db,
            action="auth.password_change_failed",
            entity="user",
            record_id=user.id,
            actor_user_id=user.id,
            company_id=user.company_id,
            ip_address=ip_address,
        )
        db.commit()
        raise UnauthorizedError("Current password is incorrect")
    user.password_hash = hash_password(new_password)
    db.add(user)
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_utcnow())
    )
    record_audit(
        db,
        action="auth.password_changed",
        entity="user",
        record_id=user.id,
        actor_user_id=user.id,
        company_id=user.company_id,
        ip_address=ip_address,
    )
