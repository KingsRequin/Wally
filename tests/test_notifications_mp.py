"""Une panne se dit en MP au créateur, pas dans un salon de discussion.

Vécu le 2026-09-18 : la veille du verrou a annoncé « je ne peux plus rien
enregistrer » dans le salon configuré — qui est un salon de discussion
ordinaire du serveur, pas un salon de logs. Le message s'adressait au seul qui
pouvait y remédier, et il est parti devant tout le monde.

Le salon reste le REPLI : mieux vaut un message mal placé qu'un silence.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.core.notifications import NotificationService


def _config(owner: str = "42", salon: int | None = 1234) -> SimpleNamespace:
    return SimpleNamespace(
        bot=SimpleNamespace(owner_discord_id=owner, notification_channel_id=salon)
    )


def _bot_avec_mp() -> SimpleNamespace:
    dm = AsyncMock()
    owner = AsyncMock()
    owner.create_dm = AsyncMock(return_value=dm)
    salon = AsyncMock()
    bot = SimpleNamespace(
        fetch_user=AsyncMock(return_value=owner),
        get_channel=lambda cid: salon,
        fetch_channel=AsyncMock(return_value=salon),
    )
    return bot, dm, salon


async def test_l_alerte_part_en_mp_et_pas_dans_le_salon():
    bot, dm, salon = _bot_avec_mp()
    service = NotificationService(_config(), bot)

    assert await service.send("🔒 panne") is True
    dm.send.assert_awaited_once_with("🔒 panne")
    salon.send.assert_not_awaited()


async def test_mp_impossible_repli_sur_le_salon():
    """MP fermés : un message mal placé vaut mieux qu'un silence."""
    bot, dm, salon = _bot_avec_mp()
    dm.send = AsyncMock(side_effect=RuntimeError("Cannot send messages to this user"))
    service = NotificationService(_config(), bot)

    assert await service.send("🔒 panne") is True
    salon.send.assert_awaited_once_with("🔒 panne")


async def test_sans_createur_connu_on_retombe_sur_le_salon():
    bot, dm, salon = _bot_avec_mp()
    service = NotificationService(_config(owner=""), bot)

    assert await service.send("🔒 panne") is True
    bot.fetch_user.assert_not_awaited()
    salon.send.assert_awaited_once_with("🔒 panne")


async def test_ni_mp_ni_salon_ne_leve_pas():
    bot, dm, salon = _bot_avec_mp()
    dm.send = AsyncMock(side_effect=RuntimeError("fermé"))
    service = NotificationService(_config(salon=None), bot)

    assert await service.send("🔒 panne") is False


async def test_sans_bot_discord_rien_ne_part():
    service = NotificationService(_config(), None)
    assert await service.send("🔒 panne") is False
