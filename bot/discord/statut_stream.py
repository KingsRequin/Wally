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

Un renommage qui échoue pour une cause durable (permission « Gérer les
salons » retirée) échouerait à CHAQUE relevé : 60 WARNING identiques par
heure. Le premier échec est dit en WARNING, puis le même échec au plus une
fois par heure par salon (`_derniers_avertissements`). Un succès efface la
mémoire : la panne suivante sera redite tout de suite.
"""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord

_renames_en_cours: dict[int, asyncio.Task] = {}

_INTERVALLE_AVERTISSEMENT = 3600.0   # secondes entre deux WARNING identiques pour un même salon
_derniers_avertissements: dict[int, tuple[str, float]] = {}   # salon → (repr de l'échec, instant)
_horloge = time.monotonic


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
    except Exception as e:  # noqa: BLE001 — le relevé suivant retente
        motif = repr(e)
        maintenant = _horloge()
        precedent = _derniers_avertissements.get(salon.id)
        if precedent is not None and precedent[0] == motif and maintenant - precedent[1] < _INTERVALLE_AVERTISSEMENT:
            return  # même échec déjà dit il y a moins d'une heure : volontairement tu (anti-inondation)
        _derniers_avertissements[salon.id] = (motif, maintenant)
        logger.warning("statut du stream : renommage de {c} impossible : {e!r}", c=salon.id, e=e)
        return
    _derniers_avertissements.pop(salon.id, None)
    logger.info("statut du stream : salon renommé « {n} »", n=nom)
