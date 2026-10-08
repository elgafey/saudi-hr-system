from __future__ import annotations

import threading

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.auth import service as auth_service
from app.auth.models import RefreshToken
from app.core.exceptions import UnauthorizedError
from tests.conftest import seed_company, seed_user

pytestmark = pytest.mark.db


def test_concurrent_refresh_rotation_has_single_winner(db_schema):
    engine = create_engine(db_schema, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    setup = factory()
    try:
        company = seed_company(setup, "Race Co")
        user = seed_user(setup, "race@race.co", company, "company_admin")
        raw, row = auth_service.issue_refresh_token(setup, user, "127.0.0.1")
        setup.commit()
        family_id = row.family_id
    finally:
        setup.close()

    barrier = threading.Barrier(2, timeout=30)
    results: list[str] = []

    def worker() -> None:
        session = factory()
        try:
            barrier.wait()
            try:
                auth_service.rotate_refresh_token(
                    session, raw_token=raw, ip_address="127.0.0.1"
                )
                session.commit()
                results.append("ok")
            except UnauthorizedError:
                session.rollback()
                results.append("rejected")
            except Exception as exc:  # pragma: no cover - diagnostics
                session.rollback()
                results.append(f"error:{exc}")
        finally:
            session.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert all(not t.is_alive() for t in threads), "rotation threads deadlocked"

    assert results.count("ok") == 1, results
    assert results.count("rejected") == 1, results

    # The rejected (reuse) path revokes the whole family: even the winner's
    # freshly minted token must be dead afterwards.
    check = factory()
    try:
        tokens = (
            check.execute(
                select(RefreshToken).where(RefreshToken.family_id == family_id)
            )
            .scalars()
            .all()
        )
        assert len(tokens) >= 2
        assert all(t.revoked_at is not None for t in tokens)
    finally:
        check.close()
        engine.dispose()


def test_sequential_reuse_after_concurrent_claim_is_rejected(db_schema):
    engine = create_engine(db_schema, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    setup = factory()
    try:
        company = seed_company(setup, "Race Seq Co")
        user = seed_user(setup, "race2@race.co", company, "company_admin")
        raw, row = auth_service.issue_refresh_token(setup, user, "127.0.0.1")
        setup.commit()
        family_id = row.family_id
    finally:
        setup.close()

    winner = factory()
    try:
        auth_service.rotate_refresh_token(
            winner, raw_token=raw, ip_address="127.0.0.1"
        )
        winner.commit()
    finally:
        winner.close()

    loser = factory()
    try:
        with pytest.raises(UnauthorizedError):
            auth_service.rotate_refresh_token(
                loser, raw_token=raw, ip_address="127.0.0.1"
            )
        loser.rollback()
    finally:
        loser.close()
        engine.dispose()

    verify = factory()
    try:
        tokens = (
            verify.execute(
                select(RefreshToken).where(RefreshToken.family_id == family_id)
            )
            .scalars()
            .all()
        )
        assert all(t.revoked_at is not None for t in tokens)
    finally:
        verify.close()
        engine.dispose()
