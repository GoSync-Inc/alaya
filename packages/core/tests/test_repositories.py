"""Tests for all repositories using mocked AsyncSession."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from alayaos_core.models.api_key import APIKey
from alayaos_core.models.entity import L1Entity
from alayaos_core.models.entity_type import EntityTypeDefinition
from alayaos_core.models.event import L0Event
from alayaos_core.models.predicate import PredicateDefinition
from alayaos_core.models.workspace import Workspace


def make_session() -> AsyncMock:
    """Create a mock async session."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


def make_result(obj) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    result.scalars.return_value.all.return_value = [obj] if obj else []
    return result


def make_scalar_result(items: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result


# ─── WorkspaceRepository ──────────────────────────────────────────────────────


class TestWorkspaceRepository:
    @pytest.mark.asyncio
    async def test_create_workspace(self) -> None:
        from alayaos_core.repositories.workspace import WorkspaceRepository

        session = make_session()
        repo = WorkspaceRepository(session)
        ws = await repo.create(name="Test WS", slug="test-ws")
        session.add.assert_called_once()
        session.flush.assert_called_once()
        assert ws.name == "Test WS"
        assert ws.slug == "test-ws"

    @pytest.mark.asyncio
    async def test_create_workspace_default_settings(self) -> None:
        from alayaos_core.repositories.workspace import WorkspaceRepository

        session = make_session()
        repo = WorkspaceRepository(session)
        ws = await repo.create(name="WS", slug="ws")
        assert ws.settings == {}

    @pytest.mark.asyncio
    async def test_get_by_id_found(self) -> None:
        from alayaos_core.repositories.workspace import WorkspaceRepository

        ws = Workspace(id=uuid.uuid4(), name="WS", slug="ws", settings={})
        session = make_session()
        session.execute.return_value = make_result(ws)
        repo = WorkspaceRepository(session)
        result = await repo.get_by_id(ws.id)
        assert result is ws

    @pytest.mark.asyncio
    async def test_get_by_id_missing(self) -> None:
        from alayaos_core.repositories.workspace import WorkspaceRepository

        session = make_session()
        session.execute.return_value = make_result(None)
        repo = WorkspaceRepository(session)
        result = await repo.get_by_id(uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_slug_found(self) -> None:
        from alayaos_core.repositories.workspace import WorkspaceRepository

        ws = Workspace(id=uuid.uuid4(), name="WS", slug="my-slug", settings={})
        session = make_session()
        session.execute.return_value = make_result(ws)
        repo = WorkspaceRepository(session)
        result = await repo.get_by_slug("my-slug")
        assert result is ws

    @pytest.mark.asyncio
    async def test_get_by_slug_missing(self) -> None:
        from alayaos_core.repositories.workspace import WorkspaceRepository

        session = make_session()
        session.execute.return_value = make_result(None)
        repo = WorkspaceRepository(session)
        result = await repo.get_by_slug("nope")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_workspace(self) -> None:
        from alayaos_core.repositories.workspace import WorkspaceRepository

        ws = Workspace(id=uuid.uuid4(), name="Old", slug="old", settings={})
        session = make_session()
        session.execute.return_value = make_result(ws)
        repo = WorkspaceRepository(session)
        result = await repo.update(ws.id, name="New")
        assert result is not None
        assert result.name == "New"
        session.flush.assert_called()

    @pytest.mark.asyncio
    async def test_update_missing_returns_none(self) -> None:
        from alayaos_core.repositories.workspace import WorkspaceRepository

        session = make_session()
        session.execute.return_value = make_result(None)
        repo = WorkspaceRepository(session)
        result = await repo.update(uuid.uuid4(), name="Ghost")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_empty(self) -> None:
        from alayaos_core.repositories.workspace import WorkspaceRepository

        session = make_session()
        session.execute.return_value = make_scalar_result([])
        repo = WorkspaceRepository(session)
        items, cursor, has_more = await repo.list()
        assert items == []
        assert cursor is None
        assert has_more is False

    @pytest.mark.asyncio
    async def test_list_returns_items(self) -> None:
        from alayaos_core.repositories.workspace import WorkspaceRepository

        now = datetime.now(UTC)
        ws1 = Workspace(id=uuid.uuid4(), name="A", slug="a", settings={})
        ws1.created_at = now
        ws2 = Workspace(id=uuid.uuid4(), name="B", slug="b", settings={})
        ws2.created_at = now
        session = make_session()
        session.execute.return_value = make_scalar_result([ws1, ws2])
        repo = WorkspaceRepository(session)
        items, cursor, has_more = await repo.list(limit=10)
        assert len(items) == 2
        assert has_more is False
        assert cursor is None

    @pytest.mark.asyncio
    async def test_list_has_more_when_extra_item(self) -> None:
        """list returns limit items + next_cursor when has_more."""
        from alayaos_core.repositories.workspace import WorkspaceRepository

        now = datetime.now(UTC)
        # simulate fetch limit+1 = 4 items for limit=3
        workspaces = []
        for i in range(4):
            ws = Workspace(id=uuid.uuid4(), name=f"WS{i}", slug=f"ws{i}", settings={})
            ws.created_at = now
            workspaces.append(ws)
        session = make_session()
        session.execute.return_value = make_scalar_result(workspaces)
        repo = WorkspaceRepository(session)
        items, cursor, has_more = await repo.list(limit=3)
        assert len(items) == 3
        assert has_more is True
        assert cursor is not None


# ─── EventRepository ─────────────────────────────────────────────────────────


class TestEventRepository:
    @pytest.mark.asyncio
    async def test_create_event(self) -> None:
        from alayaos_core.repositories.event import EventRepository

        session = make_session()
        repo = EventRepository(session)
        ev = await repo.create(
            workspace_id=uuid.uuid4(),
            source_type="slack",
            source_id="C123",
            content={"text": "hello"},
        )
        session.add.assert_called_once()
        session.flush.assert_called_once()
        assert ev.source_type == "slack"
        assert ev.source_id == "C123"

    @pytest.mark.asyncio
    async def test_create_event_with_metadata(self) -> None:
        from alayaos_core.repositories.event import EventRepository

        session = make_session()
        repo = EventRepository(session)
        ev = await repo.create(
            workspace_id=uuid.uuid4(),
            source_type="gh",
            source_id="PR1",
            content={"title": "Fix bug"},
            metadata={"author": "alice"},
        )
        assert ev.event_metadata == {"author": "alice"}

    @pytest.mark.asyncio
    async def test_get_by_id_event(self) -> None:
        from alayaos_core.repositories.event import EventRepository

        ev = L0Event(
            id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            source_type="gh",
            source_id="PR1",
            content={},
            event_metadata={},
        )
        session = make_session()
        session.execute.return_value = make_result(ev)
        repo = EventRepository(session)
        result = await repo.get_by_id(ev.id)
        assert result is ev

    @pytest.mark.asyncio
    async def test_create_or_update_creates_new(self) -> None:
        from alayaos_core.repositories.event import EventRepository

        session = make_session()
        session.execute.return_value = make_result(None)
        repo = EventRepository(session)
        ev, created = await repo.create_or_update(
            workspace_id=uuid.uuid4(),
            source_type="slack",
            source_id="MSG1",
            content={"text": "hi"},
            content_hash="hash1",
        )
        assert created is True
        assert ev.content_hash == "hash1"

    @pytest.mark.asyncio
    async def test_create_or_update_skips_if_same_hash(self) -> None:
        from alayaos_core.repositories.event import EventRepository

        existing = L0Event(
            id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            source_type="slack",
            source_id="MSG2",
            content={"text": "original"},
            content_hash="same_hash",
            event_metadata={},
        )
        session = make_session()
        session.execute.return_value = make_result(existing)
        repo = EventRepository(session)
        ev, created = await repo.create_or_update(
            workspace_id=existing.workspace_id,
            source_type="slack",
            source_id="MSG2",
            content={"text": "changed"},
            content_hash="same_hash",
        )
        assert created is False
        assert ev is existing
        # Content NOT changed
        assert ev.content == {"text": "original"}

    @pytest.mark.asyncio
    async def test_create_or_update_updates_if_hash_changed(self) -> None:
        from alayaos_core.repositories.event import EventRepository

        existing = L0Event(
            id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            source_type="slack",
            source_id="MSG3",
            content={"text": "v1"},
            content_hash="hash_v1",
            event_metadata={},
        )
        session = make_session()
        session.execute.return_value = make_result(existing)
        repo = EventRepository(session)
        ev, created = await repo.create_or_update(
            workspace_id=existing.workspace_id,
            source_type="slack",
            source_id="MSG3",
            content={"text": "v2"},
            content_hash="hash_v2",
        )
        assert created is False
        assert ev.content == {"text": "v2"}
        assert ev.content_hash == "hash_v2"
        session.flush.assert_called_once()


# ─── EntityTypeRepository ─────────────────────────────────────────────────────


class TestEntityTypeRepository:
    @pytest.mark.asyncio
    async def test_create_entity_type(self) -> None:
        from alayaos_core.repositories.entity_type import EntityTypeRepository

        session = make_session()
        repo = EntityTypeRepository(session)
        et = await repo.create(
            workspace_id=uuid.uuid4(),
            slug="person",
            display_name="Person",
        )
        session.add.assert_called_once()
        session.flush.assert_called_once()
        assert et.slug == "person"
        assert et.display_name == "Person"

    @pytest.mark.asyncio
    async def test_get_by_slug(self) -> None:
        from alayaos_core.repositories.entity_type import EntityTypeRepository

        ws_id = uuid.uuid4()
        et = EntityTypeDefinition(id=uuid.uuid4(), workspace_id=ws_id, slug="project", display_name="Project")
        session = make_session()
        session.execute.return_value = make_result(et)
        repo = EntityTypeRepository(session)
        result = await repo.get_by_slug(ws_id, "project")
        assert result is et

    @pytest.mark.asyncio
    async def test_upsert_core_creates_when_missing(self) -> None:
        from alayaos_core.repositories.entity_type import EntityTypeRepository

        session = make_session()
        session.execute.return_value = make_result(None)
        repo = EntityTypeRepository(session)
        et = await repo.upsert_core(workspace_id=uuid.uuid4(), slug="team", display_name="Team")
        assert et.is_core is True
        assert et.slug == "team"
        session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert_core_does_not_overwrite(self) -> None:
        from alayaos_core.repositories.entity_type import EntityTypeRepository

        ws_id = uuid.uuid4()
        original = EntityTypeDefinition(
            id=uuid.uuid4(), workspace_id=ws_id, slug="team", display_name="Team", is_core=True
        )
        session = make_session()
        session.execute.return_value = make_result(original)
        repo = EntityTypeRepository(session)
        result = await repo.upsert_core(workspace_id=ws_id, slug="team", display_name="Custom Team")
        assert result is original
        session.add.assert_not_called()


# ─── PredicateRepository ─────────────────────────────────────────────────────


class TestPredicateRepository:
    @pytest.mark.asyncio
    async def test_upsert_core_creates(self) -> None:
        from alayaos_core.repositories.predicate import PredicateRepository

        session = make_session()
        session.execute.return_value = make_result(None)
        repo = PredicateRepository(session)
        pred = await repo.upsert_core(workspace_id=uuid.uuid4(), slug="status", display_name="Status")
        assert pred.is_core is True
        assert pred.slug == "status"
        session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert_core_does_not_overwrite(self) -> None:
        from alayaos_core.repositories.predicate import PredicateRepository

        ws_id = uuid.uuid4()
        original = PredicateDefinition(
            id=uuid.uuid4(), workspace_id=ws_id, slug="status", display_name="Status", value_type="text", is_core=True
        )
        session = make_session()
        session.execute.return_value = make_result(original)
        repo = PredicateRepository(session)
        result = await repo.upsert_core(workspace_id=ws_id, slug="status", display_name="Custom", value_type="number")
        assert result is original
        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_by_slug(self) -> None:
        from alayaos_core.repositories.predicate import PredicateRepository

        ws_id = uuid.uuid4()
        pred = PredicateDefinition(
            id=uuid.uuid4(), workspace_id=ws_id, slug="owner", display_name="Owner", value_type="entity_ref"
        )
        session = make_session()
        session.execute.return_value = make_result(pred)
        repo = PredicateRepository(session)
        result = await repo.get_by_slug(ws_id, "owner")
        assert result is pred

    @pytest.mark.asyncio
    async def test_list_predicates(self) -> None:
        from alayaos_core.repositories.predicate import PredicateRepository

        ws_id = uuid.uuid4()
        now = datetime.now(UTC)
        preds = []
        for slug in ["p1", "p2"]:
            p = PredicateDefinition(
                id=uuid.uuid4(), workspace_id=ws_id, slug=slug, display_name=slug.upper(), value_type="text"
            )
            p.created_at = now
            preds.append(p)
        session = make_session()
        session.execute.return_value = make_scalar_result(preds)
        repo = PredicateRepository(session)
        items, _, _ = await repo.list()
        assert len(items) == 2


# ─── EntityRepository ─────────────────────────────────────────────────────────


class TestEntityRepository:
    @pytest.mark.asyncio
    async def test_create_entity(self) -> None:
        from alayaos_core.repositories.entity import EntityRepository

        session = make_session()
        repo = EntityRepository(session)
        entity = await repo.create(
            workspace_id=uuid.uuid4(),
            entity_type_id=uuid.uuid4(),
            name="Alice",
        )
        session.add.assert_called_once()
        session.flush.assert_called_once()
        assert entity.name == "Alice"

    @pytest.mark.asyncio
    async def test_update_entity(self) -> None:
        from alayaos_core.repositories.entity import EntityRepository

        ws_id = uuid.uuid4()
        entity = L1Entity(
            id=uuid.uuid4(),
            workspace_id=ws_id,
            entity_type_id=uuid.uuid4(),
            name="Charlie",
            properties={},
            is_deleted=False,
        )
        session = make_session()
        session.execute.return_value = make_result(entity)
        repo = EntityRepository(session)
        updated = await repo.update(entity.id, name="Charles", description="updated")
        assert updated is not None
        assert updated.name == "Charles"
        assert updated.description == "updated"

    @pytest.mark.asyncio
    async def test_update_missing_returns_none(self) -> None:
        from alayaos_core.repositories.entity import EntityRepository

        session = make_session()
        session.execute.return_value = make_result(None)
        repo = EntityRepository(session)
        result = await repo.update(uuid.uuid4(), name="Ghost")
        assert result is None

    @pytest.mark.asyncio
    async def test_soft_delete_flag(self) -> None:
        """update with is_deleted=True sets the flag."""
        from alayaos_core.repositories.entity import EntityRepository

        ws_id = uuid.uuid4()
        entity = L1Entity(
            id=uuid.uuid4(),
            workspace_id=ws_id,
            entity_type_id=uuid.uuid4(),
            name="Dave",
            properties={},
            is_deleted=False,
        )
        session = make_session()
        session.execute.return_value = make_result(entity)
        repo = EntityRepository(session)
        updated = await repo.update(entity.id, is_deleted=True)
        assert updated is not None
        assert updated.is_deleted is True

    @pytest.mark.asyncio
    async def test_create_external_id(self) -> None:
        from alayaos_core.repositories.entity import EntityRepository

        session = make_session()
        repo = EntityRepository(session)
        ws_id = uuid.uuid4()
        entity_id = uuid.uuid4()
        ext = await repo.create_external_id(ws_id, entity_id, "slack", "U123")
        session.add.assert_called_once()
        session.flush.assert_called_once()
        assert ext.source_type == "slack"
        assert ext.external_id == "U123"
        assert ext.entity_id == entity_id

    @pytest.mark.asyncio
    async def test_get_by_external_id(self) -> None:
        from alayaos_core.repositories.entity import EntityRepository

        ws_id = uuid.uuid4()
        entity = L1Entity(
            id=uuid.uuid4(),
            workspace_id=ws_id,
            entity_type_id=uuid.uuid4(),
            name="Eve",
            properties={},
            is_deleted=False,
        )
        session = make_session()
        session.execute.return_value = make_result(entity)
        repo = EntityRepository(session)
        result = await repo.get_by_external_id(ws_id, "slack", "U123")
        assert result is entity


# ─── APIKeyRepository ─────────────────────────────────────────────────────────


class TestAPIKeyRepository:
    @pytest.mark.asyncio
    async def test_create_api_key(self) -> None:
        from alayaos_core.repositories.api_key import APIKeyRepository

        session = make_session()
        repo = APIKeyRepository(session)
        key = await repo.create(
            workspace_id=uuid.uuid4(),
            name="My Key",
            key_prefix="ak_123456789012",
            key_hash="deadbeef",
        )
        session.add.assert_called_once()
        session.flush.assert_called_once()
        assert key.key_prefix == "ak_123456789012"
        assert key.key_hash == "deadbeef"

    @pytest.mark.asyncio
    async def test_create_api_key_default_scopes(self) -> None:
        from alayaos_core.repositories.api_key import APIKeyRepository

        session = make_session()
        repo = APIKeyRepository(session)
        key = await repo.create(
            workspace_id=uuid.uuid4(),
            name="Key",
            key_prefix="ak_aabbccddeeff",
            key_hash="abc",
        )
        assert key.scopes == ["read", "write"]

    @pytest.mark.asyncio
    async def test_get_by_prefix_found(self) -> None:
        from alayaos_core.repositories.api_key import APIKeyRepository

        ws_id = uuid.uuid4()
        api_key = APIKey(
            id=uuid.uuid4(),
            workspace_id=ws_id,
            name="Key",
            key_prefix="ak_aabbccddeeff",
            key_hash="abc",
            scopes=["read"],
        )
        session = make_session()
        session.execute.return_value = make_result(api_key)
        repo = APIKeyRepository(session)
        result = await repo.get_by_prefix("ak_aabbccddeeff")
        assert result is api_key

    @pytest.mark.asyncio
    async def test_get_by_prefix_missing(self) -> None:
        from alayaos_core.repositories.api_key import APIKeyRepository

        session = make_session()
        session.execute.return_value = make_result(None)
        repo = APIKeyRepository(session)
        result = await repo.get_by_prefix("ak_doesntexist")
        assert result is None

    @pytest.mark.asyncio
    async def test_revoke_sets_revoked_at(self) -> None:
        from alayaos_core.repositories.api_key import APIKeyRepository

        ws_id = uuid.uuid4()
        api_key = APIKey(
            id=uuid.uuid4(),
            workspace_id=ws_id,
            name="Key",
            key_prefix="ak_revokeme1234",
            key_hash="xyz",
            scopes=["read"],
            revoked_at=None,
        )
        session = make_session()
        session.execute.return_value = make_result(api_key)
        repo = APIKeyRepository(session)
        revoked = await repo.revoke("ak_revokeme1234", ws_id)
        assert revoked is not None
        assert revoked.revoked_at is not None
        session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_revoke_missing_returns_none(self) -> None:
        from alayaos_core.repositories.api_key import APIKeyRepository

        session = make_session()
        session.execute.return_value = make_result(None)
        repo = APIKeyRepository(session)
        result = await repo.revoke("ak_nonexistent", uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_list_api_keys(self) -> None:
        from alayaos_core.repositories.api_key import APIKeyRepository

        ws_id = uuid.uuid4()
        now = datetime.now(UTC)
        keys = []
        for i, prefix in enumerate(["ak_111111111111", "ak_222222222222"]):
            k = APIKey(
                id=uuid.uuid4(),
                workspace_id=ws_id,
                name=f"K{i}",
                key_prefix=prefix,
                key_hash=f"h{i}",
                scopes=["read"],
            )
            k.created_at = now
            keys.append(k)
        session = make_session()
        session.execute.return_value = make_scalar_result(keys)
        repo = APIKeyRepository(session)
        items, _, has_more = await repo.list(workspace_id=ws_id)
        assert len(items) == 2
        assert has_more is False
