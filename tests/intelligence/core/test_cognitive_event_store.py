import pytest
from bot.db.schema_v2 import create_v2_tables
from bot.intelligence.cognitive_event_store import CognitiveEventStore


@pytest.fixture
async def store(tmp_path):
    db_path = str(tmp_path / "wally.db")
    await create_v2_tables(db_path)
    return CognitiveEventStore(db_path, cap=5)


@pytest.mark.asyncio
async def test_append_and_recent_roundtrip(store):
    await store.append({"type": "THINK", "text": "bonjour"})
    rows = await store.recent(limit=10)
    assert len(rows) == 1
    assert rows[0]["type"] == "THINK"
    assert rows[0]["text"] == "bonjour"
    assert isinstance(rows[0]["id"], int)
    assert isinstance(rows[0]["ts"], float)


@pytest.mark.asyncio
async def test_recent_is_descending(store):
    for i in range(3):
        await store.append({"type": "ACT", "detail": f"a{i}"})
    rows = await store.recent(limit=10)
    assert [r["detail"] for r in rows] == ["a2", "a1", "a0"]


@pytest.mark.asyncio
async def test_rotation_caps_rows(store):
    for i in range(12):
        await store.append({"type": "ACT", "detail": f"a{i}"})
    rows = await store.recent(limit=100)
    assert len(rows) == 5                      # cap respecté
    assert rows[0]["detail"] == "a11"          # le plus récent gardé


@pytest.mark.asyncio
async def test_recent_pagination_before_id(store):
    ids = []
    for i in range(4):
        await store.append({"type": "ACT", "detail": f"a{i}"})
    rows = await store.recent(limit=10)
    mid = rows[1]["id"]                          # 3e plus récent commence après
    older = await store.recent(limit=10, before_id=mid)
    assert all(r["id"] < mid for r in older)
