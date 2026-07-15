# tests/test_emotion_beloved.py
import pytest

from bot.config import Config
from bot.core.emotion import EmotionEngine


@pytest.fixture
def emo():
    return EmotionEngine(config=Config.load("config.example.yaml"))


def test_beloved_cancels_anger(emo):
    """Une hausse de colère venant d'un utilisateur aimé est annulée."""
    result = emo.prepare_deltas({"anger": 0.5}, user_id="1", platform="discord", beloved=True)
    assert result["anger"] == 0.0


def test_beloved_cancels_sadness(emo):
    result = emo.prepare_deltas({"sadness": 0.4}, user_id="1", platform="discord", beloved=True)
    assert result["sadness"] == 0.0


def test_beloved_keeps_joy(emo):
    """L'immunité ne coupe QUE le négatif : Wally peut toujours être heureux."""
    result = emo.prepare_deltas({"joy": 0.5}, user_id="1", platform="discord", beloved=True)
    assert result["joy"] > 0.0


def test_beloved_keeps_curiosity(emo):
    result = emo.prepare_deltas({"curiosity": 0.5}, user_id="1", platform="discord", beloved=True)
    assert result["curiosity"] > 0.0


def test_beloved_allows_anger_to_decay(emo):
    """Un delta négatif (colère qui RETOMBE) doit passer — on ne bloque que les hausses."""
    result = emo.prepare_deltas({"anger": -0.3}, user_id="1", platform="discord", beloved=True)
    assert result["anger"] < 0.0


def test_non_beloved_anger_passes(emo):
    """Non-régression : tout le monde peut énerver Wally."""
    result = emo.prepare_deltas({"anger": 0.5}, user_id="1", platform="discord", beloved=False)
    assert result["anger"] > 0.0


def test_beloved_defaults_to_false(emo):
    """Sans le flag, le comportement est inchangé."""
    result = emo.prepare_deltas({"anger": 0.5}, user_id="1", platform="discord")
    assert result["anger"] > 0.0
