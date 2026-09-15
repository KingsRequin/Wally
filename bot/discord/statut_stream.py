"""Le salon qui dit si le live est en cours — repris du bot Node `wally-discord`.

Branché sur `on_poll` du `StreamWatcher` (un relevé par minute), et non sur
`on_transition` : le premier relevé y est volontairement muet, alors que le
salon doit être juste dès le démarrage. On compare le nom avant de renommer :
aucun appel à Discord tant que rien ne bascule — ce qui compte, Discord ne
tolérant que deux renommages par salon toutes les dix minutes.

Un `edit` limité en débit peut rester en vol plusieurs minutes : sans garde,
chaque relevé (toutes les 60 s) revoit encore l'ANCIEN nom en cache et relance
un `_renommer`, qui vient s'empiler derrière le même verrou de route et brûle
le quota une fois de plus dès qu'il se libère. `_renames_en_cours` retient une
seule tâche par salon pour que le relevé suivant se contente d'attendre.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord

_renames_en_cours: dict[int, asyncio.Task] = {}


def sur_releve(bot: "WallyDiscord", statut: dict) -> None:
    cfg = bot.config.discord.statut_stream
    if cfg.salon_id is None:
        return
    if not bot.is_ready():
        return  # le watcher relève avant la connexion Discord ; retenté dans 60 s
    # `bot.get_channel` rend un type large (salon texte, catégorie, DM…) ; le
    # salon de statut est configuré par l'owner comme un salon textuel.
    salon: Any = bot.get_channel(cfg.salon_id)
    if salon is None:
        logger.warning("statut du stream : salon {c} introuvable", c=cfg.salon_id)
        return
    voulu = cfg.nom_live if statut.get("live") else cfg.nom_hors_live
    if salon.name == voulu:
        return
    tache = _renames_en_cours.get(cfg.salon_id)
    if tache is not None and not tache.done():
        return  # un renommage est déjà en vol ; le relevé suivant revérifiera une fois fini
    from bot.discord.handlers import _fire
    _renames_en_cours[cfg.salon_id] = _fire(_renommer(salon, voulu))


async def _renommer(salon: Any, nom: str) -> None:
    try:
        await salon.edit(name=nom, reason="Statut du stream")
        logger.info("statut du stream : salon renommé « {n} »", n=nom)
    except Exception as e:  # noqa: BLE001 — le relevé suivant retente
        logger.warning("statut du stream : renommage impossible : {e!r}", e=e)
