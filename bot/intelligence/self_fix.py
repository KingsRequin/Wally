from __future__ import annotations

import asyncio
from dataclasses import dataclass

from loguru import logger

OWNER_DISCORD_ID = "610550333042589752"


@dataclass
class UpgradeRequest:
    goal: str


class SelfFix:
    """Wally décide de se modifier ; le créateur autorise en DM ; Claude Code exécute."""

    def __init__(self, bridge, bot, *, poll_interval: float = 10.0,
                 approval_timeout: float = 3600.0) -> None:
        self._bridge = bridge
        self._bot = bot
        self._poll_interval = poll_interval
        self._approval_timeout = approval_timeout
        self._pending = False
        self._declined: set[str] = set()

    async def request_upgrade(self, req: UpgradeRequest, *, force: bool = False) -> None:
        # force=True : demande explicite du créateur en conversation → on outrepasse
        # le filtre _declined (sinon un goal déjà refusé serait ignoré en silence).
        goal = (req.goal or "").strip()
        if not goal:
            return
        if self._pending:
            logger.info("self-upgrade ignoré: un upgrade est déjà en attente")
            return
        norm = goal.lower()
        if not force and norm in self._declined:
            logger.info("self-upgrade ignoré: goal déjà refusé — {}", goal[:60])
            return
        self._pending = True
        try:
            await self._run_upgrade(goal, norm)
        except Exception as e:  # noqa: BLE001 — jamais d'échec silencieux
            logger.exception("self-upgrade a échoué")
            await self._notify(f"❌ Ma tentative d'auto-modification a échoué : {e}")
        finally:
            self._pending = False

    async def _run_upgrade(self, goal: str, norm: str) -> None:
        owner = await self._bot.fetch_user(int(OWNER_DISCORD_ID))
        dm = await owner.create_dm()
        msg = await dm.send(
            "🧠 **J'ai repéré une faiblesse que je voudrais corriger :**\n"
            f"> {goal}\n\n"
            "Si tu autorises, **Claude Code** va modifier mon code dans ce sens "
            "(en autonomie), puis je redémarre avec la nouvelle version.\n"
            "✅ autoriser · ❌ refuser · _(timeout 1h)_"
        )
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")

        try:
            emoji = await self._await_reaction(msg, timeout=self._approval_timeout)
        except asyncio.TimeoutError:
            await dm.send("⏱ Pas de réponse — j'abandonne cette idée.")
            self._declined.add(norm)
            return

        if emoji != "✅":
            await dm.send("❌ Ok, je laisse tomber. Je ne te le reproposerai pas.")
            self._declined.add(norm)
            return

        await dm.send("👍 C'est parti, Claude Code travaille… (ça peut prendre quelques minutes)")
        job_id = await self._bridge.claude_run(goal)

        status = await self._poll(job_id)
        if status is None:
            await dm.send("❌ Claude Code n'a pas répondu à temps — j'abandonne.")
            return
        if status.get("state") != "done":
            tail = (status.get("output_tail") or "")[-500:]
            await dm.send(
                f"❌ Claude Code a échoué (exit {status.get('exit_code')}).\n```\n{tail}\n```"
            )
            return
        if not status.get("changed") and not status.get("head_changed"):
            result = (status.get("result") or "").strip()[:500]
            await dm.send(f"🤔 Finalement aucun changement de code.\n{result}")
            return

        await dm.send("⚙️ Application + rebuild…")
        await self._bridge.claude_commit(goal)
        await self._bridge.docker_rebuild("wally")
        result = (status.get("result") or "").strip()[:800]
        await dm.send(f"✅ **C'est fait** — je redémarre (~2 min).\n{result}")

    async def _poll(self, job_id: str, max_wait: float = 1800.0) -> dict | None:
        waited = 0.0
        while waited <= max_wait:
            await asyncio.sleep(self._poll_interval)
            waited += self._poll_interval if self._poll_interval > 0 else 1.0
            status = await self._bridge.claude_status(job_id)
            if status.get("state") != "running":
                return status
        return None

    async def _notify(self, text: str) -> None:
        """DM best-effort au créateur. Ne propage jamais."""
        try:
            owner = await self._bot.fetch_user(int(OWNER_DISCORD_ID))
            dm = await owner.create_dm()
            await dm.send(text)
        except Exception:  # noqa: BLE001
            logger.exception("self-upgrade: impossible de notifier le créateur en DM")

    async def _await_reaction(self, msg, timeout: float) -> str:
        def check(reaction, user):
            return (
                str(user.id) == OWNER_DISCORD_ID
                and str(reaction.emoji) in ("✅", "❌")
                and reaction.message.id == msg.id
            )
        reaction, _ = await self._bot.wait_for("reaction_add", check=check, timeout=timeout)
        return str(reaction.emoji)
