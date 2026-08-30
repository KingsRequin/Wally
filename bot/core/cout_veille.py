"""Ce que Wally coûte, surveillé — parce que personne ne regarde la table.

`log_cost()` écrit chaque appel LLM dans `cost_log` : 98 957 lignes au
2026-08-30. La table est complète, exacte, et **rien ne prévient quand la
dépense dérive**. DeepSeek est passé de 13,2 à 28,8 $/mois le 2026-08-16 et le
système ne l'a pas signalé — la donnée pour le voir venir était déjà en base.

## Pourquoi une PROJECTION, et pas un plafond mensuel

Un plafond sur le mois écoulé prévient le 31, quand la facture est déjà due.
Ce qu'on veut voir, c'est la dérive : on projette donc le rythme des sept
derniers jours sur trente. Mesuré le 2026-08-30 : 8,23 $ sur 7 jours, soit
**35,26 $/mois au rythme actuel**, alors que les 30 jours écoulés n'affichent
que 22,93 $. Un plafond mensuel serait resté muet ; la projection, non.

Sept jours et pas un : la dépense quotidienne va de 0,39 $ à 2,28 $ selon qu'il
y a stream ou non. Une projection sur la seule journée d'hier crierait un jour
sur deux et ne voudrait rien dire.

## Une alerte par franchissement, pas une par jour

Le seuil se franchit et se refranchit. Prévenir à chaque passage de la boucle
noierait le salon en trois jours, et une alerte qu'on apprend à ignorer ne vaut
pas mieux que pas d'alerte. On ne parle qu'au FRANCHISSEMENT, et on se réarme
quand la projection redescend sous le seuil — moins une marge, sinon un rythme
qui oscille autour de la valeur alerte à chaque oscillation.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from loguru import logger

# Fenêtre d'observation. Assez large pour lisser les jours sans stream, assez
# courte pour qu'une dérive se voie en moins d'une semaine.
FENETRE_JOURS = 7

# Le mois de référence de la projection — celui des factures des fournisseurs.
MOIS_JOURS = 30

# Marge de réarmement : la projection doit redescendre à 90 % du seuil pour
# qu'une nouvelle alerte soit possible. Sans elle, un rythme qui oscille autour
# du seuil alerte à chaque oscillation.
_REARMEMENT = 0.9


async def projection_mensuelle(db: Any, fenetre_jours: int = FENETRE_JOURS) -> float | None:
    """Ce que le rythme des derniers jours donnerait sur un mois, en dollars.

    `None` si la base n'a rien à dire — une base neuve ou vide ne doit pas
    rendre 0,00 $, qui se lirait « ça ne coûte rien » alors que ça veut dire
    « on ne sait pas encore ».
    """
    maintenant = time.time()
    depuis = maintenant - fenetre_jours * 86400
    try:
        total = await db.get_cost_since(depuis)
    except Exception as exc:  # noqa: BLE001 — une veille ne casse jamais le bot
        logger.warning("Veille des coûts : total illisible ({e!r})", e=exc)
        return None
    if not total:
        return None

    # La fenêtre RÉELLEMENT couverte, pas celle demandée : au premier jour de
    # vie de la base, diviser par sept sous-estimerait la projection d'un
    # facteur sept — la veille serait aveugle pile quand tout est neuf.
    try:
        plus_ancien = await db.fetch_one(
            "SELECT MIN(timestamp) AS t FROM cost_log WHERE timestamp >= ?", (depuis,)
        )
    except Exception as exc:  # noqa: BLE001 — jamais bloquant
        logger.warning("Veille des coûts : début de fenêtre illisible ({e!r})", e=exc)
        return None
    debut = float((plus_ancien["t"] if plus_ancien else None) or depuis)
    jours = max((maintenant - debut) / 86400, 0.5)   # jamais moins d'une demi-journée
    return float(total) / jours * MOIS_JOURS


class VeilleCouts:
    """Prévient une fois quand la dépense projetée passe le seuil.

    Premier appelant de `NotificationService.send()`, qui n'en avait aucun : le
    service était construit dans `main.py`, injecté au dashboard, et son envoi
    n'était déclenché de nulle part.
    """

    # Une heure. La projection porte sur sept jours, elle ne bouge donc pas en
    # une heure — mais une dérive BRUTALE (une boucle qui rappelle le LLM sans
    # fin) se voit alors dans l'heure plutôt que le lendemain, pour le prix
    # d'une requête SQLite locale.
    PERIODE_S = 3600.0

    def __init__(self, db: Any, config: Any, notifications: Any) -> None:
        self._db = db
        self._config = config
        self._notifications = notifications
        self._alerte_posee = False

    async def veiller(self, *, periode: float | None = None) -> None:
        """Boucle de veille. Même patron que `veille_clips` et `presence_stream`."""
        while True:
            await asyncio.sleep(self.PERIODE_S if periode is None else periode)
            try:
                await self.un_tour()
            except Exception as exc:  # noqa: BLE001 — une veille ne meurt pas
                logger.warning("Veille des coûts : tour raté ({e!r})", e=exc)

    async def un_tour(self) -> float | None:
        """Mesure, alerte si besoin. Rend la projection, ou `None`."""
        seuil = float(getattr(self._config.bot, "cost_alert_threshold", 0) or 0)
        if seuil <= 0:
            return None          # surveillance désactivée, et c'est un choix

        projection = await projection_mensuelle(self._db)
        if projection is None:
            return None

        if projection < seuil * _REARMEMENT and self._alerte_posee:
            self._alerte_posee = False
            logger.info(
                "Veille des coûts : retombé à {p:.2f} $/mois projetés, alerte réarmée",
                p=projection,
            )
            return projection

        if projection < seuil or self._alerte_posee:
            return projection

        self._alerte_posee = True
        logger.warning(
            "Veille des coûts : {p:.2f} $/mois projetés, au-dessus du seuil de {s:.2f} $",
            p=projection, s=seuil,
        )
        if self._notifications is not None:
            await self._notifications.send(
                f"💸 Au rythme des {FENETRE_JOURS} derniers jours, je coûterai "
                f"**{projection:.2f} $** sur le mois — le seuil est à "
                f"{seuil:.2f} $. (Réglable dans Paramètres.)"
            )
        return projection
