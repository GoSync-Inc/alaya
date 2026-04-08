"""Tests for RateLimiterService."""

import pytest

from alayaos_core.services.rate_limiter import RateLimiterService


@pytest.mark.asyncio
async def test_rate_limiter_no_redis_always_allows():
    limiter = RateLimiterService(redis=None)
    allowed, retry = await limiter.check("key", 1, 60)
    assert allowed is True
    assert retry is None
