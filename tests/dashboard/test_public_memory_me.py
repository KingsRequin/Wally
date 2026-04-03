import pytest
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.mark.asyncio
async def test_memory_me_returns_data(async_client):
    from bot.dashboard.routes import chat as chat_routes
    memory_records = [
        MagicMock(text="Aime la musique", category="PREF"),
        MagicMock(text="S'appelle Nocturne", category="FAIT"),
    ]
    async_client.app.state.wally.memory.store.get_all = AsyncMock(return_value=memory_records)
    async_client.app.state.wally.db.get_trust_score = AsyncMock(return_value=0.7)
    async_client.app.state.wally.db.get_love_score = AsyncMock(return_value=0.5)

    with patch.object(chat_routes, "_extract_user_id_from_jwt", return_value="discord:123456789"):
        resp = await async_client.get("/api/public/memory/me", headers={"Authorization": "Bearer faketoken"})

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["facts"]) == 1
    assert len(data["preferences"]) == 1
    assert data["relation"]["trust"] == pytest.approx(0.7)

@pytest.mark.asyncio
async def test_memory_me_unauthenticated(async_client):
    from bot.dashboard.routes import chat as chat_routes
    with patch.object(chat_routes, "_extract_user_id_from_jwt", return_value=None):
        resp = await async_client.get("/api/public/memory/me")
    assert resp.status_code == 401
