"""Un clip se retrouve SANS overlay — hors live, et depuis Discord.

Relevé dans les traces : « wally tu peut afficher le dernier clip fait pas
azra » → « Je peux pas lancer de clip, on est pas en live ». La demande ne
réclamait pas d'écran, seulement de savoir lequel c'était. L'API savait déjà
tout faire seule (`get_last_clip`, `find_clip`, `get_top_clips`) : le narrateur
n'était qu'un intermédiaire, et son absence emportait la réponse avec elle.

C'est le même arbitrage que `show_planning`, déjà rendu dans ce dépôt : ce qui
rend un LIEN s'offre sans condition d'écran.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.discord.handlers import run_last_clip_tool

_CLIP = {"title": "Kraber Party", "creator_name": "Lolofun", "view_count": 42,
         "url": "https://clips.twitch.tv/KraberParty"}


def _bot(*, narrateur=None, **api_kw):
    api = SimpleNamespace(
        get_last_clip=AsyncMock(return_value=api_kw.get("dernier")),
        find_clip=AsyncMock(return_value=api_kw.get("trouve")),
        get_top_clips=AsyncMock(return_value=api_kw.get("tops", [])),
    )
    return SimpleNamespace(twitch_api=api, _overlay_narrator=narrateur), api


def _narrateur(actif: bool):
    n = MagicMock()
    n.is_active.return_value = actif
    n.play_last_clip = AsyncMock(return_value={"title": "X", "author": "Y", "played": True})
    return n


# `_overlay_narrator` lit un attribut précis du bot : on le simule par monkeypatch
# plutôt que d'imiter toute la chaîne de montage.
@pytest.fixture
def sans_overlay(monkeypatch):
    monkeypatch.setattr("bot.discord.handlers._overlay_narrator", lambda _b: None)


@pytest.fixture
def overlay_eteint(monkeypatch):
    monkeypatch.setattr("bot.discord.handlers._overlay_narrator",
                        lambda _b: _narrateur(actif=False))


async def test_hors_live_le_dernier_clip_revient_en_texte(overlay_eteint):
    """Le cas exact des traces : plus de refus, un lien."""
    bot, api = _bot(dernier=_CLIP)
    out = json.loads(await run_last_clip_tool(bot, {}))
    assert out["status"] == "texte"
    assert "Kraber Party" in out["message"]
    assert "https://clips.twitch.tv/KraberParty" in out["message"]
    # Ne JAMAIS laisser croire à un affichage : il n'y a pas d'écran.
    assert "ne dis PAS que tu l'as affiché" in out["message"]
    api.get_last_clip.assert_awaited_once()


async def test_depuis_discord_sans_overlay_du_tout(sans_overlay):
    """Discord n'a jamais d'overlay — c'est pourtant là qu'on demande le plus."""
    bot, _ = _bot(dernier=_CLIP)
    out = json.loads(await run_last_clip_tool(bot, {}))
    assert out["status"] == "texte"


async def test_recherche_par_titre_sans_ecran(overlay_eteint):
    bot, api = _bot(trouve=_CLIP)
    out = json.loads(await run_last_clip_tool(bot, {"mode": "titre", "query": "kraber"}))
    assert out["status"] == "texte"
    api.find_clip.assert_awaited_once_with("kraber", days=30)


async def test_plus_vu_sans_ecran(overlay_eteint):
    bot, api = _bot(tops=[_CLIP])
    out = json.loads(await run_last_clip_tool(bot, {"mode": "plus_vu"}))
    assert out["status"] == "texte"
    api.get_top_clips.assert_awaited_once_with(days=30, first=1)


async def test_podium_sans_ecran(overlay_eteint):
    bot, _ = _bot(tops=[_CLIP, dict(_CLIP, title="Autre")])
    out = json.loads(await run_last_clip_tool(bot, {"mode": "top"}))
    assert out["status"] == "texte"
    assert "Kraber Party" in out["message"] and "Autre" in out["message"]


async def test_le_podium_reste_plafonne_a_cinq(overlay_eteint):
    """Le plafond existait sur le chemin écran ; le repli ne doit pas l'ouvrir."""
    bot, api = _bot(tops=[_CLIP])
    await run_last_clip_tool(bot, {"mode": "top", "count": 99})
    assert api.get_top_clips.await_args.kwargs["first"] == 5


async def test_aucun_clip_du_clippeur_ne_se_dit_pas_aucun_clip(overlay_eteint):
    """Distinguer les deux vides : la chaîne peut avoir des clips, pas lui."""
    bot, _ = _bot(dernier=None)
    out = json.loads(await run_last_clip_tool(bot, {"author": "azra"}))
    assert out["status"] == "nothing"
    assert "azra" in out["message"]


async def test_api_absente_ne_leve_pas(sans_overlay):
    out = json.loads(await run_last_clip_tool(SimpleNamespace(), {}))
    assert out["status"] == "unavailable"


async def test_l_ecran_garde_la_priorite_quand_il_est_actif(monkeypatch):
    """Pendant un live, la vidéo part sur l'overlay — le repli ne le vole pas."""
    n = _narrateur(actif=True)
    monkeypatch.setattr("bot.discord.handlers._overlay_narrator", lambda _b: n)
    bot, api = _bot(dernier=_CLIP)
    out = json.loads(await run_last_clip_tool(bot, {}))
    assert out["status"] == "ok"
    n.play_last_clip.assert_awaited_once()
    api.get_last_clip.assert_not_awaited()


# ── Le catalogue : l'outil doit SORTIR même sans overlay ────────────────────

async def test_offert_hors_live_des_deux_cotes():
    from bot.discord.handlers import build_chat_tools as outils_discord
    from bot.twitch.handlers import build_chat_tools as outils_twitch

    # Aucun overlay branché, mais l'API Twitch est là : c'est la situation
    # ordinaire hors live, et celle de Discord en permanence.
    nu = SimpleNamespace(
        config=SimpleNamespace(bot=SimpleNamespace(owner_discord_id="1")),
        twitch_api=object(),
    )
    d = {t["function"]["name"] for t in await outils_discord(nu, author_id="42")}
    t = {t["function"]["name"] for t in await outils_twitch(nu, overlay=True)}
    assert "show_clip" in d
    assert "show_clip" in t


async def test_pas_offert_chez_une_chaine_invitee():
    """Les clips sont ceux d'Azraël : les proposer ailleurs répond à côté."""
    from bot.twitch.handlers import build_chat_tools as outils_twitch

    nu = SimpleNamespace(
        config=SimpleNamespace(bot=SimpleNamespace(owner_discord_id="1")),
        twitch_api=object(),
    )
    noms = {t["function"]["name"] for t in await outils_twitch(nu, overlay=False)}
    assert "show_clip" not in noms


def test_la_description_ne_promet_plus_un_ecran_obligatoire():
    """La description pilote l'appel : tant qu'elle dit « affiche sur
    l'overlay », le modèle continue de refuser hors live sans même essayer."""
    from bot.intelligence.overlay_narrator import LAST_CLIP_TOOL_SPEC

    desc = LAST_CLIP_TOOL_SPEC["function"]["description"]
    assert "hors live" in desc
    assert "n'est plus une raison de refuser" in desc
