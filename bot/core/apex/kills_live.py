# bot/core/apex/kills_live.py
"""Les kills d'Azraël, partie par partie, pendant le live (§12).

Ce module ne RÉÉCRIT aucune règle de comptage. Il appelle `score_manche()`, dont
le duel a payé chaque ligne : le maximum des deltas et jamais leur somme (les
quatre trackers bougent ensemble à chaque kill — les additionner quadruple le
score), `None` plutôt que zéro quand rien n'est mesurable, un plafond de
vraisemblance contre les ré-épinglages, et le refus de trancher quand un témoin
a disparu. Le 2026-08-13, un écart de règle a fait annoncer « 0 kill » en direct
à quelqu'un qui venait d'en faire 39.

Ce qu'il ajoute est le DÉCOUPAGE en parties hors duel, et trois prudences :

  · **On attend que les compteurs se TAISENT, pas qu'un délai passe.** Les
    valeurs ne montent qu'APRÈS la fin de la partie, et pas toutes au même
    tour : le 2026-08-19 à 22:37, le RP est arrivé un tick avant les kills.
    Figer sur le premier mouvement annoncerait « 0 kill » à une partie qui en
    comptait 4. On fige donc quand un relevé répète le précédent — et le délai
    ne sert plus que de plafond, pour la partie où rien ne bouge du tout.

  · **Une partie illisible n'entre pas dans le cumul** (arbitré avec l'owner).
    Illisible n'est pas zéro : mourir sans tuer est une partie réelle, dont tous
    les compteurs sont lisibles et immobiles. C'est `score_manche` qui fait la
    différence, pas nous.

  · **Un RP immobile ne dit rien.** Le mode d'une partie n'existe nulle part
    dans l'API : un RP qui bouge est le seul signal qu'elle était classée. Zéro
    n'est donc pas « zéro point gagné », c'est « pas de classé » — et ça ne
    s'affiche pas.
"""
from __future__ import annotations

import time
from collections.abc import Callable

from loguru import logger

from bot.core.apex.duel import score_manche


class KillsDuLive:
    """Suit les parties d'un joueur et leurs kills, sur la durée d'un live."""

    # Le plafond d'attente, quand AUCUN compteur ne bouge après la sortie —
    # une partie sans kill et sans classé ne publie rien qu'on puisse guetter.
    # Généreux à dessein : un bilan qui arrive une minute trop tard reste juste,
    # un bilan figé trop tôt est faux pour toujours.
    ATTENTE_MAX_APRES_PARTIE_S = 90

    # Au-delà, ce n'est plus le résultat d'une partie : un changement de saison
    # remet le RP à plat, et un ré-étalonnage le déplace de plusieurs milliers.
    # Le meilleur gain réel tourne autour de 300 points, la pire perte autour de
    # 75 — deux ordres de grandeur en dessous.
    PLAFOND_RP_PARTIE = 1000

    def __init__(self, horloge: Callable[[], float] | None = None) -> None:
        self._maintenant = horloge or time.monotonic
        self.nouveau_live()

    def nouveau_live(self) -> None:
        """Remet les compteurs du soir à zéro."""
        self._base: dict[str, int] | None = None
        self._base_rp: int | None = None
        self._en_partie = False
        self._sortie_a: float | None = None
        self._derniers: dict[str, int] = {}
        self._dernier_rp: int | None = None
        # L'empreinte du relevé PRÉCÉDENT — c'est elle qui dit si ça bouge
        # encore. `None` tant qu'il n'y en a pas eu.
        self._empreinte: tuple | None = None
        self.total = 0
        self.parties = 0

    def relever(self, *, in_game: bool, trackers: dict | None,
                rp: int | None = None, premier: bool = False) -> dict | None:
        """Un tour de sonde. Rend le bilan d'une partie, une seule fois.

        `rp` est le score de rang du moment, `None` quand le compte n'en a pas
        ou que l'API ne l'a pas donné.

        `premier=True` dit que c'est le tout premier relevé qu'on obtient : si
        le joueur y est DÉJÀ en partie, on ne sait pas d'où elle est partie, et
        inventer un point de départ donnerait un chiffre faux. On la laisse
        filer.
        """
        lus = _entiers(trackers)
        if lus:
            self._derniers = lus
        if rp is not None:
            self._dernier_rp = _entier(rp)

        # Prise APRÈS mise à jour : c'est sur ces valeurs-là que `_figer`
        # travaillera, donc ce sont elles dont la stabilité compte.
        empreinte = (tuple(sorted(self._derniers.items())), self._dernier_rp)
        precedente, self._empreinte = self._empreinte, empreinte

        # Entrée en partie.
        if in_game and not self._en_partie:
            bilan = self._figer_si_en_attente()   # une partie enchaînée tout de suite
            self._en_partie = True
            self._sortie_a = None
            # Sans relevé lisible, on n'a pas de départ : la partie ne sera pas
            # mesurable, et c'est plus honnête que de partir de rien.
            self._base = None if (premier or not lus) else dict(lus)
            self._base_rp = None if premier else self._dernier_rp
            return bilan

        # Sortie de partie : on note l'instant, on ne fige pas encore.
        if not in_game and self._en_partie:
            self._en_partie = False
            self._sortie_a = self._maintenant()
            return None

        if not in_game and self._sortie_a is not None:
            if self._maintenant() - self._sortie_a >= self.ATTENTE_MAX_APRES_PARTIE_S:
                return self._figer()
            # Ça a bougé, puis ça s'est tu : l'API a fini de publier. Les deux
            # conditions comptent — sans mouvement, l'immobilité ne prouve rien,
            # elle est vraie dès le premier tour.
            if empreinte == precedente and self._a_bouge():
                return self._figer()
        return None

    # ── interne ─────────────────────────────────────────────────────────────

    def _a_bouge(self) -> bool:
        """Un compteur a-t-il changé depuis le début de la partie ?

        Les kills passent par `score_manche` plutôt que par une comparaison
        maison : lui seul sait écarter un tracker figé ou aberrant, et deux
        façons de lire les mêmes chiffres finiraient par diverger.
        """
        if self._base and self._derniers:
            kills = score_manche(self._base, self._derniers)
            if kills:
                return True
        return self._rp_gagne() is not None

    def _rp_gagne(self) -> int | None:
        """Les points de rang de la partie. `None` s'ils n'ont pas bougé."""
        if self._base_rp is None or self._dernier_rp is None:
            return None
        delta = self._dernier_rp - self._base_rp
        if delta == 0 or abs(delta) > self.PLAFOND_RP_PARTIE:
            return None
        return delta

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
        rp = self._rp_gagne()
        self._base_rp = None
        if kills is None:
            logger.info("Apex : partie non mesurable (trackers illisibles ou figés)")
        else:
            self.total += kills
            self.parties += 1
            logger.info("Apex : partie terminée — {k} kill(s), {t} sur le live{r}",
                        k=kills, t=self.total,
                        r=f", {rp:+d} RP" if rp is not None else "")
        return {"partie": kills, "total": self.total, "parties": self.parties,
                "rp": rp}


def _entier(valeur) -> int | None:
    """Un entier, ou `None` — jamais une conversion au jugé."""
    try:
        return int(valeur)
    except (TypeError, ValueError):
        return None


def _entiers(trackers: dict | None) -> dict[str, int]:
    """Les compteurs lisibles, en entiers.

    Cette API glisse des chaînes là où on attend des nombres — piège déjà payé
    ici. Ce qui n'est pas un entier est écarté plutôt que converti au jugé.
    """
    out: dict[str, int] = {}
    for cle, valeur in (trackers or {}).items():
        # Silence VOULU, et sans perte : cette API mêle des trackers de toutes
        # natures, dont beaucoup ne sont pas des nombres. Journaliser chacun
        # noierait les logs à raison de deux relevés par minute, et il n'y a
        # rien à en faire — `score_manche` travaille sur ce qui reste, et refuse
        # de trancher s'il ne reste rien.
        lu = _entier(valeur)
        if lu is not None:
            out[str(cle)] = lu
    return out
