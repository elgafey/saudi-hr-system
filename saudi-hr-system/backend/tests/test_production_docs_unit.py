from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app

# Note: this module intentionally carries no `db` marker.

PROD_SECRET = "correct-horse-battery-staple-9876543210!@#"
PROD_DATABASE_URL = "postgresql+psycopg2://u:p@localhost/db"


def test_docs_and_openapi_disabled_in_production(monkeypatch):
    try:
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("SECRET_KEY", PROD_SECRET)
        monkeypatch.setenv("DATABASE_URL", PROD_DATABASE_URL)
        get_settings.cache_clear()

        application = create_app()
        assert application.docs_url is None
        assert application.redoc_url is None
        assert application.openapi_url is None

        with TestClient(application) as client:
            assert client.get("/docs").status_code == 404
            assert client.get("/redoc").status_code == 404
            assert client.get("/openapi.json").status_code == 404
            # The API itself keeps working in production mode.
            health = client.get("/health")
            assert health.status_code == 200
            assert health.json()["status"] == "ok"
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()

    # Environment restored: docs come back for development/test.
    restored = create_app()
    assert restored.docs_url == "/docs"
    assert restored.redoc_url == "/redoc"
    assert restored.openapi_url == "/openapi.json"
