"""Test that set_identity is called at startup to set the bot's identity."""
import bot.intelligence.identity as identity
from bot.config import BotConfig


def test_set_identity_applies():
    """Verify that set_identity correctly sets bot_name from BotConfig."""
    cfg = BotConfig(
        trigger_names=["x"],
        language_default="fr",
        context_window_size=20,
        context_token_threshold=3000,
        journal_time="21:00",
        name="Cindy"
    )
    identity.set_identity(cfg)
    assert identity.bot_name() == "Cindy"
