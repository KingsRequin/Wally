from __future__ import annotations

import asyncio

from loguru import logger


class SelfUpgrade:
    def __init__(self, update_checker, bridge, bot) -> None:
        self._checker = update_checker
        self._bridge = bridge
        self._bot = bot
        self._task: asyncio.Task | None = None

    def _owner_id(self) -> str:
        """Lit l'ID Discord du créateur depuis config.bot.owner_discord_id."""
        cfg = getattr(self._bot, "config", None)
        return getattr(getattr(cfg, "bot", None), "owner_discord_id", "") or ""

    def _service(self) -> str:
        """Dérive le nom du service Docker depuis config.bot.name (fallback 'wally')."""
        name = getattr(getattr(getattr(self._bot, "config", None), "bot", None), "name", "") or "wally"
        return name.lower()

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
        oid = self._owner_id()
        if not oid:
            logger.warning("SelfUpgrade: owner_discord_id non configuré — abandon")
            return
        try:
            owner = await self._bot.fetch_user(int(oid))
            dm = await owner.create_dm()
            bot_name = getattr(getattr(getattr(self._bot, "config", None), "bot", None), "name", "") or "Wally"
            msg = await dm.send(
                f"🔄 **Mise à jour {bot_name} disponible.**\n"
                "Réagis ✅ pour appliquer (restart ~30s), ❌ pour ignorer.\n"
                "_(Timeout 24h)_"
            )
            await msg.add_reaction("✅")
            await msg.add_reaction("❌")
            emoji = await self._await_reaction(msg, timeout=86400)
            if emoji == "✅":
                await dm.send("⚡ Redémarrage en cours...")
                try:
                    await self._bridge.docker_restart(self._service())
                    self._checker.update_available = False
                except Exception as e:
                    logger.error("SelfUpgrade docker_restart failed: {}", e)
                    await dm.send(f"❌ Erreur restart: {e}")
            else:
                self._checker.update_available = False
                await dm.send("❌ Mise à jour ignorée.")
        except asyncio.TimeoutError:
            self._checker.update_available = False
        except Exception as e:
            logger.error("SelfUpgrade._propose failed: {}", e)

    async def _await_reaction(self, msg, timeout: float) -> str:
        owner_id = self._owner_id()

        def check(reaction, user):
            return (
                str(user.id) == owner_id
                and str(reaction.emoji) in ("✅", "❌")
                and reaction.message.id == msg.id
            )
        reaction, _ = await self._bot.wait_for("reaction_add", check=check, timeout=timeout)
        return str(reaction.emoji)
