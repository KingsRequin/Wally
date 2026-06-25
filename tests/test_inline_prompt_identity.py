# tests/test_inline_prompt_identity.py
"""TDD — prompts inline dans emotion.py / gate.py / persona_manager.py ne hardcodent pas 'Wally'.

Vérifie que :
1. Le template système de _analyze_llm (emotion.py) rendu pour "Cindy" contient
   "Cindy" et ne contient ni "{{BOT_NAME}}" ni "Wally".
2. _FALLBACK_SYSTEM de gate.py rendu via render_identity contient "Cindy" et
   pas "Wally".
3. build_emotion_tag retourne "Cindy: ..." et pas "Wally: ...".
4. PersonaManager.evolve construit un system prompt contenant "Cindy".
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.intelligence import identity


def _set_cindy():
    identity.set_identity(
        SimpleNamespace(name="Cindy", creator_name="X", owner_discord_id="1")
    )


# ── 1. emotion._analyze_llm — système prompt rendu ───────────────────────────

def test_analyze_llm_system_template_renders_cindy():
    """_ANALYSIS_SYSTEM_TEMPLATE rendu pour Cindy ne contient plus 'Wally'."""
    _set_cindy()
    from bot.core.emotion import _ANALYSIS_SYSTEM_TEMPLATE
    from bot.intelligence.identity import render_identity

    rendered = render_identity(_ANALYSIS_SYSTEM_TEMPLATE)
    assert "Cindy" in rendered, "Le prompt rendu doit contenir 'Cindy'"
    assert "{{BOT_NAME}}" not in rendered, "La sentinelle ne doit plus être présente"
    assert "Wally" not in rendered, "Le nom codé en dur ne doit pas subsister"


# ── 2. gate._FALLBACK_SYSTEM rendu pour Cindy ────────────────────────────────

def test_fallback_system_renders_cindy():
    """_FALLBACK_SYSTEM de gate.py rendu via render_identity → contient 'Cindy'."""
    _set_cindy()
    from bot.intelligence.gate import _FALLBACK_SYSTEM
    from bot.intelligence.identity import render_identity

    rendered = render_identity(_FALLBACK_SYSTEM)
    assert "Cindy" in rendered, "Le fallback rendu doit contenir 'Cindy'"
    assert "Wally" not in rendered, "Le nom codé en dur ne doit pas subsister"


# ── 3. build_emotion_tag — libellé bot_name() ────────────────────────────────

def test_build_emotion_tag_uses_bot_name():
    """build_emotion_tag retourne '<bot_name>: ...' et non 'Wally: ...'."""
    _set_cindy()
    from bot.core.emotion import build_emotion_tag

    tag = build_emotion_tag({"joy": 0.5, "anger": 0.0, "sadness": 0.0,
                             "curiosity": 0.0, "boredom": 0.0})
    assert tag.startswith("Cindy:"), f"Tag attendu 'Cindy: ...', obtenu: {tag!r}"
    assert "Wally" not in tag, "Le tag ne doit pas contenir 'Wally'"


# ── 4. PersonaManager.evolve — system prompt contient bot_name() ─────────────

@pytest.mark.asyncio
async def test_persona_manager_evolve_uses_bot_name():
    """Le prompt système d'evolve doit utiliser bot_name() et non 'Wally'."""
    _set_cindy()

    from bot.intelligence.persona_manager import PersonaManager
    from bot.intelligence.evolution_log import EvolutionLog

    # Stub evolution log: aucun changement aujourd'hui
    evo_log = MagicMock(spec=EvolutionLog)
    evo_log.change_percent_today.return_value = 0.0
    evo_log.count_today.return_value = 0
    evo_log.append = MagicMock()

    captured_system: list[str] = []

    async def fake_complete(system, messages, **kwargs):
        captured_system.append(system)
        return "# Modified content"

    llm = MagicMock()
    llm.complete = fake_complete

    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as tmp:
        p = pathlib.Path(tmp)
        soul_file = p / "SOUL.md"
        soul_file.write_text("# SOUL\nIdentity block.", encoding="utf-8")

        pm = PersonaManager(persona_dir=p, evolution_log=evo_log, llm=llm)
        await pm.evolve("SOUL", "ajoute une ligne sur la curiosité")

    assert captured_system, "llm.complete n'a pas été appelé"
    system = captured_system[0]
    assert "Cindy" in system, f"Le system prompt doit contenir 'Cindy', obtenu: {system!r}"
    assert "Wally" not in system, "Le system prompt ne doit pas contenir 'Wally'"
