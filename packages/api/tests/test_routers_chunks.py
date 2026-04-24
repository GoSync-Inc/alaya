"""Tests for the chunks router."""

import hashlib
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from alayaos_api.main import create_app
from alayaos_core.models.api_key import APIKey
from alayaos_core.models.chunk import L0Chunk

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

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_api_key] = override_api_key
    app.dependency_overrides[get_workspace_session] = override_workspace_session
    return app


def make_chunk() -> L0Chunk:
    chunk = L0Chunk(
        id=uuid.uuid4(),
        workspace_id=WS_ID,
        event_id=uuid.uuid4(),
        chunk_index=0,
        chunk_total=1,
        text="visible chunk",
        token_count=2,
        source_type="slack",
        source_id="C123",
        domain_scores={},
        primary_domain=None,
        is_crystal=True,
        classification_model=None,
        classification_verified=False,
        verification_changed=False,
        processing_stage="classified",
        error_count=0,
        error_message=None,
        extraction_run_id=None,
        created_at=datetime.now(UTC),
    )
    return chunk


def test_list_chunks_reports_acl_filtered_count() -> None:
    api_key = make_api_key()
    app = make_app_with_mock_session(api_key)
    chunk = make_chunk()

    with patch("alayaos_api.routers.chunks.ChunkRepository") as mock_cls:
        repo = AsyncMock()
        repo.list = AsyncMock(return_value=([chunk], None, False))
        repo.last_filtered_count = 3
        mock_cls.return_value = repo

        client = TestClient(app)
        response = client.get("/api/v1/chunks", headers={"X-Api-Key": RAW_KEY})

    assert response.status_code == 200
    assert response.json()["meta"] == {"filtered_count": 3, "filter_reason": "acl_filtered"}
