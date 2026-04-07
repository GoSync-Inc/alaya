"""Tests for the relations router."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

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

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_api_key] = override_api_key
    app.dependency_overrides[get_workspace_session] = override_workspace_session
    return app


def make_relation(ws_id: uuid.UUID | None = None):
    from alayaos_core.models.relation import L1Relation

    now = datetime.now(UTC)
    rel = L1Relation(
        id=uuid.uuid4(),
        workspace_id=ws_id or WS_ID,
        source_entity_id=uuid.uuid4(),
        target_entity_id=uuid.uuid4(),
        relation_type="member_of",
        confidence=0.95,
        extraction_run_id=None,
    )
    rel.created_at = now
    rel.updated_at = now
    return rel


class TestRelationsRouter:
    def test_list_relations_returns_200(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)
        rel = make_relation()

        with patch("alayaos_api.routers.relations.RelationRepository") as mock_cls:
            repo = AsyncMock()
            repo.list = AsyncMock(return_value=([rel], None, False))
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.get("/api/v1/relations", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert "pagination" in body

    def test_get_relation_returns_200(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)
        rel = make_relation()

        with patch("alayaos_api.routers.relations.RelationRepository") as mock_cls:
            repo = AsyncMock()
            repo.get_by_id = AsyncMock(return_value=rel)
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.get(f"/api/v1/relations/{rel.id}", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 200
        assert response.json()["data"]["relation_type"] == "member_of"

    def test_get_relation_not_found_returns_404(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)

        with patch("alayaos_api.routers.relations.RelationRepository") as mock_cls:
            repo = AsyncMock()
            repo.get_by_id = AsyncMock(return_value=None)
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.get(f"/api/v1/relations/{uuid.uuid4()}", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "resource.not_found"
