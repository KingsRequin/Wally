import time
import pytest
from bot.db.database import Database

@pytest.fixture
async def db(tmp_path):
    d = await Database.create(str(tmp_path / "test.db"))
    yield d
    await d._conn.close()

@pytest.mark.asyncio
async def test_create_and_get_invite(db):
    await db.create_setup_invite("tok123", expires_at=time.time() + 86400)
    row = await db.get_setup_invite("tok123")
    assert row is not None
    assert row["token"] == "tok123"
    assert row["is_preview"] == 0
    assert row["used_at"] is None

@pytest.mark.asyncio
async def test_create_preview_invite(db):
    await db.create_setup_invite("__preview__", expires_at=None, is_preview=1)
    row = await db.get_setup_invite("__preview__")
    assert row["is_preview"] == 1
    assert row["expires_at"] is None

@pytest.mark.asyncio
async def test_use_invite(db):
    await db.create_setup_invite("tok456", expires_at=time.time() + 86400)
    await db.use_setup_invite("tok456", slug="cindy", port=8081)
    row = await db.get_setup_invite("tok456")
    assert row["used_at"] is not None
    assert row["slug"] == "cindy"
    assert row["port"] == 8081

@pytest.mark.asyncio
async def test_revoke_invite(db):
    await db.create_setup_invite("tok789", expires_at=time.time() + 86400)
    await db.revoke_setup_invite("tok789")
    row = await db.get_setup_invite("tok789")
    assert row["expires_at"] < time.time()

@pytest.mark.asyncio
async def test_list_invites(db):
    await db.create_setup_invite("t1", expires_at=time.time() + 86400)
    await db.create_setup_invite("t2", expires_at=time.time() + 86400)
    rows = await db.list_setup_invites()
    tokens = [r["token"] for r in rows]
    assert "t1" in tokens and "t2" in tokens

@pytest.mark.asyncio
async def test_session_save_and_get(db):
    await db.save_setup_session("tok1", {"discord_token": "abc"})
    data = await db.get_setup_session("tok1")
    assert data["discord_token"] == "abc"

@pytest.mark.asyncio
async def test_session_merge(db):
    await db.save_setup_session("tok1", {"step1": "a"})
    await db.save_setup_session("tok1", {"step2": "b"})
    data = await db.get_setup_session("tok1")
    assert data["step1"] == "a"
    assert data["step2"] == "b"

@pytest.mark.asyncio
async def test_next_port_default(db):
    port = await db.next_setup_port()
    assert port == 8081

@pytest.mark.asyncio
async def test_next_port_increments(db):
    await db.create_setup_invite("t1", expires_at=time.time() + 86400)
    await db.use_setup_invite("t1", slug="a", port=8081)
    port = await db.next_setup_port()
    assert port == 8082
