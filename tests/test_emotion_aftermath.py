# tests/test_emotion_aftermath.py
"""La retombée : quand la colère redescend, elle laisse de la tristesse.

Mesuré sur 30 jours de production (`emotion_history`, 9364 snapshots) : la
tristesse dominait 0.3 % du temps, un seul épisode au-dessus de 0.75, et zéro
pic dans `emotion_peaks`. La cause n'était pas un seuil trop haut mais un monde
sans source de tristesse — 11 `apply_delta("joy")` dans le code, 2 pour la
colère, aucun pour la tristesse.

Le contrecoup est la première source : une vraie colère ne s'évapore pas, elle
laisse un goût amer. C'est un MÉCANISME (la décrue d'une émotion en nourrit une
autre), les couples et les coefficients restent en config.
"""

from unittest.mock import MagicMock

from bot.core.emotion import EmotionEngine


def make_config(ratio=0.7, min_peak=0.5, enabled=True, lam_anger=3.0):
    config = MagicMock()
    config.emotions = {
        e: MagicMock(decay_lambda=1.5, boredom_rise_per_hour=None)
        for e in ["anger", "joy", "sadness", "curiosity", "boredom"]
    }
    config.emotions["anger"].decay_lambda = lam_anger
    config.emotions["boredom"].boredom_rise_per_hour = 0.1
    config.bot.emotion_inertia_factor = 0.5
    config.aftermath = MagicMock(
        enabled=enabled,
        rules={
            "amertume": MagicMock(
                source="anger", target="sadness",
                ratio=ratio, min_peak=min_peak, reset_below=0.1,
            )
        },
    )
    # Les autres modules organiques sont neutralisés : on isole la retombée.
    config.mood = None
    config.fatigue = None
    config.spontaneous = None
    config.secondaries = None
    return config


def _laisser_passer(engine, minutes: int, pas_secondes: int = 60) -> None:
    """Fait tourner le decay comme le tick de production, sans dormir."""
    for _ in range(minutes * 60 // pas_secondes):
        engine._last_decay -= pas_secondes
        engine._apply_decay()


def _pic_et_duree(engine, minutes: int, emotion: str = "sadness", seuil: float = 0.2):
    """Pic atteint et minutes passées au-dessus du seuil d'injection.

    Mesurer l'état FINAL serait un faux témoin : la retombée culmine vers
    T+28 min puis redécroît, si bien qu'à T+60 elle est déjà retombée à 0.19.
    Ce qui compte en prod, c'est le pic et le temps où la directive est réellement
    injectée dans le prompt.
    """
    pic, au_dessus = 0.0, 0
    for _ in range(minutes):
        _laisser_passer(engine, 1)
        valeur = engine.get_state()[emotion]
        pic = max(pic, valeur)
        if valeur >= seuil:
            au_dessus += 1
    return pic, au_dessus


def test_une_vraie_colere_laisse_de_la_tristesse():
    engine = EmotionEngine(make_config())
    engine.apply_delta("anger", 0.9)
    assert engine.get_state()["sadness"] == 0.0

    pic, minutes_visibles = _pic_et_duree(engine, 120)

    assert engine.get_state()["anger"] < 0.1, "la colère doit être retombée"
    assert pic > 0.25, (
        f"pic de tristesse à {pic:.3f} — trop proche du seuil d'injection (0.2) "
        "pour que le mécanisme se voie en prod"
    )
    assert minutes_visibles > 30, (
        f"tristesse injectée seulement {minutes_visibles} min — une retombée qui "
        "passe en coup de vent ne sera jamais lue par personne"
    )


def test_un_agacement_passager_ne_rend_pas_triste():
    """Sous `min_peak`, aucune retombée : râler deux secondes n'est pas une crise."""
    engine = EmotionEngine(make_config(min_peak=0.5))
    engine.apply_delta("anger", 0.3)
    _laisser_passer(engine, 60)
    assert engine.get_state()["sadness"] == 0.0


def test_la_tristesse_monte_pendant_que_la_colere_baisse():
    """« Plus la colère baisse, plus la tristesse monte » — les deux courbes se croisent."""
    engine = EmotionEngine(make_config())
    engine.apply_delta("anger", 0.9)
    courbe = []
    for _ in range(60):
        _laisser_passer(engine, 1)
        etat = engine.get_state()
        courbe.append((etat["anger"], etat["sadness"]))

    assert all(courbe[i][0] >= courbe[i + 1][0] for i in range(len(courbe) - 1)), \
        "la colère ne doit que descendre"
    montee = [courbe[i][1] < courbe[i + 1][1] for i in range(len(courbe) - 1)]
    assert sum(montee) > 20, "la tristesse doit monter pendant la décrue"
    assert courbe[-1][1] > courbe[0][1]


def test_la_retombee_ne_ranime_pas_la_colere():
    """Pas de boucle : la tristesse générée ne doit pas renourrir sa propre source."""
    engine = EmotionEngine(make_config())
    engine.apply_delta("anger", 0.9)
    _laisser_passer(engine, 120)
    assert engine.get_state()["anger"] < 0.01


def test_deux_coleres_successives_ne_cumulent_pas_sans_fin():
    """Le pic se réarme sous `reset_below` : chaque crise a sa propre retombée."""
    engine = EmotionEngine(make_config())
    engine.apply_delta("anger", 0.9)
    pic_premiere, _ = _pic_et_duree(engine, 120)
    assert engine.get_state()["anger"] < 0.1, "1re crise close"

    engine.apply_delta("anger", 0.9)
    pic_seconde, _ = _pic_et_duree(engine, 120)

    assert pic_seconde > 0.25, "la 2e crise doit produire sa propre retombée"
    assert pic_seconde < pic_premiere * 2, (
        "les retombées ne doivent pas s'empiler : chaque crise repart de son "
        "propre pic, pas du cumul des précédentes"
    )


def test_desactivable():
    engine = EmotionEngine(make_config(enabled=False))
    engine.apply_delta("anger", 0.9)
    _laisser_passer(engine, 60)
    assert engine.get_state()["sadness"] == 0.0


def test_la_joie_qui_efface_la_colere_ne_rend_pas_triste():
    """Garde-fou central : seule la DÉCRUE PAR DECAY nourrit la retombée.

    La suppression fait aussi tomber la colère — si on le fait rire, `apply_delta`
    érode l'anger de 0.8×. Convertir cette baisse-là en tristesse rendrait Wally
    triste chaque fois qu'on le déride, ce qui est l'inverse du mécanisme voulu.
    """
    engine = EmotionEngine(make_config())
    engine.apply_delta("anger", 0.9)
    avant = engine.get_state()["sadness"]
    engine.apply_delta("joy", 0.9)  # suppression : la colère chute d'un coup
    etat = engine.get_state()
    assert etat["anger"] < 0.9, "la joie doit avoir érodé la colère"
    assert etat["sadness"] == avant, "aucune tristesse ne doit naître d'un fou rire"


def test_config_de_prod_produit_une_retombee_visible():
    """Le vrai `config.yaml`, pas un mock : les valeurs livrées doivent mordre.

    Un ratio timide (0.4) plafonne la tristesse à 0.18 — sous le seuil de 0.2 —
    et le mécanisme n'apparaît jamais dans un prompt. Ce test est le cliquet qui
    empêche de le remettre par « prudence ».
    """
    from bot.config import Config

    cfg = Config.load("config.yaml")
    assert cfg.aftermath.enabled
    regles = list(cfg.aftermath.rules.values())
    assert regles, "aucune règle de retombée en config"

    engine = EmotionEngine(cfg)
    engine.apply_delta("anger", 0.9)
    pic, minutes_visibles = _pic_et_duree(engine, 120)
    assert pic > 0.25, f"ratio de prod trop timide : pic à {pic:.3f}"
    assert minutes_visibles > 30
