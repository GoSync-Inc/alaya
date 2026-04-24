"""Tests for resource routers: workspaces, entities, entity_types, events, predicates, api_keys."""

import hashlib
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from alayaos_api.main import create_app
from alayaos_core.models.api_key import APIKey
from alayaos_core.models.workspace import Workspace

# ─── Helpers ──────────────────────────────────────────────────────────────────

RAW_KEY = "ak_testprefix12345678901234567890"
PREFIX = RAW_KEY[:12]
KEY_HASH = hashlib.sha256(RAW_KEY.encode()).hexdigest()
WS_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


def make_api_key(scopes=None, is_bootstrap=False, revoked=False, expired=False) -> APIKey:
    return APIKey(
        id=uuid.uuid4(),
        workspace_id=WS_ID,
        name="Test Key",
        key_prefix=PREFIX,
        key_hash=KEY_HASH,
        scopes=scopes or ["read", "write", "admin"],
        revoked_at=datetime.now(UTC) if revoked else None,
        expires_at=datetime(2000, 1, 1, tzinfo=UTC) if expired else None,
        is_bootstrap=is_bootstrap,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def make_workspace(name="Test WS", slug="test-ws") -> Workspace:
    return Workspace(
        id=WS_ID,
        name=name,
        slug=slug,
        settings={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def make_app_with_mock_session(api_key: APIKey):
    """Create app with mocked session + api key lookup."""
    app = create_app()

    async def override_session():
        session = AsyncMock()
        yield session

    async def override_api_key():
        return api_key

    from alayaos_api.deps import get_api_key, get_session, get_workspace_session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_api_key] = override_api_key

    async def override_workspace_session():
        session = AsyncMock()
        yield session

    app.dependency_overrides[get_workspace_session] = override_workspace_session

    return app


# ─── Workspaces ───────────────────────────────────────────────────────────────


class TestWorkspacesRouter:
    def test_list_workspaces_returns_200(self) -> None:
        api_key = make_api_key(is_bootstrap=True)
        app = make_app_with_mock_session(api_key)

        ws = make_workspace()
        with patch("alayaos_api.routers.workspaces.WorkspaceRepository") as mock_cls:
            repo = AsyncMock()
            repo.list = AsyncMock(return_value=([ws], None, False))
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.get("/api/v1/workspaces", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert "pagination" in body

    def test_get_workspace_not_found_returns_404(self) -> None:
        api_key = make_api_key(is_bootstrap=True)
        app = make_app_with_mock_session(api_key)

        with patch("alayaos_api.routers.workspaces.WorkspaceRepository") as mock_cls:
            repo = AsyncMock()
            repo.get_by_id = AsyncMock(return_value=None)
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.get(f"/api/v1/workspaces/{uuid.uuid4()}", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "resource.not_found"

    def test_get_workspace_returns_200(self) -> None:
        api_key = make_api_key(is_bootstrap=True)
        app = make_app_with_mock_session(api_key)

        ws = make_workspace()
        with patch("alayaos_api.routers.workspaces.WorkspaceRepository") as mock_cls:
            repo = AsyncMock()
            repo.get_by_id = AsyncMock(return_value=ws)
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.get(f"/api/v1/workspaces/{WS_ID}", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 200
        assert response.json()["data"]["slug"] == "test-ws"

    def test_non_bootstrap_key_cannot_see_other_workspace(self) -> None:
        other_ws_id = uuid.uuid4()
        api_key = make_api_key(is_bootstrap=False)  # workspace_id = WS_ID
        app = make_app_with_mock_session(api_key)

        client = TestClient(app)
        response = client.get(f"/api/v1/workspaces/{other_ws_id}", headers={"X-Api-Key": RAW_KEY})
        assert response.status_code == 404

    def test_create_workspace_requires_admin_scope(self) -> None:
        api_key = make_api_key(scopes=["read", "write"])  # no admin
        app = make_app_with_mock_session(api_key)

        client = TestClient(app)
        response = client.post(
            "/api/v1/workspaces",
            json={"name": "New WS", "slug": "new-ws"},
            headers={"X-Api-Key": RAW_KEY},
        )
        assert response.status_code == 403


# ─── Entities ─────────────────────────────────────────────────────────────────


class TestEntitiesRouter:
    def _make_entity(self):
        from alayaos_core.models.entity import L1Entity

        et_id = uuid.uuid4()
        entity = L1Entity(
            id=uuid.uuid4(),
            workspace_id=WS_ID,
            entity_type_id=et_id,
            name="Alice",
            description=None,
            properties={},
            is_deleted=False,
            first_seen_at=None,
            last_seen_at=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        entity.external_ids = []
        return entity

    def test_list_entities_returns_200(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)

        entity = self._make_entity()
        with patch("alayaos_api.routers.entities.EntityRepository") as mock_cls:
            repo = AsyncMock()
            repo.list = AsyncMock(return_value=([entity], None, False))
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.get("/api/v1/entities", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 200
        assert "data" in response.json()

    def test_list_entities_reports_acl_filtered_count(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)

        entity = self._make_entity()
        with patch("alayaos_api.routers.entities.EntityRepository") as mock_cls:
            repo = AsyncMock()
            repo.list = AsyncMock(return_value=([entity], None, False))
            repo.last_filtered_count = 1
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.get("/api/v1/entities", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 200
        assert response.json()["meta"] == {"filtered_count": 1, "filter_reason": "acl_filtered"}

    def test_get_entity_not_found_returns_404(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)

        with patch("alayaos_api.routers.entities.EntityRepository") as mock_cls:
            repo = AsyncMock()
            repo.get_by_id = AsyncMock(return_value=None)
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.get(f"/api/v1/entities/{uuid.uuid4()}", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "resource.not_found"

    def test_get_entity_returns_200(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)

        entity = self._make_entity()
        with patch("alayaos_api.routers.entities.EntityRepository") as mock_cls:
            repo = AsyncMock()
            repo.get_by_id = AsyncMock(return_value=entity)
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.get(f"/api/v1/entities/{entity.id}", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 200
        assert response.json()["data"]["name"] == "Alice"

    def test_delete_entity_returns_204(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)

        entity = self._make_entity()
        entity.is_deleted = True
        with patch("alayaos_api.routers.entities.EntityRepository") as mock_cls:
            repo = AsyncMock()
            repo.update = AsyncMock(return_value=entity)
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.delete(f"/api/v1/entities/{entity.id}", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 204

    def test_list_entities_invalid_cursor_returns_400(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)

        client = TestClient(app)
        response = client.get("/api/v1/entities?cursor=not_valid_cursor", headers={"X-Api-Key": RAW_KEY})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "validation.invalid_cursor"


# ─── Events ───────────────────────────────────────────────────────────────────


class TestEventsRouter:
    def _make_event(self):
        from alayaos_core.models.event import L0Event

        return L0Event(
            id=uuid.uuid4(),
            workspace_id=WS_ID,
            source_type="slack",
            source_id="msg-123",
            content={"text": "hello"},
            content_hash=None,
            event_metadata={},
            processed_at=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    def test_list_events_returns_200(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)

        event = self._make_event()
        with patch("alayaos_api.routers.events.EventRepository") as mock_cls:
            repo = AsyncMock()
            repo.list = AsyncMock(return_value=([event], None, False))
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.get("/api/v1/events", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 200
        assert "data" in response.json()

    def test_list_events_reports_acl_filtered_count(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)

        event = self._make_event()
        with patch("alayaos_api.routers.events.EventRepository") as mock_cls:
            repo = AsyncMock()
            repo.list = AsyncMock(return_value=([event], None, False))
            repo.last_filtered_count = 1
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.get("/api/v1/events", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 200
        assert response.json()["meta"] == {"filtered_count": 1, "filter_reason": "acl_filtered"}

    def test_create_event_idempotent_returns_201(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)

        event = self._make_event()
        with patch("alayaos_api.routers.events.EventRepository") as mock_cls:
            repo = AsyncMock()
            repo.create_or_update = AsyncMock(return_value=(event, True))
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.post(
                "/api/v1/events",
                json={"source_type": "slack", "source_id": "msg-123", "content": {"text": "hello"}},
                headers={"X-Api-Key": RAW_KEY},
            )

        assert response.status_code == 201
        assert response.json()["data"]["source_id"] == "msg-123"

    def test_get_event_not_found_returns_404(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)

        with patch("alayaos_api.routers.events.EventRepository") as mock_cls:
            repo = AsyncMock()
            repo.get_by_id = AsyncMock(return_value=None)
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.get(f"/api/v1/events/{uuid.uuid4()}", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "resource.not_found"


# ─── API Keys ─────────────────────────────────────────────────────────────────


class TestAPIKeysRouter:
    def _make_api_key_model(self) -> APIKey:
        return make_api_key()

    def test_list_api_keys_never_returns_raw_key(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)

        with patch("alayaos_api.routers.api_keys.APIKeyRepository") as mock_cls:
            repo = AsyncMock()
            repo.list = AsyncMock(return_value=([api_key], None, False))
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.get("/api/v1/api-keys", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 200
        data = response.json()["data"]
        for item in data:
            assert "raw_key" not in item
            assert "key_hash" not in item

    def test_revoke_api_key_returns_204(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)

        with patch("alayaos_api.routers.api_keys.APIKeyRepository") as mock_cls:
            repo = AsyncMock()
            revoked = make_api_key()
            revoked.revoked_at = datetime.now(UTC)
            repo.revoke = AsyncMock(return_value=revoked)
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.delete(f"/api/v1/api-keys/{PREFIX}", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 204

    def test_revoke_api_key_not_found_returns_404(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)

        with patch("alayaos_api.routers.api_keys.APIKeyRepository") as mock_cls:
            repo = AsyncMock()
            repo.revoke = AsyncMock(return_value=None)
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.delete("/api/v1/api-keys/ak_notexist", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "resource.not_found"


# ─── Predicates ───────────────────────────────────────────────────────────────


class TestPredicatesRouter:
    def _make_predicate(self):
        from alayaos_core.models.predicate import PredicateDefinition

        return PredicateDefinition(
            id=uuid.uuid4(),
            workspace_id=WS_ID,
            slug="owner",
            display_name="Owner",
            description=None,
            value_type="entity_ref",
            domain_types=None,
            cardinality="one",
            inverse_slug=None,
            is_core=True,
            schema_version=1,
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    def test_list_predicates_returns_200(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)

        predicate = self._make_predicate()
        with patch("alayaos_api.routers.predicates.PredicateRepository") as mock_cls:
            repo = AsyncMock()
            repo.list = AsyncMock(return_value=([predicate], None, False))
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.get("/api/v1/predicates", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 200
        assert "data" in response.json()

    def test_get_predicate_not_found_returns_404(self) -> None:
        api_key = make_api_key()
        app = make_app_with_mock_session(api_key)

        with patch("alayaos_api.routers.predicates.PredicateRepository") as mock_cls:
            repo = AsyncMock()
            repo.get_by_id = AsyncMock(return_value=None)
            mock_cls.return_value = repo

            client = TestClient(app)
            response = client.get(f"/api/v1/predicates/{uuid.uuid4()}", headers={"X-Api-Key": RAW_KEY})

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "resource.not_found"
