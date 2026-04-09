"""Tests for the admin router."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from alayaos_api.main import create_app
from alayaos_core.models.api_key import APIKey

RAW_KEY = "ak_testprefix12345678901234567890"
PREFIX = RAW_KEY[:12]
WS_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


def make_api_key(scopes=None) -> APIKey:
    import hashlib

    return APIKey(
        id=uuid.uuid4(),
        workspace_id=WS_ID,
        name="Test Key",
        key_prefix=PREFIX,
        key_hash=hashlib.sha256(RAW_KEY.encode()).hexdigest(),
        scopes=scopes or ["read", "write", "admin"],
        revoked_at=None,
        expires_at=None,
        is_bootstrap=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def make_app_with_mock_session(api_key: APIKey):
    app = create_app()

    async def override_session():
        session = AsyncMock()
        yield session

    async def override_api_key():
        return api_key

    async def override_workspace_session():
        session = AsyncMock()
        yield session

    from alayaos_api.deps import get_api_key, get_session, get_workspace_session
    from alayaos_api.routers.admin import get_embedding_service
    from alayaos_core.services.embedding import FakeEmbeddingService

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_api_key] = override_api_key
    app.dependency_overrides[get_workspace_session] = override_workspace_session
    # Override require_scope("admin") by overriding get_api_key (used inside require_scope)
    # get_api_key is already overridden above, so require_scope will pass for admin keys.
    app.dependency_overrides[get_embedding_service] = lambda: FakeEmbeddingService()
    return app


class TestBackfillEmbeddings:
    def test_backfill_requires_admin_scope(self) -> None:
        """Endpoint returns 403 when key lacks admin scope."""
        api_key = make_api_key(scopes=["read", "write"])
        app = make_app_with_mock_session(api_key)

        client = TestClient(app)
        response = client.post("/admin/backfill-embeddings", json={})

        assert response.status_code == 403

    def test_backfill_returns_200_with_counts(self) -> None:
        """Endpoint returns processed/failed/total counts."""
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)

        # Mock the session execute calls:
        # First call returns rows (chunks needing embedding)
        # Second call is the UPDATE (via begin_nested savepoint)
        chunk_id = uuid.uuid4()
        mock_row = MagicMock()
        mock_row.id = chunk_id
        mock_row.content = "hello world"

        fetch_result = MagicMock()
        fetch_result.all.return_value = [mock_row]

        update_result = MagicMock()

        session_mock = AsyncMock()
        session_mock.execute = AsyncMock(side_effect=[fetch_result, update_result])
        # begin_nested returns an async context manager
        nested_cm = AsyncMock()
        nested_cm.__aenter__ = AsyncMock(return_value=nested_cm)
        nested_cm.__aexit__ = AsyncMock(return_value=False)
        session_mock.begin_nested = MagicMock(return_value=nested_cm)

        async def override_session():
            yield session_mock

        from alayaos_api.deps import get_session

        app.dependency_overrides[get_session] = override_session

        client = TestClient(app)
        response = client.post("/admin/backfill-embeddings", json={})

        assert response.status_code == 200
        body = response.json()
        assert body["processed"] == 1
        assert body["failed"] == 0
        assert body["total"] == 1

    def test_backfill_no_chunks_returns_zero_counts(self) -> None:
        """When no chunks need embedding, all counts are zero."""
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)

        fetch_result = MagicMock()
        fetch_result.all.return_value = []

        session_mock = AsyncMock()
        session_mock.execute = AsyncMock(return_value=fetch_result)

        async def override_session():
            yield session_mock

        from alayaos_api.deps import get_session

        app.dependency_overrides[get_session] = override_session

        client = TestClient(app)
        response = client.post("/admin/backfill-embeddings", json={})

        assert response.status_code == 200
        body = response.json()
        assert body["processed"] == 0
        assert body["failed"] == 0
        assert body["total"] == 0

    def test_backfill_filters_by_workspace_id(self) -> None:
        """When workspace_id is provided, execute is called with a filter."""
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)

        fetch_result = MagicMock()
        fetch_result.all.return_value = []

        session_mock = AsyncMock()
        # First call: SET LOCAL; second call: SELECT
        session_mock.execute = AsyncMock(side_effect=[MagicMock(), fetch_result])

        async def override_session():
            yield session_mock

        from alayaos_api.deps import get_session

        app.dependency_overrides[get_session] = override_session

        client = TestClient(app)
        ws_id = str(uuid.uuid4())
        response = client.post(
            "/admin/backfill-embeddings",
            json={"workspace_id": ws_id},
        )

        assert response.status_code == 200
        # Two execute calls: SET LOCAL + SELECT
        assert session_mock.execute.call_count == 2

    def test_backfill_batch_size_upper_bound(self) -> None:
        """batch_size > 200 is rejected with 422."""
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)

        client = TestClient(app)
        response = client.post("/admin/backfill-embeddings", json={"batch_size": 201})

        assert response.status_code in (400, 422)

    def test_backfill_batch_size_lower_bound(self) -> None:
        """batch_size < 1 is rejected with 400 or 422."""
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)

        client = TestClient(app)
        response = client.post("/admin/backfill-embeddings", json={"batch_size": 0})

        assert response.status_code in (400, 422)
