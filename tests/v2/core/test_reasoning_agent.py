import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.v2.core.reasoning_agent import ReasoningAgent, ReasoningResult
from bot.v2.core.attention_agent import AttentionContext
from bot.v2.core.memory.facts import SQLiteFactStore, FactCategory, FactStatus


def _make_context(emotion=None) -> AttentionContext:
    return AttentionContext(
        emotion_state=emotion or {"joy": 0.5},
        active_desires=[],
        active_goals=[],
        recent_thoughts=[],
        recent_interactions=[{"channel": "1", "author": "Alice", "content": "hello", "ts": 0.0}],
        time_of_day="evening",
    )


class FakeLLM:
    """Renvoie un tuple scripté (content, reasoning) comme DeepSeek.complete_with_reasoning."""

    def __init__(self, content: str, reasoning: str):
        self._content = content
        self._reasoning = reasoning
        self.calls: list = []

    async def complete_with_reasoning(self, system_prompt, messages, **kwargs):
        self.calls.append((system_prompt, messages))
        return self._content, self._reasoning


def _make_agent(tmp_path, content, reasoning, db_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "reasoning_system.md").write_text("System reasoning test")
    fact_store = SQLiteFactStore(db_path)
    llm = FakeLLM(content, reasoning)
    return ReasoningAgent(llm, fact_store, prompts_dir), llm, fact_store


@pytest.mark.asyncio
async def test_reason_stores_reasoning_as_thought(tmp_path, tmp_db_path):
    agent, llm, fact_store = _make_agent(
        tmp_path, content="[THINK]", reasoning="Je m'ennuie ferme ce soir.", db_path=tmp_db_path
    )
    result = await agent.reason(_make_context())
    assert isinstance(result, ReasoningResult)
    # La pensée privée (reasoning) est stockée en THOUGHT.
    assert result.thought_text == "Je m'ennuie ferme ce soir."
    assert result.thought_fact_id is not None
    thoughts = await fact_store.search_by_category(FactCategory.THOUGHT, status=FactStatus.ACTIVE, limit=5)
    assert any(t.content == "Je m'ennuie ferme ce soir." and t.user_id == "wally:self" for t in thoughts)


@pytest.mark.asyncio
async def test_reason_parses_content_into_decisions(tmp_path, tmp_db_path):
    agent, _, _ = _make_agent(
        tmp_path,
        content='[SPEAK 123 "salut"]',
        reasoning="J'ai envie de parler à Alice.",
        db_path=tmp_db_path,
    )
    result = await agent.reason(_make_context())
    assert len(result.decisions) == 1
    d = result.decisions[0]
    assert d.action == "SPEAK"
    assert d.channel_id == "123"
    assert d.message == "salut"


@pytest.mark.asyncio
async def test_reason_fallback_think_when_content_empty(tmp_path, tmp_db_path):
    agent, _, _ = _make_agent(
        tmp_path, content="", reasoning="Je rumine dans le vide.", db_path=tmp_db_path
    )
    result = await agent.reason(_make_context())
    # Content vide → fallback [THINK], mais le reasoning reste la pensée.
    assert [d.action for d in result.decisions] == ["THINK"]
    assert result.thought_text == "Je rumine dans le vide."


@pytest.mark.asyncio
async def test_reason_thought_text_prefers_reasoning(tmp_path, tmp_db_path):
    agent, _, _ = _make_agent(
        tmp_path, content="[THINK]", reasoning="pensée privée", db_path=tmp_db_path
    )
    result = await agent.reason(_make_context())
    assert result.thought_text == "pensée privée"


@pytest.mark.asyncio
async def test_reason_both_empty_on_llm_error(tmp_path, tmp_db_path):
    # complete_with_reasoning retourne ("", "") en cas d'erreur LLM.
    agent, _, _ = _make_agent(tmp_path, content="", reasoning="", db_path=tmp_db_path)
    result = await agent.reason(_make_context())
    assert result.thought_text == ""
    assert result.thought_fact_id is None
    assert [d.action for d in result.decisions] == ["THINK"]


@pytest.mark.asyncio
async def test_reason_passes_system_prompt(tmp_path, tmp_db_path):
    agent, llm, _ = _make_agent(
        tmp_path, content="[THINK]", reasoning="x", db_path=tmp_db_path
    )
    await agent.reason(_make_context())
    assert llm.calls
    system_arg = llm.calls[0][0]
    assert system_arg == "System reasoning test"
