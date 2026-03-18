# bot/core/account_linker.py
"""Analyse de similarité de pseudos pour la liaison de comptes Discord/Twitch.

Logique:
- Normaliser les usernames (strip _ttv, séparateurs, chiffres trailing, lowercase)
- Score Jaro-Winkler sur les noms normalisés
- Si score >= threshold → upsert_link_proposal(discord_id, twitch_id, score)
- Discord ID est toujours canonical_id, Twitch ID est toujours alias_id
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bot.db.database import Database

import jellyfish


def _normalize(name: str) -> str:
    """Normalise un username pour la comparaison de similarité.

    Étapes:
    1. Lowercase + strip
    2. Supprimer le suffixe _ttv (avec ou sans underscore)
    3. Supprimer les séparateurs (_, -, .)
    4. Supprimer les chiffres trailing
    """
    name = name.lower().strip()
    name = re.sub(r"\d+$", "", name)
    name = re.sub(r"_?ttv$", "", name)
    name = re.sub(r"[_\-\.]", "", name)
    name = re.sub(r"\d+$", "", name)
    return name.strip()


def score(a: str, b: str) -> float:
    """Score de similarité Jaro-Winkler entre deux noms normalisés."""
    return jellyfish.jaro_winkler_similarity(_normalize(a), _normalize(b))


async def analyze_all(db: "Database", threshold: float = 0.75) -> int:
    """Compare tous les couples discord/twitch et crée des propositions si score >= threshold.

    Retourne le nombre de propositions créées/mises à jour.
    """
    proposals_count = 0
    try:
        # Récupère tous les user_ids existants
        discord_ids = await db.get_platform_users("discord")
        twitch_ids = await db.get_platform_users("twitch")

        for discord_user_id in discord_ids:
            for twitch_user_id in twitch_ids:
                s = score(discord_user_id, twitch_user_id)
                if s >= threshold:
                    canonical_id = f"discord:{discord_user_id}"
                    alias_id = f"twitch:{twitch_user_id}"
                    await db.upsert_link_proposal(canonical_id, alias_id, s)
                    proposals_count += 1
                    logger.info(
                        "Lien proposé: {c} ↔ {a} (score={s:.3f})",
                        c=canonical_id,
                        a=alias_id,
                        s=s,
                    )
    except Exception as e:
        logger.error("analyze_all error: {e}", e=e)
    return proposals_count


async def analyze_new_user(
    db: "Database", new_user_id: str, threshold: float = 0.75
) -> None:
    """Analyse un nouveau user_id contre tous les utilisateurs de la plateforme opposée.

    new_user_id format: "platform:user_id" (ex: "discord:123456789" ou "twitch:kingsrequin")
    Appelé uniquement quand new_user_id est canonique (pas un alias).
    """
    try:
        parts = new_user_id.split(":", 1)
        if len(parts) != 2:
            return
        platform, user_id = parts

        if platform == "discord":
            # Compare contre tous les Twitch
            twitch_ids = await db.get_platform_users("twitch")
            for twitch_user_id in twitch_ids:
                s = score(user_id, twitch_user_id)
                if s >= threshold:
                    canonical_id = new_user_id
                    alias_id = f"twitch:{twitch_user_id}"
                    await db.upsert_link_proposal(canonical_id, alias_id, s)
                    logger.info(
                        "Lien proposé: {c} ↔ {a} (score={s:.3f})",
                        c=canonical_id,
                        a=alias_id,
                        s=s,
                    )
        elif platform == "twitch":
            # Compare contre tous les Discord
            discord_ids = await db.get_platform_users("discord")
            for discord_user_id in discord_ids:
                s = score(discord_user_id, user_id)
                if s >= threshold:
                    canonical_id = f"discord:{discord_user_id}"
                    alias_id = new_user_id
                    await db.upsert_link_proposal(canonical_id, alias_id, s)
                    logger.info(
                        "Lien proposé: {c} ↔ {a} (score={s:.3f})",
                        c=canonical_id,
                        a=alias_id,
                        s=s,
                    )
    except Exception as e:
        logger.error("analyze_new_user error: {e}", e=e)
