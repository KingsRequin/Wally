"""Routes admin Twitch › Chat & événements et Twitch › Apex."""
from __future__ import annotations

import types
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from bot.config import (AnnoncesAutoConfig, ApexConfig, DuelConfig, TwitchConfig,
                        TwitchEventConfig)
from bot.dashboard.routes import config_twitch as r


def _requete():
    config = types.SimpleNamespace(
        twitch=TwitchConfig(guest_channels=[], cooldown_seconds=10,
                            annonces_auto=AnnoncesAutoConfig()),
        twitch_events={
            "follow": TwitchEventConfig(active=False, message="Merci {username}"),
            "raid": TwitchEventConfig(active=False, message="Raid de {raiders_count}"),
        },
        apex=ApexConfig(streamer_account="Azrael_ttv", duel=DuelConfig()),
        save=MagicMock(),
    )
    wally = types.SimpleNamespace(config=config)
    return types.SimpleNamespace(app=types.SimpleNamespace(
        state=types.SimpleNamespace(wally=wally)))


# ─── Chat & événements ────────────────────────────────────────────────────────

async def test_lecture_liste_les_six_evenements_avec_leurs_variables():
    rep = await r.lire_chat(_requete())
    cles = [e["cle"] for e in rep["evenements"]]
    assert cles == ["follow", "sub", "resub", "gift_sub", "bits", "raid"]
    sub = next(e for e in rep["evenements"] if e["cle"] == "sub")
    assert sub["active"] is False and sub["message"] == ""
    raid = next(e for e in rep["evenements"] if e["cle"] == "raid")
    assert "raiders_count" in raid["variables"]


async def test_un_evenement_modifie_est_range_en_memoire_puis_sauve():
    req = _requete()
    cfg = req.app.state.wally.config
    await r.modifier_chat(req, {"evenements": {
        "follow": {"active": True, "message": "Bienvenue {username} !"},
        "gift_sub": {"active": True, "message": "{username} offre {amount} subs"},
    }})
    assert cfg.twitch_events["follow"].active is True
    assert cfg.twitch_events["follow"].message == "Bienvenue {username} !"
    # Absent de la config : créé, puisque le lecteur fait `.get(clé)`.
    assert cfg.twitch_events["gift_sub"].message == "{username} offre {amount} subs"
    cfg.save.assert_called_once()


async def test_les_reglages_du_chat_sont_ranges():
    req = _requete()
    cfg = req.app.state.wally.config
    await r.modifier_chat(req, {
        "cooldown_seconds": 30, "attente_seuil_s": 0, "shoutout_raid": False,
        "annonces_auto": {"active": False, "cadence_minutes": 45},
    })
    assert cfg.twitch.cooldown_seconds == 30
    assert cfg.twitch.attente_seuil_s == 0.0
    assert cfg.twitch.shoutout_raid is False
    assert cfg.twitch.annonces_auto.active is False
    assert cfg.twitch.annonces_auto.cadence_minutes == 45


@pytest.mark.parametrize("corps", [
    {"evenements": {"follow": {"message": "Merci {amount}"}}},       # variable hors sujet
    {"evenements": {"follow": {"message": "Merci {username"}}},      # accolade ouverte
    {"evenements": {"follow": {"active": True, "message": ""}}},     # activé mais vide
    {"evenements": {"inconnu": {"active": True}}},
    {"evenements": {"follow": {"message": "x" * 501}}},
    {"cooldown_seconds": -1},
    {"cooldown_seconds": 2.5},
    {"cooldown_seconds": None},
    {"attente_seuil_s": 61},
    {"shoutout_raid": "oui"},
    {"annonces_auto": {"cadence_minutes": 1}},
])
async def test_une_saisie_invalide_est_refusee_sans_rien_ranger(corps):
    req = _requete()
    with pytest.raises(HTTPException) as e:
        await r.modifier_chat(req, corps)
    assert e.value.status_code == 422
    req.app.state.wally.config.save.assert_not_called()


async def test_un_refus_ne_laisse_aucune_modification_partielle_en_memoire():
    req = _requete()
    cfg = req.app.state.wally.config
    with pytest.raises(HTTPException):
        await r.modifier_chat(req, {"shoutout_raid": False, "cooldown_seconds": -5})
    assert cfg.twitch.shoutout_raid is True


async def test_les_gabarits_de_la_config_de_prod_sont_acceptes():
    """Les messages déjà rangés dans config.yaml doivent rester enregistrables."""
    req = _requete()
    await r.modifier_chat(req, {"evenements": {
        "bits": {"message": "Merci pour les {amount} bits, {username} !"},
        "raid": {"message": "Un raid de {raiders_count} personnes avec {username} !"},
        "resub": {"message": "Merci pour les {months} mois de sub, {username} !"},
    }})


# ─── Apex ─────────────────────────────────────────────────────────────────────

async def test_lecture_apex_porte_le_plafond_dur_du_lobby():
    rep = await r.lire_apex(_requete())
    assert rep["streamer_account"] == "Azrael_ttv"
    assert rep["duel"]["manches"] == 3
    assert rep["bornes"]["plafond_marge_lobby_s"] == 39.0


async def test_le_duel_modifie_est_range():
    req = _requete()
    cfg = req.app.state.wally.config
    await r.modifier_apex(req, {
        "streamer_account": " Autre ", "streamer_platform": "PS4",
        "duel": {"active": True, "manches": 5, "cadence_s": 3, "attente_squad_min": 10,
                 "plafond_kills_manche": 400, "marge_lobby_s": 20,
                 "mode_jeu": "Battle Royale", "api_muette_max_s": 240},
    })
    assert cfg.apex.streamer_account == "Autre"
    assert cfg.apex.streamer_platform == "PS4"
    d = cfg.apex.duel
    assert (d.active, d.manches, d.cadence_s, d.marge_lobby_s) == (True, 5, 3.0, 20.0)
    assert d.mode_jeu == "Battle Royale"
    cfg.save.assert_called_once()


@pytest.mark.parametrize("corps", [
    {"streamer_platform": "Switch"},
    {"duel": {"manches": 0}},
    {"duel": {"cadence_s": 0.2}},
    {"duel": {"plafond_kills_manche": 30}},
    {"duel": {"marge_lobby_s": 40}},
    # Chacun dans ses bornes, mais 2 × 15 + 10 dépasse les 39 s.
    {"duel": {"cadence_s": 15}},
    {"duel": {"api_muette_max_s": 5}},
    {"duel": {"mode_jeu": "x" * 61}},
])
async def test_un_reglage_du_duel_invalide_est_refuse(corps):
    req = _requete()
    with pytest.raises(HTTPException) as e:
        await r.modifier_apex(req, corps)
    assert e.value.status_code == 422
    req.app.state.wally.config.save.assert_not_called()
    assert req.app.state.wally.config.apex.duel == DuelConfig()


# ─── Par l'application montée : routage, jeton, corps d'erreur ────────────────

_JETON = {"Authorization": "Bearer testtoken"}


async def test_les_routes_sont_montees_sous_api_admin_et_gardees(async_client):
    assert (await async_client.get("/api/admin/twitch/chat")).status_code == 401
    rep = await async_client.get("/api/admin/twitch/chat", headers=_JETON)
    assert rep.status_code == 200
    assert rep.json()["cooldown_seconds"] == 10


async def test_un_refus_rend_un_detail_en_texte_pour_le_toast(async_client):
    rep = await async_client.patch("/api/admin/twitch/chat", headers=_JETON,
                                   json={"cooldown_seconds": -1})
    assert rep.status_code == 422
    assert isinstance(rep.json()["detail"], str)
