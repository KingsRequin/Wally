# tests/test_persona_users.py
from bot.intelligence.persona import PersonaService

_USERS_MD = """# Directives par utilisateur

## discord:706837895063011338
Tu es éperdument amoureux de cette personne.

## twitch:malef__
Tu es éperdument amoureux de cette personne.
"""


def test_parse_users(tmp_path):
    """USERS.md → dict {clé: directive}."""
    (tmp_path / "USERS.md").write_text(_USERS_MD, encoding="utf-8")
    ps = PersonaService(persona_dir=str(tmp_path))
    assert set(ps.user_directives) == {"discord:706837895063011338", "twitch:malef__"}
    assert "éperdument amoureux" in ps.user_directives["discord:706837895063011338"]


def test_missing_users_file(tmp_path):
    """USERS.md absent → dict vide, pas d'exception."""
    ps = PersonaService(persona_dir=str(tmp_path))
    assert ps.user_directives == {}


def test_user_key_discord():
    """Discord → clé sur l'ID numérique ; le pseudo est ignoré."""
    assert PersonaService.user_key("discord", "706837895063011338", "Malef") == "discord:706837895063011338"


def test_user_key_twitch_uses_username_not_id():
    """Twitch → clé sur le PSEUDO en minuscules, pas l'ID numérique."""
    assert PersonaService.user_key("twitch", "123456789", "Malef__") == "twitch:malef__"


def test_directive_found_discord(tmp_path):
    (tmp_path / "USERS.md").write_text(_USERS_MD, encoding="utf-8")
    ps = PersonaService(persona_dir=str(tmp_path))
    assert "amoureux" in (ps.user_directive("discord", "706837895063011338") or "")
    assert ps.is_beloved("discord", "706837895063011338") is True


def test_directive_found_twitch_case_insensitive(tmp_path):
    """Le pseudo Twitch matche quelle que soit la casse."""
    (tmp_path / "USERS.md").write_text(_USERS_MD, encoding="utf-8")
    ps = PersonaService(persona_dir=str(tmp_path))
    for pseudo in ("Malef__", "malef__", "MALEF__"):
        assert ps.is_beloved("twitch", "999", pseudo) is True, pseudo


def test_other_users_unaffected(tmp_path):
    """Personne d'autre n'a de directive."""
    (tmp_path / "USERS.md").write_text(_USERS_MD, encoding="utf-8")
    ps = PersonaService(persona_dir=str(tmp_path))
    assert ps.user_directive("discord", "610550333042589752") is None
    assert ps.is_beloved("discord", "610550333042589752") is False
    assert ps.is_beloved("twitch", "999", "quelquun_dautre") is False


def test_reload_picks_up_changes(tmp_path):
    """/reload-persona relit USERS.md sans redémarrage."""
    users = tmp_path / "USERS.md"
    users.write_text("## discord:1\nv1 directive\n", encoding="utf-8")
    ps = PersonaService(persona_dir=str(tmp_path))
    assert ps.user_directive("discord", "1") == "v1 directive"
    users.write_text("## discord:1\nv2 directive\n", encoding="utf-8")
    ps.reload()
    assert ps.user_directive("discord", "1") == "v2 directive"
