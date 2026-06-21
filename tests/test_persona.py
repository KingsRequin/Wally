# tests/test_persona.py
import pytest
from bot.core.persona import PersonaService


def test_load_all_files(tmp_path):
    """Chargement nominal des 3 fichiers."""
    (tmp_path / "SOUL.md").write_text("Tu es Wally.")
    (tmp_path / "IDENTITY.md").write_text("Nom : Wally")
    (tmp_path / "VOICE.md").write_text("Style : court.")
    ps = PersonaService(persona_dir=str(tmp_path))
    block = ps.build_prompt_block()
    assert "Tu es Wally." in block
    assert "Nom : Wally" in block
    assert "Style : court." in block


def test_missing_file_returns_empty_block(tmp_path):
    """Fichier manquant → bloc vide, pas d'exception."""
    (tmp_path / "SOUL.md").write_text("âme")
    # IDENTITY.md et VOICE.md absents
    ps = PersonaService(persona_dir=str(tmp_path))
    block = ps.build_prompt_block()
    assert "âme" in block
    # pas de crash


def test_all_files_missing(tmp_path):
    """Tous les fichiers absents → chaîne vide, pas d'exception."""
    ps = PersonaService(persona_dir=str(tmp_path))
    assert ps.build_prompt_block() == ""


def test_reload_picks_up_changes(tmp_path):
    """reload() relit les fichiers modifiés."""
    soul = tmp_path / "SOUL.md"
    soul.write_text("v1")
    (tmp_path / "IDENTITY.md").write_text("")
    (tmp_path / "VOICE.md").write_text("")
    ps = PersonaService(persona_dir=str(tmp_path))
    assert "v1" in ps.build_prompt_block()
    soul.write_text("v2")
    ps.reload()
    assert "v2" in ps.build_prompt_block()
    assert "v1" not in ps.build_prompt_block()


def test_capabilities_loaded_in_block(tmp_path):
    """CAPABILITIES.md est chargé et concaténé dans le bloc persona."""
    (tmp_path / "SOUL.md").write_text("âme")
    (tmp_path / "CAPABILITIES.md").write_text(
        "# CAPABILITIES\nVoici ce que je sais faire.\nJe n'ai pas de corps."
    )
    ps = PersonaService(persona_dir=str(tmp_path))
    block = ps.build_prompt_block()
    assert "ce que je sais faire" in block
    assert "pas de corps" in block


def test_capabilities_loaded_from_real_persona_dir():
    """Le vrai bot/persona/CAPABILITIES.md est présent dans le bloc des réponses."""
    ps = PersonaService(persona_dir="bot/persona")
    block = ps.build_prompt_block()
    assert "pas de corps" in block
    assert "ce que je sais faire" in block.lower()


def test_build_prompt_block_order(tmp_path):
    """SOUL apparaît avant IDENTITY, IDENTITY avant VOICE."""
    (tmp_path / "SOUL.md").write_text("SOUL_CONTENT")
    (tmp_path / "IDENTITY.md").write_text("IDENTITY_CONTENT")
    (tmp_path / "VOICE.md").write_text("VOICE_CONTENT")
    ps = PersonaService(persona_dir=str(tmp_path))
    result = ps.build_prompt_block()
    assert result.index("SOUL_CONTENT") < result.index("IDENTITY_CONTENT")
    assert result.index("IDENTITY_CONTENT") < result.index("VOICE_CONTENT")
