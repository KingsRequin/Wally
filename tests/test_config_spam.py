"""Tests for SpamDetectionConfig dataclass and nested config loading."""
import tempfile
import os
import yaml
import pytest

from bot.config import Config, SpamDetectionConfig, DiscordConfig


class TestSpamDetectionConfigDefaults:
    def test_spam_detection_config_defaults(self):
        cfg = SpamDetectionConfig()
        assert cfg.enabled is True
        assert cfg.max_messages == 10
        assert cfg.window_seconds == 120
        assert cfg.mute_minutes == 5
        assert cfg.spam_anger_delta == 0.05
        assert cfg.exempt_channels == []


class TestConfigLoadWithSpamDetection:
    def test_config_load_with_spam_detection(self, tmp_path):
        """Verify nested SpamDetectionConfig is loaded from YAML."""
        yaml_path = tmp_path / "config.yaml"
        data = _minimal_config()
        data["discord"]["spam_detection"] = {
            "enabled": False,
            "max_messages": 5,
            "window_seconds": 60,
            "mute_minutes": 10,
            "spam_anger_delta": 0.1,
            "exempt_channels": [111, 222],
        }
        yaml_path.write_text(yaml.dump(data))

        cfg = Config.load(str(yaml_path))
        spam = cfg.discord.spam_detection
        assert isinstance(spam, SpamDetectionConfig)
        assert spam.enabled is False
        assert spam.max_messages == 5
        assert spam.window_seconds == 60
        assert spam.mute_minutes == 10
        assert spam.spam_anger_delta == 0.1
        assert spam.exempt_channels == [111, 222]


class TestConfigLoadWithoutSpamDetection:
    def test_config_load_without_spam_detection_uses_defaults(self, tmp_path):
        """When spam_detection is absent from YAML, defaults are used."""
        yaml_path = tmp_path / "config.yaml"
        data = _minimal_config()
        # No spam_detection key at all
        yaml_path.write_text(yaml.dump(data))

        cfg = Config.load(str(yaml_path))
        spam = cfg.discord.spam_detection
        assert isinstance(spam, SpamDetectionConfig)
        assert spam.enabled is True
        assert spam.max_messages == 10
        assert spam.window_seconds == 120
        assert spam.mute_minutes == 5
        assert spam.spam_anger_delta == 0.05
        assert spam.exempt_channels == []


class TestConfigSaveRoundtrip:
    def test_config_save_roundtrip_spam_detection(self, tmp_path):
        """Save then reload preserves spam_detection values."""
        yaml_path = tmp_path / "config.yaml"
        data = _minimal_config()
        data["discord"]["spam_detection"] = {
            "enabled": False,
            "max_messages": 7,
            "window_seconds": 90,
            "mute_minutes": 3,
            "spam_anger_delta": 0.08,
            "exempt_channels": [333],
        }
        yaml_path.write_text(yaml.dump(data))

        cfg = Config.load(str(yaml_path))
        cfg.save()

        cfg2 = Config.load(str(yaml_path))
        spam = cfg2.discord.spam_detection
        assert spam.enabled is False
        assert spam.max_messages == 7
        assert spam.window_seconds == 90
        assert spam.mute_minutes == 3
        assert spam.spam_anger_delta == 0.08
        assert spam.exempt_channels == [333]


def _minimal_config() -> dict:
    """Return a minimal valid config dict for testing."""
    return {
        "bot": {
            "trigger_names": ["wally"],
            "language_default": "en",
            "context_window_size": 10,
            "context_token_threshold": 2000,
            "journal_time": "21:00",
        },
        "openai": {
            "primary_model": "gpt-4",
            "secondary_model": "gpt-4-mini",
            "temperature": 0.7,
            "max_tokens": 500,
        },
        "discord": {
            "anger_trigger_threshold": 3,
            "timeout_minutes": 10,
        },
        "twitch": {
            "guest_channels": [],
            "cooldown_seconds": 10,
        },
        "emotions": {
            "joy": {"decay_lambda": 0.01},
        },
        "twitch_events": {
            "follow": {"active": False, "message": "Welcome!"},
        },
    }
