# bot/intelligence/memory/consolidator.py
"""Consolidation nocturne de la mémoire.

Relit les conversations du jour (messages de session persistés), en extrait les
faits durables via le pipeline existant (FactExtractor._extract_facts →
MemoryIngest, dédupé) et produit un résumé par canal stocké dans
session_analyses pour le recall cross-session.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

from bot.intelligence.prompts import load_prompt

if TYPE_CHECKING:
    from bot.intelligence.fact_extractor import FactExtractor
    from bot.intelligence.memory.service import MemoryService

_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "Résumé 2-4 phrases de la conversation, comme un souvenir.",
        }
    },
    "required": ["summary"],
}


class MemoryConsolidator:
    def __init__(self, db, llm_secondary, fact_extractor: "FactExtractor", memory: "MemoryService"):
        self._db = db
        self._llm = llm_secondary
        self._fact_extractor = fact_extractor
        self._memory = memory

    async def consolidate_day(self, since: float | None = None) -> None:
        """Passe nocturne : faits + résumés pour chaque canal actif du jour."""
        if self._db is None:
            return
        if since is None:
            now = datetime.now()
            since = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        try:
            rows = await self._db.get_recent_session_messages(since)
        except Exception as e:  # noqa: BLE001 — non-fatal
            logger.warning("Consolidation : lecture des messages échouée : {e}", e=e)
            return
        if not rows:
            logger.debug("Consolidation : aucun message à consolider")
            return

        by_channel: dict[str, dict] = {}
        for r in rows:
            ch = by_channel.setdefault(
                r["channel_id"], {"platform": r["platform"], "messages": []}
            )
            ch["messages"].append(r)

        for channel_id, data in by_channel.items():
            try:
                await self._consolidate_channel(channel_id, data["platform"], data["messages"])
            except Exception as e:  # noqa: BLE001 — un canal ne doit pas casser les autres
                logger.warning("Consolidation canal {c} échouée : {e}", c=channel_id, e=e)
        logger.info("Consolidation nocturne terminée : {n} canal(aux)", n=len(by_channel))

    async def _consolidate_channel(self, channel_id: str, platform: str, messages: list[dict]) -> None:
        if len(messages) < 2:
            return
        # (a) Faits durables — pipeline existant, réconciliation dédupe
        await self._fact_extractor._extract_facts(
            messages, platform, channel_id, origin="consolidation"
        )
        # (b) Résumé de session pour le recall
        summary = await self._summarize(messages)
        if summary:
            session_id = f"{platform}:{channel_id}:{datetime.now().strftime('%Y-%m-%d')}"
            await self._db.insert_session_analysis(session_id, platform, channel_id, summary)

    async def _summarize(self, messages: list[dict]) -> str | None:
        convo = "\n".join(f"{m['display_name']}: {m['content']}" for m in messages)
        try:
            result = await self._llm.complete_structured(
                load_prompt("memory_session_summary"),
                [{"role": "user", "content": convo}],
                _SUMMARY_SCHEMA,
                schema_name="session_summary",
                purpose="memory_consolidation",
            )
        except Exception as e:  # noqa: BLE001 — non-fatal, on garde les faits extraits
            logger.warning("Consolidation : résumé LLM échoué : {e}", e=e)
            return None
        return (result.get("summary") or "").strip() or None
