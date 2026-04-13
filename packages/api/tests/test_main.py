"""Tests for FastAPI app factory (main.py)."""

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
    monkeypatch.delenv("ALAYA_API_DOCS_ENABLED", raising=False)

    app = create_app()
    paths = {route.path for route in app.routes}

    assert "/docs" not in paths
    assert "/redoc" not in paths
    assert "/openapi.json" not in paths


def test_create_app_allows_docs_override_in_production(monkeypatch) -> None:
    from alayaos_api.main import create_app

    monkeypatch.setenv("ALAYA_ENV", "production")
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
    trusted_host = next((m for m in app.user_middleware if m.cls is TrustedHostMiddleware), None)

    assert trusted_host is not None
    assert trusted_host.kwargs["allowed_hosts"] == ["api.example.com", "testserver"]

    allowed = TestClient(app, base_url="http://api.example.com")
    blocked = TestClient(app, base_url="http://evil.example.com")

    assert allowed.get("/health/live").status_code == 200
    assert blocked.get("/health/live").status_code == 400
