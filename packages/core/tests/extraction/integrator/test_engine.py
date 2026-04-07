"""Tests for IntegratorEngine."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from alayaos_core.extraction.integrator.schemas import IntegratorRunResult


def _make_redis_mock(dirty_ids: list[str] | None = None):
    """Create a mock Redis with dirty-set behaviour."""
    redis_mock = AsyncMock()
    # rename — atomic dirty-set drain
    redis_mock.rename = AsyncMock(return_value=True)
    # smembers — returns set of entity ID strings
    members = {str(i).encode() for i in (dirty_ids or [])}
    redis_mock.smembers = AsyncMock(return_value=members)
    redis_mock.delete = AsyncMock(return_value=1)

    # Lock methods
    redis_mock.set = AsyncMock(return_value=True)  # lock acquire
    redis_mock.eval = AsyncMock(return_value=1)  # lock release
    return redis_mock


def _make_settings(workspace_id=None):
    settings = MagicMock()
    settings.INTEGRATOR_BATCH_SIZE = 5
    settings.INTEGRATOR_WINDOW_HOURS = 48
    settings.INTEGRATOR_DEDUP_THRESHOLD = 0.85
    settings.INTEGRATOR_DEDUP_AMBIGUOUS_LOW = 0.70
    settings.INTEGRATOR_MODEL = "claude-test"
    return settings


@pytest.mark.asyncio
async def test_engine_returns_skipped_when_locked():
    """Engine returns status=skipped when lock cannot be acquired."""
    from alayaos_core.extraction.integrator.engine import IntegratorEngine

    redis_mock = _make_redis_mock()
    redis_mock.set = AsyncMock(return_value=None)  # lock NOT acquired

    engine = IntegratorEngine(
        llm=MagicMock(),
        entity_repo=AsyncMock(),
        claim_repo=AsyncMock(),
        relation_repo=AsyncMock(),
        entity_cache=AsyncMock(),
        redis=redis_mock,
        settings=_make_settings(),
    )
    ws_id = uuid.uuid4()
    session = AsyncMock()
    result = await engine.run(ws_id, session)
    assert result.status == "skipped"
    assert result.reason == "locked"


@pytest.mark.asyncio
async def test_engine_drains_dirty_set_via_rename():
    """Engine uses RENAME to atomically drain the dirty-set."""
    from alayaos_core.extraction.integrator.engine import IntegratorEngine

    ws_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    redis_mock = _make_redis_mock(dirty_ids=[str(entity_id)])

    entity_repo = AsyncMock()
    entity_repo.list_recent = AsyncMock(return_value=[])
    entity_repo.get_by_id = AsyncMock(return_value=None)

    claim_repo = AsyncMock()
    claim_repo.list = AsyncMock(return_value=([], None, False))

    relation_repo = AsyncMock()
    relation_repo.list = AsyncMock(return_value=([], None, False))

    entity_cache = AsyncMock()
    entity_cache.warm = AsyncMock()

    engine = IntegratorEngine(
        llm=MagicMock(),
        entity_repo=entity_repo,
        claim_repo=claim_repo,
        relation_repo=relation_repo,
        entity_cache=entity_cache,
        redis=redis_mock,
        settings=_make_settings(),
    )
    session = AsyncMock()
    await engine.run(ws_id, session)

    # RENAME was called to atomically drain dirty-set
    redis_mock.rename.assert_called_once()
    rename_args = redis_mock.rename.call_args.args
    assert f"dirty_set:{ws_id}" in rename_args[0]
    assert ":processing" in rename_args[1]


@pytest.mark.asyncio
async def test_engine_loads_48h_window():
    """Engine calls list_recent with the configured window hours."""
    from alayaos_core.extraction.integrator.engine import IntegratorEngine

    ws_id = uuid.uuid4()
    redis_mock = _make_redis_mock()

    entity_repo = AsyncMock()
    entity_repo.list_recent = AsyncMock(return_value=[])
    entity_repo.get_by_id = AsyncMock(return_value=None)

    claim_repo = AsyncMock()
    claim_repo.list = AsyncMock(return_value=([], None, False))

    relation_repo = AsyncMock()
    relation_repo.list = AsyncMock(return_value=([], None, False))

    entity_cache = AsyncMock()
    entity_cache.warm = AsyncMock()

    settings = _make_settings()
    settings.INTEGRATOR_WINDOW_HOURS = 48

    engine = IntegratorEngine(
        llm=MagicMock(),
        entity_repo=entity_repo,
        claim_repo=claim_repo,
        relation_repo=relation_repo,
        entity_cache=entity_cache,
        redis=redis_mock,
        settings=settings,
    )
    session = AsyncMock()
    await engine.run(ws_id, session)

    entity_repo.list_recent.assert_called_once_with(ws_id, hours=48)


@pytest.mark.asyncio
async def test_engine_result_has_counters():
    """Engine returns IntegratorRunResult with counter fields."""
    from alayaos_core.extraction.integrator.engine import IntegratorEngine

    ws_id = uuid.uuid4()
    redis_mock = _make_redis_mock()

    entity_repo = AsyncMock()
    entity_repo.list_recent = AsyncMock(return_value=[])
    entity_repo.get_by_id = AsyncMock(return_value=None)

    claim_repo = AsyncMock()
    claim_repo.list = AsyncMock(return_value=([], None, False))

    relation_repo = AsyncMock()
    relation_repo.list = AsyncMock(return_value=([], None, False))

    entity_cache = AsyncMock()
    entity_cache.warm = AsyncMock()

    engine = IntegratorEngine(
        llm=MagicMock(),
        entity_repo=entity_repo,
        claim_repo=claim_repo,
        relation_repo=relation_repo,
        entity_cache=entity_cache,
        redis=redis_mock,
        settings=_make_settings(),
    )
    session = AsyncMock()
    result = await engine.run(ws_id, session)

    assert isinstance(result, IntegratorRunResult)
    assert result.status == "completed"
    assert hasattr(result, "entities_scanned")
    assert hasattr(result, "entities_deduplicated")
    assert hasattr(result, "entities_enriched")
    assert hasattr(result, "duration_ms")


@pytest.mark.asyncio
async def test_engine_dedup_called():
    """Engine calls deduplicator when entities are found."""
    from alayaos_core.extraction.integrator.engine import IntegratorEngine

    ws_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    redis_mock = _make_redis_mock(dirty_ids=[str(entity_id)])

    entity_mock = MagicMock()
    entity_mock.id = entity_id
    entity_mock.name = "Alice"
    entity_mock.is_deleted = False
    entity_mock.entity_type_id = uuid.uuid4()
    entity_mock.aliases = []
    entity_mock.properties = {}
    entity_mock.entity_type = MagicMock()
    entity_mock.entity_type.slug = "person"

    entity_repo = AsyncMock()
    entity_repo.list_recent = AsyncMock(return_value=[entity_mock])
    entity_repo.get_by_id = AsyncMock(return_value=entity_mock)

    claim_repo = AsyncMock()
    claim_repo.list = AsyncMock(return_value=([], None, False))

    relation_repo = AsyncMock()
    relation_repo.list = AsyncMock(return_value=([], None, False))

    entity_cache = AsyncMock()
    entity_cache.warm = AsyncMock()

    dedup_mock = AsyncMock()
    dedup_mock.find_duplicates = AsyncMock(return_value=[])

    engine = IntegratorEngine(
        llm=MagicMock(),
        entity_repo=entity_repo,
        claim_repo=claim_repo,
        relation_repo=relation_repo,
        entity_cache=entity_cache,
        redis=redis_mock,
        settings=_make_settings(),
    )
    # Inject deduplicator mock
    engine._deduplicator = dedup_mock

    session = AsyncMock()
    await engine.run(ws_id, session)

    dedup_mock.find_duplicates.assert_called_once()


@pytest.mark.asyncio
async def test_engine_enricher_called():
    """Engine calls enricher when entities are found."""
    from alayaos_core.extraction.integrator.engine import IntegratorEngine
    from alayaos_core.extraction.integrator.schemas import EnrichmentResult

    ws_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    redis_mock = _make_redis_mock(dirty_ids=[str(entity_id)])

    entity_mock = MagicMock()
    entity_mock.id = entity_id
    entity_mock.name = "Alice"
    entity_mock.is_deleted = False
    entity_mock.entity_type_id = uuid.uuid4()
    entity_mock.aliases = []
    entity_mock.properties = {}
    entity_mock.entity_type = MagicMock()
    entity_mock.entity_type.slug = "person"

    entity_repo = AsyncMock()
    entity_repo.list_recent = AsyncMock(return_value=[entity_mock])
    entity_repo.get_by_id = AsyncMock(return_value=entity_mock)

    claim_repo = AsyncMock()
    claim_repo.list = AsyncMock(return_value=([], None, False))

    relation_repo = AsyncMock()
    relation_repo.list = AsyncMock(return_value=([], None, False))

    entity_cache = AsyncMock()
    entity_cache.warm = AsyncMock()

    enricher_mock = AsyncMock()
    enricher_mock.enrich_batch = AsyncMock(return_value=EnrichmentResult())

    engine = IntegratorEngine(
        llm=MagicMock(),
        entity_repo=entity_repo,
        claim_repo=claim_repo,
        relation_repo=relation_repo,
        entity_cache=entity_cache,
        redis=redis_mock,
        settings=_make_settings(),
    )
    engine._enricher = enricher_mock

    session = AsyncMock()
    await engine.run(ws_id, session)

    enricher_mock.enrich_batch.assert_called_once()


@pytest.mark.asyncio
async def test_engine_lock_released_on_completion():
    """Engine always releases lock (via finally block)."""
    from alayaos_core.extraction.integrator.engine import IntegratorEngine

    ws_id = uuid.uuid4()
    redis_mock = _make_redis_mock()
    redis_mock.set = AsyncMock(return_value=True)  # lock acquired

    entity_repo = AsyncMock()
    entity_repo.list_recent = AsyncMock(return_value=[])
    entity_repo.get_by_id = AsyncMock(return_value=None)

    claim_repo = AsyncMock()
    claim_repo.list = AsyncMock(return_value=([], None, False))

    relation_repo = AsyncMock()
    relation_repo.list = AsyncMock(return_value=([], None, False))

    entity_cache = AsyncMock()
    entity_cache.warm = AsyncMock()

    engine = IntegratorEngine(
        llm=MagicMock(),
        entity_repo=entity_repo,
        claim_repo=claim_repo,
        relation_repo=relation_repo,
        entity_cache=entity_cache,
        redis=redis_mock,
        settings=_make_settings(),
    )
    session = AsyncMock()
    await engine.run(ws_id, session)

    # eval was called (lock release Lua script)
    redis_mock.eval.assert_called_once()


@pytest.mark.asyncio
async def test_engine_entity_cache_warmed():
    """Engine calls entity_cache.warm after processing."""
    from alayaos_core.extraction.integrator.engine import IntegratorEngine

    ws_id = uuid.uuid4()
    redis_mock = _make_redis_mock()

    entity_repo = AsyncMock()
    entity_repo.list_recent = AsyncMock(return_value=[])

    claim_repo = AsyncMock()
    claim_repo.list = AsyncMock(return_value=([], None, False))

    relation_repo = AsyncMock()
    relation_repo.list = AsyncMock(return_value=([], None, False))

    entity_cache = AsyncMock()
    entity_cache.warm = AsyncMock()

    engine = IntegratorEngine(
        llm=MagicMock(),
        entity_repo=entity_repo,
        claim_repo=claim_repo,
        relation_repo=relation_repo,
        entity_cache=entity_cache,
        redis=redis_mock,
        settings=_make_settings(),
    )
    session = AsyncMock()
    await engine.run(ws_id, session)

    entity_cache.warm.assert_called_once()
