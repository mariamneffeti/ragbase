from __future__ import annotations

import logging
import time
import uuid

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

_LUA_RATE_LIMITER = """
local redis_key = KEYS[1]
local now = tonumber(ARGV[1])
local clear_before = ARGV[2]
local max_requests = tonumber(ARGV[3])
local window_seconds = tonumber(ARGV[4])
local request_id = ARGV[5]

redis.call('zremrangebyscore', redis_key, 0, '(' .. clear_before)

local current_count = redis.call('zcard', redis_key)

if current_count < max_requests then
    redis.call('zadd', redis_key, now, request_id)
    redis.call('expire', redis_key, window_seconds + 60)
    return {1, current_count + 1}
else
    return {0, current_count}
end
"""


class RateLimiterError(Exception):
    pass


class RateLimitExceededError(Exception):
    def __init__(self, tenant_id: str, endpoint: str, current: int, limit: int) -> None:
        self.tenant_id = tenant_id
        self.endpoint = endpoint
        self.current = current
        self.limit = limit
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
        now = time.time()
        redis_key = f"ratelimit:{tenant_id.replace(':', '_')}:{endpoint.replace(':', '_')}"
        clear_before = str(now - window_seconds)
        request_id = f"{now}:{uuid.uuid4().hex[:8]}"

        try:
            allowed, current_count = await self._script(
                keys=[redis_key],
                args=[now, clear_before, max_requests, window_seconds, request_id],
            )
            if not allowed:
                logger.warning(
                    "Rate limit exceeded for tenant '%s' on '%s': %d/%d in window.",
                    tenant_id,
                    endpoint,
                    current_count,
                    max_requests,
                )
                raise RateLimitExceededError(
                    tenant_id=tenant_id,
                    endpoint=endpoint,
                    current=current_count,
                    limit=max_requests,
                )
        except RateLimitExceededError:
            raise
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

    async def close(self) -> None:
        await self.redis.aclose()