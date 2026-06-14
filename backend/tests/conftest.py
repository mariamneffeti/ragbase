import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
import fakeredis.aioredis

from app.main import app
from app.core.rate_limiter import RateLimiterService

@pytest_asyncio.fixture
async def fake_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)

async def _fake_get_current_user():
    return {"sub": "tenant-1"}

@pytest_asyncio.fixture
async def client(fake_redis):
    app.state.redis = fake_redis
    app.state.rate_limiter = RateLimiterService(redis_client=fake_redis)
    llm_mock = MagicMock()
    llm_mock.generate_rag_response = AsyncMock(return_value="Hello world")
    app.state.llm_service = llm_mock
    with patch(
        "app.api.dependencies.auth.get_current_user",
        side_effect=_fake_get_current_user,
    ):
        with patch.object(
            app.state.rate_limiter, "check_rate_limit", new_callable=AsyncMock
        ) as mock_check:
            mock_check.return_value = None
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ac

@pytest.fixture
def mock_pinecone_index():
    from app.services.vector_store import _get_client, _get_index
    _get_client.cache_clear()
    _get_index.cache_clear()

    with patch("app.services.vector_store._get_index") as mock_get_index, \
         patch("app.services.vector_store._get_client") as mock_get_client:

        index = MagicMock()
        index.upsert = MagicMock()
        index.query = MagicMock(return_value=MagicMock(matches=[]))
        index.delete = MagicMock()
        index.list = MagicMock(return_value=[])
        index.list_paginated = MagicMock(return_value=MagicMock(vectors=[], pagination=None))
        mock_get_index.return_value = index

        client = MagicMock()
        fake_embedding = [0.1] * 1024
        embed_response = MagicMock()
        embed_response.data = [MagicMock(values=fake_embedding)]
        client.inference.embed = MagicMock(return_value=embed_response)
        mock_get_client.return_value = client

        yield index

@pytest.fixture
def mock_llm_stream():
    with patch(
        "app.services.llm.LLMService.generate_rag_response",
        return_value="Hello world",
    ):
        yield

@pytest.fixture
def upload_file_factory():
    import io
    from fastapi import UploadFile
    def _create(filename: str, content: bytes, content_type: str) -> UploadFile:
        return UploadFile(
            filename=filename,
            file=io.BytesIO(content),
            headers={"content-type": content_type},
        )
    return _create