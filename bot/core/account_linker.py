# bot/core/account_linker.py
"""Analyse de similarité de pseudos pour la liaison de comptes Discord/Twitch.

Logique:
- Normaliser les usernames (strip _ttv, séparateurs, chiffres trailing, lowercase)
- Score Jaro-Winkler sur les noms normalisés
- Si score >= threshold → upsert_link_proposal(discord_id, twitch_id, score)
- Discord ID est toujours canonical_id, Twitch ID est toujours alias_id

get_platform_users retourne des dicts {raw_id, username, full_id}.
Pour Discord, raw_id est numérique (inutile) → on utilise username (display_name).
Pour Twitch, raw_id EST le username.
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
    2. Supprimer les chiffres trailing
    3. Supprimer le suffixe _ttv (avec ou sans underscore)
    4. Supprimer les séparateurs (_, -, .)
    5. Supprimer les chiffres trailing (second pass)
    """
    name = name.lower().strip()
    name = re.sub(r"\d+$", "", name)
    name = re.sub(r"_?ttv$", "", name)
    name = re.sub(r"[_\-\.]", "", name)
    name = re.sub(r"\d+$", "", name)
    return name.strip()


def score(a: str, b: str) -> float:
    """Score de similarité Jaro-Winkler entre deux noms normalisés."""
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return 0.0
    return jellyfish.jaro_winkler_similarity(na, nb)


def _get_comparable_name(user: dict, platform: str) -> str | None:
    """Retourne le nom utilisable pour la comparaison Jaro-Winkler.

    Pour les deux plateformes, on utilise le champ 'username' de memory_users
    car raw_id est numérique (Discord = snowflake, Twitch = numeric user ID).
    Fallback sur raw_id uniquement s'il n'est pas purement numérique.
    """
    username = user.get("username")
    if username:
        return username
    raw_id = user.get("raw_id") or ""
    if raw_id and not raw_id.isdigit():
        return raw_id
    return None


async def analyze_all(db: "Database", threshold: float = 0.75) -> int:
    """Compare tous les couples discord/twitch et crée des propositions si score >= threshold.

    Retourne le nombre de propositions créées/mises à jour.
    """
    proposals_count = 0
    try:
        discord_users = await db.get_platform_users("discord")
        twitch_users = await db.get_platform_users("twitch")

        for d_user in discord_users:
            d_name = _get_comparable_name(d_user, "discord")
            if not d_name:
                continue
            for t_user in twitch_users:
                t_name = _get_comparable_name(t_user, "twitch")
                if not t_name:
                    continue
                s = score(d_name, t_name)
                if s >= threshold:
                    await db.upsert_link_proposal(d_user["full_id"], t_user["full_id"], s)
                    proposals_count += 1
                    logger.info(
                        "Lien proposé: {dn} ({c}) ↔ {tn} ({a}) score={s:.3f}",
                        dn=d_name, c=d_user["full_id"],
                        tn=t_name, a=t_user["full_id"],
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
            # Pour Discord, on a besoin du username — le chercher dans memory_users
            discord_users = await db.get_platform_users("discord")
            d_name = None
            for u in discord_users:
                if u["full_id"] == new_user_id:
                    d_name = _get_comparable_name(u, "discord")
                    break
            if not d_name:
                return

            twitch_users = await db.get_platform_users("twitch")
            for t_user in twitch_users:
                t_name = _get_comparable_name(t_user, "twitch")
                if not t_name:
                    continue
                s = score(d_name, t_name)
                if s >= threshold:
                    await db.upsert_link_proposal(new_user_id, t_user["full_id"], s)
                    logger.info(
                        "Lien proposé: {dn} ({c}) ↔ {tn} ({a}) score={s:.3f}",
                        dn=d_name, c=new_user_id,
                        tn=t_name, a=t_user["full_id"],
                        s=s,
                    )

        elif platform == "twitch":
            # Récupérer le username depuis memory_users (raw_id est numérique)
            twitch_users = await db.get_platform_users("twitch")
            t_name = None
            for u in twitch_users:
                if u["full_id"] == new_user_id:
                    t_name = _get_comparable_name(u, "twitch")
                    break
            if not t_name:
                return

            discord_users = await db.get_platform_users("discord")
            for d_user in discord_users:
                d_name = _get_comparable_name(d_user, "discord")
                if not d_name:
                    continue
                s = score(d_name, t_name)
                if s >= threshold:
                    await db.upsert_link_proposal(d_user["full_id"], new_user_id, s)
                    logger.info(
                        "Lien proposé: {dn} ({c}) ↔ {tn} ({a}) score={s:.3f}",
                        dn=d_name, c=d_user["full_id"],
                        tn=t_name, a=new_user_id,
                        s=s,
                    )
    except Exception as e:
        logger.error("analyze_new_user error: {e}", e=e)
