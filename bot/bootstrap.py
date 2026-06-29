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
    from bot.intelligence.memory.service import MemoryService
    from bot.core.llm.base import BaseLLMClient
    from bot.core.llm.openai_client import OpenAILLMClient
    from bot.intelligence.prompts import PromptBuilder
    from bot.core.language import LanguageDetector
    from bot.intelligence.journal import DailyJournal
    from bot.intelligence.persona import PersonaService
    from bot.core.web_search import WebSearchService
    from bot.core.scrape import ScrapeService
    from bot.core.apex_api import ApexLegendsService
    from bot.core.vision import VisionService
    from bot.intelligence.actions import ActionRegistry, ActionScheduler, ActionExecutor, ActionService
    from bot.intelligence.fact_extractor import FactExtractor
    from bot.core.reaction_tracker import ReactionTracker
    from apscheduler.schedulers.asyncio import AsyncIOScheduler


@dataclass
class CoreServices:
    config: "Config"
    db: "Database"
    emotion: "EmotionEngine"
    memory: "MemoryService"
    primary_llm: "BaseLLMClient"
    secondary_llm: "BaseLLMClient"
    image_client: "OpenAILLMClient"
    vision: "VisionService"
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
    scrape: "ScrapeService"
    apex_api: "ApexLegendsService"
    shared_scheduler: "AsyncIOScheduler"


async def build_core_services(config: "Config", db: "Database") -> CoreServices:
    """Instancie tous les services core et retourne un CoreServices câblé."""
    from bot.core.emotion import EmotionEngine
    from bot.intelligence.memory.service import MemoryService
    from bot.core.llm import create_llm_client
    from bot.core.llm.openai_client import OpenAILLMClient
    from bot.core.vision import VisionService
    from bot.intelligence.prompts import PromptBuilder
    from bot.core.language import LanguageDetector
    from bot.intelligence.journal import DailyJournal
    from bot.intelligence.persona import PersonaService
    from bot.core.web_search import WebSearchService
    from bot.core.scrape import ScrapeService
    from bot.core.apex_api import ApexLegendsService
    from bot.intelligence.actions import ActionRegistry, ActionScheduler, ActionExecutor, ActionService
    from bot.intelligence.fact_extractor import FactExtractor
    from bot.core.reaction_tracker import ReactionTracker
    from bot.dashboard.routes.sse import broadcast_action_event
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    # ── EmotionEngine ─────────────────────────────────────────────────────────
    emotion = EmotionEngine(config, db=db)
    await emotion.load_state()
    emotion.start_decay_task()
    logger.info("EmotionEngine started with decay task")

    # ── MemoryService ─────────────────────────────────────────────────────────
    memory = MemoryService(config)

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
    from bot.db.schema_v2 import create_v2_tables
    _db_path = _os.getenv("DB_PATH", "data/wally.db")
    # Garantit la table atomic_facts indépendamment du flag response_gate
    # (le backend mémoire V2 y écrit toujours).
    await create_v2_tables(_db_path)
    memory.set_embedding_backend(db_path=_db_path)
    memory.set_openai_client(secondary_llm)
    memory.set_db(db)
    await memory.load_aliases(db)
    emotion.set_openai_client(secondary_llm)
    logger.info("MemoryService and LLM clients initialized")

    # ── VisionService ─────────────────────────────────────────────────────────
    # Le bot tourne en DeepSeek-only (aveugle) : la perception d'image passe
    # obligatoirement par un modèle OpenAI multimodal, distinct du client de
    # génération d'images. Désactivé proprement si OPENAI_API_KEY est absente.
    vision_client = None
    if _os.environ.get("OPENAI_API_KEY"):
        vision_client = OpenAILLMClient(
            model=config.openai.secondary_model,  # gpt-5-nano : multimodal, peu coûteux
            db=db,
            temperature=0.3,
            max_tokens=400,
            reasoning_effort="low",
        )
    vision = VisionService(vision_client)
    if vision.available:
        logger.info("VisionService initialized (model={m})", m=config.openai.secondary_model)
    else:
        logger.warning("VisionService disabled — OPENAI_API_KEY missing")

    # ── Optional services ─────────────────────────────────────────────────────
    web_search = WebSearchService(config, db)
    if web_search.available:
        logger.info("WebSearchService initialized (Tavily)")
    else:
        logger.warning("WebSearchService disabled — TAVILY_API_KEY missing or tavily-python not installed")

    scrape = ScrapeService(config, db, summarizer=secondary_llm)
    if scrape.available:
        logger.info("ScrapeService initialized (Firecrawl)")
    else:
        logger.warning("ScrapeService disabled — FIRECRAWL_API_URL missing or disabled in config")

    apex_api = ApexLegendsService()
    if apex_api.available:
        logger.info("ApexLegendsService initialized")
    else:
        logger.warning("ApexLegendsService disabled — APEX_API_KEY missing")

    # ── Prompts, language, persona ────────────────────────────────────────────
    prompts = PromptBuilder()
    language = LanguageDetector(config.bot.language_default)
    persona = PersonaService(config=config)
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
    # MemoryIngest réutilise le store de faits (set_embedding_backend déjà appelé)
    # pour la réconciliation S-P-O 2 étages (dédup des paraphrases).
    from bot.intelligence.memory.ingest import MemoryIngest
    mem_ingest = None
    if memory.fact_store is not None:
        mem_ingest = MemoryIngest(memory.fact_store, secondary_llm)
        logger.info("MemoryIngest initialized (S-P-O reconciliation)")
    else:
        logger.warning("MemoryIngest non câblé — fact_store indisponible, fallback memory.add")
    fact_extractor = FactExtractor(config, memory, secondary_llm, db=db, ingest=mem_ingest)
    await fact_extractor.restore_buffers()
    logger.info("FactExtractor initialized")

    # ── Consolidation nocturne de la mémoire ──────────────────────────────────
    from bot.intelligence.memory.consolidator import MemoryConsolidator
    consolidator = MemoryConsolidator(db, secondary_llm)
    journal.set_consolidator(consolidator)
    logger.info("MemoryConsolidator initialized")

    # ── Modélisation des personnes (user model) ───────────────────────────────
    from bot.intelligence.memory.user_modeler import UserModeler
    user_modeler = UserModeler(db, secondary_llm)
    journal.set_user_modeler(user_modeler)
    logger.info("UserModeler initialized")

    reaction_tracker = ReactionTracker(emotion, db)
    logger.info("ReactionTracker initialized")

    return CoreServices(
        config=config,
        db=db,
        emotion=emotion,
        memory=memory,
        primary_llm=primary_llm,
        secondary_llm=secondary_llm,
        image_client=image_client,
        vision=vision,
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
        scrape=scrape,
        apex_api=apex_api,
        shared_scheduler=shared_scheduler,
    )
