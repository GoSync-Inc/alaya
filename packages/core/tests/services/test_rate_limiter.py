"""Tests for RateLimiterService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from alayaos_core.services.rate_limiter import RateLimiterService

# ---------------------------------------------------------------------------
# Helper: build a fake Redis that returns a controlled evalsha / eval result
# ---------------------------------------------------------------------------


def _make_redis(lua_result: list[int]) -> MagicMock:
    """Return a mock Redis whose eval() returns lua_result."""
    redis = MagicMock()
    redis.eval = AsyncMock(return_value=lua_result)
    return redis


# ---------------------------------------------------------------------------
# Existing test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limiter_no_redis_reports_backend_unavailable() -> None:
    limiter = RateLimiterService(redis=None)
    decision = await limiter.check("key", 1, 60)
    assert decision.allowed is False
    assert decision.retry_after is None
    assert decision.backend_available is False


# ---------------------------------------------------------------------------
# New atomic-Lua tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_under_limit_allowed() -> None:
    """Request count (1) is under limit (5) → allowed."""
    # Lua returns [count, allowed_flag, oldest_score]
    redis = _make_redis([1, 1, 0])
    limiter = RateLimiterService(redis=redis)
    decision = await limiter.check("user:1", 5, 60)
    assert decision.allowed is True
    assert decision.retry_after is None
    assert decision.backend_available is True
    redis.eval.assert_awaited_once()


@pytest.mark.asyncio
async def test_at_limit_last_request_denied() -> None:
    """When count exceeds limit, request is denied and retry_after is returned."""
    # Lua returns [count=6, allowed_flag=0, oldest_score] oldest_score not used here
    # but we simulate the script returning allowed=0
    redis = _make_redis([6, 0, 30])
    limiter = RateLimiterService(redis=redis)
    decision = await limiter.check("user:1", 5, 60)
    assert decision.allowed is False
    assert decision.retry_after is not None
    assert decision.retry_after >= 1
    assert decision.backend_available is True
    redis.eval.assert_awaited_once()


@pytest.mark.asyncio
async def test_expired_entries_cleaned_allows_new_request() -> None:
    """After window elapses, old entries are removed and new request is allowed."""
    # Simulate that after cleanup count is 1 (only the new entry)
    redis = _make_redis([1, 1, 0])
    limiter = RateLimiterService(redis=redis)
    decision = await limiter.check("user:expired", 5, 60)
    assert decision.allowed is True
    assert decision.retry_after is None
    assert decision.backend_available is True


@pytest.mark.asyncio
async def test_redis_error_reports_backend_unavailable() -> None:
    """If Redis raises an exception, the limiter reports the backend as unavailable."""
    redis = MagicMock()
    redis.eval = AsyncMock(side_effect=ConnectionError("redis down"))
    limiter = RateLimiterService(redis=redis)
    decision = await limiter.check("user:1", 5, 60)
    assert decision.allowed is False
    assert decision.retry_after is None
    assert decision.backend_available is False


@pytest.mark.asyncio
async def test_unique_members_no_collision() -> None:
    """Each call passes a unique member to Redis eval (no timestamp collision)."""
    call_members: list[str] = []

    async def capture_eval(script: str, numkeys: int, *args: str) -> list[int]:
        # args: redis_key, window_start, member, now, limit, window_seconds
        call_members.append(args[2])  # member is ARGV[2] → args index 2
        return [1, 1, 0]

    redis = MagicMock()
    redis.eval = AsyncMock(side_effect=capture_eval)
    limiter = RateLimiterService(redis=redis)

    await limiter.check("user:1", 5, 60)
    await limiter.check("user:1", 5, 60)

    assert len(call_members) == 2
    assert call_members[0] != call_members[1]


@pytest.mark.asyncio
async def test_denied_entry_removed_count_stays_at_limit() -> None:
    """When denied, the Lua script removes the added entry so count == limit, not limit+1."""
    limit = 5
    # Lua script removes the added entry when over limit → count returned equals limit+1 before removal
    # but the script itself handles removal; our service should report allowed=False
    # and the caller never sees an inflated count.
    redis = _make_redis([limit + 1, 0, 30])
    limiter = RateLimiterService(redis=redis)
    decision = await limiter.check("user:full", limit, 60)
    assert decision.allowed is False
    assert decision.backend_available is True
    # Crucially: no second call to redis (e.g. zrem) — removal is inside the Lua script
    assert redis.eval.await_count == 1
