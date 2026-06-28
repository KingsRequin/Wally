from dataclasses import asdict
from bot.config import BotConfig


def test_bedroom_channel_id_default_none():
    cfg = BotConfig(
        name="Wally", trigger_names=[], language_default="fr",
        context_window_size=10, context_token_threshold=1000,
        journal_time="09:00",
    )
    assert cfg.bedroom_channel_id is None


def test_bedroom_channel_id_roundtrips_in_asdict():
    cfg = BotConfig(
        name="Wally", trigger_names=[], language_default="fr",
        context_window_size=10, context_token_threshold=1000,
        journal_time="09:00", bedroom_channel_id=1485380606224502844,
    )
    d = asdict(cfg)
    assert d["bedroom_channel_id"] == 1485380606224502844
    # Reconstruit depuis le dict (ce que fait Config.load avec **raw["bot"])
    assert BotConfig(**d).bedroom_channel_id == 1485380606224502844
