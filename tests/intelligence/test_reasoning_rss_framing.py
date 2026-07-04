from types import SimpleNamespace

from bot.intelligence.reasoning_agent import ReasoningAgent


def _agent():
    # _format_context ne touche pas au LLM ; on pointe prompts_dir sur le dossier
    # réel des prompts cognitifs (même approche que test_reasoning_web_finding).
    import bot.intelligence as _pkg
    from pathlib import Path
    prompts = Path(_pkg.__file__).parent / "persona" / "prompts"
    return ReasoningAgent(llm=None, fact_store=None, prompts_dir=prompts)


def _ctx(**kw):
    base = dict(
        preoccupation=None, emotional_drive=None, idle_seed=None,
        rss_stimulus=None, emotion_state={}, time_of_day="afternoon",
        active_desires=[], active_goals=[], recent_thoughts=[],
        recent_interactions=[], web_finding=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_rss_idle_seed_adds_private_friction_note():
    # Amorce idle issue du RSS → recadrage : friction privée, pas un sujet à diffuser.
    agent = _agent()
    out = agent._format_context(_ctx(
        idle_seed="Une actu qui passe dans ton fil — JeuxVideo.com : « … ».",
        rss_stimulus={"feed_name": "JeuxVideo.com", "title": "…"},
    ))
    assert "friction pour ta pensée" in out
    assert "parler tout seul" in out


def test_non_rss_idle_seed_has_no_rss_note():
    # Amorce idle NON-RSS (souvenir, but…) → pas de recadrage RSS.
    agent = _agent()
    out = agent._format_context(_ctx(
        idle_seed="Une pensée d'avant qui ressurgit : …",
        rss_stimulus=None,
    ))
    assert "friction pour ta pensée" not in out


def test_no_idle_seed_no_rss_note_even_with_stimulus():
    # Sans amorce idle affichée, pas de bloc RSS (le stimulus seul ne suffit pas).
    agent = _agent()
    out = agent._format_context(_ctx(
        idle_seed=None,
        rss_stimulus={"feed_name": "Korben", "title": "…"},
    ))
    assert "friction pour ta pensée" not in out
