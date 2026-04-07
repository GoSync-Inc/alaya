"""Tests for dirty-set push logic in atomic_write (writer.py)."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_event(workspace_id: uuid.UUID | None = None):
    event = MagicMock()
    event.workspace_id = workspace_id or uuid.uuid4()
    event.id = uuid.uuid4()
    event.occurred_at = datetime(2024, 6, 1, tzinfo=UTC)
    event.created_at = datetime(2024, 6, 1, tzinfo=UTC)
    event.is_extracted = False
    return event


def _make_run():
    run = MagicMock()
    run.id = uuid.uuid4()
    run.status = "writing"
    run.event_id = uuid.uuid4()
    run.resolver_decisions = None
    return run


def _make_redis_mock():
    """Create an async mock that simulates a Redis pipeline."""
    pipeline_mock = AsyncMock()
    pipeline_mock.sadd = MagicMock(return_value=pipeline_mock)
    pipeline_mock.expire = MagicMock(return_value=pipeline_mock)
    pipeline_mock.set = MagicMock(return_value=pipeline_mock)
    pipeline_mock.execute = AsyncMock(return_value=[1, True, True])

    redis_mock = AsyncMock()
    redis_mock.pipeline = MagicMock(return_value=pipeline_mock)
    return redis_mock, pipeline_mock


def _make_run_repo_mock():
    run_repo_mock = AsyncMock()
    run_repo_mock.update_counters = AsyncMock()
    run_repo_mock.clear_raw_extraction = AsyncMock()
    return run_repo_mock


# ─── Tests ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_entity_ids_pushed_to_dirty_set() -> None:
    """After atomic_write, entity IDs are pushed to the Redis dirty-set."""
    from alayaos_core.extraction.schemas import ExtractionResult
    from alayaos_core.extraction.writer import atomic_write

    ws_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    entity_name_to_id = {"Alice": entity_id}

    event = _make_event(ws_id)
    run = _make_run()
    redis_mock, pipeline_mock = _make_redis_mock()

    session = AsyncMock()
    session.flush = AsyncMock()
    llm = MagicMock()

    extraction_result = ExtractionResult(entities=[], relations=[], claims=[])
    run_repo_mock = _make_run_repo_mock()

    mock_cache = AsyncMock()
    mock_cache.invalidate_batch = AsyncMock()

    with (
        patch("alayaos_core.extraction.writer.EntityRepository"),
        patch("alayaos_core.extraction.writer.ClaimRepository"),
        patch("alayaos_core.extraction.writer.RelationRepository"),
        patch("alayaos_core.extraction.writer.PredicateRepository"),
        patch("alayaos_core.extraction.writer.ExtractionRunRepository", return_value=run_repo_mock),
        patch("alayaos_core.services.entity_cache.EntityCacheService", return_value=mock_cache),
    ):
        await atomic_write(
            extraction_result=extraction_result,
            event=event,
            run=run,
            session=session,
            llm=llm,
            entity_name_to_id=entity_name_to_id,
            resolver_decisions=[],
            redis=redis_mock,
        )

    # Verify sadd was called with the entity ID
    pipeline_mock.sadd.assert_called_once_with(
        f"dirty_set:{ws_id}", str(entity_id)
    )


@pytest.mark.asyncio
async def test_dirty_set_ttl_48h() -> None:
    """dirty_set key gets 48h TTL after entity IDs are pushed."""
    from alayaos_core.extraction.schemas import ExtractionResult
    from alayaos_core.extraction.writer import atomic_write

    ws_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    entity_name_to_id = {"Alice": entity_id}

    event = _make_event(ws_id)
    run = _make_run()
    redis_mock, pipeline_mock = _make_redis_mock()

    session = AsyncMock()
    session.flush = AsyncMock()

    extraction_result = ExtractionResult(entities=[], relations=[], claims=[])
    run_repo_mock = _make_run_repo_mock()

    mock_cache = AsyncMock()
    mock_cache.invalidate_batch = AsyncMock()

    with (
        patch("alayaos_core.extraction.writer.EntityRepository"),
        patch("alayaos_core.extraction.writer.ClaimRepository"),
        patch("alayaos_core.extraction.writer.RelationRepository"),
        patch("alayaos_core.extraction.writer.PredicateRepository"),
        patch("alayaos_core.extraction.writer.ExtractionRunRepository", return_value=run_repo_mock),
        patch("alayaos_core.services.entity_cache.EntityCacheService", return_value=mock_cache),
    ):
        await atomic_write(
            extraction_result=extraction_result,
            event=event,
            run=run,
            session=session,
            llm=MagicMock(),
            entity_name_to_id=entity_name_to_id,
            resolver_decisions=[],
            redis=redis_mock,
        )

    # expire called with 48h = 48 * 3600 = 172800
    pipeline_mock.expire.assert_called_with(f"dirty_set:{ws_id}", 48 * 3600)


@pytest.mark.asyncio
async def test_created_at_key_set_with_nx() -> None:
    """created_at companion key is set with nx=True (first-write-only)."""
    from alayaos_core.extraction.schemas import ExtractionResult
    from alayaos_core.extraction.writer import atomic_write

    ws_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    entity_name_to_id = {"Alice": entity_id}

    event = _make_event(ws_id)
    run = _make_run()
    redis_mock, pipeline_mock = _make_redis_mock()

    session = AsyncMock()
    session.flush = AsyncMock()

    extraction_result = ExtractionResult(entities=[], relations=[], claims=[])
    run_repo_mock = _make_run_repo_mock()

    mock_cache = AsyncMock()
    mock_cache.invalidate_batch = AsyncMock()

    with (
        patch("alayaos_core.extraction.writer.EntityRepository"),
        patch("alayaos_core.extraction.writer.ClaimRepository"),
        patch("alayaos_core.extraction.writer.RelationRepository"),
        patch("alayaos_core.extraction.writer.PredicateRepository"),
        patch("alayaos_core.extraction.writer.ExtractionRunRepository", return_value=run_repo_mock),
        patch("alayaos_core.services.entity_cache.EntityCacheService", return_value=mock_cache),
    ):
        await atomic_write(
            extraction_result=extraction_result,
            event=event,
            run=run,
            session=session,
            llm=MagicMock(),
            entity_name_to_id=entity_name_to_id,
            resolver_decisions=[],
            redis=redis_mock,
        )

    # set called with nx=True
    set_calls = pipeline_mock.set.call_args_list
    assert len(set_calls) == 1
    _, kwargs = set_calls[0]
    assert kwargs.get("nx") is True
    assert kwargs.get("ex") == 48 * 3600
    # Key is the created_at companion
    assert set_calls[0].args[0] == f"dirty_set:{ws_id}:created_at"


@pytest.mark.asyncio
async def test_entity_cache_invalidated_after_write() -> None:
    """EntityCacheService.invalidate_batch is called with entity names after write."""
    from alayaos_core.extraction.schemas import ExtractionResult
    from alayaos_core.extraction.writer import atomic_write

    ws_id = uuid.uuid4()
    entity_name_to_id = {"Alice": uuid.uuid4(), "Bob": uuid.uuid4()}

    event = _make_event(ws_id)
    run = _make_run()
    redis_mock, pipeline_mock = _make_redis_mock()

    session = AsyncMock()
    session.flush = AsyncMock()

    extraction_result = ExtractionResult(entities=[], relations=[], claims=[])
    run_repo_mock = _make_run_repo_mock()

    mock_cache = AsyncMock()
    mock_cache.invalidate_batch = AsyncMock()

    with (
        patch("alayaos_core.extraction.writer.EntityRepository"),
        patch("alayaos_core.extraction.writer.ClaimRepository"),
        patch("alayaos_core.extraction.writer.RelationRepository"),
        patch("alayaos_core.extraction.writer.PredicateRepository"),
        patch("alayaos_core.extraction.writer.ExtractionRunRepository", return_value=run_repo_mock),
        patch("alayaos_core.services.entity_cache.EntityCacheService", return_value=mock_cache),
    ):
        await atomic_write(
            extraction_result=extraction_result,
            event=event,
            run=run,
            session=session,
            llm=MagicMock(),
            entity_name_to_id=entity_name_to_id,
            resolver_decisions=[],
            redis=redis_mock,
        )

    # invalidate_batch called with workspace_id and all entity names
    mock_cache.invalidate_batch.assert_called_once()
    call_args = mock_cache.invalidate_batch.call_args
    assert call_args.args[0] == ws_id
    assert set(call_args.args[1]) == {"Alice", "Bob"}


@pytest.mark.asyncio
async def test_no_redis_no_error() -> None:
    """atomic_write completes gracefully when redis=None (no dirty-set push)."""
    from alayaos_core.extraction.schemas import ExtractionResult
    from alayaos_core.extraction.writer import atomic_write

    ws_id = uuid.uuid4()
    entity_name_to_id = {"Alice": uuid.uuid4()}

    event = _make_event(ws_id)
    run = _make_run()

    session = AsyncMock()
    session.flush = AsyncMock()

    extraction_result = ExtractionResult(entities=[], relations=[], claims=[])
    run_repo_mock = _make_run_repo_mock()

    with (
        patch("alayaos_core.extraction.writer.EntityRepository"),
        patch("alayaos_core.extraction.writer.ClaimRepository"),
        patch("alayaos_core.extraction.writer.RelationRepository"),
        patch("alayaos_core.extraction.writer.PredicateRepository"),
        patch("alayaos_core.extraction.writer.ExtractionRunRepository", return_value=run_repo_mock),
    ):
        # Should NOT raise
        counters = await atomic_write(
            extraction_result=extraction_result,
            event=event,
            run=run,
            session=session,
            llm=MagicMock(),
            entity_name_to_id=entity_name_to_id,
            resolver_decisions=[],
            redis=None,
        )

    assert isinstance(counters, dict)


@pytest.mark.asyncio
async def test_no_entity_ids_no_dirty_set_push() -> None:
    """If entity_name_to_id is empty, no dirty-set push is made."""
    from alayaos_core.extraction.schemas import ExtractionResult
    from alayaos_core.extraction.writer import atomic_write

    ws_id = uuid.uuid4()
    entity_name_to_id: dict = {}

    event = _make_event(ws_id)
    run = _make_run()
    redis_mock, pipeline_mock = _make_redis_mock()

    session = AsyncMock()
    session.flush = AsyncMock()

    extraction_result = ExtractionResult(entities=[], relations=[], claims=[])
    run_repo_mock = _make_run_repo_mock()

    mock_cache = AsyncMock()
    mock_cache.invalidate_batch = AsyncMock()

    with (
        patch("alayaos_core.extraction.writer.EntityRepository"),
        patch("alayaos_core.extraction.writer.ClaimRepository"),
        patch("alayaos_core.extraction.writer.RelationRepository"),
        patch("alayaos_core.extraction.writer.PredicateRepository"),
        patch("alayaos_core.extraction.writer.ExtractionRunRepository", return_value=run_repo_mock),
        patch("alayaos_core.services.entity_cache.EntityCacheService", return_value=mock_cache),
    ):
        await atomic_write(
            extraction_result=extraction_result,
            event=event,
            run=run,
            session=session,
            llm=MagicMock(),
            entity_name_to_id=entity_name_to_id,
            resolver_decisions=[],
            redis=redis_mock,
        )

    # pipeline should NOT have been created (no entity IDs to push)
    pipeline_mock.sadd.assert_not_called()
