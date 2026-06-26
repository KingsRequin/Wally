from bot.intelligence.attention_agent import AttentionContext
from bot.intelligence.reasoning_agent import ReasoningAgent


def make_agent():
    return ReasoningAgent(
        llm=None, fact_store=None,
        prompts_dir="bot/intelligence/persona/prompts",
        channel_names={"111": "general", "222": "chambre-de-wally"},
    )


def base_ctx(interactions):
    return AttentionContext(
        emotion_state={"joy": 0.5}, active_desires=[], active_goals=[],
        recent_thoughts=[], recent_interactions=interactions, time_of_day="evening",
    )


def test_render_groups_by_channel_with_names():
    ctx = base_ctx([
        {"channel": "111", "author": "KingsRequin", "content": "salut le général", "is_dm": False},
        {"channel": "222", "author": "KingsRequin", "content": "salut la chambre", "is_dm": False},
    ])
    out = make_agent()._format_context(ctx)
    assert "#general" in out and "#chambre-de-wally" in out
    # Chaque message est sous le bon bloc, pas mélangé
    gen = out.index("#general"); cha = out.index("#chambre-de-wally")
    assert "salut le général" in out and "salut la chambre" in out


def test_render_marks_dm_block_private():
    ctx = base_ctx([
        {"channel": "999", "author": "KingsRequin", "content": "un truc privé", "is_dm": True},
    ])
    out = make_agent()._format_context(ctx)
    assert "DM privé avec KingsRequin" in out
    assert "un truc privé" in out


def test_render_includes_anti_leak_instruction():
    ctx = base_ctx([
        {"channel": "111", "author": "X", "content": "a", "is_dm": False},
    ])
    out = make_agent()._format_context(ctx)
    assert "conversation" in out.lower() and "jamais" in out.lower()
