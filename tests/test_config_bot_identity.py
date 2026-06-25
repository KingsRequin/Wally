"""Test bot identity configuration fields."""
from bot.config import BotConfig, Config


def test_botconfig_identity_defaults():
    """Test that BotConfig identity fields have correct defaults."""
    c = BotConfig(
        trigger_names=["wally"],
        language_default="fr",
        context_window_size=20,
        context_token_threshold=3000,
        journal_time="21:00",
    )
    assert c.name == "Wally"
    assert c.creator_name == "KingsRequin"
    assert c.owner_discord_id == ""
    assert c.self_modify_enabled is False


def test_config_load_save_roundtrip_identity(tmp_path):
    """Test that identity fields round-trip through Config.load/save."""
    import yaml

    # Load the actual config.yaml
    src = "config.yaml"
    raw = yaml.safe_load(open(src, encoding="utf-8"))

    # Modify identity fields
    raw["bot"]["name"] = "Cindy"
    raw["bot"]["owner_discord_id"] = "123"
    raw["bot"]["self_modify_enabled"] = False

    # Write to temp file
    p = tmp_path / "c.yaml"
    yaml.safe_dump(raw, open(p, "w", encoding="utf-8"))

    # Load via Config.load
    cfg = Config.load(str(p))

    # Verify identity fields
    assert cfg.bot.name == "Cindy"
    assert cfg.bot.owner_discord_id == "123"
    assert cfg.bot.self_modify_enabled is False
