"""Redis sliding window rate limiter — atomic Lua implementation."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    import redis.asyncio as aioredis

log = structlog.get_logger()

# Lua script runs atomically inside Redis (single-threaded eval).
# Arguments:
#   KEYS[1]  — the sorted-set key
#   ARGV[1]  — window_start  (now - window_seconds, as float string)
#   ARGV[2]  — member        (unique member string: "<timestamp_ns>:<random_hex>")
#   ARGV[3]  — now           (current timestamp, as float string — used as score)
#   ARGV[4]  — limit         (integer)
#   ARGV[5]  — window_seconds (TTL, integer)
#
# Returns a three-element array: {count, allowed, oldest_score}
#   allowed == 1  → request permitted
#   allowed == 0  → request denied; oldest_score is the score of the oldest
#                   remaining entry (used to compute retry_after)
_RATE_LIMIT_LUA = """
local key          = KEYS[1]
local window_start = tonumber(ARGV[1])
local member       = ARGV[2]
local now          = tonumber(ARGV[3])
local limit        = tonumber(ARGV[4])
local ttl          = tonumber(ARGV[5])

redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)
redis.call('ZADD', key, now, member)
local count = redis.call('ZCARD', key)
redis.call('EXPIRE', key, ttl)

if count > limit then
    redis.call('ZREM', key, member)
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local oldest_score = 0
    if #oldest > 0 then
        oldest_score = tonumber(oldest[2])
    end
    return {count, 0, oldest_score}
end

return {count, 1, 0}
"""


@dataclass(slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int | None = None
    backend_available: bool = True


class RateLimiterService:
    def __init__(self, redis: aioredis.Redis | None = None) -> None:
        self._redis = redis

    async def check(self, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        """Check rate limit and report whether the backend was available."""
        if self._redis is None:
            return RateLimitDecision(allowed=False, retry_after=None, backend_available=False)

        now = time.time()
        window_start = now - window_seconds
        redis_key = f"ratelimit:{key}"
        member = f"{time.time_ns()}:{os.urandom(4).hex()}"

        try:
            result: list[int] = await self._redis.eval(
                _RATE_LIMIT_LUA,
                1,
                redis_key,
                str(window_start),
                member,
                str(now),
                str(limit),
                str(window_seconds),
            )
        except Exception:
            log.warning("rate_limiter_redis_error", key=key)
            return RateLimitDecision(allowed=False, retry_after=None, backend_available=False)

        _count, allowed_flag, oldest_score = result[0], result[1], result[2]

        if allowed_flag == 1:
            return RateLimitDecision(allowed=True, retry_after=None, backend_available=True)

        # Compute retry_after from oldest entry's score
        retry_after = int(window_seconds - (now - oldest_score)) + 1 if oldest_score > 0 else window_seconds

        return RateLimitDecision(allowed=False, retry_after=max(retry_after, 1), backend_available=True)
