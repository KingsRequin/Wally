import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from bot.intelligence.inner_monologue import InnerMonologue, MonologueResult
from bot.intelligence.attention_agent import AttentionContext


def _make_context(emotion=None) -> AttentionContext:
    return AttentionContext(
        emotion_state=emotion or {"joy": 0.5},
        active_desires=[],
        active_goals=[],
        recent_thoughts=[],
        recent_interactions=[{"channel": "1", "author": "Alice", "content": "hello", "ts": 0.0}],
        time_of_day="evening",
    )


def _make_monologue(tmp_path, llm_response="Je pense donc je suis."):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "inner_monologue_system.md").write_text("System prompt test")
    (prompts_dir / "meta_agent_system.md").write_text("Meta system test")

    llm = MagicMock()
    llm.complete = AsyncMock(return_value=llm_response)
    fact_store = MagicMock()
    fact_store.add = AsyncMock(return_value=42)
    return InnerMonologue(llm, fact_store, prompts_dir), llm, fact_store


@pytest.mark.asyncio
async def test_generate_returns_monologue_result(tmp_path):
    mono, _, _ = _make_monologue(tmp_path)
    ctx = _make_context()
    result = await mono.generate(ctx)
    assert isinstance(result, MonologueResult)
    assert result.text == "Je pense donc je suis."
    assert result.thought_fact_id == 42


@pytest.mark.asyncio
async def test_generate_stores_thought_fact(tmp_path):
    mono, _, fact_store = _make_monologue(tmp_path)
    ctx = _make_context()
    await mono.generate(ctx)
    fact_store.add.assert_called_once()
    added_fact = fact_store.add.call_args.args[0]
    from bot.intelligence.memory.facts import FactCategory
    assert added_fact.category == FactCategory.THOUGHT
    assert added_fact.user_id == "wally:self"
    assert added_fact.content == "Je pense donc je suis."


@pytest.mark.asyncio
async def test_generate_calls_llm_with_system(tmp_path):
    mono, llm, _ = _make_monologue(tmp_path, llm_response="pensée")
    ctx = _make_context()
    await mono.generate(ctx)
    llm.complete.assert_called_once()
    system_arg = llm.complete.call_args.args[0]
    assert system_arg == "System prompt test"


@pytest.mark.asyncio
async def test_generate_formats_emotion_in_user_message(tmp_path):
    mono, llm, _ = _make_monologue(tmp_path, llm_response="pensée")
    ctx = _make_context(emotion={"joy": 0.9, "anger": 0.1})
    await mono.generate(ctx)
    user_msg = llm.complete.call_args.args[1][0]["content"]
    assert "joy" in user_msg


@pytest.mark.asyncio
async def test_active_desires_render_with_id(tmp_path):
    """Les désirs sont présentés avec leur #id pour que Wally puisse en cibler
    un précisément via drop_desire {"desire_id": N}."""
    from bot.intelligence.memory.facts import AtomicFact, FactCategory
    mono, llm, _ = _make_monologue(tmp_path, llm_response="pensée")
    ctx = _make_context()
    ctx.active_desires = [
        AtomicFact(user_id="wally:self", content="lancer le sujet zedd", category=FactCategory.DESIRE, id=4015),
    ]
    await mono.generate(ctx)
    user_msg = llm.complete.call_args.args[1][0]["content"]
    assert "#4015" in user_msg
    assert "lancer le sujet zedd" in user_msg
