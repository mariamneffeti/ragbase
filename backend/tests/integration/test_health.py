import pytest
from unittest.mock import AsyncMock, patch
from app.main import app

@pytest.mark.asyncio
async def test_health_ok(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

@pytest.mark.asyncio
async def test_health_degraded_when_redis_down(client):
    with patch.object(app.state.redis, "ping", side_effect=Exception("timeout")):
        response = await client.get("/health")
    assert response.status_code == 503
    assert response.json()["redis"] == "unreachable"