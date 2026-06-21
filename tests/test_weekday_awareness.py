# tests/test_weekday_awareness.py
import os
import tempfile

from bot.intelligence.persona import PersonaService


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


from unittest.mock import patch
from datetime import datetime
from zoneinfo import ZoneInfo

from bot.intelligence.prompts import PromptBuilder

_EMOTIONS_FLAT = {"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
_WEEKDAY_DIRECTIVES = {
    "lundi": "Tu es cynique et tu traînes les pieds.",
    "vendredi": "Tu es détendu et blagueur.",
}


@patch("bot.intelligence.prompts.datetime")
def test_weekday_directive_injected(mock_dt):
    """La directive du jour courant est injectée dans le prompt."""
    mock_dt.now.return_value = datetime(2026, 3, 20, 14, 0, tzinfo=ZoneInfo("Europe/Paris"))
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state=_EMOTIONS_FLAT,
        weekday_directives=_WEEKDAY_DIRECTIVES,
    )
    # 2026-03-20 = vendredi
    assert "détendu" in result.lower()
    assert "Directive temporelle" in result


@patch("bot.intelligence.prompts.datetime")
def test_weekday_directive_not_injected_when_none(mock_dt):
    """weekday_directives=None → pas de section temporelle."""
    mock_dt.now.return_value = datetime(2026, 3, 20, 14, 0, tzinfo=ZoneInfo("Europe/Paris"))
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state=_EMOTIONS_FLAT,
    )
    assert "Directive temporelle" not in result


@patch("bot.intelligence.prompts.datetime")
def test_weekday_directive_not_injected_when_day_missing(mock_dt):
    """Dict présent mais jour courant absent → pas de section temporelle."""
    mock_dt.now.return_value = datetime(2026, 3, 18, 14, 0, tzinfo=ZoneInfo("Europe/Paris"))
    pb = PromptBuilder()
    # 2026-03-18 = mercredi, pas dans le dict
    result = pb.build_system_prompt(
        emotion_state=_EMOTIONS_FLAT,
        weekday_directives=_WEEKDAY_DIRECTIVES,
    )
    assert "Directive temporelle" not in result


@patch("bot.intelligence.prompts.datetime")
def test_weekday_directive_before_emotion_directives(mock_dt):
    """La directive temporelle apparaît avant les directives émotionnelles."""
    mock_dt.now.return_value = datetime(2026, 3, 20, 14, 0, tzinfo=ZoneInfo("Europe/Paris"))
    pb = PromptBuilder()
    emotion_dirs = {"joy_high": "Tu es euphorique."}
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.0, "joy": 0.9, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        weekday_directives=_WEEKDAY_DIRECTIVES,
        emotion_directives=emotion_dirs,
    )
    temporal_pos = result.find("Directive temporelle")
    emotion_pos = result.find("Directive comportementale")
    assert temporal_pos < emotion_pos
