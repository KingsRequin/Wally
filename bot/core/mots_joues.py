"""Les mots déjà joués, pour ne pas les rejouer — un sac sans remise à l'envers.

`SacSansRemise` (`bot/core/tirage.py`) épuise un stock CONNU. Ici le stock
n'existe pas : le mot du pendu est inventé par Wally à chaque partie. On ne peut
donc pas tirer sans remise, seulement se souvenir de ce qui est sorti et le
refuser au coup d'après.

Le besoin est né en prod le 2026-08-31 : deux parties d'affilée sur
**peacekeeper**. Deux causes cumulées, et il faut les traiter toutes les deux —
le prompt orientait vers l'univers Apex (vivier d'une centaine de mots), et rien
ne gardait trace des parties précédentes. Un vivier élargi sans mémoire finit de
toute façon par répéter : le hasard sans mémoire retombe sur les mêmes têtes.

⚠️ **Volontairement NON borné à la session**, contrairement à `EtatPersistant`.
Un pendu joué hier soir est exactement celui qu'on ne veut pas revoir ce soir —
c'est même le cas le plus visible pour un habitué qui suit tous les lives.

⚠️ La mémoire vit en RAM et se range en tâche de fond, parce que les points
d'ouverture des parties sont SYNCHRONES (`start_hangman`). Une lecture en base à
l'ouverture demanderait de rendre tout le chemin asynchrone pour une liste de
quarante mots.
"""
from __future__ import annotations

import asyncio
import json
import unicodedata

from loguru import logger

# Quarante parties, soit plusieurs semaines de lives : au-delà, un mot revenu
# n'est plus une répétition, c'est un rappel. En deçà de la dizaine, une soirée
# animée suffirait à faire le tour et à tout ré-autoriser.
TAILLE_DEFAUT = 40


def _fold(mot: str) -> str:
    """Casse, accents et espaces multiples écrasés — « Péacekeeper » = « peacekeeper ».

    Sans ce pliage, la mémoire ne protégerait que de la répétition à
    l'identique, et une majuscule suffirait à la contourner sans le vouloir.
    """
    sans_accent = "".join(
        c for c in unicodedata.normalize("NFD", mot or "")
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(sans_accent.lower().split())


class MotsJoues:
    """Les `taille` derniers mots joués, du plus ancien au plus récent."""

    def __init__(self, db, cle: str, taille: int = TAILLE_DEFAUT) -> None:
        self._db = db
        self._cle = cle
        self._taille = max(1, taille)
        self._mots: list[str] = []
        self._taches: set[asyncio.Task] = set()

    async def charger(self) -> None:
        """Relit la mémoire au démarrage. Une base muette laisse une liste vide."""
        if self._db is None:
            return
        try:
            brut = await self._db.get_state(self._cle)
            ranges = json.loads(brut) if brut else []
        except Exception as exc:  # noqa: BLE001 — sans mémoire on répète, on ne casse pas
            logger.warning("{c} : mémoire illisible, on repart à vide ({e!r})",
                           c=self._cle, e=exc)
            return
        if not isinstance(ranges, list):
            return
        self._mots = [_fold(str(m)) for m in ranges if str(m).strip()][-self._taille:]
        logger.info("{c} : {n} mot(s) déjà joués en mémoire", c=self._cle, n=len(self._mots))

    def deja_joue(self, mot: str) -> bool:
        return _fold(mot) in self._mots

    def retenir(self, mot: str) -> None:
        """Ajoute le mot et range la liste, sans attendre.

        Un mot déjà présent REMONTE en fin de liste au lieu d'être ignoré : il
        vient d'être rejoué (par un chemin qui n'a pas consulté `deja_joue`),
        c'est donc le plus récent, et le laisser vieillir à sa place d'origine
        le rendrait ré-autorisé trop tôt.
        """
        plie = _fold(mot)
        if not plie:
            return
        if plie in self._mots:
            self._mots.remove(plie)
        self._mots.append(plie)
        del self._mots[:-self._taille]
        self._ranger()

    @property
    def recents(self) -> list[str]:
        """Du plus récent au plus ancien — l'ordre dans lequel on les cite."""
        return list(reversed(self._mots))

    def _ranger(self) -> None:
        """Écriture en tâche de fond, avec référence forte.

        La boucle asyncio ne garde qu'une référence faible sur ses tâches : une
        tâche collectée en vol perdrait précisément l'écriture qui doit survivre
        au process. Même piège, même remède que `EtatPersistant`.
        """
        if self._db is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return          # hors boucle (appel synchrone en test) : rien à ranger
        tache = loop.create_task(self._ecrire())
        self._taches.add(tache)
        tache.add_done_callback(self._taches.discard)

    async def _ecrire(self) -> None:
        try:
            await self._db.set_state(self._cle, json.dumps(self._mots))
        except Exception as exc:  # noqa: BLE001 — une mémoire non rangée n'est pas fatale
            logger.warning("{c} : mémoire non rangée ({e!r})", c=self._cle, e=exc)
