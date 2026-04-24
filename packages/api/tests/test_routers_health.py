"""Tests for health endpoints."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from alayaos_api.routers import health
from alayaos_api.routers.health import router


def make_scalar_result(value):
    result = MagicMock()
    result.scalar_one.return_value = value
    result.scalar_one_or_none.return_value = value
    return result


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


def mock_redis_ping(monkeypatch, *, result=True, side_effect=None):
    redis_client = MagicMock()
    redis_client.ping = AsyncMock(return_value=result, side_effect=side_effect)
    redis_client.aclose = AsyncMock()
    monkeypatch.setattr(health.aioredis, "from_url", MagicMock(return_value=redis_client))
    return redis_client


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


def test_health_ready_redacts_details_by_default(monkeypatch) -> None:
    monkeypatch.delenv("ALAYA_HEALTH_READY_VERBOSE", raising=False)
    health.get_settings.cache_clear()
    mock_redis_ping(monkeypatch)
    app, session_mock = make_test_app()
    session_mock.execute.side_effect = [
        MagicMock(),
        make_scalar_result("0004"),
        make_scalar_result(1),
        make_scalar_result(0),
    ]

    client = TestClient(app)
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_ready_includes_checks_when_verbose(monkeypatch) -> None:
    monkeypatch.setenv("ALAYA_HEALTH_READY_VERBOSE", "true")
    health.get_settings.cache_clear()
    mock_redis_ping(monkeypatch)
    app, session_mock = make_test_app()
    session_mock.execute.side_effect = [
        MagicMock(),
        make_scalar_result("0004"),
        make_scalar_result(1),
        make_scalar_result(0),
    ]

    client = TestClient(app)
    response = client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["migrations"] == "ok"
    assert body["checks"]["seeds"] == "ok"
    assert body["checks"]["redis"] == "ok"
    assert body["first_run"] is True


def test_health_ready_reports_redis_down_when_ping_fails(monkeypatch) -> None:
    monkeypatch.setenv("ALAYA_HEALTH_READY_VERBOSE", "true")
    health.get_settings.cache_clear()
    mock_redis_ping(monkeypatch, side_effect=ConnectionError("redis down"))
    app, session_mock = make_test_app()
    session_mock.execute.side_effect = [
        MagicMock(),
        make_scalar_result("0004"),
        make_scalar_result(1),
        make_scalar_result(0),
    ]

    client = TestClient(app)
    response = client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["redis"] == "down"


def test_health_ready_uses_cached_settings(monkeypatch) -> None:
    settings_factory = MagicMock(
        return_value=SimpleNamespace(HEALTH_READY_VERBOSE=False, REDIS_URL="redis://localhost:6379/0")
    )
    monkeypatch.setattr(health, "Settings", settings_factory)
    mock_redis_ping(monkeypatch)
    health.get_settings.cache_clear()

    app, session_mock = make_test_app()
    session_mock.execute.side_effect = [
        MagicMock(),
        make_scalar_result("0004"),
        make_scalar_result(1),
        make_scalar_result(0),
        MagicMock(),
        make_scalar_result("0004"),
        make_scalar_result(1),
        make_scalar_result(0),
    ]

    client = TestClient(app)
    first = client.get("/health/ready")
    second = client.get("/health/ready")

    assert first.status_code == 200
    assert second.status_code == 200
    assert settings_factory.call_count == 1

    health.get_settings.cache_clear()
