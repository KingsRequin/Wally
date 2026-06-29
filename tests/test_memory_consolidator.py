# tests/test_memory_consolidator.py
"""Tests TDD pour MemoryConsolidator — source = daily_log, résumé seul."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.intelligence.memory.consolidator import MemoryConsolidator


def _make(rows):
    db = MagicMock()
    db.get_today_messages = AsyncMock(return_value=rows)
    db.insert_session_analysis = AsyncMock()
    llm = MagicMock()
    llm.complete_structured = AsyncMock(return_value={"summary": "résumé test"})
    return MemoryConsolidator(db, llm), db, llm


def _msg(ch, author="Alice", content="coucou les amis ça va"):
    return {
        "channel_id": ch,
        "platform": "discord",
        "author": author,
        "content": content,
        "timestamp": 1.0,
    }


@pytest.mark.asyncio
async def test_no_messages_is_noop():
    c, db, llm = _make([])
    await c.consolidate_day()
    db.insert_session_analysis.assert_not_awaited()


@pytest.mark.asyncio
async def test_channel_below_two_messages_skipped():
    c, db, llm = _make([_msg("A")])
    await c.consolidate_day()
    db.insert_session_analysis.assert_not_awaited()


@pytest.mark.asyncio
async def test_channel_summarized():
    rows = [_msg("A", author="Alice"), _msg("A", author="Bob", content="salut ça roule")]
    c, db, llm = _make(rows)
    await c.consolidate_day()

    db.insert_session_analysis.assert_awaited_once()
    args = db.insert_session_analysis.await_args.args
    assert args[1] == "discord"      # platform
    assert args[2] == "A"            # channel_id
    assert args[3] == "résumé test"  # summary

    # La convo passée au LLM doit contenir le contenu des messages
    call_args = llm.complete_structured.await_args
    user_content = call_args.args[1][0]["content"]
    assert "coucou les amis ça va" in user_content
    assert "salut ça roule" in user_content


@pytest.mark.asyncio
async def test_channels_isolated_on_error():
    rows = [
        _msg("A", author="AliceA", content="message du canal A"),
        _msg("A", author="AliceA", content="encore canal A"),
        _msg("B", author="BobB", content="message du canal B"),
        _msg("B", author="BobB", content="encore canal B"),
    ]
    c, db, llm = _make(rows)

    async def side_effect(system, messages, schema, **kwargs):
        if "canal A" in messages[0]["content"]:
            raise RuntimeError("boom canal A")
        return {"summary": "résumé test"}

    llm.complete_structured.side_effect = side_effect
    await c.consolidate_day()  # ne doit pas lever

    inserted = [call.args[2] for call in db.insert_session_analysis.await_args_list]
    assert "B" in inserted
    assert "A" not in inserted


@pytest.mark.asyncio
async def test_llm_failure_no_insert():
    rows = [_msg("A"), _msg("A", author="Bob")]
    c, db, llm = _make(rows)
    llm.complete_structured.side_effect = RuntimeError("boom LLM")
    await c.consolidate_day()  # ne doit pas lever
    db.insert_session_analysis.assert_not_awaited()
