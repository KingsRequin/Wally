import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_list_journal_returns_entries(async_client):
    entries = [
        {"date": "2026-04-03", "content": "Journée animée.", "word_count": 342, "created_at": "2026-04-03T23:00:00"},
        {"date": "2026-04-02", "content": "Journée calme.", "word_count": 231, "created_at": "2026-04-02T23:00:00"},
    ]
    async_client.app.state.wally.db.get_journal_entries = AsyncMock(return_value=entries)
    resp = await async_client.get("/api/public/journal")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["entries"]) == 2
    assert data["entries"][0]["date"] == "2026-04-03"


@pytest.mark.asyncio
async def test_list_journal_limit_param(async_client):
    async_client.app.state.wally.db.get_journal_entries = AsyncMock(return_value=[])
    resp = await async_client.get("/api/public/journal?limit=5")
    assert resp.status_code == 200
    async_client.app.state.wally.db.get_journal_entries.assert_called_once_with(limit=5)
