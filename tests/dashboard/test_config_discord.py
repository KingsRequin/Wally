"""Routes admin Discord : Serveur communautaire, salons au rôle particulier, colère.

On vérifie ce que le LECTEUR verra : des ids en `int` dans l'objet config (le
même que `bot.config`), la forme « désactivé » attendue par chaque module, et
qu'un refus ne laisse rien en mémoire ni sur le disque.
"""
from __future__ import annotations

import types
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bot.config import (
    BienvenueConfig, DiscordConfig, JournalModerationConfig,
    SalonsTemporairesConfig, StatutStreamConfig,
)
from bot.dashboard.routes import config_discord

GROS = "1105088949887696988"   # au-delà de 2^53 : doit survivre à l'aller-retour


def _client():
    discord = DiscordConfig(
        anger_trigger_threshold=3, timeout_minutes=10,
        always_trigger_channels=[11],
        per_guild_channel_whitelist={"875421531415666698": None},
        salons_temporaires=SalonsTemporairesConfig(salon_createur_id=int(GROS), noms=["A"]),
        journal_moderation=JournalModerationConfig(salon_ids=[1], guild_ids=[2]),
        statut_stream=StatutStreamConfig(salon_id=5),
        bienvenue=BienvenueConfig(guild_ids=[2], messages=["Salut"]),
    )
    config = types.SimpleNamespace(discord=discord, save=MagicMock())
    app = FastAPI()
    app.include_router(config_discord.admin_router, prefix="/api/admin")
    app.state.wally = types.SimpleNamespace(config=config, discord_bot=None)
    return TestClient(app), config


def test_lecture_communaute_ids_en_chaines():
    client, _ = _client()
    d = client.get("/api/admin/discord/communaute").json()
    assert d["salons_temporaires"] == {"actif": True, "salon_createur_id": GROS, "noms": ["A"]}
    assert d["journal_moderation"]["salon_ids"] == ["1"]
    assert d["statut_stream"]["actif"] is True
    assert d["bienvenue"]["guild_ids"] == ["2"]


def test_salons_temporaires_ecrit_un_int_et_sauve():
    client, config = _client()
    r = client.patch("/api/admin/discord/communaute/salons_temporaires",
                     json={"actif": True, "salon_createur_id": "42", "noms": [" B ", "", "C"]})
    assert r.status_code == 200
    assert config.discord.salons_temporaires.salon_createur_id == 42
    assert config.discord.salons_temporaires.noms == ["B", "C"]
    config.save.assert_called_once()


@pytest.mark.parametrize(("module", "corps", "champ", "vide"), [
    ("salons_temporaires", {"actif": False, "salon_createur_id": "42", "noms": []},
     lambda d: d.salons_temporaires.salon_createur_id, None),
    ("journal_moderation", {"actif": False, "salon_ids": ["1"], "guild_ids": ["2"], "inclure_bots": False},
     lambda d: d.journal_moderation.salon_ids, []),
    ("statut_stream", {"actif": False, "salon_id": "5", "nom_live": "on", "nom_hors_live": "off"},
     lambda d: d.statut_stream.salon_id, None),
    ("bienvenue", {"actif": False, "salon_id": None, "guild_ids": ["2"], "messages": [], "gifs": []},
     lambda d: d.bienvenue.guild_ids, []),
])
def test_desactiver_ecrit_la_forme_que_le_lecteur_attend(module, corps, champ, vide):
    client, config = _client()
    r = client.patch(f"/api/admin/discord/communaute/{module}", json=corps)
    assert r.status_code == 200
    assert champ(config.discord) == vide
    assert r.json()[module]["actif"] is False


@pytest.mark.parametrize(("module", "corps"), [
    ("salons_temporaires", {"actif": True, "salon_createur_id": None, "noms": []}),
    ("salons_temporaires", {"actif": True, "salon_createur_id": "abc", "noms": []}),
    ("journal_moderation", {"actif": True, "salon_ids": [], "guild_ids": ["2"], "inclure_bots": False}),
    ("journal_moderation", {"actif": True, "salon_ids": ["1"], "guild_ids": [], "inclure_bots": False}),
    ("statut_stream", {"actif": True, "salon_id": "5", "nom_live": "", "nom_hors_live": "off"}),
    ("statut_stream", {"actif": True, "salon_id": "5", "nom_live": "x" * 101, "nom_hors_live": "off"}),
    ("bienvenue", {"actif": True, "salon_id": None, "guild_ids": [], "messages": [], "gifs": []}),
    ("bienvenue", {"actif": True, "salon_id": None, "guild_ids": ["2"], "messages": [], "gifs": ["ftp://x"]}),
    ("bienvenue", {"actif": "oui", "salon_id": None, "guild_ids": ["2"], "messages": [], "gifs": []}),
    ("bienvenue", {"actif": True}),
])
def test_un_refus_ne_touche_a_rien(module, corps):
    client, config = _client()
    avant = client.get("/api/admin/discord/communaute").json()
    r = client.patch(f"/api/admin/discord/communaute/{module}", json=corps)
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], str)
    assert client.get("/api/admin/discord/communaute").json() == avant
    config.save.assert_not_called()


def test_salons_speciaux_ecriture_partielle():
    client, config = _client()
    r = client.patch("/api/admin/discord/salons-speciaux", json={
        "always_trigger_channels": [GROS],
        "per_guild_channel_whitelist": {"63": ["7", "8"], "875421531415666698": None},
        "clips_channel_id": "",
        "emote_guild_id": "99",
        "emoji_reaction_probability": 0.2,
    })
    assert r.status_code == 200
    d = config.discord
    assert d.always_trigger_channels == [int(GROS)]
    # Clés en chaînes, valeurs en int : c'est ce que `_is_channel_allowed` compare.
    assert d.per_guild_channel_whitelist == {"63": [7, 8], "875421531415666698": None}
    assert d.clips_channel_id is None
    assert d.emote_guild_id == 99
    assert d.emoji_reaction_probability == 0.2
    assert d.channel_filter_mode == "blacklist"   # absent du corps : intact
    assert r.json()["always_trigger_channels"] == [GROS]
    config.save.assert_called_once()


@pytest.mark.parametrize("corps", [
    {"channel_filter_mode": "none"},
    {"emoji_reaction_probability": 1.5},
    {"emoji_reaction_probability": True},
    {"per_guild_channel_whitelist": {"abc": None}},
    {"always_trigger_channels": ["1"], "meme_channel_id": "x"},
])
def test_salons_speciaux_refus(corps):
    client, config = _client()
    r = client.patch("/api/admin/discord/salons-speciaux", json=corps)
    assert r.status_code == 422
    assert config.discord.always_trigger_channels == [11]
    config.save.assert_not_called()


def test_colere_lecture_ecriture_et_bornes():
    client, config = _client()
    assert client.get("/api/admin/discord/colere").json() == {
        "anger_trigger_threshold": 3, "timeout_minutes": 10}
    r = client.patch("/api/admin/discord/colere", json={"anger_trigger_threshold": 5, "timeout_minutes": 30})
    assert r.status_code == 200
    assert (config.discord.anger_trigger_threshold, config.discord.timeout_minutes) == (5, 30)
    for corps in ({"anger_trigger_threshold": 0}, {"timeout_minutes": 1441},
                  {"timeout_minutes": 2.5}, {"anger_trigger_threshold": True}):
        assert client.patch("/api/admin/discord/colere", json=corps).status_code == 422
    assert (config.discord.anger_trigger_threshold, config.discord.timeout_minutes) == (5, 30)
    config.save.assert_called_once()
