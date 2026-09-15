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
    bot.twitch_api.send_automatic.assert_not_awaited()   # pas de message auto


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
    bot.twitch_api.send_automatic.assert_not_awaited()


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
    bot.twitch_api.send_automatic.assert_not_awaited()


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


# ── shoutout automatique du raideur ─────────────────────────────────────────
# Lancé en tâche de fond via `_fire` : ces tests le remplacent par un mouchard
# qui capture la coroutine SANS la lancer, puis l'attendent explicitement —
# ça prouve à la fois ce qu'elle fait ET qu'elle ne bloque pas le handler.

async def _declenche_et_attend_shoutout(bot, payload):
    """Enregistre les handlers, déclenche le raid, attend le geste de fond
    (s'il a été lancé) pour pouvoir l'asserter."""
    handlers = _handlers(bot)
    captured: dict = {}
    with patch("bot.twitch.events.social._fire",
               lambda coro: captured.__setitem__("coro", coro)):
        await handlers["event_eventsub_notification_raid"](payload)
    if "coro" in captured:
        await captured["coro"]


@pytest.mark.asyncio
async def test_le_raid_declenche_le_shoutout_avec_l_id_du_raideur_meme_sans_message_auto():
    bot = make_bot({"raid": MagicMock(active=False, message="")})
    bot.stream_feed = MagicMock()
    bot.config.twitch.shoutout_raid = True
    bot.twitch_api.shoutout_statut = AsyncMock(return_value=(204, ""))
    payload = _raid_payload()
    payload.data.raider.id = "999"

    await _declenche_et_attend_shoutout(bot, payload)

    bot.twitch_api.shoutout_statut.assert_awaited_once_with("999")


@pytest.mark.asyncio
async def test_shoutout_raid_desactive_n_appelle_pas_l_api():
    bot = make_bot({"raid": MagicMock(active=False, message="")})
    bot.stream_feed = MagicMock()
    bot.config.twitch.shoutout_raid = False
    bot.twitch_api.shoutout_statut = AsyncMock(return_value=(204, ""))
    payload = _raid_payload()
    payload.data.raider.id = "999"

    await _declenche_et_attend_shoutout(bot, payload)

    bot.twitch_api.shoutout_statut.assert_not_awaited()


@pytest.mark.asyncio
async def test_shoutout_publie_se_rappelle_via_note_act():
    bot = make_bot({"raid": MagicMock(active=False, message="")})
    bot.stream_feed = MagicMock()
    bot.config.twitch.shoutout_raid = True
    bot.twitch_api.shoutout_statut = AsyncMock(return_value=(204, ""))
    payload = _raid_payload(raider="sharpylle")
    payload.data.raider.id = "999"

    with patch("bot.twitch.events.social.note_act") as note_act_mock:
        await _declenche_et_attend_shoutout(bot, payload)

    note_act_mock.assert_called_once()
    assert "sharpylle" in note_act_mock.call_args.args[0]


@pytest.mark.asyncio
async def test_le_cooldown_natif_est_une_information_pas_une_panne():
    """429/400 = Twitch fait son travail, pas Wally qui a raté le sien."""
    bot = make_bot({"raid": MagicMock(active=False, message="")})
    bot.stream_feed = MagicMock()
    bot.config.twitch.shoutout_raid = True
    bot.twitch_api.shoutout_statut = AsyncMock(
        return_value=(429, "c'est trop tôt."))
    payload = _raid_payload()
    payload.data.raider.id = "999"

    # Isole le WARNING du contexte du raideur (hors sujet ici, cf.
    # `_contexte_raideur`) de celui du shoutout, seul ce que ce test vérifie.
    with patch("bot.twitch.events.social._contexte_raideur",
               new=AsyncMock(return_value="")), \
         patch("bot.twitch.events.social.note_act") as note_act_mock, \
         patch("bot.twitch.events.social.logger") as logger_mock:
        await _declenche_et_attend_shoutout(bot, payload)

    note_act_mock.assert_not_called()
    logger_mock.info.assert_called()
    logger_mock.warning.assert_not_called()


@pytest.mark.asyncio
async def test_un_403_est_une_vraie_panne_en_warning():
    bot = make_bot({"raid": MagicMock(active=False, message="")})
    bot.stream_feed = MagicMock()
    bot.config.twitch.shoutout_raid = True
    bot.twitch_api.shoutout_statut = AsyncMock(
        return_value=(403, "je ne suis pas modérateur de la chaîne, je ne peux pas faire de shoutout."))
    payload = _raid_payload()
    payload.data.raider.id = "999"

    with patch("bot.twitch.events.social.note_act") as note_act_mock, \
         patch("bot.twitch.events.social.logger") as logger_mock:
        await _declenche_et_attend_shoutout(bot, payload)

    note_act_mock.assert_not_called()
    logger_mock.warning.assert_called()


@pytest.mark.asyncio
async def test_une_exception_de_l_api_ne_remonte_pas_et_le_flux_passif_a_tourne():
    """Le geste automatique ne casse jamais le handler qui l'a déclenché."""
    bot = make_bot({"raid": MagicMock(active=False, message="")})
    feed = MagicMock()
    bot.stream_feed = feed
    bot.config.twitch.shoutout_raid = True
    bot.twitch_api.shoutout_statut = AsyncMock(side_effect=RuntimeError("boom"))
    payload = _raid_payload()
    payload.data.raider.id = "999"

    await _declenche_et_attend_shoutout(bot, payload)   # ne doit pas lever

    assert feed.record.called, "le flux passif doit avoir tourné malgré l'échec du shoutout"


@pytest.mark.asyncio
async def test_le_shoutout_ne_bloque_pas_le_handler_du_raid():
    """Une API qui attend un `asyncio.Event` jamais libéré n'empêche pas le
    handler de finir : `_fire` (réel, pas simulé ici) part en tâche de fond."""
    import asyncio

    bot = make_bot({"raid": MagicMock(active=False, message="")})
    bot.stream_feed = MagicMock()
    bot.config.twitch.shoutout_raid = True
    jamais_libere = asyncio.Event()

    async def _bloque(*_a, **_kw):
        await jamais_libere.wait()
        return (204, "")

    bot.twitch_api.shoutout_statut = AsyncMock(side_effect=_bloque)
    handlers = _handlers(bot)
    payload = _raid_payload()
    payload.data.raider.id = "999"

    await asyncio.wait_for(
        handlers["event_eventsub_notification_raid"](payload), timeout=1,
    )
