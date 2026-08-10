# tests/test_phase9_twitch.py
"""Phase 9 de l'audit du 2026-08-10 : Twitch.

M5 — `send_message` avalait toutes ses erreurs et l'appelant rendait « helix »
     quoi qu'il arrive : cooldown posé et mémoire enrichie d'une réplique
     jamais publiée.
M6 — `_eventsub_client` n'était référencé qu'après ~15 s de souscriptions :
     toute sortie anticipée laissait des WebSockets vivantes et infermables.
M7 — `!image` et les outils d'overlay pilotables depuis une chaîne invitée.
"""
import inspect

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ────────────────────────────── M5 ──────────────────────────────
def _api():
    from bot.twitch.api import TwitchAPI

    a = TwitchAPI.__new__(TwitchAPI)
    a._tm = MagicMock(bot_token="tok")
    a._tm.refresh = AsyncMock(return_value=False)
    a._client_id = "cid"
    a._bot_id = "bid"
    a._broadcaster_id = "brd"
    return a


@pytest.mark.asyncio
async def test_un_envoi_reussi_le_dit():
    a = _api()
    reponse = MagicMock(status_code=204)
    reponse.raise_for_status = MagicMock()
    client = MagicMock()
    client.post = AsyncMock(return_value=reponse)
    with patch("httpx.AsyncClient") as cm:
        cm.return_value.__aenter__ = AsyncMock(return_value=client)
        cm.return_value.__aexit__ = AsyncMock(return_value=False)
        assert await a.send_message("coucou") is True


@pytest.mark.asyncio
async def test_un_envoi_refuse_le_dit_aussi():
    a = _api()
    reponse = MagicMock(status_code=401)
    client = MagicMock()
    client.post = AsyncMock(return_value=reponse)
    with patch("httpx.AsyncClient") as cm:
        cm.return_value.__aenter__ = AsyncMock(return_value=client)
        cm.return_value.__aexit__ = AsyncMock(return_value=False)
        assert await a.send_message("coucou") is False


@pytest.mark.asyncio
async def test_une_panne_reseau_nest_pas_un_succes():
    a = _api()
    with patch("httpx.AsyncClient", side_effect=OSError("réseau coupé")):
        assert await a.send_message("coucou") is False


@pytest.mark.asyncio
async def test_le_mode_perdu_est_atteignable_sur_helix():
    from bot.twitch.handlers import _envoyer_reponse_twitch

    bot = MagicMock()
    bot._channel_ids = {}                       # chaîne home
    bot.twitch_api.send_message = AsyncMock(return_value=False)

    mode = await _envoyer_reponse_twitch(
        bot, "azrael", "salut", author="a", parent_msg_id=None
    )
    assert mode == "perdu"


def test_une_replique_perdue_nentre_pas_en_memoire():
    from bot.twitch import handlers

    src = inspect.getsource(handlers.handle_message)
    assert 'publie = _send_mode != "perdu"' in src
    # Le message de l'utilisateur, lui, reste mémorisé quoi qu'il arrive.
    i_user = src.index("bot.memory.append_message(channel_id, author, content")
    i_garde = src.index('publie = _send_mode != "perdu"')
    assert i_garde < i_user


# ────────────────────────────── M6 ──────────────────────────────
def test_le_client_eventsub_est_reference_avant_les_souscriptions():
    from bot.twitch import events

    src = inspect.getsource(events.start_eventsub_client)
    i_creation = src.index("client = eventsub.EventSubWSClient(bot)")
    i_ref = src.index("bot._eventsub_client = client")
    i_premiere_sub = src.index("subscriptions: list[tuple[str, object]]")
    assert i_creation < i_ref < i_premiere_sub, "référencé trop tard : client infermable"


# ────────────────────────────── M7 ──────────────────────────────
def test_la_chaine_home_est_celle_qui_nest_pas_enregistree():
    from bot.twitch.handlers import est_chaine_home

    bot = MagicMock()
    bot._channel_ids = {"invitee_a": "1", "invitee_b": "2"}
    assert est_chaine_home(bot, "azrael") is True
    assert est_chaine_home(bot, "invitee_a") is False


@pytest.mark.asyncio
async def test_les_outils_overlay_sont_retires_chez_un_invite():
    from bot.twitch.handlers import build_chat_tools

    bot = MagicMock()
    bot.scrape = None
    bot.apex_api = None
    bot.action_service = None
    bot.tally = None
    bot.predictions = None
    bot.quotes = None
    bot.web_search = None

    with patch("bot.twitch.handlers._overlay_narrator", return_value=MagicMock()):
        chez_invite = await build_chat_tools(bot, overlay=False)
        chez_soi = await build_chat_tools(bot, overlay=True)

    noms = lambda ts: {t["function"]["name"] for t in ts}
    assert not (noms(chez_invite) & {"show_overlay", "cancel_overlay", "show_clip"})
    assert noms(chez_soi) & {"show_overlay", "cancel_overlay", "show_clip"}


@pytest.mark.asyncio
async def test_image_est_refusee_depuis_une_chaine_invitee():
    from bot.twitch.commands import dispatch_command

    bot = MagicMock()
    bot._channel_ids = {"invitee": "42"}
    bot.config.overlay_image.enabled = True
    bot.config.overlay_image.command = "!image"
    bot.db.get_random_gallery_image = AsyncMock(return_value={"id": 1, "username": "x"})

    traite = await dispatch_command(bot, MagicMock(), "!image", "quelqu_un", "invitee")

    assert traite is False, "la commande a été exécutée depuis une chaîne invitée"
    bot.db.get_random_gallery_image.assert_not_awaited()
