"""Clipper le live à la demande — `POST /helix/clips` avec titre et durée.

Arbitrages de l'owner du 2026-09-01 : ouvert à TOUT LE MONDE, cooldown de
deux minutes pour la CHAÎNE (la fenêtre de capture de Twitch fait ~90 s, deux
clips plus rapprochés racontent le même moment).
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

import bot.tools.clip_tool as clip_tool
from bot.tools.clip_tool import CLIP_TOOL, run_clip_tool


@pytest.fixture(autouse=True)
def _cooldown_neuf():
    """Le cooldown est un état de MODULE : sans remise à zéro, le premier test
    qui clippe ferait échouer tous les suivants."""
    clip_tool._dernier_clip_a = 0.0
    yield
    clip_tool._dernier_clip_a = 0.0


def _bot(clip=None):
    b = MagicMock()
    b.twitch_api = MagicMock()
    b.twitch_api.CLIP_DUREE_MAX_S = 60
    b.twitch_api.create_clip = AsyncMock(return_value=clip)
    return b


async def test_le_clip_rend_son_url():
    b = _bot({"url": "https://clips.twitch.tv/Abc", "title": "kill au wingman"})
    rendu = json.loads(await run_clip_tool(b, {"title": "kill au wingman",
                                               "duration": 40}))
    assert rendu["status"] == "ok"
    assert rendu["url"] == "https://clips.twitch.tv/Abc"
    b.twitch_api.create_clip.assert_awaited_once_with("kill au wingman", 40)


async def test_un_second_clip_dans_les_deux_minutes_est_refuse():
    b = _bot({"url": "https://clips.twitch.tv/Abc"})
    assert json.loads(await run_clip_tool(b, {}))["status"] == "ok"

    rendu = json.loads(await run_clip_tool(b, {}))
    assert rendu["status"] == "cooldown"
    assert rendu["reste_s"] > 0
    # Un seul appel à l'API : le refus se décide AVANT de créer quoi que ce soit.
    assert b.twitch_api.create_clip.await_count == 1


async def test_un_echec_ne_consomme_pas_le_cooldown():
    """Sinon une panne de deux minutes se transforme en quatre."""
    b = _bot(None)
    assert json.loads(await run_clip_tool(b, {}))["status"] == "failed"

    b.twitch_api.create_clip = AsyncMock(return_value={"url": "https://c/1"})
    assert json.loads(await run_clip_tool(b, {}))["status"] == "ok"


async def test_une_demande_trop_longue_est_bornee_et_DITE():
    """« clippe les 2 dernières minutes » : Twitch n'en sait faire que 60 s."""
    b = _bot({"url": "https://clips.twitch.tv/Abc"})
    rendu = json.loads(await run_clip_tool(b, {"duration": 120}))
    assert rendu["status"] == "ok"
    assert rendu["duree_reelle_s"] == 60
    assert "60" in rendu["message"]


async def test_sans_api_twitch_il_le_dit_au_lieu_de_promettre():
    b = MagicMock()
    b.twitch_api = None
    b._twitch_bot = None
    assert json.loads(await run_clip_tool(b, {}))["status"] == "unavailable"


async def test_l_echec_interdit_explicitement_d_inventer_une_url():
    """Un `{"status": "error"}` nu laisse le modèle broder — souvent qu'il ne
    sait pas faire."""
    rendu = json.loads(await run_clip_tool(_bot(None), {}))
    assert "URL" in rendu["message"]


def test_l_outil_annonce_les_bornes_de_duree_au_modele():
    params = CLIP_TOOL["function"]["parameters"]["properties"]
    assert "5" in params["duration"]["description"]
    assert "60" in params["duration"]["description"]


# ── Le vocal : le troisième chemin ────────────────────────────────────────
#
# Azraël JOUE pendant qu'il parle : « wally clippe ça » se dit à voix haute
# bien plus souvent qu'il ne s'écrit. L'outil est né le 2026-09-01 branché sur
# Discord et Twitch seulement — le chemin vocal ne le proposait pas, et un
# outil absent du catalogue manque EN SILENCE (précédent du 2026-08-25 :
# trois refus muets en direct avant qu'on le remarque).


async def test_a_la_voix_l_url_n_est_PAS_dictee():
    """Une URL de clip lue à voix haute (« h-t-t-p-s deux-points… ») est
    inutilisable : personne ne la retient. On la retire du rendu plutôt que de
    compter sur le modèle pour se retenir de la lire."""
    b = _bot({"url": "https://clips.twitch.tv/Abc", "title": "le wingman"})
    rendu = json.loads(await run_clip_tool(b, {"title": "le wingman"}, vocal=True))

    assert rendu["status"] == "ok"
    assert "url" not in rendu, "l'URL est là : le modèle va l'épeler à voix haute"
    assert "clips.twitch.tv" not in json.dumps(rendu)
    assert rendu["title"] == "le wingman"


async def test_le_clip_reste_cree_pour_de_vrai_a_la_voix():
    """Le rendu change, pas le geste : c'est le MÊME appel Twitch."""
    b = _bot({"url": "https://clips.twitch.tv/Abc"})
    assert json.loads(await run_clip_tool(b, {"duration": 40}, vocal=True))["status"] == "ok"
    b.twitch_api.create_clip.assert_awaited_once_with("", 40)


async def test_clipper_est_offert_sur_les_TROIS_chemins():
    from tests.test_parite_plateformes import _bot_avec_tout, _noms
    from bot.discord.handlers import build_chat_tools as discord
    from bot.discord.voice.tools import build_voice_tools as vocal
    from bot.twitch.handlers import build_chat_tools as twitch

    assert "create_clip" in _noms(await discord(_bot_avec_tout(), author_id="42"))
    assert "create_clip" in _noms(await twitch(_bot_avec_tout()))
    assert "create_clip" in _noms(await vocal(_bot_avec_tout())), (
        "« clippe ça » dit à voix haute pendant qu'il joue : c'est l'endroit "
        "le plus naturel de la demande, et le seul où l'outil manquait."
    )
