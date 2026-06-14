from __future__ import annotations

import logging
import time
import uuid

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_LUA_RATE_LIMITER = """
local redis_key   = KEYS[1]
local now         = tonumber(ARGV[1])
local clear_before = tonumber(ARGV[2])
local max_requests = tonumber(ARGV[3])
local window_seconds = tonumber(ARGV[4])
local request_id  = ARGV[5]

redis.call('zremrangebyscore', redis_key, 0, clear_before)
local current_count = redis.call('zcard', redis_key)

if current_count < max_requests then
    redis.call('zadd', redis_key, now, request_id)
    redis.call('expire', redis_key, window_seconds)
    return {1, current_count + 1, 0}
else
    -- Return the score (ms timestamp) of the oldest entry so the caller can
    -- compute an accurate retry-after value rather than using the full window.
    local oldest = redis.call('zrange', redis_key, 0, 0, 'WITHSCORES')
    local oldest_ms = oldest[2] and tonumber(oldest[2]) or now
    return {0, current_count, oldest_ms}
end
"""


class RateLimiterError(Exception):
    pass


class RateLimitExceededError(Exception):
    def __init__(
        self,
        tenant_id: str,
        endpoint: str,
        current: int,
        limit: int,
        retry_after_seconds: float | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.endpoint = endpoint
        self.current = current
        self.limit = limit
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"Rate limit exceeded for tenant '{tenant_id}' on '{endpoint}': "
            f"{current}/{limit} requests in window."
        )


class RateLimiterService:
    def __init__(self, redis_client: aioredis.Redis) -> None:
        self.redis = redis_client
        self._script = self.redis.register_script(_LUA_RATE_LIMITER)

    async def check_rate_limit(
        self,
        tenant_id: str,
        endpoint: str,
        max_requests: int,
        window_seconds: int,
    ) -> None:
        now_ms = int(time.time() * 1000)
        redis_key = (
            f"ratelimit:{tenant_id.replace(':', '_')}:{endpoint.replace(':', '_')}"
        )
        clear_before = now_ms - (window_seconds * 1000)
        request_id = uuid.uuid4().hex

        try:
            allowed, current_count, oldest_ms = await self._script(
                keys=[redis_key],
                args=[now_ms, clear_before, max_requests, window_seconds, request_id],
            )
        except aioredis.RedisError as exc:
            logger.error(
                "Redis fault during rate-limit check for tenant '%s' on '%s'",
                tenant_id,
                endpoint,
                exc_info=True,
            )
            raise RateLimiterError(
                "Rate limiter subsystem experienced a backing store failure."
            ) from exc

        if not allowed:
            slot_frees_at_ms = oldest_ms + (window_seconds * 1000)
            retry_after = max(0.0, min((slot_frees_at_ms - now_ms) / 1000.0, float(window_seconds)))

            logger.warning(
                "Rate limit exceeded | tenant=%s endpoint=%s count=%d limit=%d retry_after=%.2fs",
                tenant_id, endpoint, current_count, max_requests, retry_after,
            )
            raise RateLimitExceededError(
                tenant_id=tenant_id,
                endpoint=endpoint,
                current=current_count,
                limit=max_requests,
                retry_after_seconds=retry_after,
            )

    async def close(self) -> None:
        pass