# tests/test_weekday_awareness.py
import os
import tempfile

from bot.core.persona import PersonaService


def test_parse_weekdays_returns_7_keys(tmp_path):
    """WEEKDAYS.md avec 7 sections → 7 clés."""
    wd = tmp_path / "WEEKDAYS.md"
    wd.write_text(
        "Préambule\n\n"
        "## lundi\nDirective lundi.\n\n"
        "## mardi\nDirective mardi.\n\n"
        "## mercredi\nDirective mercredi.\n\n"
        "## jeudi\nDirective jeudi.\n\n"
        "## vendredi\nDirective vendredi.\n\n"
        "## samedi\nDirective samedi.\n\n"
        "## dimanche\nDirective dimanche.\n",
        encoding="utf-8",
    )
    ps = PersonaService(persona_dir=str(tmp_path))
    assert len(ps.weekday_directives) == 7
    assert "lundi" in ps.weekday_directives
    assert "dimanche" in ps.weekday_directives
    assert "Directive lundi." in ps.weekday_directives["lundi"]


def test_parse_weekdays_missing_file_returns_empty(tmp_path):
    """Fichier absent → dict vide, pas d'erreur."""
    ps = PersonaService(persona_dir=str(tmp_path))
    assert ps.weekday_directives == {}


def test_weekday_directives_reloaded(tmp_path):
    """reload() recharge aussi WEEKDAYS.md."""
    wd = tmp_path / "WEEKDAYS.md"
    wd.write_text("## lundi\nV1\n", encoding="utf-8")
    ps = PersonaService(persona_dir=str(tmp_path))
    assert "V1" in ps.weekday_directives.get("lundi", "")

    wd.write_text("## lundi\nV2\n", encoding="utf-8")
    ps.reload()
    assert "V2" in ps.weekday_directives.get("lundi", "")


def test_weekday_directives_property(tmp_path):
    """La property weekday_directives expose le dict parsé."""
    wd = tmp_path / "WEEKDAYS.md"
    wd.write_text("## samedi\nChill.\n", encoding="utf-8")
    ps = PersonaService(persona_dir=str(tmp_path))
    assert isinstance(ps.weekday_directives, dict)
    assert "samedi" in ps.weekday_directives
