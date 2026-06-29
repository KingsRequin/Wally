# bot/intelligence/memory/consolidator.py
"""Consolidation nocturne de la mémoire.

Lit les messages durables du jour (daily_log, rétention 7j) via
get_today_messages() et produit un résumé par canal stocké dans
session_analyses pour le recall cross-session.

L'extraction de faits (S-P-O) n'est PAS faite ici : elle est déjà réalisée
en continu par le live (flush à 600 s d'inactivité) et impossible proprement
depuis daily_log (pas de user_id).
"""
from __future__ import annotations

from datetime import datetime

from loguru import logger

from bot.intelligence.prompts import load_prompt

# Chargé une seule fois au niveau module — évite les I/O répétés
_SUMMARY_PROMPT = load_prompt("memory_session_summary")

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
    def __init__(self, db, llm_secondary):
        self._db = db
        self._llm = llm_secondary

    async def consolidate_day(self) -> None:
        """Passe nocturne : résumés cross-session pour chaque canal actif du jour."""
        if self._db is None:
            return

        try:
            rows = await self._db.get_today_messages()
        except Exception as e:  # noqa: BLE001 — non-fatal
            logger.warning("Consolidation : lecture daily_log échouée : {e}", e=e)
            return

        if not rows:
            logger.debug("Consolidation : aucun message à consolider aujourd'hui")
            return

        # Regrouper par canal en conservant la plateforme
        by_channel: dict[str, dict] = {}
        for r in rows:
            ch = by_channel.setdefault(
                r["channel_id"], {"platform": r["platform"], "messages": []}
            )
            ch["messages"].append(r)

        for channel_id, data in by_channel.items():
            msgs = data["messages"]
            platform = data["platform"]
            if len(msgs) < 2:
                continue
            try:
                summary = await self._summarize(msgs)
                if summary:
                    session_id = (
                        f"{platform}:{channel_id}:{datetime.now().strftime('%Y-%m-%d')}"
                    )
                    await self._db.insert_session_analysis(
                        session_id, platform, channel_id, summary
                    )
            except Exception as e:  # noqa: BLE001 — un canal ne doit pas casser les autres
                logger.warning(
                    "Consolidation canal {c} échouée : {e}", c=channel_id, e=e
                )

        logger.info(
            "Consolidation nocturne terminée : {n} canal(aux) traité(s)",
            n=len(by_channel),
        )

    async def _summarize(self, messages: list[dict]) -> str | None:
        """Génère un résumé LLM de la conversation. Retourne None en cas d'échec."""
        convo = "\n".join(f"{m['author']}: {m['content']}" for m in messages)
        try:
            result = await self._llm.complete_structured(
                _SUMMARY_PROMPT,
                [{"role": "user", "content": convo}],
                _SUMMARY_SCHEMA,
                schema_name="session_summary",
                purpose="memory_consolidation",
            )
        except Exception as e:  # noqa: BLE001 — non-fatal
            logger.warning("Consolidation : résumé LLM échoué : {e}", e=e)
            return None
        return (result.get("summary") or "").strip() or None
