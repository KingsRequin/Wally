# bot/core/apex/kills_live.py
"""Les kills d'Azraël, partie par partie, pendant le live (§12).

Ce module ne RÉÉCRIT aucune règle de comptage. Il appelle `score_manche()`, dont
le duel a payé chaque ligne : le maximum des deltas et jamais leur somme (les
quatre trackers bougent ensemble à chaque kill — les additionner quadruple le
score), `None` plutôt que zéro quand rien n'est mesurable, un plafond de
vraisemblance contre les ré-épinglages, et le refus de trancher quand un témoin
a disparu. Le 2026-08-13, un écart de règle a fait annoncer « 0 kill » en direct
à quelqu'un qui venait d'en faire 39.

Ce qu'il ajoute est le DÉCOUPAGE en parties hors duel, et deux prudences :

  · **On attend que l'API rattrape.** Les compteurs ne montent qu'APRÈS la fin
    de la partie, avec du retard. Figer à la seconde où le joueur quitte le jeu
    donnerait zéro à toutes les parties.

  · **Une partie illisible n'entre pas dans le cumul** (arbitré avec l'owner).
    Illisible n'est pas zéro : mourir sans tuer est une partie réelle, dont tous
    les compteurs sont lisibles et immobiles. C'est `score_manche` qui fait la
    différence, pas nous.
"""
from __future__ import annotations

import time
from collections.abc import Callable

from loguru import logger

from bot.core.apex.duel import score_manche


class KillsDuLive:
    """Suit les parties d'un joueur et leurs kills, sur la durée d'un live."""

    # Ce qu'on laisse à l'API pour publier les compteurs après la sortie de
    # partie. Généreux à dessein : un bilan qui arrive une minute trop tard
    # reste juste, un bilan figé trop tôt est faux pour toujours.
    ATTENTE_APRES_PARTIE_S = 90

    def __init__(self, horloge: Callable[[], float] | None = None) -> None:
        self._maintenant = horloge or time.monotonic
        self.nouveau_live()

    def nouveau_live(self) -> None:
        """Remet les compteurs du soir à zéro."""
        self._base: dict[str, int] | None = None
        self._en_partie = False
        self._sortie_a: float | None = None
        self._derniers: dict[str, int] = {}
        self.total = 0
        self.parties = 0

    def relever(self, *, in_game: bool, trackers: dict | None,
                premier: bool = False) -> dict | None:
        """Un tour de sonde. Rend le bilan d'une partie, une seule fois.

        `premier=True` dit que c'est le tout premier relevé qu'on obtient : si
        le joueur y est DÉJÀ en partie, on ne sait pas d'où elle est partie, et
        inventer un point de départ donnerait un chiffre faux. On la laisse
        filer.
        """
        lus = _entiers(trackers)
        if lus:
            self._derniers = lus

        # Entrée en partie.
        if in_game and not self._en_partie:
            bilan = self._figer_si_en_attente()   # une partie enchaînée tout de suite
            self._en_partie = True
            self._sortie_a = None
            # Sans relevé lisible, on n'a pas de départ : la partie ne sera pas
            # mesurable, et c'est plus honnête que de partir de rien.
            self._base = None if (premier or not lus) else dict(lus)
            return bilan

        # Sortie de partie : on note l'instant, on ne fige pas encore.
        if not in_game and self._en_partie:
            self._en_partie = False
            self._sortie_a = self._maintenant()
            return None

        # Hors partie, l'attente court.
        if (not in_game and self._sortie_a is not None
                and self._maintenant() - self._sortie_a >= self.ATTENTE_APRES_PARTIE_S):
            return self._figer()
        return None

    # ── interne ─────────────────────────────────────────────────────────────

    def _figer_si_en_attente(self) -> dict | None:
        """Ferme une partie encore en attente, quand la suivante démarre.

        Sans ça, quelqu'un qui relance immédiatement laisse la précédente en
        suspens pour toujours : son bilan n'arrive jamais.
        """
        return self._figer() if self._sortie_a is not None else None

    def _figer(self) -> dict:
        base, self._base = self._base, None
        self._sortie_a = None
        kills = (score_manche(base, self._derniers)
                 if base and self._derniers else None)
        if kills is None:
            logger.info("Apex : partie non mesurable (trackers illisibles ou figés)")
        else:
            self.total += kills
            self.parties += 1
            logger.info("Apex : partie terminée — {k} kill(s), {t} sur le live",
                        k=kills, t=self.total)
        return {"partie": kills, "total": self.total, "parties": self.parties}


def _entiers(trackers: dict | None) -> dict[str, int]:
    """Les compteurs lisibles, en entiers.

    Cette API glisse des chaînes là où on attend des nombres — piège déjà payé
    ici. Ce qui n'est pas un entier est écarté plutôt que converti au jugé.
    """
    out: dict[str, int] = {}
    for cle, valeur in (trackers or {}).items():
        try:
            out[str(cle)] = int(valeur)
        # Silence VOULU, et sans perte : cette API mêle des trackers de toutes
        # natures, dont beaucoup ne sont pas des nombres. Journaliser chacun
        # noierait les logs à raison de deux relevés par minute, et il n'y a
        # rien à en faire — `score_manche` travaille sur ce qui reste, et refuse
        # de trancher s'il ne reste rien.
        except (TypeError, ValueError):
            continue
    return out
