import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def make_upgrade(update_available=False):
    from bot.v2.core.self_upgrade import SelfUpgrade

    checker = MagicMock()
    checker.update_available = update_available

    bridge = MagicMock()
    bridge.docker_restart = AsyncMock()

    bot = MagicMock()
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
