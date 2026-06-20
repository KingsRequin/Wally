# bot/bootstrap.py
"""
Wiring des services core — partagé par main.py et les tests d'intégration.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bot.config import Config
    from bot.db.database import Database
    from bot.core.emotion import EmotionEngine
    from bot.core.memory import MemoryService
    from bot.core.graph import GraphService
    from bot.core.llm.base import BaseLLMClient
    from bot.core.llm.openai_client import OpenAILLMClient
    from bot.core.prompts import PromptBuilder
    from bot.core.language import LanguageDetector
    from bot.core.journal import DailyJournal
    from bot.core.persona import PersonaService
    from bot.core.web_search import WebSearchService
    from bot.core.apex_api import ApexLegendsService
    from bot.core.actions import ActionRegistry, ActionScheduler, ActionExecutor, ActionService
    from bot.core.fact_extractor import FactExtractor
    from bot.core.reaction_tracker import ReactionTracker
    from apscheduler.schedulers.asyncio import AsyncIOScheduler


@dataclass
class CoreServices:
    config: "Config"
    db: "Database"
    emotion: "EmotionEngine"
    memory: "MemoryService"
    graph: "GraphService"
    primary_llm: "BaseLLMClient"
    secondary_llm: "BaseLLMClient"
    image_client: "OpenAILLMClient"
    prompts: "PromptBuilder"
    language: "LanguageDetector"
    persona: "PersonaService"
    journal: "DailyJournal"
    action_registry: "ActionRegistry"
    action_executor: "ActionExecutor"
    action_scheduler: "ActionScheduler"
    action_service: "ActionService"
    fact_extractor: "FactExtractor"
    reaction_tracker: "ReactionTracker"
    web_search: "WebSearchService"
    apex_api: "ApexLegendsService"
    shared_scheduler: "AsyncIOScheduler"


async def build_core_services(config: "Config", db: "Database", qdrant_url: str) -> CoreServices:
    """Instancie tous les services core et retourne un CoreServices câblé."""
    from bot.core.emotion import EmotionEngine
    from bot.core.memory import MemoryService
    from bot.core.graph import GraphService
    from bot.core.llm import create_llm_client
    from bot.core.llm.openai_client import OpenAILLMClient
    from bot.core.prompts import PromptBuilder
    from bot.core.language import LanguageDetector
    from bot.core.journal import DailyJournal
    from bot.core.persona import PersonaService
    from bot.core.web_search import WebSearchService
    from bot.core.apex_api import ApexLegendsService
    from bot.core.actions import ActionRegistry, ActionScheduler, ActionExecutor, ActionService
    from bot.core.fact_extractor import FactExtractor
    from bot.core.reaction_tracker import ReactionTracker
    from bot.dashboard.routes.sse import broadcast_action_event
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    # ── EmotionEngine ─────────────────────────────────────────────────────────
    emotion = EmotionEngine(config, db=db)
    await emotion.load_state()
    emotion.start_decay_task()
    logger.info("EmotionEngine started with decay task")

    # ── MemoryService + GraphService ──────────────────────────────────────────
    memory = MemoryService(config)
    graph = GraphService(config)
    await graph.initialize()

    # ── LLM clients ───────────────────────────────────────────────────────────
    primary_llm = create_llm_client(config.llm.primary, db)
    secondary_llm = create_llm_client(config.llm.secondary, db)
    # Image client is always OpenAI (Claude/DeepSeek have no image generation API)
    image_client = OpenAILLMClient(
        model=config.llm.primary.model,  # model irrelevant for images
        db=db,
    )
    logger.info("LLM clients created — primary: {p}, secondary: {s}",
                p=type(primary_llm).__name__, s=type(secondary_llm).__name__)

    import os as _os
    from bot.core.embeddings import make_embedding_fn
    _embed_fn = await make_embedding_fn(image_client._client, db)
    _collection = _os.getenv("QDRANT_COLLECTION_NAME", "wally_v2_facts")
    memory.set_embedding_backend(
        db_path=_os.getenv("DB_PATH", "data/wally.db"),
        qdrant_url=qdrant_url,
        collection=_collection,
        embedding_fn=_embed_fn,
    )
    memory.set_openai_client(secondary_llm)
    memory.set_db(db)
    await memory.load_aliases(db)
    emotion.set_openai_client(secondary_llm)
    logger.info("MemoryService and LLM clients initialized")

    # ── Optional services ─────────────────────────────────────────────────────
    web_search = WebSearchService(config, db)
    if web_search.available:
        logger.info("WebSearchService initialized (Tavily)")
    else:
        logger.warning("WebSearchService disabled — TAVILY_API_KEY missing or tavily-python not installed")

    apex_api = ApexLegendsService()
    if apex_api.available:
        logger.info("ApexLegendsService initialized")
    else:
        logger.warning("ApexLegendsService disabled — APEX_API_KEY missing")

    # ── Prompts, language, persona ────────────────────────────────────────────
    prompts = PromptBuilder()
    language = LanguageDetector(config.bot.language_default)
    persona = PersonaService()
    logger.info("PromptBuilder, LanguageDetector, and PersonaService initialized")

    # ── Journal ───────────────────────────────────────────────────────────────
    journal = DailyJournal(config, primary_llm, secondary_llm, emotion, memory, db=db)
    logger.info("DailyJournal initialized")

    # ── Shared scheduler + Action services ────────────────────────────────────
    shared_scheduler = AsyncIOScheduler()

    action_registry = ActionRegistry(db)
    await action_registry.load_permissions()

    action_executor = ActionExecutor(action_registry)
    action_scheduler = ActionScheduler(
        db, action_executor, shared_scheduler, on_change=broadcast_action_event
    )
    action_service = ActionService(action_registry, action_scheduler, db)
    logger.info("ActionService initialized")

    # ── FactExtractor + ReactionTracker ───────────────────────────────────────
    fact_extractor = FactExtractor(config, memory, secondary_llm, db=db, graph=graph)
    await fact_extractor.restore_buffers()
    logger.info("FactExtractor initialized")

    reaction_tracker = ReactionTracker(emotion, db)
    logger.info("ReactionTracker initialized")

    return CoreServices(
        config=config,
        db=db,
        emotion=emotion,
        memory=memory,
        graph=graph,
        primary_llm=primary_llm,
        secondary_llm=secondary_llm,
        image_client=image_client,
        prompts=prompts,
        language=language,
        persona=persona,
        journal=journal,
        action_registry=action_registry,
        action_executor=action_executor,
        action_scheduler=action_scheduler,
        action_service=action_service,
        fact_extractor=fact_extractor,
        reaction_tracker=reaction_tracker,
        web_search=web_search,
        apex_api=apex_api,
        shared_scheduler=shared_scheduler,
    )
