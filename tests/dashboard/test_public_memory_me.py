import pytest
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.mark.asyncio
async def test_memory_me_unauthenticated(async_client):
    from bot.dashboard.routes import chat as chat_routes
    with patch.object(chat_routes, "_extract_user_id_from_jwt", return_value=None):
        resp = await async_client.get("/api/public/memory/me")
    assert resp.status_code == 401
