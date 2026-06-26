from bot.discord.voice.brain import _is_named

TRIGGERS = ["Wally", "wally"]


def test_exact():
    assert _is_named("wally tu es là ?", TRIGGERS) is True


def test_substring_deformation():
    # le STT colle parfois une lettre : "wallyd" contient "wally"
    assert _is_named("wallyd ça va ?", TRIGGERS) is True


def test_fuzzy_internal_deformation():
    # "wallie" ne contient pas "wally" mais reste très proche
    assert _is_named("wallie tu fais quoi", TRIGGERS) is True


def test_not_named():
    assert _is_named("on mange quoi ce soir", TRIGGERS) is False


def test_empty_triggers():
    assert _is_named("wally salut", []) is False
