# bot/dashboard/state.py
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from bot.core.overlay_feed import OverlayFeed
    from bot.dashboard.auth import SseTickets
    from bot.config import Config
    from bot.db.database import Database
    from bot.core.emotion import EmotionEngine
    from bot.intelligence.memory.service import MemoryService
    from bot.intelligence.persona import PersonaService
    from bot.core.llm import BaseLLMClient
    from bot.core.llm.openai_client import OpenAILLMClient
    from bot.twitch.token_manager import TwitchTokenManager
    from bot.twitch.api import TwitchAPI
    from bot.discord.bot import WallyDiscord
    from bot.twitch.bot import WallyTwitch
    from bot.intelligence.prompts import PromptBuilder
    from bot.intelligence.fact_extractor import FactExtractor
    from bot.core.notifications import NotificationService
    from bot.intelligence.actions import ActionService
    from bot.core.update_checker import UpdateChecker
    from bot.intelligence.cognitive_feed import CognitiveFeed


def _make_meme_library():
    from bot.core.memes import MemeLibrary
    return MemeLibrary("data/memes")


def _make_overlay_feed():
    from bot.core.overlay_feed import OverlayFeed
    return OverlayFeed()


def _make_sse_tickets():
    from bot.dashboard.auth import SseTickets
    return SseTickets()


@dataclass
class AppState:
    config: "Config"
    db: "Database"
    emotion: "EmotionEngine"
    memory: "MemoryService"
    persona: "PersonaService"
    primary_llm: "BaseLLMClient"
    secondary_llm: "BaseLLMClient"
    image_client: "OpenAILLMClient"
    token_manager: "TwitchTokenManager"
    twitch_api: Optional["TwitchAPI"]
    discord_bot: Optional["WallyDiscord"]
    twitch_bot: Optional["WallyTwitch"]
    prompts: Optional["PromptBuilder"] = None
    fact_extractor: Optional["FactExtractor"] = None
    notifications: Optional["NotificationService"] = None
    action_service: Optional["ActionService"] = None
    update_checker: Optional["UpdateChecker"] = None
    cognitive_feed: Optional["CognitiveFeed"] = None
    # Exposés pour les routes publiques observability (but courant, mémoire,
    # historique du flux) — propagés depuis le bot Discord au boot (cf. bot.py).
    fact_store: object = None
    cognitive_event_store: object = None
    # Suivi/debug du pipeline vocal (live SSE + historique) — propagés depuis bot.py.
    voice_feed: object = None
    voice_event_store: object = None
    start_time: float = field(default_factory=time.time)
    message_count: int = 0
    message_count_discord: int = 0
    message_count_twitch: int = 0
    message_count_web: int = 0
    overlay_visible: bool = True
    overlay_image_queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=1))
    # Diffuseur des bulles et widgets de l'overlay de stream. Fan-out (une file
    # par abonné) et non file unique : OBS et un navigateur de prévisualisation
    # doivent voir la même chose.
    overlay_feed: "OverlayFeed" = field(default_factory=lambda: _make_overlay_feed())
    # Tickets à usage unique des flux SSE admin : `EventSource` ne peut pas
    # porter d'en-tête Authorization (cf. bot/dashboard/auth.py).
    sse_tickets: "SseTickets" = field(default_factory=lambda: _make_sse_tickets())
    # Bibliothèque de memes déposés à la main dans data/memes/ (bind-monté :
    # l'owner y ajoute des images sans redémarrer).
    memes: object = field(default_factory=lambda: _make_meme_library())
    # Dernière télémétrie de rendu envoyée par l'overlay (fps, pire frame, GPU).
    overlay_health: Optional[dict] = None
    _response_times: deque = field(default_factory=lambda: deque(maxlen=50))

    def _init_latency(self) -> None:
        # for tests constructing via __new__ (bypassing dataclass __init__)
        self._response_times = deque(maxlen=50)

    def record_response_time(self, ms: float) -> None:
        self._response_times.append(ms)

    @property
    def avg_response_ms(self):
        if not self._response_times:
            return None
        return round(sum(self._response_times) / len(self._response_times), 1)
