# bot/core/apex/seed.py
"""Les comptes Apex qu'on connaît déjà, inscrits au démarrage.

Azraël et son créateur n'ont pas à se présenter à Wally : leurs comptes sont
dans la config. On les inscrit sur leurs DEUX identités — le vocal les reconnaît
en Discord, le chat en Twitch — pour que « mes stats » marche des deux côtés.
"""
from __future__ import annotations

from loguru import logger


async def seed_known_accounts(db, requesters: list[dict]) -> int:
    """Inscrit les comptes déclarés en config. Rend le nombre d'entrées créées.

    Ce qui a été déclaré en direct n'est jamais écrasé : sinon chaque
    redémarrage annulerait ce que la personne vient de dire à Wally.
    """
    created = 0
    for entry in requesters or []:
        entry = entry or {}
        apex_name = str(entry.get("apex_name") or "").strip()
        if not apex_name:
            continue          # rien à inscrire, et surtout rien à deviner
        login = str(entry.get("twitch_login") or "").strip()
        uid = str(entry.get("apex_uid") or "").strip() or None
        platform = str(entry.get("apex_platform") or "PC").strip() or "PC"
        identities = [
            f"discord:{entry['discord_id']}" if entry.get("discord_id") else "",
            f"twitch:{entry['twitch_id']}" if entry.get("twitch_id") else "",
        ]
        for identity in [i for i in identities if i]:
            try:
                if await db.apex_get_account(identity) is not None:
                    continue      # déclaré en direct : on ne touche pas
                await db.apex_link_account(
                    identity=identity, display_name=login or apex_name,
                    apex_name=apex_name, apex_platform=platform, uid=uid,
                )
                created += 1
            except Exception as exc:  # noqa: BLE001 — un amorçage raté ne bloque pas le boot
                logger.warning("Apex: compte {i} non inscrit : {e}", i=identity, e=exc)
    if created:
        logger.info("Apex: {n} compte(s) connu(s) inscrit(s)", n=created)
    return created
