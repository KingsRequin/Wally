# tests/test_phase2_emotion_actions.py
"""Phase 2 de l'audit du 2026-08-10 : quatre défauts critiques.

C4 — `try` trop large dans `process_message` : une exception APRÈS l'application
     des deltas LLM tombe dans le repli, qui recalcule et réapplique.
C5 — `_save_user_affinities` itère un dict muté pendant ses `await`.
C6 — `get_active_action_tasks()` rend des `sqlite3.Row` : le handler d'erreur
     de `reload_all()` fait `task.get("id")` et crashe le boot.
C7 — la livraison des tâches planifiées n'a pas de garde `allowed_mentions`.
"""
import asyncio
import sqlite3

import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.core.emotion import EmotionEngine


# ────────────────────────────── C4 ──────────────────────────────
def _moteur():
    config = MagicMock()
    for e in ("anger", "joy", "sadness", "curiosity", "boredom"):
        setattr(config.emotions, e, MagicMock(decay_lambda=0.5))
    config.bot.emotion_inertia_factor = 0.5
    config.bot.emotion_peak_threshold = 0.7
    m = EmotionEngine(config)
    m._openai = MagicMock()
    return m


@pytest.mark.asyncio
async def test_une_panne_apres_les_deltas_ne_les_applique_pas_deux_fois(monkeypatch):
    m = _moteur()
    m._analyze_llm = AsyncMock(return_value=({"anger": 0.4}, [{"word": "x"}], 0.0, 0.0, []))
    # `_learn_words` casse APRÈS que les deltas LLM ont été appliqués.
    m._learn_words = AsyncMock(side_effect=RuntimeError("écriture disque impossible"))
    m.analyze_message = AsyncMock(return_value={"anger": 0.4})

    appliques: list[tuple[str, float]] = []
    vrai_apply = m.apply_delta
    monkeypatch.setattr(m, "apply_delta",
                        lambda e, d: (appliques.append((e, d)), vrai_apply(e, d))[1])

    await m.process_message("sale con", context_messages=[{"role": "user", "content": "x"}])

    anger = [d for e, d in appliques if e == "anger"]
    assert len(anger) == 1, f"colère appliquée {len(anger)} fois : {appliques}"


@pytest.mark.asyncio
async def test_le_resultat_llm_survit_a_une_panne_de_learn_words():
    """trust/love/user_facts du LLM étaient jetés et remplacés par l'heuristique."""
    m = _moteur()
    m._analyze_llm = AsyncMock(
        return_value=({"joy": 0.2}, [{"word": "x"}], 0.3, 0.1, ["aime les chats"])
    )
    m._learn_words = AsyncMock(side_effect=RuntimeError("boom"))
    m.analyze_message = AsyncMock(return_value={"joy": 0.2})

    out = await m.process_message("coucou", context_messages=[{"role": "user", "content": "x"}])

    assert out is not None, "le repli a écrasé le résultat du LLM"
    assert out["trust_delta"] == 0.3 and out["user_facts"] == ["aime les chats"]


@pytest.mark.asyncio
async def test_une_panne_du_llm_lui_meme_passe_bien_au_repli():
    m = _moteur()
    m._analyze_llm = AsyncMock(side_effect=RuntimeError("API down"))
    m.analyze_message = AsyncMock(return_value={"anger": 0.2})
    out = await m.process_message("test", context_messages=[{"role": "user", "content": "x"}])
    assert out is None
    m.analyze_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_un_mot_appris_mal_forme_ne_casse_pas_la_liste():
    """Sans schéma (chemin image), `new_words` peut être une liste de chaînes."""
    m = _moteur()
    await m._learn_words(["pas un dict", {"word": "zbroumf", "emotion": "joy", "delta": 0.2}])
    assert any(w == "zbroumf" for w, _ in m._learned_words["joy"])


# ────────────────────────────── C5 ──────────────────────────────
@pytest.mark.asyncio
async def test_une_nouvelle_personne_pendant_la_sauvegarde_ne_casse_rien():
    m = _moteur()
    m._db = MagicMock()
    m._user_affinity = {
        (f"u{i}", "discord"): {"joy": 0.5, "_count": {"joy": 1}} for i in range(3)
    }

    async def upsert(user_id, platform, emotion, aff, count):
        # Un message arrive pendant l'écriture : le dict grossit.
        m._user_affinity[(f"nouveau-{user_id}-{emotion}", "twitch")] = {
            "joy": 0.1, "_count": {"joy": 1}
        }
        await asyncio.sleep(0)

    m._db.upsert_emotional_memory = upsert
    await m._save_user_affinities()  # ne doit pas lever RuntimeError


# ────────────────────────────── C6 ──────────────────────────────
@pytest.mark.asyncio
async def test_les_taches_actives_sont_des_dict():
    """Le handler d'erreur de `reload_all()` appelle `task.get("id")`."""
    from bot.db.mixins.actions import ActionMixin

    class _DB(ActionMixin):
        async def fetch_all(self, query, params=()):
            conn = sqlite3.connect(":memory:")
            conn.row_factory = sqlite3.Row
            return conn.execute("SELECT 1 AS id, 'once' AS schedule_type").fetchall()

    taches = await _DB().get_active_action_tasks()
    assert taches[0].get("id") == 1, "sqlite3.Row n'a pas de .get() — le boot crashe"


@pytest.mark.asyncio
async def test_la_recherche_de_taches_rend_aussi_des_dict():
    from bot.db.mixins.actions import ActionMixin

    class _DB(ActionMixin):
        async def fetch_all(self, query, params=()):
            conn = sqlite3.connect(":memory:")
            conn.row_factory = sqlite3.Row
            return conn.execute("SELECT 7 AS id").fetchall()

    r = await _DB().search_action_tasks("x", "1", "discord")
    assert r[0].get("id") == 7


# ────────────────────────────── C7 ──────────────────────────────
@pytest.mark.asyncio
async def test_une_tache_planifiee_ne_peut_pas_ping_everyone():
    from bot.intelligence.actions.executor import ActionExecutor

    salon = MagicMock()
    salon.send = AsyncMock()
    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=salon)

    ex = ActionExecutor(MagicMock())
    ex.set_bots(bot, None)
    await ex.deliver("@everyone debout !", "discord", "123")

    salon.send.assert_awaited_once()
    mentions = salon.send.await_args.kwargs.get("allowed_mentions")
    assert mentions is not None, "envoi nu : @everyone passe"
    assert mentions.everyone is False
