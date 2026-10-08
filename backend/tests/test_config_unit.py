from __future__ import annotations

import pytest

from app.core.config import DEV_DEFAULT_SECRET, Settings


def test_development_defaults_load():
    settings = Settings(
        _env_file=None, environment="development", secret_key="x"
    )
    assert settings.is_production is False
    assert settings.secure_cookies is False


def test_production_missing_secret_key_fails():
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(
            _env_file=None,
            environment="production",
            database_url="postgresql+psycopg2://u:p@localhost/db",
        )


def test_production_dev_default_secret_fails():
    with pytest.raises(ValueError, match="development default"):
        Settings(
            _env_file=None,
            environment="production",
            database_url="postgresql+psycopg2://u:p@localhost/db",
            secret_key=DEV_DEFAULT_SECRET,
        )


def test_production_short_secret_fails():
    with pytest.raises(ValueError, match="at least 32"):
        Settings(
            _env_file=None,
            environment="production",
            database_url="postgresql+psycopg2://u:p@localhost/db",
            secret_key="shortsecret",
        )


def test_production_weak_secret_fails():
    with pytest.raises(ValueError, match="too weak"):
        Settings(
            _env_file=None,
            environment="production",
            database_url="postgresql+psycopg2://u:p@localhost/db",
            secret_key="a" * 64,
        )


def test_production_missing_database_url_fails():
    with pytest.raises(ValueError, match="DATABASE_URL"):
        Settings(
            _env_file=None,
            environment="production",
            secret_key="correct-horse-battery-staple-9876543210!@#",
        )


def test_production_valid_config_passes():
    settings = Settings(
        _env_file=None,
        environment="production",
        database_url="postgresql+psycopg2://u:p@localhost/db",
        secret_key="correct-horse-battery-staple-9876543210!@#",
    )
    assert settings.is_production is True
    assert settings.secure_cookies is True
