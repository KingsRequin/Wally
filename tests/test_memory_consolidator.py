# tests/test_memory_consolidator.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.intelligence.memory.consolidator import MemoryConsolidator


def _make(rows):
    db = MagicMock()
    db.get_recent_session_messages = AsyncMock(return_value=rows)
    db.insert_session_analysis = AsyncMock()
    fact_extractor = MagicMock()
    fact_extractor._extract_facts = AsyncMock(return_value=1)
    llm = MagicMock()
    llm.complete_structured = AsyncMock(return_value={"summary": "résumé test"})
    memory = MagicMock()
    return MemoryConsolidator(db, llm, fact_extractor, memory), db, fact_extractor, llm


def _msg(ch, uid="1", name="Alice", content="coucou les amis ça va"):
    return {"channel_id": ch, "platform": "discord", "user_id": uid,
            "display_name": name, "content": content, "timestamp": 1.0}


@pytest.mark.asyncio
async def test_no_messages_is_noop():
    c, db, fx, llm = _make([])
    await c.consolidate_day(since=0.0)
    fx._extract_facts.assert_not_awaited()
    db.insert_session_analysis.assert_not_awaited()


@pytest.mark.asyncio
async def test_channel_below_two_messages_skipped():
    c, db, fx, llm = _make([_msg("A")])
    await c.consolidate_day(since=0.0)
    fx._extract_facts.assert_not_awaited()


@pytest.mark.asyncio
async def test_channel_extracts_and_summarizes():
    rows = [_msg("A", "1"), _msg("A", "2", "Bob")]
    c, db, fx, llm = _make(rows)
    await c.consolidate_day(since=0.0)
    fx._extract_facts.assert_awaited_once()
    args = fx._extract_facts.await_args.args
    assert args[1] == "discord" and args[2] == "A"
    db.insert_session_analysis.assert_awaited_once()
    ins = db.insert_session_analysis.await_args.args
    assert ins[1] == "discord" and ins[2] == "A" and ins[3] == "résumé test"


@pytest.mark.asyncio
async def test_channels_isolated_on_error():
    rows = [_msg("A", "1"), _msg("A", "2"), _msg("B", "1"), _msg("B", "2")]
    c, db, fx, llm = _make(rows)
    # Le canal A lève, B doit quand même être traité
    async def boom(messages, platform, channel_id, origin=None):
        if channel_id == "A":
            raise RuntimeError("extract fail A")
        return 1
    fx._extract_facts.side_effect = boom
    await c.consolidate_day(since=0.0)
    # B a produit un résumé malgré l'échec de A
    inserted_channels = [call.args[2] for call in db.insert_session_analysis.await_args_list]
    assert "B" in inserted_channels and "A" not in inserted_channels
