# tests/test_emotion_world_events.py
"""Les événements du monde qui touchent Wally — dont, enfin, des tristes.

Constat de production (30 j) : le code comptait 11 `apply_delta("joy")`,
3 pour la curiosité, 2 pour la colère et AUCUN pour la tristesse. Sub, bits,
raid, follow, réaction emoji, on lui répond → joie. Ignoré → colère. Rien, dans
son monde, ne pouvait l'attrister.

`world_event()` est le point d'entrée unique de ces déclencheurs : les noms et
les intensités vivent dans `config.yaml` (`emotions.world_events`), le code ne
porte que le mécanisme. Sans lui, chaque source serait un `apply_delta` en dur
de plus, dispersé dans un sous-système différent — c'est exactement comme ça
qu'on s'est retrouvé avec onze sources de joie et zéro de tristesse.
"""

from unittest.mock import MagicMock

from bot.core.emotion import EmotionEngine


def make_config(events=None):
    config = MagicMock()
    config.emotions = {
        e: MagicMock(decay_lambda=1.5, boredom_rise_per_hour=None)
        for e in ["anger", "joy", "sadness", "curiosity", "boredom"]
    }
    config.emotions["boredom"].boredom_rise_per_hour = 0.1
    config.bot.emotion_inertia_factor = 0.5
    config.bot.emotion_peak_threshold = 0.7
    config.aftermath = MagicMock(enabled=False, rules={})
    config.world_events = events if events is not None else {
        "stream_ended": MagicMock(effects={"sadness": 0.35}),
        "left_alone_in_voice": MagicMock(effects={"sadness": 0.3, "boredom": 0.1}),
    }
    return config


def test_la_fin_du_live_rend_triste():
    engine = EmotionEngine(make_config())
    assert engine.get_state()["sadness"] == 0.0
    engine.world_event("stream_ended")
    assert engine.get_state()["sadness"] > 0.3


def test_un_evenement_peut_toucher_plusieurs_emotions():
    engine = EmotionEngine(make_config())
    engine.world_event("left_alone_in_voice")
    etat = engine.get_state()
    assert etat["sadness"] > 0.25
    assert etat["boredom"] > 0.05


def test_un_evenement_inconnu_ne_fait_rien():
    """Un nom retiré de la config ne doit pas lever : le monde continue."""
    engine = EmotionEngine(make_config())
    engine.world_event("evenement_qui_nexiste_pas")
    assert all(v == 0.0 for v in engine.get_state().values())


def test_sans_config_le_mecanisme_dort():
    config = make_config(events={})
    engine = EmotionEngine(config)
    engine.world_event("stream_ended")
    assert engine.get_state()["sadness"] == 0.0


def test_la_tristesse_du_monde_erode_la_joie():
    """Passe par `apply_delta`, donc subit la suppression comme le reste.

    Une écriture directe dans `_state` aurait laissé Wally joyeux ET triste à
    fond, ce que la mécanique de suppression existe précisément pour empêcher.
    """
    engine = EmotionEngine(make_config())
    engine.apply_delta("joy", 0.8)
    engine.world_event("stream_ended")
    assert engine.get_state()["joy"] < 0.8


def test_config_de_prod_contient_des_sources_de_tristesse():
    """Le cliquet : c'est l'ABSENCE de sources tristes qui était le défaut.

    Le mécanisme peut très bien exister et n'être câblé que sur des événements
    joyeux — on serait revenu au point de départ sans que rien ne rougisse.
    """
    from bot.config import Config

    cfg = Config.load("config.yaml")
    assert cfg.world_events, "aucun événement du monde en config"
    tristes = [
        nom for nom, ev in cfg.world_events.items()
        if ev.effects.get("sadness", 0.0) > 0
    ]
    assert len(tristes) >= 2, (
        f"seulement {len(tristes)} source(s) de tristesse : {tristes} — le monde "
        "de Wally comptait 11 sources de joie pour 0 de tristesse, c'est ce "
        "déséquilibre qu'on corrige"
    )
    # Au moins un événement MARQUANT doit franchir le seuil d'injection (0.2) à
    # lui seul : sans ça, aucune source ne se verrait jamais dans un prompt.
    marquants = [
        nom for nom in tristes
        if cfg.world_events[nom].effects.get("sadness", 0.0) >= 0.2
    ]
    assert marquants, (
        f"aucune source de tristesse marquante — la plus forte vaut "
        f"{max(cfg.world_events[n].effects.get('sadness', 0) for n in tristes):.2f}, "
        "sous le seuil d'injection des directives"
    )
    engine = EmotionEngine(cfg)
    engine.world_event(marquants[0])
    assert engine.get_state()["sadness"] >= 0.2


def test_les_petites_blessures_s_accumulent():
    """Une source mineure ne doit PAS franchir le seuil seule, mais y arriver en série.

    Être ignoré une fois ne rend pas dépressif — être ignoré cinq fois de suite,
    si. Régler `ignored` assez haut pour se voir d'un coup ferait basculer Wally
    au premier silence d'un salon calme.
    """
    from bot.config import Config

    cfg = Config.load("config.yaml")
    if "ignored" not in cfg.world_events:
        import pytest
        pytest.skip("pas d'événement `ignored` en config")

    engine = EmotionEngine(cfg)
    engine.world_event("ignored")
    assert engine.get_state()["sadness"] < 0.2, "un silence isolé ne doit pas suffire"

    for _ in range(4):
        engine.world_event("ignored")
    assert engine.get_state()["sadness"] >= 0.2, "mais la répétition doit finir par peser"
