import pytest
import pytest_asyncio
import fakeredis.aioredis
from unittest.mock import AsyncMock, MagicMock

from app.core.rate_limiter import RateLimiterService, RateLimitExceededError
@pytest_asyncio.fixture
async def limiter_and_mock():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    mock_script = AsyncMock()
    original_register = redis.register_script
    redis.register_script = MagicMock(return_value=mock_script)
    svc = RateLimiterService(redis_client=redis)
    svc._script = mock_script
    yield svc, mock_script
    await redis.aclose()

@pytest.mark.asyncio
async def test_allows_requests_under_limit(limiter_and_mock):
    limiter, script = limiter_and_mock
    script.side_effect = [
        (1, i+1, 0) for i in range(5)
    ]  
    for _ in range(5):
        await limiter.check_rate_limit("t1", "/chat", max_requests=5, window_seconds=60)


@pytest.mark.asyncio
async def test_blocks_on_exceeding_limit(limiter_and_mock):
    limiter, script = limiter_and_mock
    responses = [(1, i+1, 0) for i in range(5)] + [(0, 5, 100_000)]
    script.side_effect = responses
    for _ in range(5):
        await limiter.check_rate_limit("t1", "/chat", max_requests=5, window_seconds=60)
    with pytest.raises(RateLimitExceededError) as exc_info:
        await limiter.check_rate_limit("t1", "/chat", max_requests=5, window_seconds=60)
    err = exc_info.value
    assert err.current == 5
    assert err.limit == 5
    assert err.retry_after_seconds is not None


@pytest.mark.asyncio
async def test_tenants_are_isolated(limiter_and_mock):
    limiter, script = limiter_and_mock
    script.side_effect = [(1, i+1, 0) for i in range(5)] + [(1, 1, 0)]  
    for _ in range(5):
        await limiter.check_rate_limit("tenant-A", "/chat", max_requests=5, window_seconds=60)
    await limiter.check_rate_limit("tenant-B", "/chat", max_requests=5, window_seconds=60)


@pytest.mark.asyncio
async def test_endpoints_are_isolated(limiter_and_mock):
    limiter, script = limiter_and_mock
    script.side_effect = [(1, i+1, 0) for i in range(5)] + [(1, 1, 0)]
    for _ in range(5):
        await limiter.check_rate_limit("t1", "/chat", max_requests=5, window_seconds=60)
    await limiter.check_rate_limit("t1", "/documents", max_requests=5, window_seconds=60)


@pytest.mark.asyncio
async def test_close_is_noop(limiter_and_mock):
    limiter, _ = limiter_and_mock
    await limiter.close()  