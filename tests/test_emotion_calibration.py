# tests/test_emotion_calibration.py
"""Combien de temps une émotion dure, et à partir de quand elle est « haute ».

Mesuré sur 30 jours de production : le palier haut (≥ 0.75) n'était atteint que
5,1 h par mois pour la joie, 50 min pour la colère, 35 min pour la curiosité et
10 min pour la tristesse. Les directives extrêmes existaient donc pour ~1 % du
temps de vie du bot.

Deux causes, traitées ensemble parce qu'elles interagissent :

1. Les émotions ne DURENT pas — la colère avait une demi-vie de 14 minutes,
   soit une crise évaporée avant que quiconque l'ait lue.
2. La porte du palier haut était trop loin (0.75) pour des états qui culminent
   en pratique vers 0.5.

Le piège de l'interaction : ralentir la colère ÉTALE sa décrue, donc affaiblit
la retombée en tristesse (qui décroît pendant qu'elle s'accumule). Mesuré :
λ 3.0 → 1.0 à ratio constant fait passer la retombée de 57 min visibles à ZÉRO.
Les deux réglages doivent bouger ensemble.
"""

import math

from bot.config import Config
from bot.core.emotion import EmotionEngine
from bot.intelligence.prompts import _get_tier, _get_tier_fluid


def _minutes_au_dessus(lam: float, depart: float, seuil: float) -> float:
    """Durée pendant laquelle une émotion partie de `depart` reste ≥ `seuil`."""
    if depart <= seuil:
        return 0.0
    return math.log(depart / seuil) / lam * 60


def test_une_colere_dure_assez_pour_etre_lue():
    cfg = Config.load("config.yaml")
    lam = cfg.emotions["anger"].decay_lambda
    demi_vie = math.log(2) / lam * 60
    assert demi_vie >= 25, (
        f"demi-vie de la colère : {demi_vie:.0f} min — une crise qui s'évapore "
        "avant d'avoir été lue ne se voit jamais en live"
    )
    # Une grosse colère doit tenir le palier mid (0.45) une vraie tranche de temps.
    assert _minutes_au_dessus(lam, 0.9, 0.45) >= 25


def test_les_emotions_durent_au_moins_une_demi_heure():
    """Cliquet global : aucune émotion ne doit redevenir un feu de paille."""
    cfg = Config.load("config.yaml")
    for e in ("anger", "joy", "sadness", "curiosity"):
        demi_vie = math.log(2) / cfg.emotions[e].decay_lambda * 60
        assert demi_vie >= 25, f"{e} : demi-vie de {demi_vie:.0f} min, trop courte"


def test_le_palier_haut_est_atteignable():
    """Les états relevés en production culminent vers 0.5–0.6, pas 0.9.

    À 0.75, la porte du palier haut ne s'ouvrait que 6,8 h par mois toutes
    émotions confondues (hors ennui).
    """
    assert _get_tier(0.6) == "high"
    assert _get_tier_fluid(0.7)[0] == "high"
    # Les paliers bas ne bougent pas : c'est le HAUT qu'on rapproche.
    assert _get_tier(0.2) == "low"
    assert _get_tier(0.45) == "mid"
    # L'ordre reste strict, sans trou ni chevauchement.
    assert _get_tier(0.59) == "mid"


def test_la_retombee_survit_au_ralentissement_de_la_colere():
    """Le piège d'interaction, verrouillé sur la config réelle.

    Ralentir la colère sans relever le ratio de retombée aurait annulé en
    silence le mécanisme livré juste avant : la tristesse serait restée sous le
    seuil d'injection (0.2) du début à la fin.
    """
    cfg = Config.load("config.yaml")
    engine = EmotionEngine(cfg)
    engine.apply_delta("anger", 0.9)

    pic, visible = 0.0, 0
    for _ in range(240):
        engine._last_decay -= 60
        engine._apply_decay()
        s = engine.get_state()["sadness"]
        pic = max(pic, s)
        if s >= 0.2:
            visible += 1

    assert pic > 0.3, f"pic de retombée à {pic:.2f}"
    assert visible >= 60, (
        f"retombée visible {visible} min — le ralentissement de la colère l'a "
        "diluée, il faut relever `emotions.aftermath.rules.*.ratio`"
    )
