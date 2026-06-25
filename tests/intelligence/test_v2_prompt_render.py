"""TDD — sentinelles {{BOT_NAME}}/{{CREATOR_NAME}}/{{OWNER_ID}} dans les prompts V2.

Vérifie :
1. Aucun fichier bot/intelligence/persona/prompts/*.md ne contient "Wally",
   "KingsRequin" ou "610550333042589752" littéral.
2. ReasoningAgent.self._system, après construction avec identité "Cindy", contient
   "Cindy" et ne contient ni "{{BOT_NAME}}" ni "Wally".
3. ResponseGate._system, après construction avec identité "Cindy", contient "Cindy"
   et ne contient ni "{{BOT_NAME}}" ni "Wally".
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

_V2_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "bot" / "intelligence" / "persona" / "prompts"

_FORBIDDEN_LITERALS = ["Wally", "KingsRequin", "610550333042589752"]


# ── 1. Scan statique des .md ──────────────────────────────────────────────────

def test_no_hardcoded_names_in_v2_prompt_files():
    """Les 6 .md V2 ne doivent contenir aucun nom codé en dur."""
    assert _V2_PROMPTS_DIR.is_dir(), f"Dossier V2 prompts introuvable : {_V2_PROMPTS_DIR}"

    violations: list[str] = []
    for fpath in sorted(_V2_PROMPTS_DIR.glob("*.md")):
        content = fpath.read_text(encoding="utf-8")
        for forbidden in _FORBIDDEN_LITERALS:
            for lineno, line in enumerate(content.splitlines(), 1):
                if forbidden in line:
                    violations.append(f"{fpath.name}:{lineno} [{forbidden!r}]: {line.strip()}")

    assert not violations, (
        "Les fichiers .md V2 suivants contiennent encore des noms littéraux :\n"
        + "\n".join(violations)
    )


# ── 2. ReasoningAgent — rendu au __init__ ─────────────────────────────────────

def test_reasoning_agent_system_rendered_for_cindy(tmp_path):
    """ReasoningAgent construit avec identité Cindy → _system contient 'Cindy'."""
    from bot.intelligence import identity
    identity.set_identity(
        SimpleNamespace(name="Cindy", creator_name="Bob", owner_discord_id="42")
    )

    # Copie le prompt réel dans un répertoire tmp pour isoler le test.
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    src = _V2_PROMPTS_DIR / "reasoning_system.md"
    (prompts_dir / "reasoning_system.md").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    llm = MagicMock()
    fact_store = MagicMock()
    fact_store.add = AsyncMock(return_value=1)

    from bot.intelligence.reasoning_agent import ReasoningAgent
    agent = ReasoningAgent(llm, fact_store, prompts_dir)

    assert "Cindy" in agent._system, "_system doit contenir le nom rendu"
    assert "{{BOT_NAME}}" not in agent._system, "La sentinelle ne doit plus être présente"
    assert "Wally" not in agent._system, "Le nom codé en dur ne doit pas apparaître"
    assert "Bob" in agent._system, "_system doit contenir le créateur rendu"
    assert "{{CREATOR_NAME}}" not in agent._system
    assert "42" in agent._system, "_system doit contenir l'owner_id rendu"
    assert "{{OWNER_ID}}" not in agent._system


# ── 3. ResponseGate — rendu au __init__ ───────────────────────────────────────

def test_gate_system_rendered_for_cindy():
    """ResponseGate construit avec identité Cindy → _system contient 'Cindy'."""
    from bot.intelligence import identity
    identity.set_identity(
        SimpleNamespace(name="Cindy", creator_name="Bob", owner_discord_id="42")
    )

    llm = MagicMock()
    llm.complete_structured = AsyncMock(return_value={"decision": "RESPOND"})
    fact_store = MagicMock()
    fact_store.add = AsyncMock(return_value=1)

    from bot.intelligence.gate import ResponseGate
    gate = ResponseGate(llm=llm, fact_store=fact_store, prompts_dir=_V2_PROMPTS_DIR)

    assert "Cindy" in gate._system, "_system doit contenir le nom rendu"
    assert "{{BOT_NAME}}" not in gate._system, "La sentinelle ne doit plus être présente"
    assert "Wally" not in gate._system, "Le nom codé en dur ne doit pas apparaître"
