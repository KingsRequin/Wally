# tests/test_twitch_token_refresh.py
"""Tests pour le refresh périodique de token Twitch + restart EventSub conditionnel.

Régression : à chaque cycle de refresh, l'ancien code relançait TOUT l'EventSub
(_restart_eventsub) même quand le token n'avait pas changé, provoquant des 429
Ratelimit Reached et des tracebacks twitchio non gérés très bruyants.

Le restart ne doit avoir lieu QUE si un token a réellement changé.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


def make_twitch_bot():
    """Retourne un WallyTwitch minimal mocké pour les tests de refresh."""
    from bot.twitch.bot import WallyTwitch
    bot = object.__new__(WallyTwitch)
    bot.token_manager = MagicMock()
    bot.token_manager.startup_validate = AsyncMock()
    # Valeurs de token par défaut (inchangées) — properties simples
    bot.token_manager.bot_token = "bot_tok"
    bot.token_manager.streamer_token = "streamer_tok"
    return bot


@pytest.mark.asyncio
async def test_refresh_no_token_change_skips_eventsub_restart():
    """Token inchangé après validation → PAS de _restart_eventsub (source du 429)."""
    bot = make_twitch_bot()
    bot._restart_eventsub = AsyncMock()

    await bot._refresh_tokens_and_maybe_restart_eventsub()

    bot.token_manager.startup_validate.assert_awaited_once()
    bot._restart_eventsub.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_bot_token_change_triggers_eventsub_restart():
    """Token bot changé → _restart_eventsub appelé pour prendre le nouveau token."""
    bot = make_twitch_bot()
    bot._restart_eventsub = AsyncMock()

    # startup_validate rote le bot_token (comme un 401 déclenchant refresh)
    async def _rotate():
        bot.token_manager.bot_token = "bot_tok_NEW"

    bot.token_manager.startup_validate = AsyncMock(side_effect=_rotate)

    await bot._refresh_tokens_and_maybe_restart_eventsub()

    bot._restart_eventsub.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_streamer_token_change_triggers_eventsub_restart():
    """Token streamer changé → _restart_eventsub appelé."""
    bot = make_twitch_bot()
    bot._restart_eventsub = AsyncMock()

    async def _rotate():
        bot.token_manager.streamer_token = "streamer_tok_NEW"

    bot.token_manager.startup_validate = AsyncMock(side_effect=_rotate)

    await bot._refresh_tokens_and_maybe_restart_eventsub()

    bot._restart_eventsub.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_swallows_eventsub_restart_errors(caplog):
    """Une erreur du restart EventSub ne doit PAS remonter (pas de traceback non géré)."""
    bot = make_twitch_bot()

    async def _rotate():
        bot.token_manager.bot_token = "bot_tok_NEW"

    bot.token_manager.startup_validate = AsyncMock(side_effect=_rotate)
    bot._restart_eventsub = AsyncMock(side_effect=RuntimeError("429 Ratelimit Reached"))

    # Ne doit pas lever
    await bot._refresh_tokens_and_maybe_restart_eventsub()

    bot._restart_eventsub.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_swallows_validate_errors():
    """Une erreur de startup_validate ne doit pas faire planter le cycle de refresh."""
    bot = make_twitch_bot()
    bot._restart_eventsub = AsyncMock()
    bot.token_manager.startup_validate = AsyncMock(side_effect=Exception("network down"))

    # Ne doit pas lever
    await bot._refresh_tokens_and_maybe_restart_eventsub()

    bot._restart_eventsub.assert_not_awaited()
