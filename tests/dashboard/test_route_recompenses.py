"""Routes admin des récompenses : validation, et rien ne part sans Twitch."""
from __future__ import annotations

import types
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from bot.config import PrixDynamiqueConfig, RecompenseConfig
from bot.dashboard.routes import recompenses as r


def _requete(gestion=None):
    config = types.SimpleNamespace(
        twitch=types.SimpleNamespace(
            recompenses={"tts_viewer": RecompenseConfig(titre="t", cout=500, prompt="p")},
            prix_dynamique_tts=PrixDynamiqueConfig()),
        save=MagicMock())
    bot = types.SimpleNamespace(recompenses=gestion) if gestion else None
    wally = types.SimpleNamespace(config=config, twitch_bot=bot)
    return types.SimpleNamespace(app=types.SimpleNamespace(
        state=types.SimpleNamespace(wally=wally)))


def _gestion():
    g = MagicMock()
    g.appliquer = AsyncMock(return_value="RW")
    g.supprimer = AsyncMock(return_value=True)
    g.pousser_prix_tts = AsyncMock(return_value=600)
    return g


async def test_sans_twitch_la_route_repond_503():
    with pytest.raises(HTTPException) as e:
        await r.lister(_requete())
    assert e.value.status_code == 503


async def test_un_prix_modifie_est_range_puis_pousse():
    g = _gestion()
    req = _requete(g)
    rep = await r.modifier(req, "tts_viewer", r.ModifRecompense(cout=700))
    assert rep["en_ligne"] is True
    assert req.app.state.wally.config.twitch.recompenses["tts_viewer"].cout == 700
    req.app.state.wally.config.save.assert_called_once()
    g.appliquer.assert_awaited_once_with("tts_viewer")


@pytest.mark.parametrize("corps", [
    {"cout": 0}, {"titre": ""}, {"titre": "x" * 46}, {"prompt": "x" * 201},
    {"recharge_s": -1},
])
async def test_une_valeur_hors_bornes_est_refusee_sans_rien_ranger(corps):
    req = _requete(_gestion())
    with pytest.raises(HTTPException) as e:
        await r.modifier(req, "tts_viewer", r.ModifRecompense(**corps))
    assert e.value.status_code == 422
    req.app.state.wally.config.save.assert_not_called()


async def test_une_cle_inconnue_rend_404():
    with pytest.raises(HTTPException) as e:
        await r.supprimer(_requete(_gestion()), "im_out")
    assert e.value.status_code == 404


async def test_le_prix_dynamique_se_regle_et_se_pousse():
    g = _gestion()
    req = _requete(g)
    rep = await r.modifier_prix_dynamique(
        req, r.ModifPrixDynamique(hausse_pct=35, demi_vie_minutes=5))
    assert rep["prix_dynamique_tts"] == {"hausse_pct": 35.0, "demi_vie_minutes": 5.0}
    g.pousser_prix_tts.assert_awaited_once()


async def test_une_demi_vie_nulle_est_refusee():
    with pytest.raises(HTTPException):
        await r.modifier_prix_dynamique(_requete(_gestion()),
                                        r.ModifPrixDynamique(demi_vie_minutes=0))
