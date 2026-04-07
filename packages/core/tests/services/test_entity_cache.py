"""Tests for EntityCacheService — Redis snapshot for Crystallizer prompts."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from alayaos_core.services.entity_cache import EntityCacheService


def make_redis_mock():
    """Build a mock Redis client with a pipeline that tracks calls."""
    redis = MagicMock()
    pipeline = MagicMock()
    pipeline.zadd = MagicMock()
    pipeline.hset = MagicMock()
    pipeline.expire = MagicMock()
    pipeline.zrem = MagicMock()
    pipeline.hdel = MagicMock()
    pipeline.hget = MagicMock()
    pipeline.execute = AsyncMock()
    redis.pipeline = MagicMock(return_value=pipeline)
    redis.zrevrange = AsyncMock()
    return redis, pipeline


@pytest.mark.asyncio
async def test_warm_populates_sorted_set_and_hash() -> None:
    redis, pipeline = make_redis_mock()
    pipeline.execute.return_value = []

    svc = EntityCacheService(redis)
    ws = uuid.uuid4()
    entities = [
        {"name": "Alice", "entity_type": "person", "aliases": ["Al"], "last_seen_at": 1000.0},
        {"name": "Beta Project", "entity_type": "project", "aliases": [], "last_seen_at": 2000.0},
    ]
    await svc.warm(ws, entities)

    # zadd called twice (once per entity)
    assert pipeline.zadd.call_count == 2
    pipeline.zadd.assert_any_call(f"entity_cache:{ws}", {"Alice": 1000.0})
    pipeline.zadd.assert_any_call(f"entity_cache:{ws}", {"Beta Project": 2000.0})

    # hset called twice
    assert pipeline.hset.call_count == 2

    # expire called for both sorted set and hash keys
    assert pipeline.expire.call_count == 2


@pytest.mark.asyncio
async def test_warm_sets_ttl() -> None:
    redis, pipeline = make_redis_mock()
    pipeline.execute.return_value = []

    svc = EntityCacheService(redis)
    ws = uuid.uuid4()
    await svc.warm(ws, [{"name": "Alice", "entity_type": "person", "aliases": [], "last_seen_at": 1.0}], ttl=7200)

    key = f"entity_cache:{ws}"
    hash_key = f"entity_cache:{ws}:details"
    pipeline.expire.assert_any_call(key, 7200)
    pipeline.expire.assert_any_call(hash_key, 7200)


@pytest.mark.asyncio
async def test_get_snapshot_returns_entities_sorted_by_score() -> None:
    redis, pipeline = make_redis_mock()

    ws = uuid.uuid4()
    redis.zrevrange.return_value = ["Beta Project", "Alice"]
    detail_alice = json.dumps({"name": "Alice", "entity_type": "person", "aliases": []})
    detail_beta = json.dumps({"name": "Beta Project", "entity_type": "project", "aliases": []})
    pipeline.execute.return_value = [detail_beta, detail_alice]

    svc = EntityCacheService(redis)
    result = await svc.get_snapshot(ws)

    assert len(result) == 2
    assert result[0]["name"] == "Beta Project"
    assert result[1]["name"] == "Alice"


@pytest.mark.asyncio
async def test_get_snapshot_with_types_filter() -> None:
    redis, pipeline = make_redis_mock()

    ws = uuid.uuid4()
    redis.zrevrange.return_value = ["Beta Project", "Alice"]
    detail_alice = json.dumps({"name": "Alice", "entity_type": "person", "aliases": []})
    detail_beta = json.dumps({"name": "Beta Project", "entity_type": "project", "aliases": []})
    pipeline.execute.return_value = [detail_beta, detail_alice]

    svc = EntityCacheService(redis)
    result = await svc.get_snapshot(ws, types=["person"])

    assert len(result) == 1
    assert result[0]["name"] == "Alice"


@pytest.mark.asyncio
async def test_get_snapshot_empty_cache_returns_empty_list() -> None:
    redis, _pipeline = make_redis_mock()
    redis.zrevrange.return_value = []

    svc = EntityCacheService(redis)
    ws = uuid.uuid4()
    result = await svc.get_snapshot(ws)

    assert result == []


@pytest.mark.asyncio
async def test_invalidate_removes_entity_from_both_structures() -> None:
    redis, pipeline = make_redis_mock()
    pipeline.execute.return_value = []

    svc = EntityCacheService(redis)
    ws = uuid.uuid4()
    await svc.invalidate(ws, "Alice")

    pipeline.zrem.assert_called_once_with(f"entity_cache:{ws}", "Alice")
    pipeline.hdel.assert_called_once_with(f"entity_cache:{ws}:details", "Alice")
    pipeline.execute.assert_called_once()


@pytest.mark.asyncio
async def test_invalidate_batch_removes_multiple_entities() -> None:
    redis, pipeline = make_redis_mock()
    pipeline.execute.return_value = []

    svc = EntityCacheService(redis)
    ws = uuid.uuid4()
    await svc.invalidate_batch(ws, ["Alice", "Bob", "Beta Project"])

    pipeline.zrem.assert_called_once_with(f"entity_cache:{ws}", "Alice", "Bob", "Beta Project")
    pipeline.hdel.assert_called_once_with(f"entity_cache:{ws}:details", "Alice", "Bob", "Beta Project")


@pytest.mark.asyncio
async def test_invalidate_batch_empty_list_does_nothing() -> None:
    redis, pipeline = make_redis_mock()

    svc = EntityCacheService(redis)
    ws = uuid.uuid4()
    await svc.invalidate_batch(ws, [])

    pipeline.execute.assert_not_called()


@pytest.mark.asyncio
async def test_warm_with_datetime_last_seen_at() -> None:
    """warm() converts datetime.timestamp() to float score."""
    import datetime

    redis, pipeline = make_redis_mock()
    pipeline.execute.return_value = []

    svc = EntityCacheService(redis)
    ws = uuid.uuid4()
    dt = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
    entities = [{"name": "Alice", "entity_type": "person", "aliases": [], "last_seen_at": dt}]
    await svc.warm(ws, entities)

    expected_score = dt.timestamp()
    pipeline.zadd.assert_called_once_with(f"entity_cache:{ws}", {"Alice": expected_score})


@pytest.mark.asyncio
async def test_entity_cache_none_redis_returns_empty() -> None:
    """EntityCacheService with redis=None gracefully returns empty results."""
    svc = EntityCacheService(redis=None)
    ws = uuid.uuid4()

    result = await svc.get_snapshot(ws)
    assert result == []

    # warm and invalidate should not raise
    await svc.warm(ws, [{"name": "Alice", "entity_type": "person", "aliases": [], "last_seen_at": 1.0}])
    await svc.invalidate(ws, "Alice")
    await svc.invalidate_batch(ws, ["Alice"])
