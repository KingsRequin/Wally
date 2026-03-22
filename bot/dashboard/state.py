# bot/dashboard/state.py
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from bot.config import Config
    from bot.db.database import Database
    from bot.core.emotion import EmotionEngine
    from bot.core.memory import MemoryService
    from bot.core.persona import PersonaService
    from bot.core.openai_client import OpenAIClient
    from bot.twitch.token_manager import TwitchTokenManager
    from bot.twitch.api import TwitchAPI
    from bot.discord.bot import WallyDiscord
    from bot.twitch.bot import WallyTwitch
    from bot.core.prompts import PromptBuilder
    from bot.core.fact_extractor import FactExtractor
    from bot.core.notifications import NotificationService
    from bot.core.actions import ActionService


@dataclass
class AppState:
    config: "Config"
    db: "Database"
    emotion: "EmotionEngine"
    memory: "MemoryService"
    persona: "PersonaService"
    openai_client: "OpenAIClient"
    token_manager: "TwitchTokenManager"
    twitch_api: Optional["TwitchAPI"]
    discord_bot: Optional["WallyDiscord"]
    twitch_bot: Optional["WallyTwitch"]
    prompts: Optional["PromptBuilder"] = None
    fact_extractor: Optional["FactExtractor"] = None
    notifications: Optional["NotificationService"] = None
    action_service: Optional["ActionService"] = None
    start_time: float = field(default_factory=time.time)
    message_count: int = 0
    message_count_discord: int = 0
    message_count_twitch: int = 0
    message_count_web: int = 0
    overlay_visible: bool = True
    overlay_image_queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=1))
