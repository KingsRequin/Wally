# bot/intelligence/memory/user_modeler.py
"""Modélisation des personnes : portrait en prose, évolutif et dialectique.

Chaque nuit, pour les personnes dont des faits ont bougé dans la journée,
régénère un portrait à partir de leurs faits actifs ET révolus (superseded)
+ trust/love, stocké dans user_profiles et réinjecté au prompt.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from loguru import logger

from bot.intelligence.prompts import load_prompt

_PORTRAIT_PROMPT = load_prompt("user_portrait")

# ── Genre : lu dans les faits, jamais déduit du pseudo ────────────────────────
# La consigne seule ne mordait pas. Le 2026-08-24, 58 des 126 portraits parlaient
# au féminin alors que 3 personnes seulement avaient un fait de genre : le modèle
# le devinait du pseudo, et se contredisait dans la phrase même (« toineleviking
# est un joueur (…) séduite (…) elle », « Jubeii (…) père de famille (…) elle »).
# On tranche donc AVANT l'appel, sur ce que la base dit — et l'inconnu reste
# inconnu. Les deux formulations couvertes sont celles que le `fact_extractor`
# produit réellement (« est un homme (pronom il) »).
_GENRE_MOTIFS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("masculin", re.compile(r"est un homme|pronom\s*:?\s*«?\s*il\b", re.IGNORECASE)),
    ("féminin", re.compile(r"est une femme|pronom\s*:?\s*«?\s*elle\b", re.IGNORECASE)),
)


def genre_etabli(faits: list[dict]) -> str | None:
    """Genre affirmé par les faits, ou None — inconnu ET contradictoire.

    Deux faits qui s'opposent rendent None à dessein : un portrait neutre est
    toujours moins faux qu'un portrait qui tranche à pile ou face.
    """
    trouves = {
        nom
        for nom, motif in _GENRE_MOTIFS
        for f in faits
        if motif.search(f.get("content") or "")
    }
    return trouves.pop() if len(trouves) == 1 else None

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
            logger.warning("UserModeler : sélection des personnes échouée : {e!r}", e=e)
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
                logger.warning("UserModeler : portrait de {u} échoué : {e!r}", u=user_id, e=e)
        logger.info("UserModeler : {n} portrait(s) régénéré(s)", n=done)

    async def _refresh_one(self, user_id: str) -> bool:
        active = await self._db.get_active_facts_for_user(user_id)
        if not active:
            return False
        superseded = await self._db.get_superseded_facts_for_user(user_id)
        platform, raw_id = user_id.split(":", 1) if ":" in user_id else ("discord", user_id)
        trust = await self._db.get_trust_score(platform, raw_id)
        love = await self._db.get_love_score(platform, raw_id)
        name = await self._username(user_id) or raw_id
        # Le genre se cherche hors du lot servi au portrait : celui-ci est
        # plafonné à 50 faits par importance, et chez une personne à 900 faits
        # celui qui porte le genre n'y est pas. Vu le 2026-08-24 — KingsRequin
        # restait au féminin cinq jours après s'être corrigé.
        genre = genre_etabli(await self._db.get_gender_facts_for_user(user_id))
        portrait = await self._build_portrait(name, active, superseded, trust, love, genre)
        if not portrait:
            return False
        await self._db.upsert_user_profile(user_id, portrait)
        return True

    async def _username(self, user_id: str) -> str | None:
        # Sans nom, le seul nom du contexte est celui du bot (le prompt système
        # est écrit à la 2e personne) : le modèle attribue alors le portrait à
        # Wally. 11 fiches sur 95 étaient dans ce cas au 2026-08-10.
        try:
            return await self._db.get_memory_username(user_id)
        except Exception as e:  # noqa: BLE001 — un pseudo manquant ne bloque rien
            logger.warning("UserModeler : pseudo de {u} illisible : {e!r}", u=user_id, e=e)
            return None

    async def _build_portrait(
        self, name, active, superseded, trust, love, genre=None
    ) -> str | None:
        present = "\n".join(f"- {f['content']}" for f in active)
        past = "\n".join(f"- {f['content']}" for f in superseded) or "(rien)"
        consigne_genre = (
            f"Genre : {genre} — emploie ce genre, pronoms et accords compris."
            if genre
            else "Genre : INCONNU — n'emploie ni « il », ni « elle », ni aucun accord genré. "
            "Reprends le pseudo, ou tourne la phrase autrement."
        )
        payload = (
            f"Personne décrite : {name}\n"
            f"{consigne_genre}\n\n"
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
            logger.warning("UserModeler : génération LLM échouée : {e!r}", e=e)
            return None
        return (result.get("portrait") or "").strip() or None
