from types import SimpleNamespace

from bot.intelligence.self_model import build_self_model


def _cfg(voice_enabled: bool):
    return SimpleNamespace(voice=SimpleNamespace(enabled=voice_enabled))


def test_voice_enabled_states_capability_active():
    out = build_self_model("Je suis Wally.", _cfg(True))
    assert "parler en vocal" in out
    # Aucune trace de l'ancienne affirmation fossilisée :
    assert "désactivé" not in out
    assert "pas branché" not in out
    assert "pas activé" not in out


def test_voice_disabled_states_capability_inactive():
    out = build_self_model("Je n'ai pas de corps.", _cfg(False))
    assert "n'est pas activé" in out
    assert "parler en vocal" not in out
    assert "Je n'ai pas de corps." in out


def test_static_text_is_preserved():
    static = "Je n'ai pas de corps. Je ne prétends jamais me souvenir d'un moment vécu."
    out = build_self_model(static, _cfg(True))
    assert "Je n'ai pas de corps." in out
    assert "Je ne prétends jamais me souvenir d'un moment vécu." in out


def test_derived_section_has_title():
    out = build_self_model("X", _cfg(True))
    assert "## Mes capacités techniques actuelles" in out


def test_malformed_config_falls_back_to_inactive():
    out = build_self_model("X", SimpleNamespace())  # pas d'attribut voice
    assert "n'est pas activé" in out
