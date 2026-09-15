from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.discord import statut_stream as ss


@pytest.fixture(autouse=True)
def _nettoyer_taches_en_cours():
    """`_renames_en_cours` est un état MODULE : sans nettoyage, une tâche
    laissée en vol par un test (ou son salon_id=10 partagé) polluerait le
    suivant."""
    ss._renames_en_cours.clear()
    ss._derniers_avertissements.clear()
    yield
    ss._renames_en_cours.clear()
    ss._derniers_avertissements.clear()


def _bot(nom_actuel, *, salon_id=10, pret=True):
    salon = SimpleNamespace(id=10, name=nom_actuel, edit=AsyncMock())
    cfg = SimpleNamespace(salon_id=salon_id, nom_live="🟢live", nom_hors_live="🔴off")
    bot = SimpleNamespace(config=SimpleNamespace(discord=SimpleNamespace(statut_stream=cfg)))
    bot.get_channel = lambda cid: salon if cid == 10 else None
    bot.is_ready = lambda: pret
    return bot, salon


def _bot_avec_edit_lent(nom_actuel, *, salon_id, evenement):
    """Un salon dont `edit` reste en vol tant que `evenement` n'est pas posé —
    simule un renommage retenu par la limite de débit de Discord."""
    async def _edit_lent(**kwargs):
        await evenement.wait()

    salon = SimpleNamespace(id=salon_id, name=nom_actuel, edit=AsyncMock(side_effect=_edit_lent))
    cfg = SimpleNamespace(salon_id=salon_id, nom_live="🟢live", nom_hors_live="🔴off")
    bot = SimpleNamespace(config=SimpleNamespace(discord=SimpleNamespace(statut_stream=cfg)))
    bot.get_channel = lambda cid: salon if cid == salon_id else None
    bot.is_ready = lambda: True
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


async def test_renommage_en_vol_aucun_doublon():
    evenement = asyncio.Event()
    bot, salon = _bot_avec_edit_lent("🔴off", salon_id=30, evenement=evenement)

    ss.sur_releve(bot, {"live": True})
    await asyncio.sleep(0)
    ss.sur_releve(bot, {"live": True})  # le relevé suivant, pendant que le 1er est en vol
    await asyncio.sleep(0)
    salon.edit.assert_awaited_once()

    evenement.set()
    await _laisser_tourner()


async def test_relance_une_fois_le_renommage_termine():
    evenement = asyncio.Event()
    bot, salon = _bot_avec_edit_lent("🔴off", salon_id=31, evenement=evenement)

    ss.sur_releve(bot, {"live": True})
    await asyncio.sleep(0)
    evenement.set()
    await _laisser_tourner()
    salon.edit.assert_awaited_once()

    # `salon.name` n'a pas bougé (comme après un échec réel) : le relevé
    # suivant doit pouvoir relancer, la tâche précédente étant terminée.
    ss.sur_releve(bot, {"live": True})
    await _laisser_tourner()
    assert salon.edit.await_count == 2


async def test_echec_repete_averti_au_plus_une_fois_par_heure(monkeypatch):
    """Une permission retirée fait échouer CHAQUE relevé : sans plafond, 60
    WARNING identiques par heure."""
    instant = [1000.0]
    monkeypatch.setattr(ss, "_horloge", lambda: instant[0])
    bot, salon = _bot("🔴off")
    salon.edit.side_effect = RuntimeError("Missing Permissions")
    dits: list[str] = []
    jeton = ss.logger.add(lambda m: dits.append(str(m)), level="WARNING")
    try:
        for decalage in (0, 60, 1800, 3599):
            instant[0] = 1000.0 + decalage
            ss.sur_releve(bot, {"live": True})
            await _laisser_tourner()
        assert len(dits) == 1
        instant[0] = 1000.0 + 3600
        ss.sur_releve(bot, {"live": True})
        await _laisser_tourner()
        assert len(dits) == 2
        # Un échec DIFFÉRENT est dit tout de suite.
        salon.edit.side_effect = RuntimeError("autre chose")
        instant[0] += 60
        ss.sur_releve(bot, {"live": True})
        await _laisser_tourner()
        assert len(dits) == 3
    finally:
        ss.logger.remove(jeton)
    assert salon.edit.await_count == 6


async def test_un_succes_efface_la_memoire_des_echecs(monkeypatch):
    monkeypatch.setattr(ss, "_horloge", lambda: 1000.0)
    bot, salon = _bot("🔴off")
    dits: list[str] = []
    jeton = ss.logger.add(lambda m: dits.append(str(m)), level="WARNING")
    try:
        salon.edit.side_effect = RuntimeError("429")
        ss.sur_releve(bot, {"live": True})
        await _laisser_tourner()
        salon.edit.side_effect = None
        ss.sur_releve(bot, {"live": True})
        await _laisser_tourner()
        salon.edit.side_effect = RuntimeError("429")
        ss.sur_releve(bot, {"live": True})
        await _laisser_tourner()
    finally:
        ss.logger.remove(jeton)
    assert len(dits) == 2
