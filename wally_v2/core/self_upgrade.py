from __future__ import annotations

import asyncio

from loguru import logger

OWNER_DISCORD_ID = "610550333042589752"


class SelfUpgrade:
    def __init__(self, update_checker, bridge, bot) -> None:
        self._checker = update_checker
        self._bridge = bridge
        self._bot = bot
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(300)
            if self._checker.update_available:
                await self._propose()

    async def _propose(self) -> None:
        try:
            owner = await self._bot.fetch_user(int(OWNER_DISCORD_ID))
            dm = await owner.create_dm()
            msg = await dm.send(
                "🔄 **Mise à jour Wally disponible.**\n"
                "Réagis ✅ pour appliquer (restart ~30s), ❌ pour ignorer.\n"
                "_(Timeout 24h)_"
            )
            await msg.add_reaction("✅")
            await msg.add_reaction("❌")
            emoji = await self._await_reaction(msg, timeout=86400)
            if emoji == "✅":
                await dm.send("⚡ Redémarrage en cours...")
                await self._bridge.docker_restart("wally")
            else:
                self._checker.update_available = False
                await dm.send("❌ Mise à jour ignorée.")
        except asyncio.TimeoutError:
            self._checker.update_available = False
        except Exception as e:
            logger.error("SelfUpgrade._propose failed: {}", e)

    async def _await_reaction(self, msg, timeout: float) -> str:
        def check(reaction, user):
            return (
                str(user.id) == OWNER_DISCORD_ID
                and str(reaction.emoji) in ("✅", "❌")
                and reaction.message.id == msg.id
            )
        reaction, _ = await self._bot.wait_for("reaction_add", check=check, timeout=timeout)
        return str(reaction.emoji)
