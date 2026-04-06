"""Tests for FastAPI app factory (main.py)."""

from fastapi import FastAPI


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
