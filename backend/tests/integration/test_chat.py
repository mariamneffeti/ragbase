import pytest
from app.main import app
from app.api.dependencies.auth import get_current_user

CHAT_URL = "/api/v1/chat/query"

async def fake_get_current_user():
    return {"sub": "tenant-1"}

@pytest.mark.asyncio
async def test_chat_returns_response(client, mock_llm_stream, mock_pinecone_index):
    response = await client.post(
        CHAT_URL,
        headers={"X-Tenant-ID": "tenant-1"},
        json={"message": "Hello"},
    )
    assert response.status_code == 200
    assert "Hello world" in response.text

@pytest.mark.asyncio
async def test_chat_rate_limited_after_quota(client, mock_llm_stream, mock_pinecone_index):
    from app.core.rate_limiter import RateLimitExceededError
    original_check = app.state.rate_limiter.check_rate_limit
    async def mock_check(*args, **kwargs):
        mock_check.counter += 1
        if mock_check.counter > 5:
            raise RateLimitExceededError("tenant-1", "chat:query", 5, 5, retry_after_seconds=10)
        return None
    mock_check.counter = 0
    app.state.rate_limiter.check_rate_limit = mock_check

    for _ in range(5):
        resp = await client.post(
            CHAT_URL,
            headers={"X-Tenant-ID": "tenant-1"},
            json={"message": "ping"},
        )
        assert resp.status_code == 200

    resp = await client.post(
        CHAT_URL,
        headers={"X-Tenant-ID": "tenant-1"},
        json={"message": "ping"},
    )
    assert resp.status_code == 429
    assert "retry-after" in resp.headers

    app.state.rate_limiter.check_rate_limit = original_check