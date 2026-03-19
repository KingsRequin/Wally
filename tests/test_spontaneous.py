# tests/test_spontaneous.py
from bot.discord.handlers import _check_spontaneous_trigger


def test_passion_keyword_bouchon():
    result = _check_spontaneous_trigger("j'ai trouvé un bouchon rare", curiosity=0.0, anger=0.0, boredom=0.0)
    assert result == "passion"


def test_aversion_keyword_ananas():
    result = _check_spontaneous_trigger("qui veut de la pizza ananas ?", curiosity=0.0, anger=0.0, boredom=0.0)
    assert result == "passion"


def test_no_keyword_no_emotion():
    result = _check_spontaneous_trigger("je vais au magasin", curiosity=0.0, anger=0.0, boredom=0.0)
    assert result is None


def test_emotion_curiosity_high():
    result = _check_spontaneous_trigger("je vais au magasin", curiosity=0.6, anger=0.0, boredom=0.0)
    assert result == "emotion"


def test_emotion_boredom_high():
    result = _check_spontaneous_trigger("salut", curiosity=0.0, anger=0.0, boredom=0.7)
    assert result == "emotion"


def test_emotion_anger_high():
    result = _check_spontaneous_trigger("blabla", curiosity=0.0, anger=0.7, boredom=0.0)
    assert result == "emotion"


def test_emotion_below_threshold():
    result = _check_spontaneous_trigger("blabla", curiosity=0.4, anger=0.3, boredom=0.2)
    assert result is None


def test_passion_takes_priority_over_emotion():
    """If both passion keyword and emotion match, return passion."""
    result = _check_spontaneous_trigger("ce bouchon est incroyable", curiosity=0.8, anger=0.0, boredom=0.0)
    assert result == "passion"
