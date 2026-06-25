"""Integration tests: {{BOT_NAME}} sentinelles dans les prompts rendus au runtime.

Vérifie :
1. load_prompt avec render=True (défaut) remplace {{BOT_NAME}} selon l'identité active.
2. load_prompt avec render=False retourne le texte brut (sentinelles non rendues).
3. Aucun des 15 .md de bot/persona/prompts/ ne contient le littéral "Wally".
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest


# ── helpers ──────────────────────────────────────────────────────────────────

def _set_cindy():
    from bot.intelligence import identity
    identity.set_identity(SimpleNamespace(name="Cindy", creator_name="X", owner_discord_id="1"))


def _set_wally():
    from bot.intelligence import identity
    identity.set_identity(SimpleNamespace(name="Wally", creator_name="KingsRequin", owner_discord_id=""))


# ── tests ─────────────────────────────────────────────────────────────────────

def test_load_prompt_render_default_replaces_bot_name():
    """load_prompt('journal_system') avec Cindy active → contient 'Cindy', pas '{{BOT_NAME}}', pas 'Wally'."""
    _set_cindy()
    from bot.intelligence.prompts import load_prompt
    text = load_prompt("journal_system")
    assert "Cindy" in text, "Le nom de l'instance doit apparaître dans le texte rendu"
    assert "{{BOT_NAME}}" not in text, "Les sentinelles ne doivent plus être présentes après rendu"
    assert "Wally" not in text, "Le nom codé en dur ne doit pas apparaître pour une autre instance"


def test_load_prompt_render_false_returns_raw_sentinel():
    """load_prompt('journal_system', render=False) → contient '{{BOT_NAME}}' brut."""
    _set_cindy()
    from bot.intelligence.prompts import load_prompt
    text = load_prompt("journal_system", render=False)
    assert "{{BOT_NAME}}" in text, "render=False doit retourner le template non rendu"


def test_load_prompt_render_wally_default_unchanged():
    """Avec l'identité Wally (défaut), le rendu doit contenir 'Wally', pas '{{BOT_NAME}}'."""
    _set_wally()
    from bot.intelligence.prompts import load_prompt
    text = load_prompt("journal_system")
    assert "Wally" in text
    assert "{{BOT_NAME}}" not in text


def test_no_literal_wally_in_prompt_md_files():
    """Aucun fichier .md dans bot/persona/prompts/ ne doit contenir 'Wally' littéralement."""
    prompts_dir = os.path.join(
        os.path.dirname(__file__), "..", "..", "bot", "persona", "prompts"
    )
    prompts_dir = os.path.normpath(prompts_dir)
    assert os.path.isdir(prompts_dir), f"Dossier introuvable : {prompts_dir}"

    violations: list[str] = []
    for fname in os.listdir(prompts_dir):
        if not fname.endswith(".md"):
            continue
        path = os.path.join(prompts_dir, fname)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        if "Wally" in content:
            # Collect lines for a useful error message
            for lineno, line in enumerate(content.splitlines(), 1):
                if "Wally" in line:
                    violations.append(f"{fname}:{lineno}: {line.strip()}")

    assert not violations, (
        "Les fichiers .md suivants contiennent encore 'Wally' littéral :\n"
        + "\n".join(violations)
    )
