import pytest
from httpx import AsyncClient
from prometheus.main import app


@pytest.mark.asyncio
async def test_ping() -> None:
    """Test the /ping health check endpoint."""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/ping")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_chat_stub() -> None:
    """Test the chat SSE stub endpoint."""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post("/api/v1/chat/stream")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
