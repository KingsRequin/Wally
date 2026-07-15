# tests/test_beloved_immunity_discord.py
from bot.intelligence.persona import PersonaService

_USERS_MD = "## discord:706837895063011338\nTu es amoureux.\n"


def _persona(tmp_path):
    (tmp_path / "USERS.md").write_text(_USERS_MD, encoding="utf-8")
    return PersonaService(persona_dir=str(tmp_path))


def test_malef_is_beloved_on_discord(tmp_path):
    assert _persona(tmp_path).is_beloved("discord", "706837895063011338") is True


def test_owner_is_not_beloved(tmp_path):
    """L'owner (KingsRequin) n'est pas concerné — la feature ne vise que Malef."""
    assert _persona(tmp_path).is_beloved("discord", "610550333042589752") is False


def test_directive_reaches_prompt(tmp_path):
    """Bout-en-bout : la directive de Malef atteint le prompt et étouffe la colère."""
    from bot.intelligence.prompts import PromptBuilder

    ps = _persona(tmp_path)
    result = PromptBuilder().build_system_prompt(
        emotion_state={"anger": 0.9, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        emotion_directives={"anger_high": "Tu es furax et cinglant."},
        user_directive=ps.user_directive("discord", "706837895063011338"),
    )
    assert "amoureux" in result
    assert "furax" not in result.lower()
