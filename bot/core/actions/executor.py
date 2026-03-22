"""ActionExecutor — action routing and message delivery."""

from __future__ import annotations

import json

from loguru import logger


class ActionExecutor:
    def __init__(self, registry) -> None:
        self._registry = registry
        self._discord_bot = None
        self._twitch_bot = None

    def set_bots(self, discord_bot, twitch_bot) -> None:
        self._discord_bot = discord_bot
        self._twitch_bot = twitch_bot

    async def execute(self, task: dict) -> str:
        if self._discord_bot is None and self._twitch_bot is None:
            logger.warning("ActionExecutor: bots not set, cannot execute task {}", task["id"])
            return "Error: bots not set, delivery not available"

        action_type = task["action_type"]
        defn = self._registry.get(action_type)
        if defn is None:
            return f"Unknown action type: {action_type}"

        payload = json.loads(task.get("payload", "{}"))
        target = {
            "platform": task.get("target_platform"),
            "channel_id": task.get("target_channel"),
            "creator_id": task.get("creator_id"),
            "creator_platform": task.get("creator_platform"),
        }

        # Call the handler — let exceptions propagate for the scheduler to handle
        result = await defn.handler(payload, target)

        # Deliver result to target channel
        if result and target["platform"] and target["channel_id"]:
            try:
                await self.deliver(str(result), target["platform"], target["channel_id"], dm=False)
            except Exception as e:
                logger.error("Failed to deliver result for task {}: {}", task["id"], e)

        return str(result) if result else "OK"

    async def deliver(self, message: str, platform: str, channel_id: str, dm: bool = False) -> None:
        if platform == "discord":
            if self._discord_bot is None:
                logger.warning("Discord bot not available for delivery")
                return
            try:
                channel = self._discord_bot.get_channel(int(channel_id))
            except (ValueError, TypeError):
                channel = None
            if channel:
                await channel.send(message)
            else:
                logger.warning("Discord channel {} not found", channel_id)
        elif platform == "twitch":
            if self._twitch_bot is None:
                logger.warning("Twitch bot not available for delivery")
                return
            channel = self._twitch_bot.get_channel(channel_id)
            if channel:
                await channel.send(message)
            else:
                logger.warning("Twitch channel {} not found", channel_id)
        else:
            logger.warning("Unsupported delivery platform: {}", platform)
