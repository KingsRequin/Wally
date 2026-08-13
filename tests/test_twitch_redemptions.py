"""L'achat de la récompense ouvre un duel — ou rembourse, mais ne se tait jamais."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.twitch.events.redemptions import _est_notre_recompense, handle_redemption


def _bot(reward_id="RW", duel_en_cours=None, persisted_reward_id=None):
    bot = MagicMock()
    bot.twitch_api.refund_redemption = AsyncMock(return_value=True)
    bot.duel_runner = MagicMock()
    bot.duel_runner._reward_id = reward_id
    bot.duel_runner.duel_en_cours = duel_en_cours
    bot.duel_runner.ouvrir = AsyncMock()
    bot.db.get_state = AsyncMock(return_value=persisted_reward_id)
    return bot


def _event(reward_id="RW", user="bob", texte="1012242925358"):
    e = MagicMock()
    e.reward.id = reward_id
    e.id = "RD1"
    e.user.name = user
    e.input = texte
    return e


@pytest.mark.asyncio
async def test_une_autre_recompense_est_ignoree():
    assert await _est_notre_recompense(_bot("RW"), "AUTRE") is False
    assert await _est_notre_recompense(_bot("RW"), "RW") is True


@pytest.mark.asyncio
async def test_reward_id_non_configure_n_attrape_rien():
    """Vide = duel désactivé. Sans ce garde, toute récompense de la chaîne
    lancerait un duel."""
    assert await _est_notre_recompense(_bot("", persisted_reward_id=None), "") is False
    assert await _est_notre_recompense(_bot("", persisted_reward_id=None), "RW") is False


@pytest.mark.asyncio
async def test_duel_deja_en_cours_est_delegue_a_ouvrir():
    """Le refus « déjà en cours » n'est plus court-circuité ici (Task 8 —
    revue) : `ouvrir()` est le seul endroit qui détient à la fois le
    remboursement ET le canal d'annonce, un court-circuit muet dans ce
    handler laissait le viewer sans un mot d'explication."""
    bot = _bot(duel_en_cours=object())
    await handle_redemption(bot, _event())
    bot.duel_runner.ouvrir.assert_awaited_once()
    bot.twitch_api.refund_redemption.assert_not_awaited()


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


@pytest.mark.asyncio
async def test_runner_absent_rembourse_via_lid_persiste():
    """CRITICAL : sans repli sur `bot_state`, cette branche était du code mort —
    `_est_notre_recompense` rendait False avant que `handle_redemption` puisse
    seulement atteindre son `if runner is None`. Un achat pendant que le runner
    est indisponible (Apex down au boot) n'était donc JAMAIS remboursé."""
    bot = _bot(persisted_reward_id="RW")
    bot.duel_runner = None
    await handle_redemption(bot, _event(reward_id="RW"))
    bot.twitch_api.refund_redemption.assert_awaited_once()


@pytest.mark.asyncio
async def test_exception_dans_ouvrir_rembourse():
    """Un crash réseau au milieu d'`ouvrir()` ne doit pas avaler les points du
    viewer : à ce stade reward_id/redemption_id sont connus, aucun duel n'est
    ouvert."""
    bot = _bot()
    bot.duel_runner.ouvrir = AsyncMock(side_effect=RuntimeError("timeout"))
    await handle_redemption(bot, _event())
    bot.twitch_api.refund_redemption.assert_awaited_once_with("RW", "RD1")
