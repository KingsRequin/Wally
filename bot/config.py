# bot/config.py
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional
import yaml


@dataclass
class BotConfig:
    trigger_names: list[str]
    language_default: str
    context_window_size: int
    context_token_threshold: int
    journal_time: str
    system_prompt: str
    journal_channel_id: Optional[int] = None
    dashboard_token: Optional[str] = None
    prelude_window_size: int = 15


@dataclass
class OpenAIConfig:
    primary_model: str
    secondary_model: str
    temperature: float
    max_tokens: int


@dataclass
class DiscordConfig:
    allowed_channels: list[int]
    anger_trigger_threshold: int
    timeout_minutes: int


@dataclass
class TwitchConfig:
    channels: list[str]
    cooldown_seconds: int


@dataclass
class EmotionDecayConfig:
    decay_lambda: float


@dataclass
class TwitchEventConfig:
    active: bool
    message: str


@dataclass
class Config:
    bot: BotConfig
    openai: OpenAIConfig
    discord: DiscordConfig
    twitch: TwitchConfig
    emotions: dict[str, EmotionDecayConfig]
    twitch_events: dict[str, TwitchEventConfig]
    _path: str = field(default="", init=False, repr=False)

    @classmethod
    def load(cls, path: str = "config.yaml") -> "Config":
        with open(path) as f:
            raw = yaml.safe_load(f)
        try:
            emotions = {
                k: EmotionDecayConfig(**v)
                for k, v in raw.get("emotions", {}).items()
            }
            twitch_events = {
                k: TwitchEventConfig(**v)
                for k, v in raw.get("twitch_events", {}).items()
            }
            instance = cls(
                bot=BotConfig(**raw["bot"]),
                openai=OpenAIConfig(**raw["openai"]),
                discord=DiscordConfig(**raw["discord"]),
                twitch=TwitchConfig(**raw["twitch"]),
                emotions=emotions,
                twitch_events=twitch_events,
            )
        except KeyError as e:
            raise ValueError(
                f"Missing required section {e} in config file: {path}"
            ) from e
        instance._path = path
        return instance

    def save(self) -> None:
        if not self._path:
            raise RuntimeError("Config.save() called before Config.load() — no path set")
        data = {
            "bot": asdict(self.bot),
            "openai": asdict(self.openai),
            "discord": asdict(self.discord),
            "twitch": asdict(self.twitch),
            "emotions": {k: asdict(v) for k, v in self.emotions.items()},
            "twitch_events": {k: asdict(v) for k, v in self.twitch_events.items()},
        }
        with open(self._path, "w") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
