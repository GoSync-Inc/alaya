"""Tests for RateLimiterService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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
async def test_rate_limiter_no_redis_always_allows() -> None:
    limiter = RateLimiterService(redis=None)
    allowed, retry = await limiter.check("key", 1, 60)
    assert allowed is True
    assert retry is None


# ---------------------------------------------------------------------------
# New atomic-Lua tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_under_limit_allowed() -> None:
    """Request count (1) is under limit (5) → allowed."""
    # Lua returns [count, allowed_flag, oldest_score]
    redis = _make_redis([1, 1, 0])
    limiter = RateLimiterService(redis=redis)
    allowed, retry = await limiter.check("user:1", 5, 60)
    assert allowed is True
    assert retry is None
    redis.eval.assert_awaited_once()


@pytest.mark.asyncio
async def test_at_limit_last_request_denied() -> None:
    """When count exceeds limit, request is denied and retry_after is returned."""
    # Lua returns [count=6, allowed_flag=0, oldest_score] oldest_score not used here
    # but we simulate the script returning allowed=0
    redis = _make_redis([6, 0, 30])
    limiter = RateLimiterService(redis=redis)
    allowed, retry = await limiter.check("user:1", 5, 60)
    assert allowed is False
    assert retry is not None
    assert retry >= 1
    redis.eval.assert_awaited_once()


@pytest.mark.asyncio
async def test_expired_entries_cleaned_allows_new_request() -> None:
    """After window elapses, old entries are removed and new request is allowed."""
    # Simulate that after cleanup count is 1 (only the new entry)
    redis = _make_redis([1, 1, 0])
    limiter = RateLimiterService(redis=redis)
    allowed, retry = await limiter.check("user:expired", 5, 60)
    assert allowed is True
    assert retry is None


@pytest.mark.asyncio
async def test_denied_entry_removed_count_stays_at_limit() -> None:
    """When denied, the Lua script removes the added entry so count == limit, not limit+1."""
    limit = 5
    # Lua script removes the added entry when over limit → count returned equals limit+1 before removal
    # but the script itself handles removal; our service should report allowed=False
    # and the caller never sees an inflated count.
    redis = _make_redis([limit + 1, 0, 30])
    limiter = RateLimiterService(redis=redis)
    allowed, retry = await limiter.check("user:full", limit, 60)
    assert allowed is False
    # Crucially: no second call to redis (e.g. zrem) — removal is inside the Lua script
    assert redis.eval.await_count == 1
