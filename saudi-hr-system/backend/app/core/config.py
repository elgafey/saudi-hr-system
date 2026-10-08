from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_DEFAULT_SECRET = "dev-only-insecure-secret-key-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: str = "development"
    database_url: str = (
        "postgresql+psycopg2://saudi_hr_user:@127.0.0.1:5432/saudi_hr"
    )
    test_database_url: str | None = None
    secret_key: str = DEV_DEFAULT_SECRET
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 14
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    storage_path: str = "./storage"

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def secure_cookies(self) -> bool:
        return self.is_production

    @model_validator(mode="after")
    def _validate_production_security(self) -> Settings:
        if not self.is_production:
            return self
        errors: list[str] = []
        if "database_url" not in self.model_fields_set:
            errors.append(
                "DATABASE_URL must be set explicitly in production "
                "(no implicit development default is allowed)."
            )
        if "secret_key" not in self.model_fields_set:
            errors.append("SECRET_KEY must be set explicitly in production.")
        elif self.secret_key == DEV_DEFAULT_SECRET:
            errors.append("SECRET_KEY is the development default and cannot be used in production.")
        elif len(self.secret_key) < 32:
            errors.append("SECRET_KEY must be at least 32 characters long in production.")
        elif len(set(self.secret_key)) < 10:
            errors.append("SECRET_KEY is too weak (too few distinct characters) for production.")
        if errors:
            raise ValueError("Production configuration invalid: " + " ".join(errors))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
