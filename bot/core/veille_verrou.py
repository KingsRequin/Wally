"""La base est-elle encore accessible en ÉCRITURE ? Personne ne le demandait.

Vécu le 2026-08-30 : de 11 h 43 à 21 h 54, chaque écriture a échoué en
`OperationalError('database is locked')` — coûts LLM, état émotionnel, profils
Apex, kills du live, compteur de messages, snapshots d'humeur. **Dix heures**,
1 756 lignes de WARNING, et rien d'autre. Le redémarrage du soir a tout remis
d'aplomb sans que personne ait su qu'il y avait quoi que ce soit à remettre.

C'est la signature décrite dans `CLAUDE.md` : quelque chose échoue, personne
n'est prévenu, le défaut vit. Chaque site attrapait pourtant SON échec
proprement — c'est justement ce qui l'a rendu invisible : quinze replis
gracieux ne font pas un signal.

## Ce que cette veille surveille, et ce qu'elle ne surveille pas

Elle ne teste RIEN de son côté : elle regarde le résultat de l'écriture
périodique qui existe déjà (le snapshot d'émotion, toutes les 5 minutes).
Une sonde qui écrirait sa propre ligne témoin mesurerait sa propre ligne
témoin ; celle-ci mesure ce que la prod fait vraiment.

Un verrou passager est NORMAL — `busy_timeout` en absorbe tous les jours sans
qu'on ait à le savoir. Ce qui n'est pas normal, c'est qu'il DURE : on ne parle
qu'au bout de `seuil` échecs consécutifs, soit un quart d'heure aux réglages
livrés. Et on ne parle qu'une fois, avec réarmement au retour à la normale :
une alerte répétée toutes les cinq minutes pendant dix heures s'apprend à
s'ignorer aussi vite qu'un warning.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bot.core.notifications import NotificationService

# Trois tours de la boucle des snapshots, soit un quart d'heure de base muette.
SEUIL_ECHECS = 3


class VeilleVerrou:
    """Compte les écritures périodiques refusées par un verrou, et alerte."""

    def __init__(
        self,
        notifications: "NotificationService | None",
        seuil: int = SEUIL_ECHECS,
    ) -> None:
        self._notifications = notifications
        self._seuil = seuil
        self._consecutifs = 0
        self.alerte_posee = False

    async def constater(self, echec: BaseException | None) -> None:
        """Rend compte d'une écriture périodique : `None` si elle a abouti.

        Seul « database is locked » compte. Une table absente ou un disque
        plein est un AUTRE problème — les additionner ferait annoncer un verrou
        là où il n'y en a pas, et enverrait le diagnostic sur une fausse piste.
        """
        if echec is not None and "database is locked" in str(echec).lower():
            self._consecutifs += 1
            if self._consecutifs >= self._seuil and not self.alerte_posee:
                await self._alerter()
            return

        self._consecutifs = 0
        if self.alerte_posee:
            self.alerte_posee = False
            logger.info("Veille du verrou : la base réaccepte les écritures")
            await self._dire(
                "✅ La base est revenue — j'enregistre à nouveau ce qui se passe."
            )

    async def _alerter(self) -> None:
        self.alerte_posee = True
        logger.error(
            "Veille du verrou : {n} écritures périodiques d'affilée refusées "
            "(« database is locked ») — plus rien n'est enregistré",
            n=self._consecutifs,
        )
        await self._dire(
            "🔒 Un verrou tient la base depuis un moment : je ne peux plus rien "
            "enregistrer (coûts, humeurs, profils Apex, souvenirs). Un "
            "redémarrage libère la connexion fautive."
        )

    async def _dire(self, message: str) -> None:
        if self._notifications is None:
            return
        await self._notifications.send(message)
