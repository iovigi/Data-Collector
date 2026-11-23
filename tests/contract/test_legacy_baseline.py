"""Contract tests for legacy app.py hardening (M1)."""

from __future__ import annotations

import pytest


def test_legacy_app_fails_without_strong_jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "your-secret-key")
    import app as legacy_app_module

    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        legacy_app_module.create_app()


def test_legacy_routes_disabled_by_default(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "a-very-strong-secret-key-at-least-32-chars-long!")
    monkeypatch.setenv("ENABLE_LEGACY_API", "false")
    import app as legacy_app_module

    flask_app = legacy_app_module.create_app()
    with flask_app.test_client() as client:
        resp = client.get("/api/query?type=items")
        assert resp.status_code == 410
        assert resp.get_json()["error"]["code"] == "LEGACY_API_DISABLED"


def test_legacy_seeder_disabled():
    from api.utils.seeder import seed_users

    with pytest.raises(RuntimeError, match="SEC-002"):
        seed_users()
