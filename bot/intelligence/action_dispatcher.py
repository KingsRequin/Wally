from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

from loguru import logger

from bot.intelligence.meta_agent import MetaDecision


class ActionDispatcher:
    def __init__(
        self,
        bot=None,
        persona_manager=None,
        fact_store=None,
        feed=None,
    ) -> None:
        self._bot = bot
        self._persona = persona_manager
        self._facts = fact_store
        self._feed = feed

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
                if self._feed:
                    self._feed.publish({"type": "SPEAK", "channel": channel_id, "detail": message})
            else:
                logger.warning("SPEAK: canal {} introuvable", channel_id)
        except Exception as e:
            logger.error("SPEAK failed: {}", e)

    async def _react(self, channel_id: str, message_id: str, emoji: str) -> None:
        """Réagit en emoji à un message récent. Geste léger et humain.

        Ne crash jamais : un emoji invalide ou un manque de permissions est
        simplement loggé en warning.
        """
        if not channel_id or not message_id or not emoji:
            logger.warning("react: arguments manquants (channel/message/emoji)")
            return
        if self._bot is None:
            logger.debug("react supprimé: bot non disponible")
            return
        try:
            channel = self._bot.get_channel(int(channel_id))
            if channel is None:
                logger.warning("react: canal introuvable {}", channel_id)
                return
            try:
                message = await channel.fetch_message(int(message_id))
            except Exception as e:
                logger.warning("react: message {} introuvable: {}", message_id, e)
                return
            await message.add_reaction(emoji)
            logger.info("Cognitive REACT {} → msg {}", emoji, message_id)
            if self._feed:
                self._feed.publish({"type": "ACT", "detail": f"react {emoji}"})
        except Exception as e:
            logger.warning("react failed: {}", e)

    async def _dm(self, user_id: str, message: str) -> None:
        """Envoie un DM Discord — réservé au créateur (owner) uniquement.

        Sécurité stricte : Wally ne peut DM que son créateur, jamais un autre
        membre. Ne crash jamais (DM fermés → Forbidden simplement loggé).
        """
        user_id = str(user_id or "").strip()
        message = (message or "").strip()
        if not user_id or not message:
            logger.warning("dm: arguments manquants (user_id/message)")
            return
        if self._bot is None:
            logger.debug("dm supprimé: bot non disponible")
            return
        owner_id = os.getenv("OWNER_DISCORD_ID", "610550333042589752")
        if user_id != owner_id:
            logger.warning("DM non autorisé vers {} (réservé au créateur)", user_id)
            return
        try:
            try:
                user = await self._bot.fetch_user(int(user_id))
            except Exception as e:
                logger.warning("dm: utilisateur {} introuvable: {}", user_id, e)
                return
            await user.send(message)
            logger.info("Cognitive DM → {} : {}", user_id, message[:80])
            if self._feed:
                self._feed.publish({"type": "ACT", "detail": f"DM créateur : {message[:300]}"})
        except Exception as e:
            logger.warning("DM failed: {}", e)

    @staticmethod
    def _coerce_goal_id(act_name: str, raw) -> int | None:
        """Convertit goal_id en int (le LLM peut l'envoyer en str). Retourne None
        et log un warning si absent/invalide — ne crash jamais.
        """
        if raw is None:
            logger.warning("ACT {}: 'goal_id' manquant", act_name)
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            logger.warning("ACT {}: goal_id invalide {!r}", act_name, raw)
            return None

    async def _act(self, act_name: str, args: dict) -> None:
        from bot.intelligence.memory.facts import AtomicFact, FactCategory, FactStatus

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
                if self._feed:
                    self._feed.publish({"type": "ACT", "detail": f"create_memory: {content[:300]}"})

        elif act_name == "create_goal" and self._facts:
            desc = args.get("description", "")
            if desc:
                await self._facts.add(AtomicFact(
                    user_id="wally:self",
                    content=desc,
                    category=FactCategory.GOAL,
                    confidence=1.0,
                    created_at=now,
                    last_seen_at=now,
                ))
                logger.info("ACT create_goal: {}", desc[:60])
                if self._feed:
                    self._feed.publish({"type": "ACT", "detail": f"create_goal: {desc[:300]}"})

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
                if self._feed:
                    self._feed.publish({"type": "ACT", "detail": f"create_desire: {content[:300]}"})

        elif act_name == "advance_goal" and self._facts:
            goal_id = self._coerce_goal_id(act_name, args.get("goal_id"))
            step = (args.get("step") or "").strip()
            if goal_id is None:
                return
            if not step:
                logger.warning("ACT advance_goal: 'step' manquant pour #{}", goal_id)
                return
            ok = await self._facts.append_progress(goal_id, step)
            if ok:
                logger.info("ACT advance_goal: #{} {}", goal_id, step[:60])
                if self._feed:
                    self._feed.publish(
                        {"type": "ACT", "detail": f"advance_goal #{goal_id}: {step[:300]}"}
                    )

        elif act_name == "fulfill_goal" and self._facts:
            goal_id = self._coerce_goal_id(act_name, args.get("goal_id"))
            if goal_id is None:
                return
            await self._facts.set_status(goal_id, FactStatus.ARCHIVED)
            logger.info("ACT fulfill_goal: #{} accompli", goal_id)
            if self._feed:
                self._feed.publish({"type": "ACT", "detail": f"fulfill_goal #{goal_id}"})

        elif act_name == "react":
            await self._react(
                args.get("channel_id", ""),
                args.get("message_id", ""),
                args.get("emoji", ""),
            )

        elif act_name == "dm":
            await self._dm(args.get("user_id", ""), args.get("message", ""))

        elif act_name == "note_to_self" and self._facts:
            note = (args.get("note") or "").strip()
            kind = args.get("kind", "reminder")
            if not note:
                return
            cat = {
                "mood": FactCategory.EMOTION,
                "question": FactCategory.DESIRE,
                "reminder": FactCategory.DESIRE,
            }.get(kind, FactCategory.THOUGHT)
            await self._facts.add(AtomicFact(
                user_id="wally:self",
                content=note,
                category=cat,
                source="note_to_self",
                confidence=1.0,
                created_at=now,
                last_seen_at=now,
            ))
            logger.info("ACT note_to_self ({}): {}", kind, note[:60])
            if self._feed:
                self._feed.publish({"type": "ACT", "detail": f"note ({kind}): {note[:300]}"})

        elif act_name == "set_focus" and self._facts:
            focus = (args.get("focus") or "").strip()
            if not focus:
                return
            # Une seule préoccupation active à la fois : archive la précédente.
            old = await self._facts.get_latest_by_source("wally:self", "focus")
            if old is not None and old.id is not None:
                await self._facts.set_status(old.id, FactStatus.ARCHIVED)
            await self._facts.add(AtomicFact(
                user_id="wally:self",
                content=focus,
                category=FactCategory.THOUGHT,
                source="focus",
                confidence=1.0,
                created_at=now,
                last_seen_at=now,
            ))
            logger.info("ACT set_focus: {}", focus[:60])
            if self._feed:
                self._feed.publish({"type": "ACT", "detail": f"focus: {focus[:300]}"})

        elif act_name == "reflect_self" and self._facts:
            narrative = args.get("narrative", "").strip()
            if not narrative:
                return
            # Récit de soi cumulatif : on N'archive PAS les précédents (contraste
            # avec set_focus). Chaque récit s'ajoute à la trace de l'identité.
            await self._facts.add(AtomicFact(
                user_id="wally:self",
                content=narrative,
                category=FactCategory.THOUGHT,
                source="self_narrative",
                confidence=1.0,
                created_at=now,
                last_seen_at=now,
            ))
            logger.info("ACT reflect_self: {}", narrative[:60])
            if self._feed:
                self._feed.publish(
                    {"type": "ACT", "detail": f"récit de soi : {narrative[:300]}"}
                )

        elif act_name == "note_relation" and self._facts:
            about = (args.get("about") or "").strip()
            opinion = (args.get("opinion") or "").strip()
            if not about or not opinion:
                return
            # Opinion cumulative : Wally se fait SES propres avis sur les gens,
            # stockés sous wally:self (sa perspective). Pas d'archivage — ses
            # opinions évoluent par accumulation, les plus récentes priment au
            # surfaçage (get_by_user trie par last_seen_at DESC).
            await self._facts.add(AtomicFact(
                user_id="wally:self",
                content=f"{about} — {opinion}",
                category=FactCategory.REL,
                source="opinion",
                confidence=1.0,
                created_at=now,
                last_seen_at=now,
            ))
            logger.info("ACT note_relation: {} — {}", about, opinion[:50])
            if self._feed:
                self._feed.publish({"type": "ACT", "detail": f"opinion sur {about}"})

        elif act_name == "code_fix":
            self_fix = getattr(self._bot, "self_fix", None) if self._bot else None
            if self_fix is None:
                logger.warning(
                    "ACT code_fix: SelfFix non disponible (BRIDGE_SECRET non configuré)"
                )
                return
            requester_id = args.get("requester_discord_id", "")
            if requester_id != "610550333042589752":
                logger.warning("ACT code_fix refusé: {} n'est pas owner", requester_id)
                return
            from bot.intelligence.self_fix import FixRequest
            asyncio.create_task(
                self_fix.fix(
                    FixRequest(
                        requester_discord_id=requester_id,
                        file_path=args.get("file_path", ""),
                        description=args.get("description", ""),
                    )
                )
            )

        else:
            logger.info("ACT {} non implémenté Plan B — ignoré", act_name)

    async def _evolve(self, section: str, change: str) -> None:
        if self._persona is None:
            logger.warning("EVOLVE ignoré: PersonaManager non disponible")
            return
        try:
            await self._persona.evolve(section, change)
            if self._feed:
                self._feed.publish({"type": "EVOLVE", "detail": section})
        except Exception as e:
            logger.warning("EVOLVE {}: {}", section, e)
