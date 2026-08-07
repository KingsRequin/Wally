"""Outils de comptage exposés à Wally.

Les totaux viennent de la base, jamais du modèle : « ça en est où ? » doit avoir
une réponse vérifiable.
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.discord.handlers import run_tally_tool


def _bot(**tally_methods):
    tally = MagicMock()
    for name, value in tally_methods.items():
        setattr(tally, name, AsyncMock(return_value=value))
    return SimpleNamespace(tally=tally)


@pytest.mark.asyncio
async def test_ouvrir_un_compteur():
    bot = _bot(start={"label": "pas rechargé", "count": 0})
    out = json.loads(await run_tally_tool(bot, "start_counting",
                                          {"label": "pas rechargé", "keywords": ["pas recharge"]}))
    assert out["status"] == "ok" and "pas rechargé" in out["message"]


@pytest.mark.asyncio
async def test_un_compteur_inexploitable_est_refuse():
    bot = _bot(start=None)
    out = json.loads(await run_tally_tool(bot, "start_counting", {"label": "x", "keywords": []}))
    assert out["status"] == "rejected"


@pytest.mark.asyncio
async def test_relancer_annonce_le_total_repris():
    """On ne remet pas à zéro un gag qui court depuis trois streams."""
    bot = _bot(start={"label": "morts", "count": 42})
    out = json.loads(await run_tally_tool(bot, "start_counting",
                                          {"label": "morts", "keywords": ["je suis mort"]}))
    assert "42" in out["message"]


@pytest.mark.asyncio
async def test_arreter_un_compteur_donne_son_total():
    bot = _bot(stop={"label": "morts", "count": 7})
    out = json.loads(await run_tally_tool(bot, "stop_counting", {"label": "morts"}))
    assert out["status"] == "ok" and "7" in out["message"]


@pytest.mark.asyncio
async def test_arreter_un_compteur_inconnu():
    bot = _bot(stop=None)
    assert json.loads(await run_tally_tool(bot, "stop_counting", {"label": "?"}))["status"] == "not_found"


@pytest.mark.asyncio
async def test_lister_montre_les_totaux_et_les_arretes():
    bot = _bot(list=[{"label": "morts", "count": 7, "active": 1},
                     {"label": "ping", "count": 3, "active": 0}])
    msg = json.loads(await run_tally_tool(bot, "list_counters", {}))["message"]
    assert "morts : 7" in msg and "ping : 3 (arrêté)" in msg


@pytest.mark.asyncio
async def test_lister_quand_il_n_y_a_rien():
    bot = _bot(list=[])
    assert json.loads(await run_tally_tool(bot, "list_counters", {}))["status"] == "empty"


@pytest.mark.asyncio
async def test_une_panne_ne_casse_pas_la_reponse():
    bot = SimpleNamespace(tally=MagicMock())
    bot.tally.list = AsyncMock(side_effect=RuntimeError("base HS"))
    assert json.loads(await run_tally_tool(bot, "list_counters", {}))["status"] == "error"


@pytest.mark.asyncio
async def test_sans_service_l_outil_le_dit():
    out = json.loads(await run_tally_tool(SimpleNamespace(), "list_counters", {}))
    assert out["status"] == "unavailable"
