# tests/test_overlay_persistance_sondage.py
"""L'overlay garde aussi son sondage, son podium et ses saluts (2026-08-20).

Le bingo, le pendu et l'objectif traversaient déjà les redémarrages ; trois
états du même écran ne le faisaient pas :

  · **Le sondage en cours** — question, votes déjà exprimés, et surtout sa
    CLÔTURE PLANIFIÉE. Perdue, le dépouillement n'arrivait jamais : le widget
    s'effaçait sans gagnant, et « alors, ça a donné quoi ? » restait sans
    réponse. Son échéance est un `time.monotonic()`, qui repart de zéro dans le
    nouveau process — il voyage donc en temps mural.
  · **Le podium des bavards**, remis à zéro à chaque rebuild.
  · **Qui a déjà été salué.** Cinq rebuilds = jusqu'à cinq « tiens, revoilà
    machin ! » à la même personne dans la même soirée.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.overlay_feed import OverlayFeed
from bot.intelligence.overlay_narrator import OverlayNarrator


def _db():
    db = MagicMock()
    db._v = {}

    async def _set(c, v): db._v[c] = v
    async def _get(c): return db._v.get(c)
    async def _del(c): db._v.pop(c, None)

    db.set_state = AsyncMock(side_effect=_set)
    db.get_state = AsyncMock(side_effect=_get)
    db.delete_state = AsyncMock(side_effect=_del)
    return db


def _n(db, statut=None):
    return OverlayNarrator(OverlayFeed(), MagicMock(), lambda: True, db=db,
                           stream_status=lambda: statut or {"started_at": "live-A"})


@pytest.mark.asyncio
async def test_le_sondage_et_ses_votes_traversent_le_rebuild():
    db = _db()
    avant = _n(db)
    avant.start_poll("Fuse ou Bangalore ?", ["Fuse", "Bangalore"], seconds=60)
    avant._count_vote("alice", "1")
    avant._count_vote("bob", "2")
    await avant.flush_live_state()

    apres = _n(db)
    await apres.restore_live_state()

    assert apres._poll is not None
    assert apres._poll["question"] == "Fuse ou Bangalore ?"
    assert len(apres._poll["votes"]) == 2


@pytest.mark.asyncio
async def test_un_sondage_expire_pendant_la_coupure_est_depouille():
    """Sinon il reste à l'écran sans gagnant, et Wally ne sait pas quoi
    répondre quand on lui demande le résultat."""
    db = _db()
    avant = _n(db)
    avant.start_poll("Fuse ou Bangalore ?", ["Fuse", "Bangalore"], seconds=10)
    avant._count_vote("alice", "1")
    await avant.flush_live_state()

    # La coupure a duré plus longtemps que le sondage.
    brut = db._v["overlay:live_state"]
    import json
    data = json.loads(brut)
    data["poll"]["restant"] = 0.0
    db._v["overlay:live_state"] = json.dumps(data)

    apres = _n(db)
    await apres.restore_live_state()

    assert apres._poll is None
    assert apres._last_poll is not None
    assert apres._last_poll["winner"] == "Fuse"


@pytest.mark.asyncio
async def test_la_cloture_est_bien_replanifiee():
    """Sans réarmement, le dépouillement n'arrive jamais."""
    db = _db()
    avant = _n(db)
    avant.start_poll("Fuse ou Bangalore ?", ["Fuse", "Bangalore"], seconds=60)
    await avant.flush_live_state()

    apres = _n(db)
    await apres.restore_live_state()

    assert apres._poll_task is not None and not apres._poll_task.done()
    apres._poll_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await apres._poll_task


@pytest.mark.asyncio
async def test_le_dernier_resultat_reste_repondable():
    """« Alors, ça a donné quoi ? » après un rebuild."""
    db = _db()
    avant = _n(db)
    avant.start_poll("Fuse ou Bangalore ?", ["Fuse", "Bangalore"], seconds=60)
    avant._count_vote("alice", "1")
    avant.close_poll()
    await avant.flush_live_state()

    apres = _n(db)
    await apres.restore_live_state()

    assert "Fuse" in apres.poll_result_line()


@pytest.mark.asyncio
async def test_personne_n_est_resalue_apres_un_rebuild():
    db = _db()
    avant = _n(db)
    avant._greeted.add("alice")
    avant._talkers["alice"] = 7
    await avant.flush_live_state()

    apres = _n(db)
    await apres.restore_live_state()

    assert "alice" in apres._greeted
    assert apres._talkers.get("alice") == 7


@pytest.mark.asyncio
async def test_rien_de_tout_ca_ne_vient_d_un_autre_live():
    db = _db()
    avant = _n(db, statut={"started_at": "live-A"})
    avant.start_poll("Fuse ou Bangalore ?", ["Fuse", "Bangalore"], seconds=60)
    avant._greeted.add("alice")
    await avant.flush_live_state()

    apres = _n(db, statut={"started_at": "live-B"})
    await apres.restore_live_state()

    assert apres._poll is None
    assert not apres._greeted
