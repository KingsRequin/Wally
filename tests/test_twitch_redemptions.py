"""L'achat de la récompense ouvre un duel — ou rembourse, mais ne se tait jamais."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.twitch.events.redemptions import _est_notre_recompense, handle_redemption


def _bot(reward_id="RW", duel_en_cours=None):
    bot = MagicMock()
    bot.twitch_api.refund_redemption = AsyncMock(return_value=True)
    bot.duel_runner = MagicMock()
    bot.duel_runner._reward_id = reward_id
    bot.duel_runner.duel_en_cours = duel_en_cours
    bot.duel_runner.ouvrir = AsyncMock()
    return bot


def _event(reward_id="RW", user="bob", texte="1012242925358"):
    e = MagicMock()
    e.reward.id = reward_id
    e.id = "RD1"
    e.user.name = user
    e.input = texte
    return e


def test_une_autre_recompense_est_ignoree():
    assert _est_notre_recompense(_bot("RW"), "AUTRE") is False
    assert _est_notre_recompense(_bot("RW"), "RW") is True


def test_reward_id_non_configure_n_attrape_rien():
    """Vide = duel désactivé. Sans ce garde, toute récompense de la chaîne
    lancerait un duel."""
    assert _est_notre_recompense(_bot(""), "") is False
    assert _est_notre_recompense(_bot(""), "RW") is False


@pytest.mark.asyncio
async def test_duel_deja_en_cours_rembourse():
    bot = _bot(duel_en_cours=object())
    await handle_redemption(bot, _event())
    bot.twitch_api.refund_redemption.assert_awaited_once()
    bot.duel_runner.ouvrir.assert_not_awaited()


@pytest.mark.asyncio
async def test_achat_valide_ouvre_le_duel():
    bot = _bot()
    await handle_redemption(bot, _event(texte="1012242925358"))
    bot.duel_runner.ouvrir.assert_awaited_once()
    args = bot.duel_runner.ouvrir.await_args.kwargs
    assert args["saisie"] == "1012242925358"
    assert args["redemption_id"] == "RD1"
    bot.twitch_api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_une_exception_ne_remonte_jamais():
    """Un handler d'événement ne crashe pas le bot."""
    bot = _bot()
    bot.duel_runner.ouvrir = AsyncMock(side_effect=RuntimeError("boum"))
    await handle_redemption(bot, _event())  # ne doit pas lever
