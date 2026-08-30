"""Un raid n'est plus un pseudo et un compteur.

`_celebrate_raid` posait des confettis avec un nom et un nombre de spectateurs,
et c'était tout ce que Wally savait de celui qui lui amène des inconnus. C'est
le moment le plus social d'un stream.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.twitch.events import register_events
from bot.twitch.events.social import _contexte_raideur
from tests.test_twitch_events import make_bot


def _handlers(bot):
    captured = {}

    def _event():
        def deco(fn):
            captured[fn.__name__] = fn
            return fn
        return deco

    bot.event = _event
    with patch("bot.twitch.events.social._check_peak"):
        register_events(bot)
    return captured


def _raid_payload(raider="sharpylle", raider_id="777", viewers=42, chan="azrael_ttv"):
    payload = MagicMock()
    payload.data.raider.name = raider
    payload.data.raider.id = raider_id
    payload.data.viewer_count = viewers
    payload.data.reciever.name = chan      # la typo vient de twitchio v2
    return payload


# ── La clause elle-même ───────────────────────────────────────────────────


async def test_jeu_et_titre_sont_rendus():
    bot = MagicMock()
    bot.twitch_api.get_channel_info = AsyncMock(
        return_value={"game_name": "Apex Legends", "title": "run ranked", "tags": []}
    )

    assert await _contexte_raideur(bot, "777") == (
        "il streamait Apex Legends, sous le titre « run ranked »"
    )


async def test_un_titre_seul_se_dit_quand_meme():
    bot = MagicMock()
    bot.twitch_api.get_channel_info = AsyncMock(
        return_value={"game_name": "", "title": "chill", "tags": []}
    )

    assert await _contexte_raideur(bot, "777") == "sous le titre « chill »"


async def test_titre_d_inconnu_est_borne():
    """Le titre est écrit par quelqu'un qu'on ne contrôle pas."""
    bot = MagicMock()
    bot.twitch_api.get_channel_info = AsyncMock(
        return_value={"game_name": "", "title": "x" * 400, "tags": []}
    )

    assert len(await _contexte_raideur(bot, "777")) < 160


@pytest.mark.parametrize("reponse", [None, {}, {"game_name": "", "title": ""}])
async def test_api_muette_ne_dit_rien_plutot_que_n_importe_quoi(reponse):
    bot = MagicMock()
    bot.twitch_api.get_channel_info = AsyncMock(return_value=reponse)

    assert await _contexte_raideur(bot, "777") == ""


async def test_api_en_panne_ne_fait_pas_tomber_le_raid():
    bot = MagicMock()
    bot.twitch_api.get_channel_info = AsyncMock(side_effect=RuntimeError("réseau"))

    assert await _contexte_raideur(bot, "777") == ""


async def test_sans_identifiant_aucune_requete():
    bot = MagicMock()
    bot.twitch_api.get_channel_info = AsyncMock()

    assert await _contexte_raideur(bot, "") == ""
    bot.twitch_api.get_channel_info.assert_not_awaited()


# ── Le câblage dans l'événement ───────────────────────────────────────────


async def test_le_flux_du_stream_porte_le_contexte():
    """Message automatique coupé — le réglage d'aujourd'hui : la perception
    passive est le SEUL chemin par lequel Wally peut en parler."""
    bot = make_bot({"raid": MagicMock(active=False, message="")})
    bot.stream_feed = MagicMock()
    bot.twitch_api.get_channel_info = AsyncMock(
        return_value={"game_name": "Apex Legends", "title": "run ranked", "tags": []}
    )
    handlers = _handlers(bot)

    await handlers["event_eventsub_notification_raid"](_raid_payload())

    trace = bot.stream_feed.record.call_args[0][0]
    assert "sharpylle" in trace and "42" in trace
    assert "Apex Legends" in trace


async def test_les_confettis_partent_avant_le_reseau():
    """L'accueil à l'écran ne doit pas attendre une requête HTTP : les
    arrivants seraient déjà là."""
    ordre = []
    bot = make_bot({"raid": MagicMock(active=False, message="")})
    bot.stream_feed = MagicMock()

    async def _lente(_id):
        ordre.append("api")
        return {"game_name": "Apex Legends", "title": "", "tags": []}

    bot.twitch_api.get_channel_info = _lente
    handlers = _handlers(bot)

    with patch("bot.twitch.events.social._celebrate_raid",
               side_effect=lambda *a, **k: ordre.append("overlay")):
        await handlers["event_eventsub_notification_raid"](_raid_payload())

    assert ordre == ["overlay", "api"]


async def test_le_gabarit_recoit_le_contexte():
    bot = make_bot({"raid": MagicMock(active=True, message="raid {username} : {contexte}")})
    bot.stream_feed = MagicMock()
    bot.twitch_api.get_channel_info = AsyncMock(
        return_value={"game_name": "Apex Legends", "title": "", "tags": []}
    )
    handlers = _handlers(bot)

    await handlers["event_eventsub_notification_raid"](_raid_payload())

    envoye = str(bot.llm.complete.call_args)
    assert "il streamait Apex Legends" in envoye


# ── get_channel_info : trois retours distincts ────────────────────────────


def _api():
    from bot.twitch.api import TwitchAPI

    tm = MagicMock()
    tm.bot_token = "tok"
    tm.refresh = AsyncMock(return_value=True)
    return TwitchAPI(token_manager=tm, client_id="cid", bot_id="bot", broadcaster_id="maison")


async def test_get_channel_info_vise_la_chaine_demandee_pas_la_maison():
    api = _api()
    with patch.object(type(api), "_get_json", AsyncMock(return_value={"data": [
        {"game_name": "Apex Legends", "title": "run", "tags": ["FR"]}
    ]})) as get_json:
        infos = await api.get_channel_info("777")

    assert get_json.await_args[0][1] == {"broadcaster_id": "777"}
    assert infos == {"game_name": "Apex Legends", "title": "run", "tags": ["FR"]}


async def test_get_channel_info_distingue_api_muette_et_chaine_inconnue():
    api = _api()
    with patch.object(type(api), "_get_json", AsyncMock(return_value=None)):
        assert await api.get_channel_info("777") is None
    with patch.object(type(api), "_get_json", AsyncMock(return_value={"data": []})):
        assert await api.get_channel_info("777") == {}
