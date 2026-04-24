"""Tests for ACL-aware tree router behavior."""

import hashlib
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from structlog.contextvars import bind_contextvars, clear_contextvars

from alayaos_api.main import create_app
from alayaos_core.models.api_key import APIKey

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
        clear_contextvars()
        bind_contextvars(allowed_access_levels="channel,public")
        session = AsyncMock()
        yield session
        clear_contextvars()

    async def override_api_key():
        return api_key

    from alayaos_api.deps import get_api_key, get_session, get_workspace_session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_workspace_session] = override_workspace_session
    app.dependency_overrides[get_api_key] = override_api_key
    return app


def test_tree_node_passes_allowed_tiers_and_allows_view_summary_none() -> None:
    app = make_app(make_api_key(scopes=["read"]))
    now = datetime.now(UTC)
    node = SimpleNamespace(
        id=uuid.uuid4(),
        path="people/alice",
        workspace_id=WS_ID,
        entity_id=uuid.uuid4(),
        node_type="entity",
        is_dirty=False,
        last_rebuilt_at=now,
        markdown_cache="# Alice",
        summary=None,
    )

    with patch("alayaos_api.routers.tree.TreeService") as mock_service_cls:
        service = mock_service_cls.return_value
        service.get_node = AsyncMock(return_value=node)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/tree/people/alice", headers={"X-Api-Key": RAW_KEY})

    service.get_node.assert_awaited_once_with("people/alice", allowed_tiers={"channel", "public"})
    assert response.status_code == 200
    assert response.json()["data"]["summary"] is None


def test_tree_root_hides_cached_markdown_for_non_admin() -> None:
    app = make_app(make_api_key(scopes=["read"]))
    now = datetime.now(UTC)
    node = SimpleNamespace(
        id=uuid.uuid4(),
        path="people",
        workspace_id=WS_ID,
        entity_id=None,
        node_type="index",
        is_dirty=False,
        last_rebuilt_at=now,
        markdown_cache="# People\n\nrestricted briefing",
        summary={"overview": "restricted summary"},
    )

    with patch("alayaos_api.routers.tree.TreeService") as mock_service_cls:
        service = mock_service_cls.return_value
        service.get_root = AsyncMock(return_value=[node])
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/tree", headers={"X-Api-Key": RAW_KEY})

    assert response.status_code == 200
    payload = response.json()["data"][0]
    assert payload["markdown_cache"] is None
    assert payload["summary"] is None


def test_tree_path_hides_index_cached_markdown_for_non_admin() -> None:
    app = make_app(make_api_key(scopes=["read"]))
    now = datetime.now(UTC)
    node = SimpleNamespace(
        id=uuid.uuid4(),
        path="people",
        workspace_id=WS_ID,
        entity_id=None,
        node_type="index",
        is_dirty=False,
        last_rebuilt_at=now,
        markdown_cache="# People\n\nrestricted codename BLACKBIRD",
        summary={"overview": "restricted codename BLACKBIRD"},
    )

    with patch("alayaos_api.routers.tree.TreeService") as mock_service_cls:
        service = mock_service_cls.return_value
        service.get_node = AsyncMock(return_value=node)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/tree/people", headers={"X-Api-Key": RAW_KEY})

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["markdown_cache"] is None
    assert payload["summary"] is None
