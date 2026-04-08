"""Redis sliding window rate limiter."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis.asyncio as aioredis


class RateLimiterService:
    def __init__(self, redis: aioredis.Redis | None = None) -> None:
        self._redis = redis

    async def check(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int | None]:
        """Check rate limit. Returns (allowed, retry_after_seconds)."""
        if self._redis is None:
            return True, None

        now = time.time()
        window_start = now - window_seconds
        redis_key = f"ratelimit:{key}"

        pipe = self._redis.pipeline()
        pipe.zremrangebyscore(redis_key, "-inf", window_start)
        pipe.zadd(redis_key, {str(now): now})
        pipe.zcard(redis_key)
        pipe.expire(redis_key, window_seconds)
        results = await pipe.execute()

        count = results[2]
        if count > limit:
            # Over limit — remove the just-added entry
            await self._redis.zrem(redis_key, str(now))
            oldest = await self._redis.zrange(redis_key, 0, 0, withscores=True)
            if oldest:
                retry_after = int(window_seconds - (now - oldest[0][1])) + 1
                return False, max(retry_after, 1)
            return False, window_seconds

        return True, None
