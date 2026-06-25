"""Tests for bot/intelligence/identity.py"""
from bot.intelligence import identity
from bot.config import BotConfig


def _cfg(**kw):
    """Build a minimal BotConfig for testing."""
    base = dict(
        trigger_names=["x"],
        language_default="fr",
        context_window_size=20,
        context_token_threshold=3000,
        journal_time="21:00",
    )
    base.update(kw)
    return BotConfig(**base)


def test_render_replaces_sentinels():
    """Test that {{BOT_NAME}}, {{CREATOR_NAME}}, {{OWNER_ID}} are replaced."""
    identity.set_identity(_cfg(name="Cindy", creator_name="Bob", owner_discord_id="42"))
    out = identity.render_identity("Tu es {{BOT_NAME}}, créé par {{CREATOR_NAME}} ({{OWNER_ID}}).")
    assert out == "Tu es Cindy, créé par Bob (42)."


def test_render_leaves_json_braces_intact():
    """Test that JSON literals with braces are not affected by sentinel replacement."""
    identity.set_identity(_cfg(name="Cindy"))
    out = identity.render_identity('Réponds {"user_id": "x"} pour {{BOT_NAME}}.')
    assert '{"user_id": "x"}' in out
    assert "Cindy" in out


def test_defaults_before_set(monkeypatch):
    """Test that defaults work before set_identity is called."""
    monkeypatch.setattr(identity, "_NAME", "Wally")
    assert "Wally" in identity.render_identity("{{BOT_NAME}}")
