# tests/test_user_modeler.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.intelligence.memory.user_modeler import UserModeler


def _make(users, active_by_user):
    db = MagicMock()
    db.get_users_with_recent_facts = AsyncMock(return_value=users)
    db.get_active_facts_for_user = AsyncMock(side_effect=lambda uid, **k: active_by_user.get(uid, []))
    db.get_superseded_facts_for_user = AsyncMock(return_value=[{"content": "détestait le solo", "category": "PREF"}])
    db.get_trust_score = AsyncMock(return_value=0.5)
    db.get_love_score = AsyncMock(return_value=0.2)
    db.upsert_user_profile = AsyncMock()
    llm = MagicMock()
    llm.complete_structured = AsyncMock(return_value={"portrait": "portrait test"})
    return UserModeler(db, llm), db, llm


@pytest.mark.asyncio
async def test_no_users_is_noop():
    c, db, llm = _make([], {})
    await c.refresh_profiles(since="2026-06-28T00:00:00")
    db.upsert_user_profile.assert_not_awaited()
    llm.complete_structured.assert_not_awaited()


@pytest.mark.asyncio
async def test_user_without_active_facts_skipped():
    c, db, llm = _make(["discord:1"], {"discord:1": []})
    await c.refresh_profiles(since="2026-06-28T00:00:00")
    db.upsert_user_profile.assert_not_awaited()


@pytest.mark.asyncio
async def test_portrait_generated_with_dialectic_material():
    active = {"discord:1": [{"content": "aime la stratégie", "category": "PREF"}]}
    c, db, llm = _make(["discord:1"], active)
    await c.refresh_profiles(since="2026-06-28T00:00:00")
    # trust/love appelés avec l'id BRUT (sans préfixe)
    db.get_trust_score.assert_awaited_with("discord", "1")
    # la matière dialectique (faits révolus) est passée au LLM
    payload = llm.complete_structured.await_args.args[1][0]["content"]
    assert "aime la stratégie" in payload
    assert "détestait le solo" in payload
    db.upsert_user_profile.assert_awaited_once_with("discord:1", "portrait test")


@pytest.mark.asyncio
async def test_users_isolated_on_error():
    active = {"discord:1": [{"content": "f1", "category": "FAIT"}],
              "discord:2": [{"content": "f2", "category": "FAIT"}]}
    c, db, llm = _make(["discord:1", "discord:2"], active)
    async def boom(prompt, messages, schema, **k):
        if "f1" in messages[0]["content"]:
            raise RuntimeError("LLM down for user 1")
        return {"portrait": "ok"}
    llm.complete_structured.side_effect = boom
    await c.refresh_profiles(since="2026-06-28T00:00:00")
    upserted = [call.args[0] for call in db.upsert_user_profile.await_args_list]
    assert "discord:2" in upserted and "discord:1" not in upserted
