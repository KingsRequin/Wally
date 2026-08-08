# tests/test_twitch_events_perception.py
"""Percevoir et répondre sont deux choses distinctes.

Vécu le 2026-08-07 : un raid sur la chaîne d'Azraël, et rien sur l'overlay. La
cause n'était pas l'overlay mais un couplage — `twitch_events.raid.active`
gouverne le message de remerciement automatique dans le chat (« Merci pour les
{amount} bits ! »), désactivé volontairement. Le handler sortait AVANT
d'alimenter le flux du stream, qui est ce qui déclenche la bulle.

Un raid reste un raid, même quand on ne veut pas de message automatique.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.twitch.events import register_events
from tests.test_twitch_events import make_bot


def _handlers(bot):
    """Enregistre les événements et rend {nom: fonction}."""
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


def _raid_payload(raider="sharpylle", viewers=42, chan="azrael_ttv"):
    payload = MagicMock()
    payload.data.raider.name = raider
    payload.data.viewer_count = viewers
    payload.data.reciever.name = chan      # la typo vient de twitchio v2
    return payload


@pytest.mark.asyncio
async def test_un_raid_alimente_le_flux_meme_sans_message_automatique():
    bot = make_bot({"raid": MagicMock(active=False, message="")})
    feed = MagicMock()
    bot.stream_feed = feed
    handlers = _handlers(bot)

    await handlers["event_eventsub_notification_raid"](_raid_payload())

    assert feed.record.called, "le raid n'a pas été perçu"
    assert "raid" in str(feed.record.call_args).lower()
    bot.twitch_api.send_message.assert_not_awaited()   # pas de message auto


@pytest.mark.asyncio
async def test_un_raid_reste_joyeux_meme_sans_message_automatique():
    bot = make_bot({"raid": MagicMock(active=False, message="")})
    bot.stream_feed = MagicMock()
    handlers = _handlers(bot)

    await handlers["event_eventsub_notification_raid"](_raid_payload())

    assert any(c.args and c.args[0] == "joy" for c in bot.emotion.apply_delta.call_args_list)


@pytest.mark.asyncio
async def test_un_abonnement_est_percu_meme_sans_message_automatique():
    bot = make_bot({"sub": MagicMock(active=False, message="")})
    feed = MagicMock()
    bot.stream_feed = feed
    handlers = _handlers(bot)

    payload = MagicMock()
    payload.data.is_gift = False
    payload.data.user.name = "keychka"
    payload.data.broadcaster.name = "azrael_ttv"
    await handlers["event_eventsub_notification_subscription"](payload)

    assert feed.record.called
    bot.twitch_api.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_des_bits_sont_percus_meme_sans_message_automatique():
    bot = make_bot({"bits": MagicMock(active=False, message="")})
    feed = MagicMock()
    bot.stream_feed = feed
    handlers = _handlers(bot)

    payload = MagicMock()
    payload.data.user.name = "projetmnk"
    payload.data.bits = 500
    payload.data.broadcaster.name = "azrael_ttv"
    await handlers["event_eventsub_notification_cheer"](payload)

    assert feed.record.called
    bot.twitch_api.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_le_message_automatique_part_toujours_quand_il_est_actif():
    """La bascule garde son sens : active = Wally remercie dans le chat."""
    bot = make_bot({"raid": MagicMock(active=True, message="raid {username}")})
    bot.stream_feed = MagicMock()
    handlers = _handlers(bot)

    with patch("bot.twitch.events.social._generate_and_send",
               new=AsyncMock()) as envoi:
        await handlers["event_eventsub_notification_raid"](_raid_payload())

    envoi.assert_awaited_once()
