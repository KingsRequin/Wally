# tests/test_composite_emotions.py
from bot.intelligence.persona import PersonaService


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


from unittest.mock import patch
from datetime import datetime
from zoneinfo import ZoneInfo

from bot.intelligence.prompts import PromptBuilder

_EMOTIONS_FLAT = {"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}

_TIERED_DIRECTIVES = {
    "joy_mid": "Tu es chaleureux.",
    "joy_high": "Tu es euphorique.",
    "curiosity_mid": "Tu es curieux.",
    "curiosity_high": "Tu es passionné.",
    "curiosity_low": "Tu es intrigué.",
    "sadness_mid": "Tu es mélancolique.",
    "anger_mid": "Tu es irrité.",
}

_COMPOSITE_DIRECTIVES = {
    "curiosity_joy": "Tu es enthousiaste, surexcité.",
    "anger_sadness": "Tu es amer et rancunier.",
    "boredom_sadness": "Tu es déprimé.",
}


@patch("bot.intelligence.prompts.datetime")
def test_composite_replaces_atomics_when_both_mid(mock_dt):
    """joy=0.5 + curiosity=0.6 → composite curiosity_joy, pas les atomiques."""
    mock_dt.now.return_value = datetime(2026, 3, 20, 14, 0, tzinfo=ZoneInfo("Europe/Paris"))
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.0, "joy": 0.5, "sadness": 0.0, "curiosity": 0.6, "boredom": 0.0},
        emotion_directives=_TIERED_DIRECTIVES,
        composite_directives=_COMPOSITE_DIRECTIVES,
    )
    assert "enthousiaste" in result.lower()
    assert "chaleureux" not in result.lower()
    assert "curieux" not in result.lower()


@patch("bot.intelligence.prompts.datetime")
def test_composite_not_triggered_when_one_below_mid(mock_dt):
    """joy=0.5 + curiosity=0.3 → atomiques normales (curiosity < 0.4)."""
    mock_dt.now.return_value = datetime(2026, 3, 20, 14, 0, tzinfo=ZoneInfo("Europe/Paris"))
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.0, "joy": 0.5, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.0},
        emotion_directives=_TIERED_DIRECTIVES,
        composite_directives=_COMPOSITE_DIRECTIVES,
    )
    assert "enthousiaste" not in result.lower()
    assert "chaleureux" in result.lower()


@patch("bot.intelligence.prompts.datetime")
def test_composite_not_triggered_when_pair_unknown(mock_dt):
    """joy=0.5 + sadness=0.5 → paire joy_sadness inconnue → atomiques."""
    mock_dt.now.return_value = datetime(2026, 3, 20, 14, 0, tzinfo=ZoneInfo("Europe/Paris"))
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.0, "joy": 0.5, "sadness": 0.5, "curiosity": 0.0, "boredom": 0.0},
        emotion_directives=_TIERED_DIRECTIVES,
        composite_directives=_COMPOSITE_DIRECTIVES,
    )
    assert "chaleureux" in result.lower()
    assert "mélancolique" in result.lower()


@patch("bot.intelligence.prompts.datetime")
def test_composite_fallback_when_no_dict(mock_dt):
    """composite_directives=None → atomiques normales."""
    mock_dt.now.return_value = datetime(2026, 3, 20, 14, 0, tzinfo=ZoneInfo("Europe/Paris"))
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.0, "joy": 0.5, "sadness": 0.0, "curiosity": 0.6, "boredom": 0.0},
        emotion_directives=_TIERED_DIRECTIVES,
    )
    assert "enthousiaste" not in result.lower()
    assert "chaleureux" in result.lower()


def test_composite_key_is_alphabetically_sorted():
    key = "_".join(sorted(["joy", "anger"]))
    assert key == "anger_joy"
    key2 = "_".join(sorted(["curiosity", "joy"]))
    assert key2 == "curiosity_joy"
    key3 = "_".join(sorted(["sadness", "boredom"]))
    assert key3 == "boredom_sadness"


@patch("bot.intelligence.prompts.datetime")
def test_composite_not_triggered_when_only_one_dominant(mock_dt):
    """Seule joy=0.5 au-dessus de 0.2 → pas de composite."""
    mock_dt.now.return_value = datetime(2026, 3, 20, 14, 0, tzinfo=ZoneInfo("Europe/Paris"))
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.0, "joy": 0.5, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        emotion_directives=_TIERED_DIRECTIVES,
        composite_directives=_COMPOSITE_DIRECTIVES,
    )
    assert "enthousiaste" not in result.lower()
    assert "chaleureux" in result.lower()
