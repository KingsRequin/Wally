# tests/test_emotion_secondaires_priorite.py
"""Deux secondaires sur le même couple : la plus exigeante doit gagner.

Mesuré sur 30 jours de production : `contempt`, `frustration`, `nostalgia` et
`wonder` ne s'étaient JAMAIS déclenchées. Pour `wonder`, la raison n'était ni le
hasard ni un seuil trop haut — c'est qu'elle est structurellement inatteignable :

- `pride`  = joy + curiosity, seuils 0.4
- `wonder` = curiosity + joy, seuils 0.5

C'est le même couple d'émotions. Or l'intensité d'une secondaire vaut
`min(a, b)` : elle est donc IDENTIQUE pour les deux, le tri par intensité ne
peut pas les départager, et `prompts.py` s'arrête à la première trouvée. `pride`,
inséré avant dans la config, gagnait à chaque fois — `wonder` avait pourtant
15 occurrences éligibles sur la période.

Même situation pour `frustration` (anger+boredom, 0.3) et `contempt`
(anger+boredom, 0.4/0.5).

Le tri doit donc départager par SPÉCIFICITÉ : à intensité égale, la règle qui
exige le plus passe devant — comme une règle précise l'emporte sur une règle
générale.
"""

from unittest.mock import MagicMock

from bot.core.emotion import EmotionEngine


def make_config():
    config = MagicMock()
    config.emotions = {
        e: MagicMock(decay_lambda=1.0, boredom_rise_per_hour=None)
        for e in ["anger", "joy", "sadness", "curiosity", "boredom"]
    }
    config.emotions["boredom"].boredom_rise_per_hour = 0.1
    config.bot.emotion_inertia_factor = 0.0
    config.aftermath = MagicMock(enabled=False, rules={})
    config.world_events = {}
    config.secondaries = {
        "pride": MagicMock(a="joy", b="curiosity", threshold=0.4),
        "wonder": MagicMock(a="curiosity", b="joy", threshold=0.5),
        "frustration": MagicMock(a="anger", b="boredom", threshold=0.3),
        "contempt": MagicMock(a="anger", b="boredom", threshold=[0.4, 0.5]),
    }
    return config


def _premiere(engine) -> str:
    """Celle que `prompts.py` retiendra : il prend la première et s'arrête."""
    actives = engine.get_secondary_emotions()
    return actives[0][0] if actives else ""


def test_la_plus_exigeante_passe_devant_sur_le_meme_couple():
    engine = EmotionEngine(make_config())
    engine.set_emotion("joy", 0.7)
    engine.set_emotion("curiosity", 0.7)
    actives = dict(engine.get_secondary_emotions())
    assert "pride" in actives and "wonder" in actives, "les deux sont éligibles ici"
    assert _premiere(engine) == "wonder", (
        "à intensité égale, `wonder` (seuils 0.5) doit primer sur `pride` (0.4) — "
        "sinon elle n'est jamais lue une seule fois"
    )


def test_la_moins_exigeante_reste_seule_quand_elle_est_seule():
    """Entre les deux seuils, seule `pride` est éligible : elle doit sortir."""
    engine = EmotionEngine(make_config())
    engine.set_emotion("joy", 0.45)
    engine.set_emotion("curiosity", 0.45)
    actives = dict(engine.get_secondary_emotions())
    assert "wonder" not in actives
    assert _premiere(engine) == "pride"


def test_contempt_prime_sur_frustration_quand_les_deux_tiennent():
    engine = EmotionEngine(make_config())
    engine.set_emotion("anger", 0.6)
    engine.set_emotion("boredom", 0.6)
    assert _premiere(engine) == "contempt"


def test_une_intensite_plus_forte_gagne_malgre_un_seuil_plus_bas():
    """La spécificité ne départage QU'À intensité égale — l'intensité reste reine."""
    engine = EmotionEngine(make_config())
    engine.set_emotion("joy", 0.9)
    engine.set_emotion("curiosity", 0.9)   # pride/wonder → intensité 0.9
    engine.set_emotion("anger", 0.5)
    engine.set_emotion("boredom", 0.5)     # frustration/contempt → intensité 0.5
    assert _premiere(engine) in ("wonder", "pride")


def test_le_contrat_de_retour_ne_change_pas():
    """Consommé par le dashboard, les handlers Twitch/Discord et le vocal."""
    engine = EmotionEngine(make_config())
    engine.set_emotion("joy", 0.7)
    engine.set_emotion("curiosity", 0.7)
    for entree in engine.get_secondary_emotions():
        assert isinstance(entree, tuple) and len(entree) == 2
        assert isinstance(entree[0], str) and isinstance(entree[1], float)


def test_config_de_prod_aucun_seuil_sous_la_garde_d_injection():
    """Un seuil sous 0.4 ne veut rien dire : `prompts.py` n'injecte qu'à partir de là.

    `frustration`, `nostalgia` et `anxiety` annonçaient 0.3 — un réglage sans
    effet, qui laissait croire qu'on pouvait les rendre plus sensibles en le
    baissant encore.
    """
    from bot.config import Config

    cfg = Config.load("config.yaml")
    for nom, defn in cfg.secondaries.items():
        seuils = defn.threshold if isinstance(defn.threshold, list) else [defn.threshold]
        assert min(seuils) >= 0.4, (
            f"{nom} annonce un seuil de {min(seuils)}, sous la garde d'injection "
            "(0.4) : il n'a aucun effet réel"
        )
