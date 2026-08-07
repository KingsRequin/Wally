from bot.discord.voice.style import mood_to_style, parse_style_tag, resolve_style


def test_mood_dominant_above_threshold():
    assert mood_to_style({"anger": 0.6, "joy": 0.1, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}) == "angry"
    assert mood_to_style({"anger": 0.0, "joy": 0.5, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}) == "joyful"


def test_mood_below_threshold_is_neutral():
    assert mood_to_style({"anger": 0.2, "joy": 0.3, "sadness": 0.1, "curiosity": 0.1, "boredom": 0.0}) is None


def test_mood_empty():
    assert mood_to_style({}) is None
    assert mood_to_style(None) is None


def test_parse_tag_whispering():
    style, clean = parse_style_tag("[murmure] viens là je te dis un truc")
    assert style == "whispering"
    assert clean == "viens là je te dis un truc"


def test_parse_tag_parenthesis_and_accents():
    style, clean = parse_style_tag("(énervé) bon ça suffit maintenant")
    assert style == "angry"
    assert clean == "bon ça suffit maintenant"


def test_parse_no_tag():
    style, clean = parse_style_tag("salut tout le monde")
    assert style is None
    assert clean == "salut tout le monde"


def test_unknown_tag_stripped_but_no_style():
    style, clean = parse_style_tag("[bizarre] coucou")
    assert style is None
    assert clean == "coucou"


def test_resolve_tag_overrides_mood():
    # tag whispering doit primer sur l'humeur colère
    style, clean = resolve_style("[murmure] doucement", {"anger": 0.9, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0})
    assert style == "whispering"
    assert clean == "doucement"


def test_resolve_falls_back_to_mood():
    style, clean = resolve_style("je suis super content", {"anger": 0.0, "joy": 0.7, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0})
    assert style == "joyful"
    assert clean == "je suis super content"


def test_resolve_strips_full_sentence_brackets():
    # Wally entoure parfois toute sa phrase de crochets → on retire les crochets, pas le texte
    style, clean = resolve_style("[C'est pour une pizza ou t'as un truc à dire ?]", None)
    assert style is None
    assert "[" not in clean and "]" not in clean
    assert clean == "C'est pour une pizza ou t'as un truc à dire ?"


def test_resolve_strips_emojis():
    style, clean = resolve_style("super content de te voir 🔥😎", None)
    assert "🔥" not in clean and "😎" not in clean
    assert clean.strip() == "super content de te voir"


def test_resolve_drops_short_stage_direction():
    # didascalie courte type [rire] au milieu → supprimée
    style, clean = resolve_style("ça me fait bien marrer [il rigole] franchement", None)
    assert "[" not in clean and "rigole" not in clean


# ── styles selon la voix (2026-08-07) ──

from bot.discord.voice.style import supported_styles, adapt_style

_HENRI = "fr-FR-HenriNeural"
_MARC = "fr-FR-Marc:MAI-Voice-2"


def test_les_voix_standard_nont_que_quatre_styles():
    """Doc Azure : Henri et Denise sont les SEULES voix fr-FR hors MAI à
    supporter des styles, et seulement ces quatre-là."""
    assert supported_styles(_HENRI) == frozenset(
        {"cheerful", "excited", "sad", "whispering"})
    assert supported_styles("fr-FR-DeniseNeural") == supported_styles(_HENRI)


def test_une_voix_sans_style_connu_nen_recoit_aucun():
    """Un `mstts:express-as` inconnu fait ÉCHOUER la synthèse — donc un Wally
    muet. Face à une voix qu'on ne connaît pas, on n'envoie rien."""
    assert supported_styles("fr-FR-Remy:DragonHDLatestNeural") == frozenset()
    assert adapt_style("sad", "fr-FR-Remy:DragonHDLatestNeural") is None


def test_les_voix_mai_gardent_tous_leurs_styles():
    assert "angry" in supported_styles(_MARC)
    assert adapt_style("angry", _MARC) == "angry"
    assert adapt_style("softvoice", "fr-FR-Soleil:MAI-Voice-2-Flash") == "softvoice"


def test_un_style_supporte_passe_tel_quel():
    assert adapt_style("sad", _HENRI) == "sad"
    assert adapt_style("whispering", _HENRI) == "whispering"


def test_un_style_absent_retombe_sur_le_plus_proche():
    """Arbitrage owner : mieux vaut une voix expressive approchante qu'une voix
    plate. Henri n'a ni `angry`, ni `joyful`, ni `softvoice`."""
    assert adapt_style("angry", _HENRI) == "excited"
    assert adapt_style("joyful", _HENRI) == "cheerful"
    assert adapt_style("softvoice", _HENRI) == "whispering"
    assert adapt_style("surprised", _HENRI) == "excited"
    assert adapt_style("fearful", _HENRI) == "sad"
    assert adapt_style("shouting", _HENRI) == "excited"


def test_toute_emotion_reste_audible_sur_henri():
    """Les 5 émotions du moteur doivent produire un style valide sur Henri :
    c'était le point de la question — « on change de voix, mais plus
    d'émotion » n'est vrai que si on ne fait pas ce repli."""
    from bot.discord.voice.style import _MOOD_STYLE
    ok = supported_styles(_HENRI)
    for emotion, style in _MOOD_STYLE.items():
        adapted = adapt_style(style, _HENRI)
        assert adapted in ok, f"{emotion} → {style} n'a pas d'équivalent"


def test_resolve_style_adapte_a_la_voix():
    from bot.discord.voice.style import resolve_style
    colere = {"anger": 0.9, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    assert resolve_style("salut", colere, voice=_MARC)[0] == "angry"
    assert resolve_style("salut", colere, voice=_HENRI)[0] == "excited"


def test_resolve_style_sans_voix_reste_compatible():
    """L'ancien appel à deux arguments ne doit pas casser."""
    from bot.discord.voice.style import resolve_style
    style, clean = resolve_style("[murmure] doucement", None)
    assert style == "whispering" and clean == "doucement"
