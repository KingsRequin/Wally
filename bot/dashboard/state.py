# bot/dashboard/state.py
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
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
    start_time: float = field(default_factory=time.time)
    message_count: int = 0
    message_count_discord: int = 0
    message_count_twitch: int = 0
    message_count_web: int = 0
    overlay_visible: bool = True
    overlay_image_queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=1))
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
