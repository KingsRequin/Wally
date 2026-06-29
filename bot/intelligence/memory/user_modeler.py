# bot/intelligence/memory/user_modeler.py
"""Modélisation des personnes : portrait en prose, évolutif et dialectique.

Chaque nuit, pour les personnes dont des faits ont bougé dans la journée,
régénère un portrait à partir de leurs faits actifs ET révolus (superseded)
+ trust/love, stocké dans user_profiles et réinjecté au prompt.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from loguru import logger

from bot.intelligence.prompts import load_prompt

if TYPE_CHECKING:
    pass

_PORTRAIT_PROMPT = load_prompt("user_portrait")

_PORTRAIT_SCHEMA = {
    "type": "object",
    "properties": {
        "portrait": {
            "type": "string",
            "description": "Portrait 3-5 phrases de la personne, intégrant son évolution.",
        }
    },
    "required": ["portrait"],
}


class UserModeler:
    def __init__(self, db, llm_secondary):
        self._db = db
        self._llm = llm_secondary

    async def refresh_profiles(self, since: str | None = None) -> None:
        """Régénère le portrait des personnes actives depuis `since` (ISO UTC)."""
        if self._db is None:
            return
        if since is None:
            since = (datetime.utcnow() - timedelta(days=1)).isoformat()
        try:
            user_ids = await self._db.get_users_with_recent_facts(since)
        except Exception as e:  # noqa: BLE001 — non-fatal
            logger.warning("UserModeler : sélection des personnes échouée : {e}", e=e)
            return
        if not user_ids:
            logger.debug("UserModeler : aucune personne active à modéliser")
            return
        done = 0
        for user_id in user_ids:
            try:
                if await self._refresh_one(user_id):
                    done += 1
            except Exception as e:  # noqa: BLE001 — une personne ne casse pas les autres
                logger.warning("UserModeler : portrait de {u} échoué : {e}", u=user_id, e=e)
        logger.info("UserModeler : {n} portrait(s) régénéré(s)", n=done)

    async def _refresh_one(self, user_id: str) -> bool:
        active = await self._db.get_active_facts_for_user(user_id)
        if not active:
            return False
        superseded = await self._db.get_superseded_facts_for_user(user_id)
        platform, raw_id = user_id.split(":", 1) if ":" in user_id else ("discord", user_id)
        trust = await self._db.get_trust_score(platform, raw_id)
        love = await self._db.get_love_score(platform, raw_id)
        portrait = await self._build_portrait(active, superseded, trust, love)
        if not portrait:
            return False
        await self._db.upsert_user_profile(user_id, portrait)
        return True

    async def _build_portrait(self, active, superseded, trust, love) -> str | None:
        present = "\n".join(f"- {f['content']}" for f in active)
        past = "\n".join(f"- {f['content']}" for f in superseded) or "(rien)"
        payload = (
            f"Traits actuels :\n{present}\n\n"
            f"Ce qu'elle disait avant (révolu) :\n{past}\n\n"
            f"Confiance : {trust:.2f}/1.0 | Affection : {love:.2f}/1.0"
        )
        try:
            result = await self._llm.complete_structured(
                _PORTRAIT_PROMPT,
                [{"role": "user", "content": payload}],
                _PORTRAIT_SCHEMA,
                schema_name="user_portrait",
                purpose="user_model",
            )
        except Exception as e:  # noqa: BLE001 — non-fatal
            logger.warning("UserModeler : génération LLM échouée : {e}", e=e)
            return None
        return (result.get("portrait") or "").strip() or None
