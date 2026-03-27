"""Tests for organic emotion config dataclasses."""
import pytest
from bot.config import (
    MoodConfig, FatigueConfig, HabituationConfig, EmotionalMemoryConfig,
    CircadianPeriod, CircadianConfig, SpontaneousEvent, SpontaneousConfig,
    SecondaryEmotionDef, Config,
)


def test_mood_config_defaults():
    cfg = MoodConfig()
    assert cfg.alpha == 0.02
    assert cfg.decay_lambda == 0.1
    assert cfg.bias_factor == 0.3


def test_fatigue_config_defaults():
    cfg = FatigueConfig()
    assert cfg.dampening == 0.7
    assert cfg.recovery_rate == 0.1


def test_habituation_config_defaults():
    cfg = HabituationConfig()
    assert cfg.threshold_count == 3
    assert cfg.window_seconds == 600
    assert cfg.decay_factor == 0.5
    assert cfg.reset_seconds == 1800
    assert cfg.exempt == ["anger"]


def test_emotional_memory_config_defaults():
    cfg = EmotionalMemoryConfig()
    assert cfg.learning_rate == 0.05
    assert cfg.priming_factor == 0.05
    assert cfg.amplification_factor == 0.3
    assert cfg.decay_lambda_per_day == 0.01


def test_circadian_period():
    p = CircadianPeriod(hours=[0, 6], anger=1.3, joy=1.0, sadness=1.0, curiosity=0.8, boredom=1.1)
    assert p.hours == [0, 6]
    assert p.anger == 1.3


def test_circadian_config_defaults():
    cfg = CircadianConfig()
    assert cfg.enabled is True
    assert cfg.timezone == "Europe/Paris"
    assert cfg.transition_minutes == 30
    assert "night" in cfg.periods
    assert "morning" in cfg.periods
    assert "afternoon" in cfg.periods
    assert "evening" in cfg.periods


def test_spontaneous_event():
    e = SpontaneousEvent(weight=30, effects={"curiosity": 0.05})
    assert e.weight == 30
    assert e.effects == {"curiosity": 0.05}


def test_spontaneous_config_defaults():
    cfg = SpontaneousConfig()
    assert cfg.probability_per_tick == 0.02
    assert cfg.max_delta == 0.1
    assert "wandering_thought" in cfg.events


def test_secondary_emotion_def():
    s = SecondaryEmotionDef(a="anger", b="boredom", threshold=0.3)
    assert s.a == "anger"
    assert s.threshold == 0.3


def test_secondary_emotion_def_asymmetric_threshold():
    s = SecondaryEmotionDef(a="anger", b="boredom", threshold=[0.4, 0.5])
    assert s.threshold == [0.4, 0.5]


def test_config_save_load_roundtrip(tmp_path):
    """New organic emotion configs should survive save/load cycle."""
    cfg = Config.load("config.yaml")
    cfg.mood.alpha = 0.05
    cfg.fatigue.dampening = 0.9
    cfg.circadian.enabled = False
    test_path = str(tmp_path / "test_config.yaml")
    cfg._path = test_path
    cfg.save()
    cfg2 = Config.load(test_path)
    assert cfg2.mood.alpha == 0.05
    assert cfg2.fatigue.dampening == 0.9
    assert cfg2.circadian.enabled is False
