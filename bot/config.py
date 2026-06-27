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
    memory_search_min_score: float = 0.5
    memory_context_max_tokens: int = 800
    love_decay_lambda: float = 0.1
    update_image: str = ""          # ex: "ghcr.io/user/wally-ai:latest" — vide = polling désactivé
    # --- identité multi-instance ---
    name: str = "Wally"
    creator_name: str = "KingsRequin"
    owner_discord_id: str = ""
    self_modify_enabled: bool = False


VALID_REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh")
VALID_TEXT_VERBOSITIES = ("low", "medium", "high")
VALID_LLM_PROVIDERS = ("openai", "claude")
VALID_THINKING_TYPES = ("disabled", "enabled", "adaptive")
VALID_THINKING_EFFORTS = ("low", "medium", "high", "max")


@dataclass
class LLMRoleConfig:
    provider: str
    model: str
    temperature: float = 0.8
    max_tokens: int = 1000
    reasoning_effort: str = "medium"      # OpenAI-specific, ignored by Claude
    text_verbosity: str = "medium"        # OpenAI-specific, ignored by Claude
    thinking_type: str = "disabled"       # Claude-specific: disabled/enabled/adaptive
    thinking_budget_tokens: int = 10000   # Claude-specific: budget for type=enabled
    thinking_effort: str = "medium"       # Claude-specific: effort for type=adaptive (low/medium/high)


@dataclass
class LLMConfig:
    primary: LLMRoleConfig
    secondary: LLMRoleConfig


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
class VoiceConfig:
    enabled: bool = False
    stt_provider: str = "azure"  # "azure" | "faster_whisper" (STT local CPU) | "remote_stream" (GPU distant)
    tts_provider: str = "azure"
    language: str = "fr-FR"
    azure_voice: str = "fr-FR-DeniseNeural"  # voix FR à affiner plus tard
    auto_leave_minutes: int = 2
    vad_aggressiveness: int = 2  # webrtcvad 0..3
    # Discord supprime les silences → plus aucune frame quand on se tait, et le VAD ne voit
    # jamais la fin de l'énoncé. Ce délai (s) sans frame clôt l'énoncé à l'horloge (flush_idle).
    vad_silence_timeout_s: float = 0.6
    whisper_model: str = "small"  # faster-whisper : tiny|base|small|medium...
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_cpu_threads: int = 0  # 0 = auto ; les transcriptions sont sérialisées (1 à la fois)
    # STT streaming distant (serveur RealtimeSTT GPU, cf docs/voice/REMOTE_STT_API.md)
    remote_stt_url: str = "ws://192.168.1.49:9090"
    remote_stt_max_connections: int = 2  # limite VRAM du serveur (2 sur RTX 4070 12 Go)
    remote_stt_idle_timeout: float = 30.0  # ferme une session inactive (libère un slot serveur)
    remote_stt_health_cache_s: float = 30.0  # durée du cache « serveur injoignable » avant retry
    remote_stt_fallback: str = "faster_whisper"  # provider batch CPU si le distant est indispo


@dataclass
class DiscordConfig:
    anger_trigger_threshold: int
    timeout_minutes: int
    channel_filter_mode: str = "blacklist"
    channel_whitelist: list[int] = field(default_factory=list)
    channel_blacklist: list[int] = field(default_factory=list)
    ignored_guilds: list[int] = field(default_factory=list)
    per_guild_channel_whitelist: dict = field(default_factory=dict)
    always_trigger_channels: list[int] = field(default_factory=list)
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
class MoodConfig:
    alpha: float = 0.02
    decay_lambda: float = 0.1
    bias_factor: float = 0.3


@dataclass
class FatigueConfig:
    dampening: float = 0.7
    recovery_rate: float = 0.1


@dataclass
class HabituationConfig:
    threshold_count: int = 3
    window_seconds: int = 600
    decay_factor: float = 0.5
    reset_seconds: int = 1800
    exempt: list[str] = field(default_factory=lambda: ["anger"])


@dataclass
class EmotionalMemoryConfig:
    learning_rate: float = 0.05
    priming_factor: float = 0.05
    amplification_factor: float = 0.3
    decay_lambda_per_day: float = 0.01


@dataclass
class CircadianPeriod:
    hours: list[int] = field(default_factory=lambda: [0, 0])
    anger: float = 1.0
    joy: float = 1.0
    sadness: float = 1.0
    curiosity: float = 1.0
    boredom: float = 1.0


@dataclass
class CircadianConfig:
    enabled: bool = True
    timezone: str = "Europe/Paris"
    transition_minutes: int = 30
    periods: dict[str, CircadianPeriod] = field(default_factory=lambda: {
        "night": CircadianPeriod(hours=[0, 6], anger=1.3, curiosity=0.8, boredom=1.1),
        "morning": CircadianPeriod(hours=[6, 12], anger=0.9, joy=1.1, sadness=0.9, curiosity=1.2, boredom=0.9),
        "afternoon": CircadianPeriod(hours=[12, 18]),
        "evening": CircadianPeriod(hours=[18, 24], sadness=1.15),
    })


@dataclass
class SpontaneousEvent:
    weight: int = 0
    effects: dict[str, float] = field(default_factory=dict)


@dataclass
class SpontaneousConfig:
    probability_per_tick: float = 0.02
    max_delta: float = 0.1
    events: dict[str, SpontaneousEvent] = field(default_factory=lambda: {
        "wandering_thought": SpontaneousEvent(weight=30, effects={"curiosity": 0.05}),
        "pleasant_memory": SpontaneousEvent(weight=20, effects={"joy": 0.05}),
        "unpleasant_memory": SpontaneousEvent(weight=10, effects={"sadness": 0.05}),
        "existential_ennui": SpontaneousEvent(weight=25, effects={"boredom": 0.08}),
        "creative_spark": SpontaneousEvent(weight=15, effects={"curiosity": 0.08, "boredom": -0.1}),
    })


@dataclass
class SecondaryEmotionDef:
    a: str = ""
    b: str = ""
    threshold: float | list[float] = 0.3


@dataclass
class TwitchEventConfig:
    active: bool
    message: str


@dataclass
class TavilyConfig:
    monthly_limit: int = 200


@dataclass
class FirecrawlConfig:
    enabled: bool = True
    inline_max_tokens: int = 2000
    auto_scrape_links: bool = True
    auto_scrape_cooldown_s: int = 30
    daily_limit: int = 200


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


VALID_LAYOUT_VARIANTS = ("sidebar-left", "sidebar-top", "sidebar-mini")
VALID_TAB_STYLES = ("icons-only", "icons-labels", "text-only")


@dataclass
class ThemeConfig:
    accent_color: str = "#06b6d4"
    bg_color: str = "#11151c"
    surface_color: str = "rgba(255,255,255,0.03)"
    sidebar_bg: str = "rgba(255,255,255,0.02)"
    layout_variant: str = "sidebar-left"
    tab_style: str = "icons-only"


@dataclass
class Config:
    bot: BotConfig
    openai: OpenAIConfig
    llm: LLMConfig
    discord: DiscordConfig
    twitch: TwitchConfig
    emotions: dict[str, EmotionDecayConfig]
    twitch_events: dict[str, TwitchEventConfig]
    tavily: TavilyConfig = field(default_factory=TavilyConfig)
    firecrawl: FirecrawlConfig = field(default_factory=FirecrawlConfig)
    web_chat: WebChatConfig = field(default_factory=WebChatConfig)
    image_generation: ImageGenerationConfig = field(default_factory=ImageGenerationConfig)
    overlay_image: OverlayImageConfig = field(default_factory=OverlayImageConfig)
    theme: ThemeConfig = field(default_factory=ThemeConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    mood: MoodConfig = field(default_factory=MoodConfig)
    fatigue: FatigueConfig = field(default_factory=FatigueConfig)
    habituation: HabituationConfig = field(default_factory=HabituationConfig)
    emotional_memory: EmotionalMemoryConfig = field(default_factory=EmotionalMemoryConfig)
    circadian: CircadianConfig = field(default_factory=CircadianConfig)
    spontaneous: SpontaneousConfig = field(default_factory=SpontaneousConfig)
    response_gate: dict = field(default_factory=dict)
    cognitive_loop: dict = field(default_factory=dict)
    secondaries: dict[str, SecondaryEmotionDef] = field(default_factory=lambda: {
        "frustration": SecondaryEmotionDef(a="anger", b="boredom", threshold=0.3),
        "nostalgia": SecondaryEmotionDef(a="joy", b="sadness", threshold=0.3),
        "pride": SecondaryEmotionDef(a="joy", b="curiosity", threshold=0.4),
        "anxiety": SecondaryEmotionDef(a="sadness", b="curiosity", threshold=0.3),
        "contempt": SecondaryEmotionDef(a="anger", b="boredom", threshold=[0.4, 0.5]),
        "wonder": SecondaryEmotionDef(a="curiosity", b="joy", threshold=0.5),
    })
    _path: str = field(default="", init=False, repr=False)

    @classmethod
    def _build_llm_config(cls, raw: dict) -> LLMConfig:
        """Build LLMConfig from raw YAML data.

        Supports new 'llm' section. Falls back to legacy 'openai' section
        if 'llm' is absent (all providers default to openai).
        """
        if "llm" in raw:
            llm_raw = raw["llm"]
            return LLMConfig(
                primary=LLMRoleConfig(**llm_raw["primary"]),
                secondary=LLMRoleConfig(**llm_raw["secondary"]),
            )
        # Legacy fallback: build from openai section
        openai_raw = raw.get("openai", {})
        return LLMConfig(
            primary=LLMRoleConfig(
                provider="openai",
                model=openai_raw.get("primary_model", "gpt-5.1"),
                temperature=openai_raw.get("temperature", 0.8),
                max_tokens=openai_raw.get("max_tokens", 1000),
                reasoning_effort=openai_raw.get("reasoning_effort", "medium"),
                text_verbosity=openai_raw.get("text_verbosity", "medium"),
            ),
            secondary=LLMRoleConfig(
                provider="openai",
                model=openai_raw.get("secondary_model", "gpt-5-mini"),
                temperature=openai_raw.get("temperature", 0.8),
                max_tokens=openai_raw.get("max_tokens", 1000),
                reasoning_effort=openai_raw.get("reasoning_effort", "medium"),
                text_verbosity=openai_raw.get("text_verbosity", "medium"),
            ),
        )

    @classmethod
    def load(cls, path: str = "config.yaml") -> "Config":
        with open(path) as f:
            raw = yaml.safe_load(f)
        try:
            _ORGANIC_KEYS = {"mood", "fatigue", "habituation", "memory", "circadian", "spontaneous", "secondaries"}
            emotions = {
                k: EmotionDecayConfig(**v)
                for k, v in raw.get("emotions", {}).items()
                if k not in _ORGANIC_KEYS
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
            firecrawl_raw = raw.get("firecrawl", {})
            web_chat_raw = raw.get("web_chat", {})
            image_generation = ImageGenerationConfig(**raw.get("image_generation", {}))
            overlay_image = OverlayImageConfig(**raw.get("overlay_image", {}))
            theme = ThemeConfig(**raw.get("theme", {}))
            voice_raw = dict(raw.get("voice", {}))
            # --- Organic emotion configs (nested under emotions:) ---
            emo_raw = raw.get("emotions", {})
            mood_cfg = MoodConfig(**emo_raw.get("mood", {}))
            fatigue_cfg = FatigueConfig(**emo_raw.get("fatigue", {}))
            habituation_cfg = HabituationConfig(**emo_raw.get("habituation", {}))
            emotional_memory_cfg = EmotionalMemoryConfig(**emo_raw.get("memory", {}))
            # Circadian
            circ_raw = emo_raw.get("circadian", {})
            if circ_raw:
                circ_periods = {}
                for name, pdata in circ_raw.get("periods", {}).items():
                    circ_periods[name] = CircadianPeriod(**pdata)
                circ_kwargs = {k: v for k, v in circ_raw.items() if k != "periods"}
                if circ_periods:
                    circ_kwargs["periods"] = circ_periods
                circadian_cfg = CircadianConfig(**circ_kwargs)
            else:
                circadian_cfg = CircadianConfig()
            # Spontaneous
            spont_raw = emo_raw.get("spontaneous", {})
            if spont_raw:
                spont_events = {}
                for name, edata in spont_raw.get("events", {}).items():
                    spont_events[name] = SpontaneousEvent(**edata)
                spont_kwargs = {k: v for k, v in spont_raw.items() if k != "events"}
                if spont_events:
                    spont_kwargs["events"] = spont_events
                spontaneous_cfg = SpontaneousConfig(**spont_kwargs)
            else:
                spontaneous_cfg = SpontaneousConfig()
            # Secondaries
            sec_raw = emo_raw.get("secondaries", {})
            if sec_raw:
                secondaries_cfg = {
                    name: SecondaryEmotionDef(**sdata) for name, sdata in sec_raw.items()
                }
            else:
                secondaries_cfg = None  # use default_factory
            response_gate_cfg = raw.get("response_gate", {})
            cognitive_loop_cfg = raw.get("cognitive_loop", {})
            discord_raw = dict(raw.get("discord", {}))
            spam_raw = discord_raw.pop("spam_detection", {})
            llm_config = cls._build_llm_config(raw)
            # Build OpenAIConfig from raw or synthesize from llm config
            openai_raw = raw.get("openai")
            if openai_raw:
                openai_config = OpenAIConfig(**openai_raw)
            else:
                openai_config = OpenAIConfig(
                    primary_model=llm_config.primary.model,
                    secondary_model=llm_config.secondary.model,
                    temperature=llm_config.primary.temperature,
                    max_tokens=llm_config.primary.max_tokens,
                    reasoning_effort=llm_config.primary.reasoning_effort,
                    text_verbosity=llm_config.primary.text_verbosity,
                )
            instance = cls(
                bot=BotConfig(**raw["bot"]),
                openai=openai_config,
                llm=llm_config,
                discord=DiscordConfig(**discord_raw, spam_detection=SpamDetectionConfig(**spam_raw)),
                twitch=TwitchConfig(**twitch_raw),
                emotions=emotions,
                twitch_events=twitch_events,
                tavily=TavilyConfig(**tavily_raw),
                firecrawl=FirecrawlConfig(**firecrawl_raw),
                web_chat=WebChatConfig(**web_chat_raw),
                image_generation=image_generation,
                overlay_image=overlay_image,
                theme=theme,
                voice=VoiceConfig(**voice_raw),
                mood=mood_cfg,
                fatigue=fatigue_cfg,
                habituation=habituation_cfg,
                emotional_memory=emotional_memory_cfg,
                circadian=circadian_cfg,
                spontaneous=spontaneous_cfg,
                response_gate=response_gate_cfg,
                cognitive_loop=cognitive_loop_cfg,
                **({"secondaries": secondaries_cfg} if secondaries_cfg is not None else {}),
            )
        except (KeyError, TypeError) as e:
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
            "llm": asdict(self.llm),
            "discord": asdict(self.discord),
            "twitch": asdict(self.twitch),
            "twitch_events": {k: asdict(v) for k, v in self.twitch_events.items()},
            "tavily": asdict(self.tavily),
            "firecrawl": asdict(self.firecrawl),
            "web_chat": asdict(self.web_chat),
            "image_generation": asdict(self.image_generation),
            "overlay_image": asdict(self.overlay_image),
            "theme": asdict(self.theme),
            "voice": asdict(self.voice),
            "response_gate": self.response_gate,
            "cognitive_loop": self.cognitive_loop,
        }
        emotions_data = {k: asdict(v) for k, v in self.emotions.items()}
        emotions_data["mood"] = asdict(self.mood)
        emotions_data["fatigue"] = asdict(self.fatigue)
        emotions_data["habituation"] = asdict(self.habituation)
        emotions_data["memory"] = asdict(self.emotional_memory)
        emotions_data["circadian"] = asdict(self.circadian)
        emotions_data["spontaneous"] = asdict(self.spontaneous)
        emotions_data["secondaries"] = {k: asdict(v) for k, v in self.secondaries.items()}
        data["emotions"] = emotions_data
        with open(self._path, "w") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
