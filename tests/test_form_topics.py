import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.intelligence.journal import DailyJournal


def _journal():
    config = MagicMock()
    config.bot.name = "Wally"
    j = DailyJournal(config, MagicMock(), MagicMock(), MagicMock(), MagicMock(), db=MagicMock())
    return j


@pytest.mark.asyncio
async def test_form_topics_resolves_participants_and_upserts():
    j = _journal()
    j._db.get_topics = AsyncMock(return_value=[{"name": "Apex"}])
    j._db.upsert_topic = AsyncMock()
    j._db.cleanup_topics = AsyncMock()
    j._llm_secondary.complete_structured = AsyncMock(return_value={
        "topics": [{"name": "Apex", "summary": "chaud", "participants": ["Azrael", "Inconnu"], "opinion": "surcoté"}]
    })
    # alias cache : Azrael connu, Inconnu non
    j._memory._alias_cache = {"nickname:azrael": "discord:123"}
    await j._form_topics("résumé du jour")
    # noms existants injectés au prompt (anti-fragmentation)
    payload = j._llm_secondary.complete_structured.await_args.args[1][0]["content"]
    assert "Apex" in payload
    # participants résolus : Azrael→uid, Inconnu→nom brut
    args = j._db.upsert_topic.await_args.args
    parts = args[2]
    assert {"name": "Azrael", "uid": "discord:123"} in parts
    assert {"name": "Inconnu", "uid": None} in parts


@pytest.mark.asyncio
async def test_form_topics_non_fatal_on_llm_error():
    j = _journal()
    j._db.get_topics = AsyncMock(return_value=[])
    j._db.upsert_topic = AsyncMock()
    j._db.cleanup_topics = AsyncMock()
    j._llm_secondary.complete_structured = AsyncMock(side_effect=RuntimeError("LLM down"))
    j._memory._alias_cache = {}
    await j._form_topics("résumé")  # ne lève pas
    j._db.upsert_topic.assert_not_awaited()
