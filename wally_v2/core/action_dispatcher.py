from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger

from wally_v2.core.meta_agent import MetaDecision


class ActionDispatcher:
    def __init__(
        self,
        bot=None,
        persona_manager=None,
        fact_store=None,
    ) -> None:
        self._bot = bot
        self._persona = persona_manager
        self._facts = fact_store

    async def dispatch(self, decision: MetaDecision) -> None:
        action = decision.action
        if action == "THINK":
            pass
        elif action == "SPEAK":
            await self._speak(decision.channel_id, decision.message)
        elif action == "ACT":
            await self._act(decision.act_name or "", decision.act_args)
        elif action == "EVOLVE":
            await self._evolve(decision.section or "", decision.change or "")
        elif action == "SLEEP":
            pass  # handled by CognitiveLoop
        else:
            logger.warning("ActionDispatcher: action inconnue '{}'", action)

    async def _speak(self, channel_id: str | None, message: str | None) -> None:
        if not channel_id or not message:
            return
        if self._bot is None:
            logger.debug("SPEAK supprimé: bot non disponible (channel={})", channel_id)
            return
        try:
            channel = self._bot.get_channel(int(channel_id))
            if channel:
                await channel.send(message)
                logger.info("Cognitive SPEAK → canal {} : {}", channel_id, message[:80])
            else:
                logger.warning("SPEAK: canal {} introuvable", channel_id)
        except Exception as e:
            logger.error("SPEAK failed: {}", e)

    async def _act(self, act_name: str, args: dict) -> None:
        from wally_v2.core.memory.facts import AtomicFact, FactCategory

        now = datetime.now(timezone.utc)

        if act_name == "create_memory" and self._facts:
            content = args.get("fact_content", "")
            if content:
                await self._facts.add(AtomicFact(
                    user_id="wally:self",
                    content=content,
                    category=FactCategory.THOUGHT,
                    confidence=1.0,
                    created_at=now,
                    last_seen_at=now,
                ))
                logger.info("ACT create_memory: {}", content[:60])

        elif act_name == "create_goal" and self._facts:
            desc = args.get("description", "")
            if desc:
                await self._facts.add(AtomicFact(
                    user_id="wally:self",
                    content=desc,
                    category=FactCategory.GOAL,
                    confidence=1.0,
                    decay_rate=0.005,
                    created_at=now,
                    last_seen_at=now,
                ))
                logger.info("ACT create_goal: {}", desc[:60])

        elif act_name == "create_desire" and self._facts:
            content = args.get("content", "")
            if content:
                await self._facts.add(AtomicFact(
                    user_id="wally:self",
                    content=content,
                    category=FactCategory.DESIRE,
                    confidence=0.8,
                    created_at=now,
                    last_seen_at=now,
                ))
                logger.info("ACT create_desire: {}", content[:60])

        elif act_name == "code_fix":
            logger.warning(
                "ACT code_fix reçu via cognitive loop — ignoré (Plan C seulement via owner DM)"
            )

        else:
            logger.info("ACT {} non implémenté Plan B — ignoré", act_name)

    async def _evolve(self, section: str, change: str) -> None:
        if self._persona is None:
            logger.warning("EVOLVE ignoré: PersonaManager non disponible")
            return
        try:
            await self._persona.evolve(section, change)
        except Exception as e:
            logger.warning("EVOLVE {}: {}", section, e)
