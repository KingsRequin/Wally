# tests/test_config.py
import pytest
import yaml
from bot.config import Config, BotConfig, OpenAIConfig, DiscordConfig, TwitchConfig

MINIMAL_CONFIG = {
    "bot": {
        "trigger_names": ["wally"],
        "language_default": "fr",
        "context_window_size": 20,
        "context_token_threshold": 3000,
        "journal_time": "03:00",
        "journal_channel_id": None,
        "dashboard_token": None,
        "prelude_window_size": 15,
    },
    "openai": {
        "primary_model": "gpt-4o",
        "secondary_model": "gpt-4o-mini",
        "temperature": 0.8,
        "max_tokens": 1000,
    },
    "discord": {
        "anger_trigger_threshold": 3,
        "timeout_minutes": 10,
    },
    "twitch": {"channels": [], "cooldown_seconds": 10},
    "emotions": {
        "anger": {"decay_lambda": 0.1},
        "joy": {"decay_lambda": 0.05},
        "sadness": {"decay_lambda": 0.08},
        "curiosity": {"decay_lambda": 0.1},
        "boredom": {"decay_lambda": 0.15},
    },
    "twitch_events": {
        "follow": {"active": True, "message": "Hey {username}!"},
    },
}


def test_load_config(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(MINIMAL_CONFIG))
    config = Config.load(str(cfg_file))
    assert config.bot.trigger_names == ["wally"]
    assert config.bot.language_default == "fr"
    assert config.bot.prelude_window_size == 15
    assert config.openai.primary_model == "gpt-4o"
    assert config.discord.anger_trigger_threshold == 3
    assert config.twitch.cooldown_seconds == 10
    assert config.emotions["anger"].decay_lambda == 0.1
    assert config.twitch_events["follow"].active is True
    assert config.twitch_events["follow"].message == "Hey {username}!"


def test_save_config(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(MINIMAL_CONFIG))
    config = Config.load(str(cfg_file))

    config.bot.trigger_names.append("hey-wally")
    config.save()

    reloaded = Config.load(str(cfg_file))
    assert "hey-wally" in reloaded.bot.trigger_names


def test_save_preserves_all_sections(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(MINIMAL_CONFIG))
    config = Config.load(str(cfg_file))
    config.openai.temperature = 0.5
    config.save()

    reloaded = Config.load(str(cfg_file))
    assert reloaded.openai.temperature == 0.5
    assert reloaded.bot.trigger_names == ["wally"]  # unchanged


def test_optional_fields_default_none(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(MINIMAL_CONFIG))
    config = Config.load(str(cfg_file))
    assert config.bot.journal_channel_id is None
    assert config.bot.dashboard_token is None


def test_missing_section_raises_valueerror(tmp_path):
    bad_config = {"bot": MINIMAL_CONFIG["bot"]}  # missing openai, discord, twitch
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(bad_config))
    with pytest.raises(ValueError, match="Missing required section"):
        Config.load(str(cfg_file))


def test_optional_fields_absent_from_yaml(tmp_path):
    # Test that optional fields work when omitted entirely from YAML (not just set to None)
    config_without_optionals = {
        k: v for k, v in MINIMAL_CONFIG["bot"].items()
        if k not in ("journal_channel_id", "dashboard_token")
    }
    data = {**MINIMAL_CONFIG, "bot": config_without_optionals}
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(data))
    config = Config.load(str(cfg_file))
    assert config.bot.journal_channel_id is None
    assert config.bot.dashboard_token is None


def test_theme_config_defaults():
    """ThemeConfig a des valeurs par défaut sensées."""
    from bot.config import ThemeConfig
    t = ThemeConfig()
    assert t.accent_color == "#06b6d4"
    assert t.bg_color == "#11151c"
    assert t.layout_variant == "sidebar-left"
    assert t.tab_style == "icons-only"


def test_load_config_theme_defaults(tmp_path):
    """Config.load() crée un ThemeConfig par défaut si absent du YAML."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(MINIMAL_CONFIG))
    config = Config.load(str(cfg_file))
    assert config.theme.accent_color == "#06b6d4"
    assert config.theme.layout_variant == "sidebar-left"


def test_load_config_theme_from_yaml(tmp_path):
    """Config.load() lit le bloc theme: du YAML."""
    data = dict(MINIMAL_CONFIG)
    data["theme"] = {"accent_color": "#ff6b6b", "layout_variant": "sidebar-top"}
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(data))
    config = Config.load(str(cfg_file))
    assert config.theme.accent_color == "#ff6b6b"
    assert config.theme.layout_variant == "sidebar-top"
    assert config.theme.bg_color == "#11151c"  # défaut conservé


def test_save_config_includes_theme(tmp_path):
    """Config.save() sérialise le bloc theme: dans le YAML."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(MINIMAL_CONFIG))
    config = Config.load(str(cfg_file))
    config.theme.accent_color = "#abc123"
    config.save()
    saved = yaml.safe_load(cfg_file.read_text())
    assert saved["theme"]["accent_color"] == "#abc123"
