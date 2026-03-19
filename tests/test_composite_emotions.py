# tests/test_composite_emotions.py
from bot.core.persona import PersonaService


def test_parse_composites_returns_5_keys(tmp_path):
    wd = tmp_path / "COMPOSITES.md"
    wd.write_text(
        "Préambule\n\n"
        "## curiosity_joy\nEnthousiaste.\n\n"
        "## boredom_sadness\nDéprimé.\n\n"
        "## anger_sadness\nAmer.\n\n"
        "## anger_curiosity\nProvocateur.\n\n"
        "## boredom_joy\nSarcastique-nonchalant.\n",
        encoding="utf-8",
    )
    ps = PersonaService(persona_dir=str(tmp_path))
    assert len(ps.composite_directives) == 5
    assert "curiosity_joy" in ps.composite_directives
    assert "Enthousiaste." in ps.composite_directives["curiosity_joy"]


def test_parse_composites_missing_file_returns_empty(tmp_path):
    ps = PersonaService(persona_dir=str(tmp_path))
    assert ps.composite_directives == {}


def test_composite_directives_property(tmp_path):
    wd = tmp_path / "COMPOSITES.md"
    wd.write_text("## anger_sadness\nAmer.\n", encoding="utf-8")
    ps = PersonaService(persona_dir=str(tmp_path))
    assert isinstance(ps.composite_directives, dict)
    assert "anger_sadness" in ps.composite_directives
