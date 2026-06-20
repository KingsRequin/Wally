from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

OWNER_DISCORD_ID = "610550333042589752"

_FIX_SYSTEM = (
    "Tu es un assistant de correction de code Python. "
    "Génère UNIQUEMENT un diff unifié (format git diff) pour corriger le problème décrit. "
    "Le diff doit être applicable via `git apply`. "
    "Aucune explication, seulement le diff."
)


@dataclass
class FixRequest:
    requester_discord_id: str
    file_path: str       # relative to repo root, e.g. "bot/core/emotion.py"
    description: str


class SelfFix:
    def __init__(self, llm, bridge, bot, repo_root: str = "/app") -> None:
        self._llm = llm
        self._bridge = bridge
        self._bot = bot
        self._repo_root = Path(repo_root)

    async def fix(self, request: FixRequest) -> None:
        if request.requester_discord_id != OWNER_DISCORD_ID:
            logger.warning("SelfFix refusé: {} n'est pas owner", request.requester_discord_id)
            return

        abs_path = self._repo_root / request.file_path
        if not abs_path.exists():
            logger.warning("SelfFix: fichier {} introuvable", abs_path)
            return

        original = abs_path.read_text(encoding="utf-8")
        user_msg = (
            f"Fichier : {request.file_path}\n\n"
            f"```python\n{original[:6000]}\n```\n\n"
            f"Problème : {request.description}"
        )
        diff = await self._llm.complete(_FIX_SYSTEM, [{"role": "user", "content": user_msg}])

        owner = await self._bot.fetch_user(int(OWNER_DISCORD_ID))
        dm = await owner.create_dm()
        preview = diff[:1800]
        msg = await dm.send(
            f"🔧 **Correction proposée — `{request.file_path}`**\n"
            f"```diff\n{preview}\n```\n"
            "✅ appliquer (rebuild + restart ~2min) · ❌ annuler · _(timeout 1h)_"
        )
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")

        try:
            emoji = await self._await_reaction(msg, timeout=3600)
        except asyncio.TimeoutError:
            await dm.send("⏱ Timeout — correction annulée.")
            return

        if emoji == "✅":
            await dm.send("⚙️ Application du patch + rebuild...")
            try:
                await self._bridge.git_apply(diff)
                await self._bridge.docker_rebuild("wally")
            except Exception as e:
                await dm.send(f"❌ Erreur bridge: {e}")
        else:
            await dm.send("❌ Correction annulée.")

    async def _await_reaction(self, msg, timeout: float) -> str:
        def check(reaction, user):
            return (
                str(user.id) == OWNER_DISCORD_ID
                and str(reaction.emoji) in ("✅", "❌")
                and reaction.message.id == msg.id
            )
        reaction, _ = await self._bot.wait_for("reaction_add", check=check, timeout=timeout)
        return str(reaction.emoji)
