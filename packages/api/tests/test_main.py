"""Tests for FastAPI app factory (main.py)."""

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.trustedhost import TrustedHostMiddleware


def test_create_app_returns_fastapi_instance() -> None:
    from alayaos_api.main import create_app

    app = create_app()
    assert isinstance(app, FastAPI)


def test_app_title_and_version() -> None:
    from alayaos_api.main import create_app

    app = create_app()
    assert app.title == "AlayaOS API"
    assert app.version == "0.1.0"


def test_module_level_app_exists() -> None:
    from alayaos_api.main import app

    assert isinstance(app, FastAPI)


def test_health_live_route_exists() -> None:
    """Health live endpoint is accessible without auth."""
    from alayaos_api.main import create_app

    app = create_app()
    routes = [r.path for r in app.routes]
    assert "/health/live" in routes


def test_api_v1_routes_registered() -> None:
    """v1 resource routes are registered under /api/v1/."""
    from alayaos_api.main import create_app

    app = create_app()
    paths = [r.path for r in app.routes]
    assert any(p.startswith("/api/v1/") for p in paths)


def test_create_app_disables_docs_in_production(monkeypatch) -> None:
    from alayaos_api.main import create_app

    monkeypatch.setenv("ALAYA_ENV", "production")
    monkeypatch.setenv("ALAYA_SECRET_KEY", "a-real-production-secret-value")
    monkeypatch.delenv("ALAYA_API_DOCS_ENABLED", raising=False)

    app = create_app()
    paths = {route.path for route in app.routes}

    assert "/docs" not in paths
    assert "/redoc" not in paths
    assert "/openapi.json" not in paths


def test_create_app_allows_docs_override_in_production(monkeypatch) -> None:
    from alayaos_api.main import create_app

    monkeypatch.setenv("ALAYA_ENV", "production")
    monkeypatch.setenv("ALAYA_SECRET_KEY", "a-real-production-secret-value")
    monkeypatch.setenv("ALAYA_API_DOCS_ENABLED", "true")

    app = create_app()
    paths = {route.path for route in app.routes}

    assert "/docs" in paths
    assert "/redoc" in paths
    assert "/openapi.json" in paths


def test_create_app_adds_trusted_host_middleware_when_configured(monkeypatch) -> None:
    from alayaos_api.main import create_app

    monkeypatch.setenv("ALAYA_TRUSTED_HOSTS", '["api.example.com","testserver"]')

    app = create_app()
    trusted_host = next((m for m in app.user_middleware if issubclass(m.cls, TrustedHostMiddleware)), None)

    assert trusted_host is not None
    assert trusted_host.kwargs["allowed_hosts"] == ["api.example.com", "testserver"]

    allowed = TestClient(app, base_url="http://api.example.com")
    blocked = TestClient(app, base_url="http://evil.example.com")

    assert allowed.get("/health/live").status_code == 200
    blocked_response = blocked.get("/health/live")
    assert blocked_response.status_code == 400
    assert blocked_response.headers["content-type"].startswith("application/json")
    assert blocked_response.json()["error"]["code"] == "validation.invalid_host"
    assert blocked_response.json()["error"]["request_id"] == blocked_response.headers["X-Request-ID"]


def test_request_id_matches_error_envelope_for_allowed_host_errors(monkeypatch) -> None:
    from alayaos_api.main import create_app

    monkeypatch.setenv("ALAYA_TRUSTED_HOSTS", '["api.example.com","testserver"]')

    async def fake_validate_pgvector_extension(engine) -> None:
        pass

    monkeypatch.setattr(
        "alayaos_api.main._validate_pgvector_extension",
        fake_validate_pgvector_extension,
    )

    app = create_app()
    with TestClient(app, base_url="http://api.example.com") as client:
        response = client.get("/api/v1/workspaces")

    assert response.status_code == 401
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


def test_create_app_warns_when_production_has_no_trusted_hosts(monkeypatch) -> None:
    from alayaos_api.main import create_app

    monkeypatch.setenv("ALAYA_ENV", "production")
    monkeypatch.setenv("ALAYA_SECRET_KEY", "a-real-production-secret-value")
    monkeypatch.delenv("ALAYA_TRUSTED_HOSTS", raising=False)

    with patch("alayaos_api.main.log.warning") as mock_warning:
        create_app()

    mock_warning.assert_called_once_with(
        "trusted_hosts_not_configured_for_production",
        message="Host validation is not configured for production. Set ALAYA_TRUSTED_HOSTS or enforce trusted hosts at ingress.",
    )


def test_create_app_raises_on_default_secret_in_production(monkeypatch) -> None:
    """Import-time fail-fast covers paths that skip lifespan (e.g. --lifespan off).

    Regression for codex review P2 on PR #98: guard must run in
    create_app(), not only inside the lifespan hook.
    """
    import pytest

    from alayaos_api.main import create_app

    monkeypatch.setenv("ALAYA_ENV", "production")
    monkeypatch.delenv("ALAYA_SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app()


# -----------------------------------------------------------------------------
# P0-3: SECRET_KEY production guard
# -----------------------------------------------------------------------------


def test_validate_production_secrets_passes_for_dev() -> None:
    """Default SECRET_KEY is acceptable outside production."""
    from alayaos_api.main import _validate_production_secrets
    from alayaos_core.config import Settings

    settings = Settings()
    assert settings.ENV == "dev"
    # Should not raise — dev env tolerates the default sentinel.
    _validate_production_secrets(settings)


def test_validate_production_secrets_raises_on_default_in_prod(monkeypatch) -> None:
    """Production refuses to start with the 'change-me-in-production' default."""
    import pytest

    from alayaos_api.main import _validate_production_secrets
    from alayaos_core.config import Settings

    monkeypatch.setenv("ALAYA_ENV", "production")
    monkeypatch.delenv("ALAYA_SECRET_KEY", raising=False)

    settings = Settings()
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        _validate_production_secrets(settings)


def test_validate_production_secrets_passes_with_real_secret(monkeypatch) -> None:
    """A non-default SECRET_KEY clears the production guard."""
    from alayaos_api.main import _validate_production_secrets
    from alayaos_core.config import Settings

    monkeypatch.setenv("ALAYA_ENV", "production")
    monkeypatch.setenv("ALAYA_SECRET_KEY", "a-very-real-32-byte-random-secret")

    settings = Settings()
    # Should not raise.
    _validate_production_secrets(settings)


def test_validate_production_secrets_rejects_empty_secret(monkeypatch) -> None:
    """Blank ALAYA_SECRET_KEY (=) must be rejected in production (codex 7th review)."""
    import pytest

    from alayaos_api.main import _validate_production_secrets
    from alayaos_core.config import Settings

    monkeypatch.setenv("ALAYA_ENV", "production")
    monkeypatch.setenv("ALAYA_SECRET_KEY", "")

    settings = Settings()
    with pytest.raises(RuntimeError, match="non-empty"):
        _validate_production_secrets(settings)


def test_validate_production_secrets_rejects_whitespace_secret(monkeypatch) -> None:
    """Whitespace-only SECRET_KEY (common Compose bug) must be rejected."""
    import pytest

    from alayaos_api.main import _validate_production_secrets
    from alayaos_core.config import Settings

    monkeypatch.setenv("ALAYA_ENV", "production")
    monkeypatch.setenv("ALAYA_SECRET_KEY", "   \t\n  ")

    settings = Settings()
    with pytest.raises(RuntimeError, match="non-empty"):
        _validate_production_secrets(settings)
