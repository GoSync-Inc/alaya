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


@pytest.mark.asyncio
async def test_merge_duplicates_soft_deletes_entity_b_and_merges_aliases():
    """_merge_duplicates soft-deletes entity_b and merges aliases into entity_a."""
    from alayaos_core.extraction.integrator.engine import IntegratorEngine
    from alayaos_core.extraction.integrator.schemas import DuplicatePair

    ws_id = uuid.uuid4()
    entity_a_id = uuid.uuid4()
    entity_b_id = uuid.uuid4()

    entity_a = MagicMock()
    entity_a.id = entity_a_id
    entity_a.name = "Alice Smith"
    entity_a.aliases = ["Ali"]

    entity_b = MagicMock()
    entity_b.id = entity_b_id
    entity_b.name = "Alice Smyth"
    entity_b.aliases = ["Alicia"]

    entity_repo = AsyncMock()
    entity_repo.update = AsyncMock(return_value=None)

    async def get_by_id(eid):
        if eid == entity_a_id:
            return entity_a
        if eid == entity_b_id:
            return entity_b
        return None

    entity_repo.get_by_id = get_by_id

    engine = IntegratorEngine(
        llm=MagicMock(),
        entity_repo=entity_repo,
        claim_repo=AsyncMock(),
        relation_repo=AsyncMock(),
        entity_cache=AsyncMock(),
        redis=_make_redis_mock(),
        settings=_make_settings(),
    )

    pair = DuplicatePair(
        entity_a_id=entity_a_id,
        entity_b_id=entity_b_id,
        entity_a_name="Alice Smith",
        entity_b_name="Alice Smyth",
        score=0.92,
        method="fuzzy",
    )

    session = AsyncMock()
    merged_count = await engine._merge_duplicates([pair], ws_id, session)

    assert merged_count == 1
    # entity_b must be soft-deleted
    delete_calls = [call for call in entity_repo.update.call_args_list if call.kwargs.get("is_deleted") is True]
    assert any(c.args[0] == entity_b_id for c in delete_calls)
    # entity_a must have its aliases updated (merged)
    alias_calls = [call for call in entity_repo.update.call_args_list if "aliases" in call.kwargs]
    assert alias_calls, "entity_a.aliases should be updated"
    merged_aliases = alias_calls[0].kwargs["aliases"]
    # entity_b's name should appear in merged aliases
    assert "Alice Smyth" in merged_aliases


@pytest.mark.asyncio
async def test_merge_reassigns_claims():
    """_merge_duplicates reassigns entity_b's claims to entity_a via raw SQL."""
    from alayaos_core.extraction.integrator.engine import IntegratorEngine
    from alayaos_core.extraction.integrator.schemas import DuplicatePair

    ws_id = uuid.uuid4()
    entity_a_id = uuid.uuid4()
    entity_b_id = uuid.uuid4()

    entity_a = MagicMock()
    entity_a.id = entity_a_id
    entity_a.name = "Alice Smith"
    entity_a.aliases = []
    entity_a.properties = {}

    entity_b = MagicMock()
    entity_b.id = entity_b_id
    entity_b.name = "Alice Smyth"
    entity_b.aliases = []
    entity_b.properties = {}

    entity_repo = AsyncMock()
    entity_repo.update = AsyncMock(return_value=None)

    async def get_by_id(eid):
        if eid == entity_a_id:
            return entity_a
        if eid == entity_b_id:
            return entity_b
        return None

    entity_repo.get_by_id = get_by_id

    engine = IntegratorEngine(
        llm=MagicMock(),
        entity_repo=entity_repo,
        claim_repo=AsyncMock(),
        relation_repo=AsyncMock(),
        entity_cache=AsyncMock(),
        redis=_make_redis_mock(),
        settings=_make_settings(),
    )

    pair = DuplicatePair(
        entity_a_id=entity_a_id,
        entity_b_id=entity_b_id,
        entity_a_name="Alice Smith",
        entity_b_name="Alice Smyth",
        score=0.92,
        method="fuzzy",
    )

    session = AsyncMock()
    await engine._merge_duplicates([pair], ws_id, session)

    # session.execute must be called with an UPDATE l2_claims statement
    executed_sqls = [str(call.args[0]) for call in session.execute.call_args_list]
    claims_reassign = [s for s in executed_sqls if "l2_claims" in s and "entity_id" in s]
    assert claims_reassign, "Expected UPDATE l2_claims to reassign claims to entity_a"


@pytest.mark.asyncio
async def test_merge_reassigns_relations():
    """_merge_duplicates reassigns both source and target relations from entity_b to entity_a."""
    from alayaos_core.extraction.integrator.engine import IntegratorEngine
    from alayaos_core.extraction.integrator.schemas import DuplicatePair

    ws_id = uuid.uuid4()
    entity_a_id = uuid.uuid4()
    entity_b_id = uuid.uuid4()

    entity_a = MagicMock()
    entity_a.id = entity_a_id
    entity_a.name = "Alice"
    entity_a.aliases = []
    entity_a.properties = {}

    entity_b = MagicMock()
    entity_b.id = entity_b_id
    entity_b.name = "Alice B"
    entity_b.aliases = []
    entity_b.properties = {}

    entity_repo = AsyncMock()
    entity_repo.update = AsyncMock(return_value=None)

    async def get_by_id(eid):
        if eid == entity_a_id:
            return entity_a
        if eid == entity_b_id:
            return entity_b
        return None

    entity_repo.get_by_id = get_by_id

    engine = IntegratorEngine(
        llm=MagicMock(),
        entity_repo=entity_repo,
        claim_repo=AsyncMock(),
        relation_repo=AsyncMock(),
        entity_cache=AsyncMock(),
        redis=_make_redis_mock(),
        settings=_make_settings(),
    )

    pair = DuplicatePair(
        entity_a_id=entity_a_id,
        entity_b_id=entity_b_id,
        entity_a_name="Alice",
        entity_b_name="Alice B",
        score=0.91,
        method="fuzzy",
    )

    session = AsyncMock()
    await engine._merge_duplicates([pair], ws_id, session)

    executed_sqls = [str(call.args[0]) for call in session.execute.call_args_list]
    source_reassign = [s for s in executed_sqls if "l1_relations" in s and "source_entity_id" in s]
    target_reassign = [s for s in executed_sqls if "l1_relations" in s and "target_entity_id" in s]
    assert source_reassign, "Expected UPDATE l1_relations source_entity_id reassignment"
    assert target_reassign, "Expected UPDATE l1_relations target_entity_id reassignment"


@pytest.mark.asyncio
async def test_merge_removes_self_referential_relations():
    """_merge_duplicates deletes self-referential relations on entity_a after reassignment."""
    from alayaos_core.extraction.integrator.engine import IntegratorEngine
    from alayaos_core.extraction.integrator.schemas import DuplicatePair

    ws_id = uuid.uuid4()
    entity_a_id = uuid.uuid4()
    entity_b_id = uuid.uuid4()

    entity_a = MagicMock()
    entity_a.id = entity_a_id
    entity_a.name = "Alice"
    entity_a.aliases = []
    entity_a.properties = {}

    entity_b = MagicMock()
    entity_b.id = entity_b_id
    entity_b.name = "Alice B"
    entity_b.aliases = []
    entity_b.properties = {}

    entity_repo = AsyncMock()
    entity_repo.update = AsyncMock(return_value=None)

    async def get_by_id(eid):
        if eid == entity_a_id:
            return entity_a
        if eid == entity_b_id:
            return entity_b
        return None

    entity_repo.get_by_id = get_by_id

    engine = IntegratorEngine(
        llm=MagicMock(),
        entity_repo=entity_repo,
        claim_repo=AsyncMock(),
        relation_repo=AsyncMock(),
        entity_cache=AsyncMock(),
        redis=_make_redis_mock(),
        settings=_make_settings(),
    )

    pair = DuplicatePair(
        entity_a_id=entity_a_id,
        entity_b_id=entity_b_id,
        entity_a_name="Alice",
        entity_b_name="Alice B",
        score=0.91,
        method="fuzzy",
    )

    session = AsyncMock()
    await engine._merge_duplicates([pair], ws_id, session)

    executed_sqls = [str(call.args[0]) for call in session.execute.call_args_list]
    self_ref_delete = [
        s for s in executed_sqls
        if "DELETE" in s and "l1_relations" in s and "source_entity_id" in s and "target_entity_id" in s
    ]
    assert self_ref_delete, "Expected DELETE of self-referential relations on entity_a"


@pytest.mark.asyncio
async def test_merge_updates_vector_chunks():
    """_merge_duplicates updates vector_chunks source_id from entity_b to entity_a."""
    from alayaos_core.extraction.integrator.engine import IntegratorEngine
    from alayaos_core.extraction.integrator.schemas import DuplicatePair

    ws_id = uuid.uuid4()
    entity_a_id = uuid.uuid4()
    entity_b_id = uuid.uuid4()

    entity_a = MagicMock()
    entity_a.id = entity_a_id
    entity_a.name = "Alice"
    entity_a.aliases = []
    entity_a.properties = {}

    entity_b = MagicMock()
    entity_b.id = entity_b_id
    entity_b.name = "Alice B"
    entity_b.aliases = []
    entity_b.properties = {}

    entity_repo = AsyncMock()
    entity_repo.update = AsyncMock(return_value=None)

    async def get_by_id(eid):
        if eid == entity_a_id:
            return entity_a
        if eid == entity_b_id:
            return entity_b
        return None

    entity_repo.get_by_id = get_by_id

    engine = IntegratorEngine(
        llm=MagicMock(),
        entity_repo=entity_repo,
        claim_repo=AsyncMock(),
        relation_repo=AsyncMock(),
        entity_cache=AsyncMock(),
        redis=_make_redis_mock(),
        settings=_make_settings(),
    )

    pair = DuplicatePair(
        entity_a_id=entity_a_id,
        entity_b_id=entity_b_id,
        entity_a_name="Alice",
        entity_b_name="Alice B",
        score=0.91,
        method="fuzzy",
    )

    session = AsyncMock()
    await engine._merge_duplicates([pair], ws_id, session)

    executed_sqls = [str(call.args[0]) for call in session.execute.call_args_list]
    chunk_reassign = [s for s in executed_sqls if "vector_chunks" in s and "source_id" in s]
    assert chunk_reassign, "Expected UPDATE vector_chunks to reassign source_id to entity_a"


@pytest.mark.asyncio
async def test_merge_records_merged_into():
    """_merge_duplicates stores merged_into=entity_a.id in entity_b's properties before soft-delete."""
    from alayaos_core.extraction.integrator.engine import IntegratorEngine
    from alayaos_core.extraction.integrator.schemas import DuplicatePair

    ws_id = uuid.uuid4()
    entity_a_id = uuid.uuid4()
    entity_b_id = uuid.uuid4()

    entity_a = MagicMock()
    entity_a.id = entity_a_id
    entity_a.name = "Alice"
    entity_a.aliases = []
    entity_a.properties = {}

    entity_b = MagicMock()
    entity_b.id = entity_b_id
    entity_b.name = "Alice B"
    entity_b.aliases = []
    entity_b.properties = {"existing": "value"}

    entity_repo = AsyncMock()
    entity_repo.update = AsyncMock(return_value=None)

    async def get_by_id(eid):
        if eid == entity_a_id:
            return entity_a
        if eid == entity_b_id:
            return entity_b
        return None

    entity_repo.get_by_id = get_by_id

    engine = IntegratorEngine(
        llm=MagicMock(),
        entity_repo=entity_repo,
        claim_repo=AsyncMock(),
        relation_repo=AsyncMock(),
        entity_cache=AsyncMock(),
        redis=_make_redis_mock(),
        settings=_make_settings(),
    )

    pair = DuplicatePair(
        entity_a_id=entity_a_id,
        entity_b_id=entity_b_id,
        entity_a_name="Alice",
        entity_b_name="Alice B",
        score=0.91,
        method="fuzzy",
    )

    session = AsyncMock()
    await engine._merge_duplicates([pair], ws_id, session)

    # The call that soft-deletes entity_b must also carry merged_into in properties
    delete_calls = [
        call for call in entity_repo.update.call_args_list
        if call.kwargs.get("is_deleted") is True and call.args[0] == entity_b_id
    ]
    assert delete_calls, "entity_b must be soft-deleted"
    props = delete_calls[0].kwargs.get("properties", {})
    assert props.get("merged_into") == str(entity_a_id), (
        f"expected merged_into={entity_a_id}, got properties={props}"
    )


@pytest.mark.asyncio
async def test_merge_duplicates_skips_missing_entities():
    """_merge_duplicates skips pair if either entity is missing."""
    from alayaos_core.extraction.integrator.engine import IntegratorEngine
    from alayaos_core.extraction.integrator.schemas import DuplicatePair

    ws_id = uuid.uuid4()
    entity_a_id = uuid.uuid4()
    entity_b_id = uuid.uuid4()

    entity_repo = AsyncMock()
    entity_repo.get_by_id = AsyncMock(return_value=None)  # both missing
    entity_repo.update = AsyncMock()

    engine = IntegratorEngine(
        llm=MagicMock(),
        entity_repo=entity_repo,
        claim_repo=AsyncMock(),
        relation_repo=AsyncMock(),
        entity_cache=AsyncMock(),
        redis=_make_redis_mock(),
        settings=_make_settings(),
    )

    pair = DuplicatePair(
        entity_a_id=entity_a_id,
        entity_b_id=entity_b_id,
        entity_a_name="A",
        entity_b_name="B",
        score=0.9,
        method="fuzzy",
    )

    merged_count = await engine._merge_duplicates([pair], ws_id, AsyncMock())
    assert merged_count == 0
    entity_repo.update.assert_not_called()


@pytest.mark.asyncio
async def test_apply_action_update_status_merges_properties():
    """update_status action merges into existing properties instead of replacing."""
    from alayaos_core.extraction.integrator.engine import IntegratorEngine
    from alayaos_core.extraction.integrator.schemas import EnrichmentAction

    entity_id = uuid.uuid4()
    entity_mock = MagicMock()
    entity_mock.id = entity_id
    entity_mock.properties = {"existing_key": "existing_value"}

    entity_repo = AsyncMock()
    entity_repo.get_by_id = AsyncMock(return_value=entity_mock)
    entity_repo.update = AsyncMock(return_value=entity_mock)

    engine = IntegratorEngine(
        llm=MagicMock(),
        entity_repo=entity_repo,
        claim_repo=AsyncMock(),
        relation_repo=AsyncMock(),
        entity_cache=AsyncMock(),
        redis=_make_redis_mock(),
        settings=_make_settings(),
    )

    action = EnrichmentAction(
        action="update_status",
        entity_id=entity_id,
        details={"status": "active"},
    )

    ws_id = uuid.uuid4()
    counters = await engine._apply_action(action, ws_id, AsyncMock())

    assert counters.get("claims_updated") == 1
    update_kwargs = entity_repo.update.call_args.kwargs
    merged_props = update_kwargs["properties"]
    # Both old key and new key should be present
    assert merged_props["existing_key"] == "existing_value"
    assert merged_props["status"] == "active"


@pytest.mark.asyncio
async def test_apply_action_normalize_date_calls_date_normalizer():
    """normalize_date action calls DateNormalizer and stores normalized result."""
    from alayaos_core.extraction.integrator.engine import IntegratorEngine
    from alayaos_core.extraction.integrator.schemas import EnrichmentAction

    entity_id = uuid.uuid4()
    entity_mock = MagicMock()
    entity_mock.id = entity_id
    entity_mock.properties = {"project": "X"}

    entity_repo = AsyncMock()
    entity_repo.get_by_id = AsyncMock(return_value=entity_mock)
    entity_repo.update = AsyncMock(return_value=entity_mock)

    engine = IntegratorEngine(
        llm=MagicMock(),
        entity_repo=entity_repo,
        claim_repo=AsyncMock(),
        relation_repo=AsyncMock(),
        entity_cache=AsyncMock(),
        redis=_make_redis_mock(),
        settings=_make_settings(),
    )

    action = EnrichmentAction(
        action="normalize_date",
        entity_id=entity_id,
        details={"date_value": "2024-04-15"},
    )

    ws_id = uuid.uuid4()
    counters = await engine._apply_action(action, ws_id, AsyncMock())

    assert counters.get("claims_updated") == 1
    update_kwargs = entity_repo.update.call_args.kwargs
    props = update_kwargs["properties"]
    # DateNormalizer should have stored normalized_date
    assert "normalized_date" in props
