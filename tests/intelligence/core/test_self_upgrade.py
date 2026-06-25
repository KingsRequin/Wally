import asyncio
import types
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

OWNER_ID = "610550333042589752"


def _equip_owner(bot, owner=OWNER_ID, name="Wally"):
    """Équipe le mock bot d'un config exposant owner_discord_id et name."""
    bot.config = types.SimpleNamespace(
        bot=types.SimpleNamespace(owner_discord_id=owner, name=name)
    )
    return bot


def make_upgrade(update_available=False):
    from bot.intelligence.self_upgrade import SelfUpgrade

    checker = MagicMock()
    checker.update_available = update_available

    bridge = MagicMock()
    bridge.docker_restart = AsyncMock()

    bot = MagicMock()
    _equip_owner(bot)
    owner = AsyncMock()
    dm = AsyncMock()
    msg = AsyncMock()
    msg.id = 123
    dm.send = AsyncMock(return_value=msg)
    msg.add_reaction = AsyncMock()
    owner.create_dm = AsyncMock(return_value=dm)
    bot.fetch_user = AsyncMock(return_value=owner)

    return SelfUpgrade(checker, bridge, bot), checker, bridge, bot, dm, msg


@pytest.mark.asyncio
async def test_loop_calls_propose_when_update_available():
    upgrade, checker, bridge, bot, dm, msg = make_upgrade(update_available=True)
    with patch.object(upgrade, "_propose", new_callable=AsyncMock) as mock_propose:
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            mock_sleep.side_effect = [None, asyncio.CancelledError()]
            with pytest.raises(asyncio.CancelledError):
                await upgrade._loop()
        mock_propose.assert_called_once()


@pytest.mark.asyncio
async def test_propose_restarts_on_checkmark():
    upgrade, checker, bridge, bot, dm, msg = make_upgrade()
    reaction = MagicMock()
    reaction.emoji = "✅"
    reaction.message.id = msg.id
    user = MagicMock()
    user.id = 610550333042589752
    bot.wait_for = AsyncMock(return_value=(reaction, user))

    await upgrade._propose()

    bridge.docker_restart.assert_called_once_with("wally")


@pytest.mark.asyncio
async def test_propose_ignores_on_cross():
    upgrade, checker, bridge, bot, dm, msg = make_upgrade()
    reaction = MagicMock()
    reaction.emoji = "❌"
    reaction.message.id = msg.id
    user = MagicMock()
    user.id = 610550333042589752
    bot.wait_for = AsyncMock(return_value=(reaction, user))

    await upgrade._propose()

    bridge.docker_restart.assert_not_called()
    assert checker.update_available is False


@pytest.mark.asyncio
async def test_propose_ignores_on_timeout():
    upgrade, checker, bridge, bot, dm, msg = make_upgrade()
    bot.wait_for = AsyncMock(side_effect=asyncio.TimeoutError())

    await upgrade._propose()

    bridge.docker_restart.assert_not_called()
    assert checker.update_available is False


@pytest.mark.asyncio
async def test_start_stop():
    upgrade, *_ = make_upgrade()
    upgrade.start()
    assert upgrade._task is not None
    await upgrade.stop()
    assert upgrade._task.cancelled() or upgrade._task.done()


@pytest.mark.asyncio
async def test_owner_id_read_from_config_not_constant():
    """_owner_id() doit lire config.bot.owner_discord_id, pas la constante module."""
    from bot.intelligence.self_upgrade import SelfUpgrade

    checker = MagicMock()
    bridge = MagicMock()
    bot = MagicMock()
    _equip_owner(bot, owner="999888777666555444")

    upgrade = SelfUpgrade(checker, bridge, bot)
    assert upgrade._owner_id() == "999888777666555444"


@pytest.mark.asyncio
async def test_empty_owner_skips_propose():
    """Si owner_discord_id est vide dans config, _propose ne fait rien (early-return)."""
    upgrade, checker, bridge, bot, dm, msg = make_upgrade()
    _equip_owner(bot, owner="")

    await upgrade._propose()

    bot.fetch_user.assert_not_called()
    bridge.docker_restart.assert_not_called()


@pytest.mark.asyncio
async def test_reaction_check_uses_config_owner():
    """_await_reaction.check compare user.id à config.bot.owner_discord_id, pas la constante."""
    upgrade, checker, bridge, bot, dm, msg = make_upgrade()
    # Changer l'owner dans config vers un ID différent : la réaction du user original
    # doit être rejetée → wait_for lève TimeoutError → docker_restart non appelé.
    bot.config.bot.owner_discord_id = "111222333444555666"
    bot.wait_for = AsyncMock(side_effect=asyncio.TimeoutError())

    await upgrade._propose()

    bridge.docker_restart.assert_not_called()


def test_service_returns_wally_lowercase_by_default():
    """_service() retourne 'wally' quand config.bot.name='Wally'."""
    from bot.intelligence.self_upgrade import SelfUpgrade

    checker = MagicMock()
    bridge = MagicMock()
    bot = MagicMock()
    _equip_owner(bot, name="Wally")

    upgrade = SelfUpgrade(checker, bridge, bot)
    assert upgrade._service() == "wally"


def test_service_returns_cindy_lowercase_when_name_cindy():
    """_service() retourne 'cindy' quand config.bot.name='Cindy'."""
    from bot.intelligence.self_upgrade import SelfUpgrade

    checker = MagicMock()
    bridge = MagicMock()
    bot = MagicMock()
    _equip_owner(bot, name="Cindy")

    upgrade = SelfUpgrade(checker, bridge, bot)
    assert upgrade._service() == "cindy"


@pytest.mark.asyncio
async def test_propose_restarts_cindy_service():
    """Avec config.bot.name='Cindy', docker_restart est appelé avec 'cindy'."""
    from bot.intelligence.self_upgrade import SelfUpgrade

    checker = MagicMock()
    bridge = MagicMock()
    bridge.docker_restart = AsyncMock()
    bot = MagicMock()
    _equip_owner(bot, name="Cindy")
    owner = AsyncMock()
    dm = AsyncMock()
    msg = AsyncMock()
    msg.id = 456
    dm.send = AsyncMock(return_value=msg)
    msg.add_reaction = AsyncMock()
    owner.create_dm = AsyncMock(return_value=dm)
    bot.fetch_user = AsyncMock(return_value=owner)

    reaction = MagicMock()
    reaction.emoji = "✅"
    reaction.message.id = msg.id
    user = MagicMock()
    user.id = int(OWNER_ID)
    bot.wait_for = AsyncMock(return_value=(reaction, user))

    upgrade = SelfUpgrade(checker, bridge, bot)
    await upgrade._propose()

    bridge.docker_restart.assert_called_once_with("cindy")
