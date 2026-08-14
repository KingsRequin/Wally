"""Phase 5 : lexique en sous-chaîne, affinité cliquet, sauvegarde jamais écrite."""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.emotion import (
    COMPETITION_PAIRS,
    SUPPRESSION_MAP,
    EmotionEngine,
    _mot_present,
)


def make_config():
    config = MagicMock()
    config.emotions = {
        e: MagicMock(decay_lambda=0.1, boredom_rise_per_hour=None)
        for e in ["anger", "joy", "sadness", "curiosity", "boredom"]
    }
    config.bot.emotion_inertia_factor = 0.0
    config.emotional_memory = MagicMock(
        learning_rate=0.05, priming_factor=0.05,
        amplification_factor=0.3, decay_lambda_per_day=0.05,
    )
    return config


# ── Le lexique FR ne matche plus n'importe quel préfixe ──────────────────────
#
# `if w in text_lower` testait la SOUS-CHAÎNE. « con » est un préfixe
# extrêmement fréquent en français : concert, conseil, configuration, content.
# Ce chemin est le repli, utilisé quand le LLM est absent ou en échec —
# c'est-à-dire précisément le moment où plus rien ne vient contredire une colère
# qui monte à chaque phrase anodine.

@pytest.mark.parametrize("mot,texte", [
    ("con", "on va au concert"),
    ("con", "d'accord avec ton conseil"),
    ("con", "change la configuration"),
    ("nul", "le match est annulé"),
    ("top", "fais-moi un topo"),
    ("gg", "il creuse, digger"),
    ("rip", "la description du truc"),
])
def test_un_prefixe_ne_declenche_plus_lemotion(mot, texte):
    assert _mot_present(mot, texte) is False


@pytest.mark.parametrize("mot,texte", [
    ("con", "quel con celui-là"),
    ("nul", "c'est vraiment nul"),
    ("top", "ça c'est top"),
    ("rip", "rip"),
])
def test_le_mot_seul_declenche_toujours(mot, texte):
    assert _mot_present(mot, texte) is True


@pytest.mark.parametrize("mot,texte", [
    ("mdr", "mdrrrrr j'ai pas tenu"),
    ("ptdr", "ptdrrr"),
    ("xd", "xddd"),
    ("gg", "gggg"),
])
def test_lallongement_de_chat_reste_reconnu(mot, texte):
    """Sur Twitch, « mdrrr » est la règle. Corriger les faux positifs en perdant
    ces formes aurait été un échange perdant."""
    assert _mot_present(mot, texte) is True


def test_une_expression_apprise_a_plusieurs_mots_fonctionne():
    assert _mot_present("à côté de la plaque", "t'es à côté de la plaque là") is True


# ── L'asymétrie joy/anger est rétablie ───────────────────────────────────────

def test_la_carte_de_suppression_a_un_seul_coefficient_par_sens():
    """Le parcours de la liste brute cumulait deux règles pour joy/anger, donc
    1.2 dans les DEUX sens — l'asymétrie annoncée par le code et par CLAUDE.md
    (« anger érode joy, mais moins que l'inverse ») était annulée."""
    assert SUPPRESSION_MAP["joy"]["anger"] == 0.8
    assert SUPPRESSION_MAP["anger"]["joy"] == 0.4      # le sens explicite l'emporte
    assert SUPPRESSION_MAP["joy"]["sadness"] == 0.8
    assert SUPPRESSION_MAP["sadness"]["joy"] == 0.8    # complété par l'inverse


def test_la_competition_ne_traite_chaque_paire_quune_fois():
    assert COMPETITION_PAIRS == [("anger", "joy"), ("joy", "sadness")]


# ── L'affinité par personne s'estompe ────────────────────────────────────────

def test_laffinite_decroit_avec_le_temps():
    """`decay_lambda_per_day` existait dans la config et dans `config.yaml` mais
    n'était lu NULLE PART : l'affinité, alimentée uniquement par des deltas ≥ 0,
    ne pouvait que croître jusqu'au clamp à 1.0 — et elle est persistée, donc le
    cliquet survivait aux redémarrages."""
    engine = EmotionEngine(make_config())
    engine._user_affinity[("610", "discord")] = {
        "joy": 0.8, "anger": 0.4, "sadness": 0.0,
        "curiosity": 0.0, "boredom": 0.0,
        "_count": {},
    }

    engine._decay_user_affinity(10.0)          # dix jours

    aff = engine._user_affinity[("610", "discord")]
    assert aff["joy"] < 0.8
    assert aff["anger"] < 0.4
    assert aff["joy"] > 0.0                    # ça s'estompe, ça ne s'efface pas


def test_le_decay_daffinite_est_branche_sur_le_tick():
    engine = EmotionEngine(make_config())
    engine._user_affinity[("610", "discord")] = {
        e: 0.5 for e in ("joy", "anger", "sadness", "curiosity", "boredom")
    }
    engine._user_affinity[("610", "discord")]["_count"] = {}

    engine._last_decay = time.time() - 86400    # un jour
    engine._apply_decay()

    assert engine._user_affinity[("610", "discord")]["joy"] < 0.5


def test_sans_lambda_configure_rien_ne_bouge():
    config = make_config()
    config.emotional_memory.decay_lambda_per_day = 0.0
    engine = EmotionEngine(config)
    engine._user_affinity[("610", "discord")] = {"joy": 0.5, "_count": {}}

    engine._decay_user_affinity(10.0)

    assert engine._user_affinity[("610", "discord")]["joy"] == 0.5


# ── La sauvegarde finit par partir, et part à l'arrêt ────────────────────────

async def test_le_debounce_est_borne():
    """`process_message` appelle `apply_delta` cinq fois par message, et chaque
    appel replanifiait la sauvegarde à +5 s. Un message toutes les 4 s suffisait
    donc à ce qu'elle ne parte JAMAIS — pendant un live, précisément."""
    engine = EmotionEngine(make_config())
    engine._db = MagicMock()
    engine._dirty = True

    engine._schedule_save()
    premiere = engine._save_task
    engine._schedule_save()
    assert engine._save_task is not premiere        # replanifiée, debounce normal

    # Au-delà du plafond, la demande en attente n'est plus repoussée.
    engine._save_first_requested_at -= EmotionEngine.SAVE_MAX_DEFERRAL_S + 1
    encore = engine._save_task
    engine._schedule_save()
    assert engine._save_task is encore

    engine._save_task.cancel()


async def test_flush_ecrit_meme_avec_une_sauvegarde_en_attente():
    """Rien ne forçait l'écriture à l'arrêt : la tâche était annulée avec la
    boucle, et l'état non écrit perdu."""
    engine = EmotionEngine(make_config())
    db = MagicMock()
    db.save_emotion_state = AsyncMock()
    db.save_mood_state = AsyncMock()
    db.save_fatigue_state = AsyncMock()
    engine._db = db
    engine._save_user_affinities = AsyncMock()
    engine._dirty = True
    engine._schedule_save()                          # une écriture attend

    await engine.flush()

    db.save_emotion_state.assert_awaited_once()
    assert engine._dirty is False


async def test_flush_sans_rien_a_ecrire_ne_fait_rien():
    engine = EmotionEngine(make_config())
    db = MagicMock()
    db.save_emotion_state = AsyncMock()
    engine._db = db
    engine._dirty = False

    await engine.flush()

    db.save_emotion_state.assert_not_awaited()


def test_larret_du_process_appelle_flush():
    from pathlib import Path

    source = Path("bot/main.py").read_text(encoding="utf-8")
    assert "await emotion.flush()" in source
    # AVANT la fermeture de la base, sinon l'écriture n'a plus de destination.
    assert source.index("await emotion.flush()") < source.index("await db.close()")


# ── Une pensée vide n'est pas une pensée ─────────────────────────────────────

@pytest.mark.asyncio
async def test_une_pensee_vide_est_abandonnee():
    """`complete_with_reasoning` rend `("", "")` quand l'API tombe. L'échec était
    compté comme « ça avance », ce qui ACCÉLÈRE la cadence pendant une panne, et
    publiait un THINK vide suivi d'une condensation LLM sur du vide.

    Vérifié sur le COMPORTEMENT du tick — rien n'est publié, rien n'est
    dispatché, l'overlay n'est pas sollicité — et non sur l'ordre de deux
    lignes du source : une reformulation du code ferait tomber le second sans
    que le défaut soit revenu.
    """
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bot.intelligence.cognitive_loop import CognitiveLoop

    class _Attention:
        async def build_context(self, *a, **kw):
            return SimpleNamespace()

    class _Reasoning:
        async def reason(self, context):
            return SimpleNamespace(thought_text="", decisions=[], thought_fact_id=None)

    class _Feed:
        def __init__(self):
            self.events = []

        def publish(self, event):
            self.events.append(event)

    class _Dispatcher:
        def __init__(self):
            self.dispatched = []

        async def dispatch(self, decision):
            self.dispatched.append(decision)

    feed, dispatcher = _Feed(), _Dispatcher()
    narrator = SimpleNamespace(on_thought=AsyncMock(return_value=None))
    loop = CognitiveLoop(
        _Attention(), _Reasoning(), dispatcher, feed=feed, overlay_narrator=narrator,
    )

    await loop._tick()

    assert not [e for e in feed.events if e.get("type") == "THINK"]
    assert dispatcher.dispatched == []
    narrator.on_thought.assert_not_called()


def test_la_demande_dauto_modification_garde_sa_reference():
    """Le GC peut annuler une tâche détachée sans référence forte, et son
    exception n'apparaît jamais dans loguru."""
    import inspect

    from bot.intelligence.action_dispatcher import ActionDispatcher

    source = inspect.getsource(ActionDispatcher)
    assert "self._fire(self_fix.request_upgrade" in source
    assert "asyncio.create_task(self_fix.request_upgrade" not in source
