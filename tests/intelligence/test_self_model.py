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


def test_web_available_phrase_active():
    out = build_self_model("", object(), web_available=True)
    assert "chercher sur le web" in out.lower()
    assert "indisponible" not in out.lower()


def test_web_unavailable_phrase_inactive():
    out = build_self_model("", object(), web_available=False)
    assert "indisponible" in out.lower()


# ── capacités overlay ──

def test_wally_sait_dire_ce_qu_il_peut_afficher():
    """« Tu peux faire quoi sur l'overlay ? » doit avoir une réponse juste."""
    out = build_self_model("", _cfg(False), web_available=False)
    assert "overlay" in out
    assert "pile ou face" in out and "bingo" in out


def test_la_liste_suit_le_code_et_non_une_copie():
    """Une liste recopiée finirait par promettre un widget retiré, ou ignorer
    un widget ajouté."""
    from bot.intelligence.overlay_narrator import OverlayNarrator
    from bot.intelligence.self_model import _WIDGET_WORDS

    manquants = set(OverlayNarrator._WIDGETS) - set(_WIDGET_WORDS)
    assert not manquants, f"widget sans formulation : {manquants}"


def test_il_precise_que_le_streamer_ne_voit_pas_l_overlay():
    """C'est la règle qui l'empêche de s'adresser à Azraël dessus."""
    assert "streamer non" in build_self_model("", _cfg(False))


def test_un_overlay_indisponible_ne_casse_pas_le_prompt(monkeypatch):
    import bot.intelligence.self_model as mod

    monkeypatch.setattr(mod, "_overlay_line", lambda: "")
    out = build_self_model("", _cfg(False))
    assert "Mes capacités techniques" in out
