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


# ── Le vocal : le clip passe par les outils TWITCH ────────────────────────
#
# Pendant un live, Wally est en ÉCOUTE SEULE : `_on_transcript` s'arrête à
# `_observe_transcript`, et `build_voice_tools()` n'est jamais consulté. « Wally
# clippe ça » dit à voix haute passe par `voice/request.py`, qui emprunte
# `build_chat_tools` du chemin TWITCH et répond dans le chat, lien compris.
#
# Rien à brancher sur `build_voice_tools()`, donc : ce catalogue sert la
# CONVERSATION vocale, et Azraël ne stream pas pendant qu'il discute en vocal —
# l'outil n'y aboutirait jamais (arbitrage owner du 2026-09-01). Un outil qui ne
# peut pas aboutir est un bouton branché sur rien.


async def test_la_demande_orale_emprunte_les_outils_twitch():
    """Le seul chemin vocal qui clippe. S'il perdait `create_clip`, « wally
    clippe ça » dit en direct ne ferait plus rien — sans erreur, sans log."""
    from tests.test_parite_plateformes import _bot_avec_tout, _noms
    from bot.twitch.handlers import build_chat_tools

    assert "create_clip" in _noms(await build_chat_tools(_bot_avec_tout()))


async def test_la_conversation_vocale_ne_propose_PAS_de_clipper():
    """Volontaire, et non un oubli : hors live l'outil ne peut qu'échouer."""
    from tests.test_parite_plateformes import _bot_avec_tout, _noms
    from bot.discord.voice.tools import build_voice_tools

    assert "create_clip" not in _noms(await build_voice_tools(_bot_avec_tout()))
