# bot/core/apex/duel.py
"""Le duel Apex : machine à états PURE, sans réseau ni I/O.

Elle reçoit des relevés et rend des décisions ; tout se teste en rejouant une
séquence, sans toucher l'API. Le réseau, la persistance et les effets vivent
dans `duel_runner.py`.

Spec : docs/superpowers/specs/2026-08-13-apex-duel-points-chaine-design.md
"""
from __future__ import annotations

# Au-delà de ce delta sur une seule manche, ce n'est pas un score : c'est un
# tracker qu'on vient d'épingler. Mesuré le 2026-08-13 : +7793 d'un coup, sans
# un kill joué. Le plafond est volontairement haut — les records connus en Apex
# tournent autour de 25-30 kills — pour ne jamais mordre sur un vrai résultat.
PLAFOND_KILLS_MANCHE = 30


def score_manche(avant: dict[str, int], apres: dict[str, int],
                 *, plafond: int = PLAFOND_KILLS_MANCHE) -> int | None:
    """Les kills faits entre deux relevés, ou None si la manche n'est pas mesurable.

    Le MAXIMUM des deltas, jamais leur somme : les quatre trackers bougent du
    même montant à chaque kill (4 kills → +4 partout), donc les additionner
    donnerait 16. C'est le piège exactement symétrique de la règle d'addition
    qui vaut, elle, pour un total carrière.

    Seules les clés présentes dans les DEUX relevés comptent : un tracker apparu
    en cours de manche n'a pas de point de départ.

    `None` et non `0` quand rien n'est mesurable : un zéro inventé est un
    mensonge, pas une valeur par défaut. La Mixtape, qui n'incrémente aucun
    compteur (10 kills → 0, mesuré), tombe dans ce cas.
    """
    deltas = []
    for cle, depart in avant.items():
        arrivee = apres.get(cle)
        if arrivee is None:
            continue
        delta = arrivee - depart
        if delta < 0 or delta > plafond:
            continue
        deltas.append(delta)
    if not deltas:
        return None
    return max(deltas)
