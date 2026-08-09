"""Phase 4 de l'audit : EventSub qui martèle, statut de live mal attribué, ban tardif."""
from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch



# ── La reprise différée ne survit pas au démontage du client ─────────────────
#
# `_retry_failed_subscriptions` capture le client et le token de l'appel qui l'a
# créée, et se réveille jusqu'à 20 min plus tard. Laissée vivante après une
# reconstruction, elle travaille sur un client mort : soit elle se bloque à vie
# sur un `await sub.created` jamais résolu (et les souscriptions différées
# restantes sont perdues), soit twitchio lui ouvre une NOUVELLE WebSocket hors
# de `_eventsub_client` — donc infermable, et pour `channel.chat.message` c'est
# la double réception de `2c035a9` qui revient.

def _bot_avec_tache_de_reprise():
    from bot.twitch.bot import WallyTwitch

    bot = MagicMock(spec=WallyTwitch)
    bot._eventsub_retry_task = None
    return bot


async def test_cancel_retry_task_annule_la_reprise_en_vol():
    from bot.twitch.events import cancel_retry_task

    bot = _bot_avec_tache_de_reprise()

    async def _dort_longtemps():
        await asyncio.sleep(3600)

    bot._eventsub_retry_task = asyncio.create_task(_dort_longtemps())
    await asyncio.sleep(0)

    assert cancel_retry_task(bot) is True
    await asyncio.sleep(0)
    assert bot._eventsub_retry_task is None


async def test_cancel_retry_task_est_inoffensif_sans_tache():
    from bot.twitch.events import cancel_retry_task

    assert cancel_retry_task(_bot_avec_tache_de_reprise()) is False


def test_le_redemarrage_annule_la_reprise_avant_de_fermer():
    """L'ordre compte : annuler APRÈS la fermeture laisserait une fenêtre où la
    reprise atterrit sur des sockets déjà morts."""
    from bot.twitch.bot import WallyTwitch

    source = inspect.getsource(WallyTwitch._do_restart_eventsub)
    assert "cancel_retry_task(self)" in source
    assert source.index("cancel_retry_task(self)") < source.index("_pump_task")
    assert "_sockets.clear()" in source


def test_larret_du_bot_annule_aussi_la_reprise():
    from bot.twitch.events import close_eventsub_client

    assert "cancel_retry_task(bot)" in inspect.getsource(close_eventsub_client)


# ── Le watchdog recule au lieu de marteler ───────────────────────────────────
#
# `start_eventsub_client` pose `_eventsub_client` même quand les 9 souscriptions
# ont échoué. Le watchdog voyait alors 0, relançait, échouait à l'identique, et
# repartait 60 s plus tard — indéfiniment, en martelant justement la ressource
# dont le budget se recharge en MINUTES, donc en empêchant la recharge qui
# l'aurait débloqué. Et chaque tour laissait une reprise différée de plus.

def _bot_watchdog(actifs: int | None):
    from bot.twitch.bot import WallyTwitch

    bot = MagicMock()
    bot._eventsub_restart_pending = False
    bot._eventsub_restart_lock = asyncio.Lock()
    bot._eventsub_zero_readings = 0
    bot._eventsub_failed_restarts = 0
    bot._eventsub_last_restart_at = 0.0
    bot.token_manager.bot_token = "tok"
    bot._restart_eventsub = AsyncMock()
    bot._check_eventsub_alive = WallyTwitch._check_eventsub_alive.__get__(bot)
    return bot


async def test_une_seule_lecture_a_zero_ne_declenche_rien():
    """Une reconstruction dure ~15 s et passe elle-même par zéro souscription."""
    bot = _bot_watchdog(0)
    with patch("bot.twitch.events.count_active_subscriptions", AsyncMock(return_value=0)):
        await bot._check_eventsub_alive()

    bot._restart_eventsub.assert_not_awaited()
    assert bot._eventsub_zero_readings == 1


async def test_deux_lectures_a_zero_declenchent_une_relance():
    bot = _bot_watchdog(0)
    with patch("bot.twitch.events.count_active_subscriptions", AsyncMock(return_value=0)):
        await bot._check_eventsub_alive()
        await bot._check_eventsub_alive()

    bot._restart_eventsub.assert_awaited_once()
    assert bot._eventsub_failed_restarts == 1     # relance sans effet


async def test_une_relance_sans_effet_impose_un_recul():
    """Sans backoff, le tour suivant relançait 60 s plus tard, sans fin."""
    bot = _bot_watchdog(0)
    with patch("bot.twitch.events.count_active_subscriptions", AsyncMock(return_value=0)):
        for _ in range(6):
            await bot._check_eventsub_alive()

    # Une seule relance : les suivantes tombent dans la fenêtre de recul.
    assert bot._restart_eventsub.await_count == 1


async def test_un_service_rendu_efface_lhistorique_dechecs():
    bot = _bot_watchdog(0)
    bot._eventsub_failed_restarts = 3
    bot._eventsub_zero_readings = 5
    with patch("bot.twitch.events.count_active_subscriptions", AsyncMock(return_value=7)):
        await bot._check_eventsub_alive()

    assert bot._eventsub_failed_restarts == 0
    assert bot._eventsub_zero_readings == 0


async def test_une_sonde_muette_ne_compte_pas_comme_un_zero():
    bot = _bot_watchdog(None)
    with patch("bot.twitch.events.count_active_subscriptions", AsyncMock(return_value=None)):
        await bot._check_eventsub_alive()

    bot._restart_eventsub.assert_not_awaited()
    assert bot._eventsub_zero_readings == 0


# ── Le live de la maison n'est pas celui des invités ─────────────────────────

def _bot_situation(live: bool):
    bot = MagicMock()
    bot._stream_info = {
        "live": live, "category": "Apex Legends",
        "title": "on grind", "viewers": 42,
    }
    bot._channel_ids = {"un_invite": "999"}
    return bot


def test_le_statut_du_live_maison_ne_fuit_pas_chez_un_invite(monkeypatch):
    """Wally affirmait au chat d'une chaîne invitée le jeu, le titre et les
    viewers du live d'Azraël — des faits sur un AUTRE stream."""
    monkeypatch.delenv("TWITCH_BOT_NICK", raising=False)
    from bot.twitch.handlers import _build_situation

    chez_invite = _build_situation(_bot_situation(live=True), "un_invite")
    assert "stream_live" not in chez_invite
    assert "stream_title" not in chez_invite

    chez_soi = _build_situation(_bot_situation(live=True), "azrael_ttv")
    assert chez_soi["stream_live"] is True
    assert chez_soi["stream_viewers"] == 42


# ── Le ban s'applique avant les commandes ────────────────────────────────────

def test_le_filtre_de_ban_precede_dispatch_command():
    """En aval, un banni gardait `!image` — donc l'affichage d'une image sur
    l'overlay du live, annoncée dans le chat — et `!mood`."""
    import bot.twitch.handlers as h

    source = inspect.getsource(h)
    assert source.index("is_chat_user_banned") < source.index("await dispatch_command(")


# ── Le resub porte son type ──────────────────────────────────────────────────

def test_le_resub_transmet_son_type_au_flux():
    """Sans `kind`, l'overlay retombait sur le socle générique et réactivait la
    détection par mots-clés que `44108b5` avait remplacée par le typage."""
    from pathlib import Path

    from bot.intelligence.overlay_narrator import _EVENT_KINDS, _STRONG_EVENT_KINDS

    assert "resub" in _EVENT_KINDS
    assert "resub" in _STRONG_EVENT_KINDS
    assert 'kind="resub"' in Path("bot/twitch/events/social.py").read_text(encoding="utf-8")


def test_chaque_type_fort_a_son_registre_dans_events_md():
    """Un type sans section produit une directive vide, donc le socle générique."""
    from bot.intelligence.persona import PersonaService

    sections = PersonaService._parse_sections(
        MagicMock(_dir="bot/persona"), "EVENTS.md"
    )
    from bot.intelligence.overlay_narrator import _EVENT_KINDS

    # `audience` est émis en notify=False : il ne produit jamais de bulle.
    attendus = {k for k in _EVENT_KINDS if k != "audience"}
    assert attendus <= set(sections), sorted(attendus - set(sections))


# ── Un statut « inconnu » n'est pas mis en cache comme un hors-ligne ─────────

async def test_le_dashboard_ne_fige_pas_un_statut_inconnu():
    """`_UNKNOWN_STREAM` porte `live: False` : mis en cache, il faisait basculer
    le TTL sur celui du hors-ligne et figeait l'affichage 5 MINUTES en plein
    live, pour une coupure réseau d'une seconde."""
    from bot.dashboard.routes import twitch as route

    route._cache.update({"data": None, "fetched_at": 0.0, "is_live": False})

    request = MagicMock()
    request.app.state.wally.twitch_api.get_stream = AsyncMock(
        return_value={"live": True, "title": "on grind", "category": "Apex",
                      "viewers": 42, "started_at": "2026-08-09T00:00:00Z"}
    )
    assert (await route.get_stream_status(request))["live"] is True

    # L'API devient muette : le dernier statut CONNU est rendu, rien n'est figé.
    request.app.state.wally.twitch_api.get_stream = AsyncMock(
        return_value={"live": False, "title": None, "category": None,
                      "viewers": 0, "started_at": None, "unknown": True}
    )
    route._cache["fetched_at"] = 0.0          # force l'expiration du TTL
    encore = await route.get_stream_status(request)

    assert encore["live"] is True
    assert route._cache["is_live"] is True    # le cache n'a PAS basculé
