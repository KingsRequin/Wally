# bot/config.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import yaml
from dotenv import load_dotenv

load_dotenv()


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
    _path: str
    bot: BotConfig
    openai: OpenAIConfig
    discord: DiscordConfig
    twitch: TwitchConfig
    emotions: dict[str, EmotionDecayConfig]
    twitch_events: dict[str, TwitchEventConfig]

    @classmethod
    def load(cls, path: str = "config.yaml") -> "Config":
        with open(path) as f:
            raw = yaml.safe_load(f)
        emotions = {
            k: EmotionDecayConfig(**v)
            for k, v in raw.get("emotions", {}).items()
        }
        twitch_events = {
            k: TwitchEventConfig(**v)
            for k, v in raw.get("twitch_events", {}).items()
        }
        return cls(
            _path=path,
            bot=BotConfig(**raw["bot"]),
            openai=OpenAIConfig(**raw["openai"]),
            discord=DiscordConfig(**raw["discord"]),
            twitch=TwitchConfig(**raw["twitch"]),
            emotions=emotions,
            twitch_events=twitch_events,
        )

    def save(self) -> None:
        data = {
            "bot": {k: v for k, v in vars(self.bot).items()},
            "openai": vars(self.openai),
            "discord": vars(self.discord),
            "twitch": vars(self.twitch),
            "emotions": {k: vars(v) for k, v in self.emotions.items()},
            "twitch_events": {k: vars(v) for k, v in self.twitch_events.items()},
        }
        with open(self._path, "w") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
