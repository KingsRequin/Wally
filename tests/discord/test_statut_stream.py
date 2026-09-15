from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot.discord import statut_stream as ss


def _bot(nom_actuel, *, salon_id=10, pret=True):
    salon = SimpleNamespace(id=10, name=nom_actuel, edit=AsyncMock())
    cfg = SimpleNamespace(salon_id=salon_id, nom_live="🟢live", nom_hors_live="🔴off")
    bot = SimpleNamespace(config=SimpleNamespace(discord=SimpleNamespace(statut_stream=cfg)))
    bot.get_channel = lambda cid: salon if cid == 10 else None
    bot.is_ready = lambda: pret
    return bot, salon


async def _laisser_tourner():
    await asyncio.sleep(0)
    await asyncio.sleep(0)


async def test_nom_deja_bon_aucun_appel():
    bot, salon = _bot("🔴off")
    ss.sur_releve(bot, {"live": False})
    await _laisser_tourner()
    salon.edit.assert_not_awaited()


async def test_bascule_live_renomme():
    bot, salon = _bot("🔴off")
    ss.sur_releve(bot, {"live": True})
    await _laisser_tourner()
    salon.edit.assert_awaited_once()
    assert salon.edit.await_args.kwargs["name"] == "🟢live"


async def test_desactive_ou_discord_pas_pret():
    for bot, salon in (_bot("🔴off", salon_id=None), _bot("🔴off", pret=False)):
        ss.sur_releve(bot, {"live": True})
        await _laisser_tourner()
        salon.edit.assert_not_awaited()


async def test_echec_du_renommage_ne_leve_pas():
    bot, salon = _bot("🔴off")
    salon.edit.side_effect = RuntimeError("429")
    ss.sur_releve(bot, {"live": True})
    await _laisser_tourner()
