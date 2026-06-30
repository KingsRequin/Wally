from bot.config import TavilyConfig


def test_tavily_cooldown_default():
    assert TavilyConfig().cognitive_cooldown_minutes == 45


def test_tavily_cooldown_override():
    assert TavilyConfig(cognitive_cooldown_minutes=10).cognitive_cooldown_minutes == 10
