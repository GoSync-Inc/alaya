"""Redis sliding window rate limiter — atomic Lua implementation."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis.asyncio as aioredis

# Lua script runs atomically inside Redis (single-threaded eval).
# Arguments:
#   KEYS[1]  — the sorted-set key
#   ARGV[1]  — window_start  (now - window_seconds, as float string)
#   ARGV[2]  — now           (current timestamp, as float string)
#   ARGV[3]  — limit         (integer)
#   ARGV[4]  — window_seconds (TTL, integer)
#
# Returns a three-element array: {count, allowed, oldest_score}
#   allowed == 1  → request permitted
#   allowed == 0  → request denied; oldest_score is the score of the oldest
#                   remaining entry (used to compute retry_after)
_RATE_LIMIT_LUA = """
local key          = KEYS[1]
local window_start = tonumber(ARGV[1])
local now          = tonumber(ARGV[2])
local limit        = tonumber(ARGV[3])
local ttl          = tonumber(ARGV[4])

redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)
redis.call('ZADD', key, now, tostring(now))
local count = redis.call('ZCARD', key)
redis.call('EXPIRE', key, ttl)

if count > limit then
    redis.call('ZREM', key, tostring(now))
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local oldest_score = 0
    if #oldest > 0 then
        oldest_score = tonumber(oldest[2])
    end
    return {count, 0, oldest_score}
end

return {count, 1, 0}
"""


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

        result: list[int] = await self._redis.eval(
            _RATE_LIMIT_LUA,
            1,
            redis_key,
            str(window_start),
            str(now),
            str(limit),
            str(window_seconds),
        )

        _count, allowed_flag, oldest_score = result[0], result[1], result[2]

        if allowed_flag == 1:
            return True, None

        # Compute retry_after from oldest entry's score
        if oldest_score:
            retry_after = int(window_seconds - (now - oldest_score)) + 1
        else:
            retry_after = window_seconds

        return False, max(retry_after, 1)
