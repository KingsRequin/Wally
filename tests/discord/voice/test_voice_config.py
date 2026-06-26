# tests/discord/voice/test_voice_config.py
import yaml
from bot.config import Config, VoiceConfig

# Copie du dict config valide minimal utilisé par tests/test_config.py
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


def test_voice_config_defaults_when_section_absent(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    base = dict(MINIMAL_CONFIG)  # sans clé "voice"
    cfg_file.write_text(yaml.dump(base))
    cfg = Config.load(str(cfg_file))
    assert isinstance(cfg.voice, VoiceConfig)
    assert cfg.voice.enabled is False
    assert cfg.voice.auto_leave_minutes == 2


def test_voice_config_roundtrip(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    base = dict(MINIMAL_CONFIG)
    base["voice"] = {"enabled": True, "language": "fr-FR", "auto_leave_minutes": 2}
    cfg_file.write_text(yaml.dump(base))
    cfg = Config.load(str(cfg_file))
    cfg.save()
    reloaded = Config.load(str(cfg_file))
    assert reloaded.voice.enabled is True
    assert reloaded.voice.language == "fr-FR"
