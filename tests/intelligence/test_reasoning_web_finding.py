from types import SimpleNamespace

from bot.intelligence.reasoning_agent import ReasoningAgent


def _agent(tmp_path):
    # _format_context ne touche pas au LLM ; on construit un agent minimal en
    # pointant prompts_dir sur le dossier réel des prompts cognitifs.
    import bot.intelligence as _pkg
    from pathlib import Path
    prompts = Path(_pkg.__file__).parent / "persona" / "prompts"
    return ReasoningAgent(llm=None, fact_store=None, prompts_dir=prompts)


def _ctx(**kw):
    base = dict(
        preoccupation=None, emotional_drive=None, idle_seed=None,
        emotion_state={}, time_of_day="afternoon", active_desires=[],
        active_goals=[], recent_thoughts=[], recent_interactions=[],
        web_finding=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_web_finding_rendered(tmp_path):
    agent = _agent(tmp_path)
    out = agent._format_context(_ctx(web_finding="qui a gagné l'euro 2024 → l'Espagne"))
    assert "Tu viens de chercher sur le web" in out
    assert "l'Espagne" in out


def test_no_web_finding_no_block(tmp_path):
    agent = _agent(tmp_path)
    out = agent._format_context(_ctx())
    assert "Tu viens de chercher" not in out
