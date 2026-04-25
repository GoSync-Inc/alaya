"""Cross-workspace isolation tests for IntegratorEngine.

Verify that IntegratorEngine for workspace A never touches workspace B entities.
Uses mock repos and mock Redis — no real database required.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alayaos_core.extraction.integrator.engine import IntegratorEngine
from alayaos_core.extraction.integrator.schemas import IntegratorRunResult
from alayaos_core.llm.fake import FakeLLMAdapter


def _make_settings():
    settings = MagicMock()
    settings.INTEGRATOR_DEDUP_THRESHOLD = 0.85
    settings.INTEGRATOR_DEDUP_AMBIGUOUS_LOW = 0.6
    settings.INTEGRATOR_BATCH_SIZE = 10
    settings.INTEGRATOR_WINDOW_HOURS = 48
    return settings


def _make_session() -> AsyncMock:
    """AsyncMock session with begin_nested properly configured as an async CM."""
    session = AsyncMock()
    nested_cm = MagicMock()
    nested_cm.__aenter__ = AsyncMock(return_value=None)
    nested_cm.__aexit__ = AsyncMock(return_value=False)
    session.begin_nested = MagicMock(return_value=nested_cm)
    return session


def _make_entity(entity_id: uuid.UUID, name: str, workspace_id: uuid.UUID) -> MagicMock:
    entity = MagicMock()
    entity.id = entity_id
    entity.name = name
    entity.workspace_id = workspace_id
    entity.is_deleted = False
    entity.aliases = []
    entity.properties = {}
    entity.entity_type = MagicMock()
    entity.entity_type.slug = "person"
    return entity


def _make_redis(workspace_id: uuid.UUID, entity_ids: list[uuid.UUID] | None = None) -> AsyncMock:
    """Return a mock Redis that returns entity_ids from dirty_set:{workspace_id}."""
    redis = AsyncMock()
    # RENAME raises no-such-key error (dirty set empty — common in unit tests)
    redis.rename = AsyncMock(side_effect=Exception("ERR no such key"))
    redis.smembers = AsyncMock(return_value=set())
    redis.delete = AsyncMock()
    redis.get = AsyncMock(return_value=None)

    # Lock acquisition
    redis.set = AsyncMock(return_value=True)  # acquire lock
    redis.eval = AsyncMock(return_value=1)  # release lock
    redis.exists = AsyncMock(return_value=False)
    return redis


@pytest.mark.asyncio
async def test_integrator_runs_in_workspace_isolation():
    """Integrator for workspace A never sees workspace B entities.

    Verify: entity_repo.list_recent is called with workspace_id A,
    and workspace B entity IDs never appear in the call args.
    """
    ws_a = uuid.uuid4()
    ws_b = uuid.uuid4()

    entity_a = _make_entity(uuid.uuid4(), "Alice", ws_a)
    entity_b = _make_entity(uuid.uuid4(), "Bob", ws_b)  # must NOT appear in ws_a run

    # Workspace A entity repo only returns workspace A entities
    entity_repo_a = AsyncMock()
    entity_repo_a.list_recent = AsyncMock(return_value=[entity_a])
    entity_repo_a.get_by_id = AsyncMock(return_value=entity_a)

    claim_repo_a = AsyncMock()
    claim_repo_a.list = AsyncMock(return_value=([], None, False))

    relation_repo_a = AsyncMock()
    relation_repo_a.list = AsyncMock(return_value=([], None, False))

    entity_cache = AsyncMock()
    entity_cache.set_entity = AsyncMock()

    redis = _make_redis(ws_a)
    settings = _make_settings()
    llm = FakeLLMAdapter()
    session = _make_session()

    engine = IntegratorEngine(
        llm=llm,
        entity_repo=entity_repo_a,
        claim_repo=claim_repo_a,
        relation_repo=relation_repo_a,
        entity_cache=entity_cache,
        redis=redis,
        settings=settings,
    )

    with (
        patch("alayaos_core.extraction.writer.acquire_workspace_lock", new=AsyncMock(return_value="token")),
        patch("alayaos_core.extraction.writer.release_workspace_lock", new=AsyncMock()),
    ):
        result = await engine.run(ws_a, session)

    assert isinstance(result, IntegratorRunResult)

    # Verify list_recent was called with workspace A
    # Note: called at least twice — initial load and post-convergence reload (Fix 3)
    assert entity_repo_a.list_recent.call_count >= 1
    call_args = entity_repo_a.list_recent.call_args
    called_ws_id = call_args[0][0] if call_args[0] else call_args[1].get("workspace_id")
    assert called_ws_id == ws_a, f"Expected workspace {ws_a}, got {called_ws_id}"

    # Workspace B entity ID should never appear in get_by_id calls
    all_calls = entity_repo_a.get_by_id.call_args_list
    called_entity_ids = [c[0][0] if c[0] else c[1].get("entity_id") for c in all_calls]
    assert entity_b.id not in called_entity_ids, "Workspace B entity leaked into workspace A run"


@pytest.mark.asyncio
async def test_integrator_dirty_set_key_scoped_to_workspace():
    """dirty-set Redis key must be scoped to workspace: dirty_set:{workspace_id}."""
    ws_a = uuid.uuid4()
    ws_b = uuid.uuid4()

    entity_repo = AsyncMock()
    entity_repo.list_recent = AsyncMock(return_value=[])

    claim_repo = AsyncMock()
    relation_repo = AsyncMock()
    entity_cache = AsyncMock()
    session = _make_session()
    settings = _make_settings()
    llm = FakeLLMAdapter()

    rename_calls: list[str] = []

    async def mock_rename(src, dst):
        rename_calls.append(src)
        raise Exception("ERR no such key")

    redis = AsyncMock()
    redis.rename = mock_rename
    redis.smembers = AsyncMock(return_value=set())
    redis.delete = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.eval = AsyncMock(return_value=1)

    engine = IntegratorEngine(
        llm=llm,
        entity_repo=entity_repo,
        claim_repo=claim_repo,
        relation_repo=relation_repo,
        entity_cache=entity_cache,
        redis=redis,
        settings=settings,
    )

    with (
        patch("alayaos_core.extraction.writer.acquire_workspace_lock", new=AsyncMock(return_value="token")),
        patch("alayaos_core.extraction.writer.release_workspace_lock", new=AsyncMock()),
    ):
        await engine.run(ws_a, session)

    # Verify dirty-set key is scoped to workspace A
    assert rename_calls, "Redis RENAME should have been called"
    dirty_key = rename_calls[0]
    assert str(ws_a) in dirty_key, f"Expected workspace A in key, got: {dirty_key}"
    assert str(ws_b) not in dirty_key, f"Workspace B leaked into key: {dirty_key}"


@pytest.mark.asyncio
async def test_integrator_two_workspaces_independent():
    """Running integrator for WS-A and WS-B independently does not cross-contaminate."""
    ws_a = uuid.uuid4()
    ws_b = uuid.uuid4()

    entity_a = _make_entity(uuid.uuid4(), "Alice", ws_a)
    entity_b = _make_entity(uuid.uuid4(), "Bob", ws_b)

    entity_repo_a = AsyncMock()
    entity_repo_a.list_recent = AsyncMock(return_value=[entity_a])
    entity_repo_a.get_by_id = AsyncMock(return_value=entity_a)

    entity_repo_b = AsyncMock()
    entity_repo_b.list_recent = AsyncMock(return_value=[entity_b])
    entity_repo_b.get_by_id = AsyncMock(return_value=entity_b)

    def _make_engine(entity_repo, workspace_id):
        claim_repo = AsyncMock()
        claim_repo.list = AsyncMock(return_value=([], None, False))
        relation_repo = AsyncMock()
        relation_repo.list = AsyncMock(return_value=([], None, False))
        entity_cache = AsyncMock()
        entity_cache.set_entity = AsyncMock()
        redis = _make_redis(workspace_id)
        settings = _make_settings()
        return IntegratorEngine(
            llm=FakeLLMAdapter(),
            entity_repo=entity_repo,
            claim_repo=claim_repo,
            relation_repo=relation_repo,
            entity_cache=entity_cache,
            redis=redis,
            settings=settings,
        )

    engine_a = _make_engine(entity_repo_a, ws_a)
    engine_b = _make_engine(entity_repo_b, ws_b)

    session = _make_session()

    with (
        patch("alayaos_core.extraction.writer.acquire_workspace_lock", new=AsyncMock(return_value="token")),
        patch("alayaos_core.extraction.writer.release_workspace_lock", new=AsyncMock()),
    ):
        result_a = await engine_a.run(ws_a, session)
        result_b = await engine_b.run(ws_b, session)

    assert isinstance(result_a, IntegratorRunResult)
    assert isinstance(result_b, IntegratorRunResult)

    # Verify repo A only called with workspace A entities
    a_get_ids = [c[0][0] for c in entity_repo_a.get_by_id.call_args_list if c[0]]
    assert entity_b.id not in a_get_ids, "WS-B entity appeared in WS-A engine"

    # Verify repo B only called with workspace B entities
    b_get_ids = [c[0][0] for c in entity_repo_b.get_by_id.call_args_list if c[0]]
    assert entity_a.id not in b_get_ids, "WS-A entity appeared in WS-B engine"
