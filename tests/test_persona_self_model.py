from types import SimpleNamespace

from bot.intelligence.persona import PersonaService


def _persona_dir(tmp_path, caps_text="Je n'ai pas de corps."):
    (tmp_path / "SOUL.md").write_text("âme", encoding="utf-8")
    (tmp_path / "IDENTITY.md").write_text("Nom : Wally", encoding="utf-8")
    (tmp_path / "VOICE.md").write_text("Style : court.", encoding="utf-8")
    (tmp_path / "CAPABILITIES.md").write_text(caps_text, encoding="utf-8")
    return str(tmp_path)


def test_block_reflects_voice_enabled(tmp_path):
    cfg = SimpleNamespace(voice=SimpleNamespace(enabled=True))
    ps = PersonaService(persona_dir=_persona_dir(tmp_path), config=cfg)
    block = ps.build_prompt_block()
    assert "parler en vocal" in block
    assert "Je n'ai pas de corps." in block  # narratif statique préservé


def test_block_reflects_voice_disabled(tmp_path):
    cfg = SimpleNamespace(voice=SimpleNamespace(enabled=False))
    ps = PersonaService(persona_dir=_persona_dir(tmp_path), config=cfg)
    block = ps.build_prompt_block()
    assert "n'est pas activé" in block


def test_block_without_config_uses_static_only(tmp_path):
    ps = PersonaService(persona_dir=_persona_dir(tmp_path))  # config=None
    block = ps.build_prompt_block()
    assert "Je n'ai pas de corps." in block
    assert "Mes capacités techniques actuelles" not in block


def test_real_capabilities_md_has_no_fossilised_voice_line():
    # Le fichier réel ne doit plus affirmer que le vocal est désactivé/pas branché.
    with open("bot/persona/CAPABILITIES.md", encoding="utf-8") as f:
        content = f.read()
    assert "pas branché" not in content
    assert "elle est désactivée" not in content
