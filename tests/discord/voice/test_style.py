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
