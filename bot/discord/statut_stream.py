"""Le salon qui dit si le live est en cours — repris du bot Node `wally-discord`.

Branché sur `on_poll` du `StreamWatcher` (un relevé par minute), et non sur
`on_transition` : le premier relevé y est volontairement muet, alors que le
salon doit être juste dès le démarrage. On compare le nom avant de renommer :
aucun appel à Discord tant que rien ne bascule — ce qui compte, Discord ne
tolérant que deux renommages par salon toutes les dix minutes.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord


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
    from bot.discord.handlers import _fire
    _fire(_renommer(salon, voulu))


async def _renommer(salon: Any, nom: str) -> None:
    try:
        await salon.edit(name=nom, reason="Statut du stream")
        logger.info("statut du stream : salon renommé « {n} »", n=nom)
    except Exception as e:  # noqa: BLE001 — le relevé suivant retente
        logger.warning("statut du stream : renommage impossible : {e!r}", e=e)
