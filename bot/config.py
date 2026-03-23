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
    journal_channel_id: Optional[int] = None
    dashboard_token: Optional[str] = None
    prelude_window_size: int = 15
    link_min_confidence: float = 0.75
    cost_alert_threshold: float = 25.0
    notification_guild_id: int | None = None
    notification_channel_id: int | None = None
    emotion_peak_threshold: float = 0.7
    emotion_inertia_factor: float = 0.5
    spontaneous_discord_enabled: bool = True
    spontaneous_twitch_enabled: bool = True
    spontaneous_probability: float = 0.05
    spontaneous_passion_probability: float = 0.15
    spontaneous_cooldown_seconds: int = 300
    spontaneous_memory_probability: float = 0.2
    memory_recall_min_score: float = 0.75
    love_decay_lambda: float = 0.1


VALID_REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh")
VALID_TEXT_VERBOSITIES = ("low", "medium", "high")


@dataclass
class OpenAIConfig:
    primary_model: str
    secondary_model: str
    temperature: float
    max_tokens: int
    reasoning_effort: str = "medium"
    text_verbosity: str = "medium"


@dataclass
class SpamDetectionConfig:
    enabled: bool = True
    max_messages: int = 10
    window_seconds: int = 120
    mute_minutes: int = 5
    spam_anger_delta: float = 0.05
    exempt_channels: list[int] = field(default_factory=list)


@dataclass
class DiscordConfig:
    anger_trigger_threshold: int
    timeout_minutes: int
    channel_filter_mode: str = "blacklist"
    channel_whitelist: list[int] = field(default_factory=list)
    channel_blacklist: list[int] = field(default_factory=list)
    emoji_reaction_probability: float = 0.05
    spam_detection: SpamDetectionConfig = field(default_factory=SpamDetectionConfig)


@dataclass
class TwitchConfig:
    guest_channels: list[str]
    cooldown_seconds: int


@dataclass
class EmotionDecayConfig:
    decay_lambda: float
    boredom_rise_per_hour: float | None = None


@dataclass
class TwitchEventConfig:
    active: bool
    message: str


@dataclass
class TavilyConfig:
    monthly_limit: int = 200


@dataclass
class WebChatConfig:
    cooldown_seconds: int = 10
    history_limit: int = 50
    random_avatar_chance: float = 0.05
    overlay_visible: bool = True


@dataclass
class ImageGenerationConfig:
    model: str = "gpt-image-1.5"
    quality: str = "medium"
    size: str = "1024x1024"
    background: str = "auto"
    format: str = "png"
    daily_limit: int = -1
    per_user_limit: int = 5


@dataclass
class OverlayImageConfig:
    command: str = "!image"
    display_duration: int = 15
    animation_in: str = "fadeIn"
    animation_out: str = "fadeOut"
    animation_duration: float = 1.0
    random_filter: str = "all"
    enabled: bool = True


@dataclass
class Config:
    bot: BotConfig
    openai: OpenAIConfig
    discord: DiscordConfig
    twitch: TwitchConfig
    emotions: dict[str, EmotionDecayConfig]
    twitch_events: dict[str, TwitchEventConfig]
    tavily: TavilyConfig = field(default_factory=TavilyConfig)
    web_chat: WebChatConfig = field(default_factory=WebChatConfig)
    image_generation: ImageGenerationConfig = field(default_factory=ImageGenerationConfig)
    overlay_image: OverlayImageConfig = field(default_factory=OverlayImageConfig)
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
            twitch_raw = dict(raw.get("twitch", {}))
            # Migration : ancien champ "channels" → "guest_channels"
            if "guest_channels" not in twitch_raw and "channels" in twitch_raw:
                import os as _os
                home_login = _os.getenv("TWITCH_BROADCASTER_LOGIN", "").lower()
                twitch_raw["guest_channels"] = [
                    ch for ch in twitch_raw.pop("channels") if ch.lower() != home_login
                ]
            else:
                twitch_raw.setdefault("guest_channels", [])
                twitch_raw.pop("channels", None)
            tavily_raw = raw.get("tavily", {})
            web_chat_raw = raw.get("web_chat", {})
            image_generation = ImageGenerationConfig(**raw.get("image_generation", {}))
            overlay_image = OverlayImageConfig(**raw.get("overlay_image", {}))
            discord_raw = dict(raw.get("discord", {}))
            spam_raw = discord_raw.pop("spam_detection", {})
            instance = cls(
                bot=BotConfig(**raw["bot"]),
                openai=OpenAIConfig(**raw["openai"]),
                discord=DiscordConfig(**discord_raw, spam_detection=SpamDetectionConfig(**spam_raw)),
                twitch=TwitchConfig(**twitch_raw),
                emotions=emotions,
                twitch_events=twitch_events,
                tavily=TavilyConfig(**tavily_raw),
                web_chat=WebChatConfig(**web_chat_raw),
                image_generation=image_generation,
                overlay_image=overlay_image,
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
            "tavily": asdict(self.tavily),
            "web_chat": asdict(self.web_chat),
            "image_generation": asdict(self.image_generation),
            "overlay_image": asdict(self.overlay_image),
        }
        with open(self._path, "w") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
