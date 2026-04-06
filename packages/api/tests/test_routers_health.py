"""Tests for health endpoints."""

from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from alayaos_api.routers.health import router


def make_test_app():
    app = FastAPI()

    # Set up fake session factory
    async def fake_session_factory():
        return AsyncMock()

    session_mock = AsyncMock()
    session_mock.execute = AsyncMock()
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=None)
    session_mock.begin = MagicMock(return_value=session_mock)

    factory = MagicMock()
    factory.return_value = session_mock
    app.state.session_factory = factory

    app.include_router(router)
    return app, session_mock


def test_health_live_returns_ok() -> None:
    app, _ = make_test_app()
    client = TestClient(app)
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_live_no_auth_required() -> None:
    """Health live must work without X-Api-Key header."""
    app, _ = make_test_app()
    client = TestClient(app)
    response = client.get("/health/live")
    assert response.status_code == 200
