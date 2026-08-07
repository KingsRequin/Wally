"""Paris de Wally sur l'issue d'une partie (widget 16).

Ce widget est resté bloqué longtemps : aucune source ne dit si une partie est
gagnée. La sortie n'est pas de deviner mieux, c'est de laisser Wally constater
et assumer — d'où un score cumulé qui suit ses ratés.
"""
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.predictions import PredictionService, _STALE_AFTER_S
from bot.discord.handlers import run_predict_tool


class _FakeDB:
    def __init__(self):
        self.rows = []
        self._next = 1

    async def execute(self, query, params=()):
        q = " ".join(query.split())
        if q.startswith("UPDATE predictions SET outcome = 'void'"):
            for r in self.rows:
                if r["outcome"] is None:
                    r["outcome"] = "void"
        elif q.startswith("INSERT INTO predictions"):
            bet, created = params
            self.rows.append({"id": self._next, "bet": bet, "created_at": created,
                              "outcome": None, "resolved_at": None})
            self._next += 1
        elif q.startswith("UPDATE predictions SET outcome = ?"):
            outcome, at, rid = params
            for r in self.rows:
                if r["id"] == rid:
                    r.update(outcome=outcome, resolved_at=at)

    async def fetch_one(self, query, params=()):
        open_rows = [r for r in self.rows if r["outcome"] is None]
        return open_rows[-1] if open_rows else None

    async def fetch_all(self, query, params=()):
        counts = {}
        for r in self.rows:
            if r["outcome"] in ("right", "wrong"):
                counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
        return [{"outcome": k, "n": v} for k, v in counts.items()]


def _svc():
    return PredictionService(_FakeDB())


@pytest.mark.asyncio
async def test_un_pari_s_ouvre_puis_se_tranche():
    s = _svc()
    await s.open("on finit top 3")
    out = await s.resolve(True)
    assert out["outcome"] == "right" and out["right"] == 1


@pytest.mark.asyncio
async def test_on_ne_peut_pas_trancher_sans_avoir_parie():
    """Sinon Wally s'attribuerait des points sans rien risquer."""
    s = _svc()
    assert await s.resolve(True) is None


@pytest.mark.asyncio
async def test_un_pari_vide_est_refuse():
    assert await _svc().open("   ") is None


@pytest.mark.asyncio
async def test_ouvrir_un_pari_abandonne_le_precedent():
    """Sinon on trancherait le mauvais, une partie plus tard."""
    s = _svc()
    await s.open("premier")
    await s.open("second")
    assert (await s.current())["bet"] == "second"
    out = await s.resolve(True)
    assert out["total"] == 1        # le premier ne compte pas


@pytest.mark.asyncio
async def test_un_pari_oublie_expire():
    """Trancher un pari vieux de deux heures n'aurait aucun rapport avec la
    partie en cours."""
    s = _svc()
    await s.open("on gagne")
    s._db.rows[0]["created_at"] = time.time() - _STALE_AFTER_S - 1
    assert await s.current() is None
    assert await s.resolve(True) is None


@pytest.mark.asyncio
async def test_le_score_cumule_compte_les_deux_cotes():
    s = _svc()
    for right in (True, False, True):
        await s.open("un pari")
        await s.resolve(right)
    assert await s.score() == {"right": 2, "wrong": 1, "total": 3}


@pytest.mark.asyncio
async def test_les_paris_abandonnes_ne_comptent_pas():
    s = _svc()
    await s.open("abandonné")
    await s.open("tranché")
    await s.resolve(False)
    assert (await s.score())["total"] == 1


# ── l'outil ──

def _bot(**methods):
    svc = MagicMock()
    for k, v in methods.items():
        setattr(svc, k, AsyncMock(return_value=v))
    narrator = MagicMock()
    return SimpleNamespace(predictions=svc, overlay_narrator=narrator), narrator


@pytest.mark.asyncio
async def test_l_outil_ouvre_un_pari_et_l_affiche():
    bot, narrator = _bot(open={"bet": "on finit top 3"}, score={"right": 2, "total": 3})
    out = json.loads(await run_predict_tool(bot, {"bet": "on finit top 3"}))
    assert out["status"] == "ok"
    narrator.show_prediction.assert_called_once()


@pytest.mark.asyncio
async def test_l_outil_annonce_le_verdict_et_le_score():
    bot, _ = _bot(resolve={"bet": "top 3", "right": 2, "total": 3})
    msg = json.loads(await run_predict_tool(bot, {"outcome": "right"}))["message"]
    assert "2/3" in msg and "vu juste" in msg


@pytest.mark.asyncio
async def test_l_outil_refuse_de_trancher_sans_pari():
    bot, _ = _bot(resolve=None)
    assert json.loads(await run_predict_tool(bot, {"outcome": "wrong"}))["status"] == "no_bet"


@pytest.mark.asyncio
async def test_sans_service_l_outil_le_dit():
    out = json.loads(await run_predict_tool(SimpleNamespace(), {"bet": "x"}))
    assert out["status"] == "unavailable"
