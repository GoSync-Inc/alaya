"""Tests for the ask router."""

import hashlib
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from alayaos_api.main import create_app
from alayaos_core.models.api_key import APIKey
from alayaos_core.services.ask import AskResult

RAW_KEY = "ak_testprefix12345678901234567890"
PREFIX = RAW_KEY[:12]
WS_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


def make_api_key(scopes=None) -> APIKey:
    return APIKey(
        id=uuid.uuid4(),
        workspace_id=WS_ID,
        name="Test Key",
        key_prefix=PREFIX,
        key_hash=hashlib.sha256(RAW_KEY.encode()).hexdigest(),
        scopes=scopes or ["read"],
        revoked_at=None,
        expires_at=None,
        is_bootstrap=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def make_app(api_key: APIKey):
    app = create_app()

    async def override_session():
        session = AsyncMock()
        yield session

    async def override_workspace_session():
        session = AsyncMock()
        yield session

    async def override_api_key():
        return api_key

    from alayaos_api.deps import get_api_key, get_session, get_workspace_session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_workspace_session] = override_workspace_session
    app.dependency_overrides[get_api_key] = override_api_key
    return app


def _mock_redis_client() -> MagicMock:
    client = MagicMock()
    client.aclose = AsyncMock()
    return client


def test_ask_allows_read_scope() -> None:
    app = make_app(make_api_key(scopes=["read"]))
    redis_client = _mock_redis_client()
    ask_result = AskResult(
        answer="Project Alpha is on track.",
        answerable=True,
        citations=[],
        evidence=[],
        tokens_used=12,
        cost_usd=0.001,
    )

    with (
        patch("alayaos_api.routers.ask.aioredis.from_url", return_value=redis_client),
        patch("alayaos_api.routers.ask.RateLimiterService") as mock_limiter_cls,
        patch("alayaos_api.routers.ask.ask", new=AsyncMock(return_value=ask_result)),
    ):
        mock_limiter_cls.return_value.check = AsyncMock(
            return_value=SimpleNamespace(allowed=True, retry_after=None, backend_available=True)
        )
        client = TestClient(app)
        response = client.post("/api/v1/ask", headers={"X-Api-Key": RAW_KEY}, json={"question": "status?"})

    assert response.status_code == 200
    assert response.json()["answer"] == "Project Alpha is on track."


def test_ask_preserves_service_meta() -> None:
    app = make_app(make_api_key(scopes=["read"]))
    redis_client = _mock_redis_client()
    ask_result = {
        "answer": "Project Alpha is on track.",
        "answerable": True,
        "citations": [],
        "evidence": [],
        "tokens_used": 12,
        "cost_usd": 0.001,
        "meta": {"filtered_count": 1, "filter_reason": "access_level"},
    }

    with (
        patch("alayaos_api.routers.ask.aioredis.from_url", return_value=redis_client),
        patch("alayaos_api.routers.ask.RateLimiterService") as mock_limiter_cls,
        patch("alayaos_api.routers.ask.ask", new=AsyncMock(return_value=ask_result)),
    ):
        mock_limiter_cls.return_value.check = AsyncMock(
            return_value=SimpleNamespace(allowed=True, retry_after=None, backend_available=True)
        )
        client = TestClient(app)
        response = client.post("/api/v1/ask", headers={"X-Api-Key": RAW_KEY}, json={"question": "status?"})

    assert response.status_code == 200
    assert response.json()["meta"] == {"filtered_count": 1, "filter_reason": "access_level"}


def test_ask_requires_read_scope() -> None:
    app = make_app(make_api_key(scopes=["write"]))

    client = TestClient(app)
    response = client.post("/api/v1/ask", headers={"X-Api-Key": RAW_KEY}, json={"question": "status?"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "auth.insufficient_scope"


def test_ask_returns_structured_429_when_limited() -> None:
    app = make_app(make_api_key(scopes=["read"]))
    redis_client = _mock_redis_client()

    with (
        patch("alayaos_api.routers.ask.aioredis.from_url", return_value=redis_client),
        patch("alayaos_api.routers.ask.RateLimiterService") as mock_limiter_cls,
    ):
        mock_limiter_cls.return_value.check = AsyncMock(
            return_value=SimpleNamespace(allowed=False, retry_after=9, backend_available=True)
        )
        client = TestClient(app)
        response = client.post("/api/v1/ask", headers={"X-Api-Key": RAW_KEY}, json={"question": "status?"})

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "9"
    assert response.json()["error"]["code"] == "rate_limit.exceeded"


def test_ask_returns_503_when_rate_limiter_backend_is_unavailable() -> None:
    app = make_app(make_api_key(scopes=["read"]))
    redis_client = _mock_redis_client()

    with (
        patch("alayaos_api.routers.ask.aioredis.from_url", return_value=redis_client),
        patch("alayaos_api.routers.ask.RateLimiterService") as mock_limiter_cls,
    ):
        mock_limiter_cls.return_value.check = AsyncMock(
            return_value=SimpleNamespace(allowed=False, retry_after=None, backend_available=False)
        )
        client = TestClient(app)
        response = client.post("/api/v1/ask", headers={"X-Api-Key": RAW_KEY}, json={"question": "status?"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "server.rate_limit_unavailable"
