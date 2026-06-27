from __future__ import annotations

import asyncio
import difflib
import re
import time
from datetime import datetime, timezone

from loguru import logger

import discord

from bot.intelligence.meta_agent import MetaDecision

# Cooldown entre deux DM créateur proactifs : un humain ne relance pas son
# interlocuteur toutes les cinq minutes. Filet de sécurité anti-harcèlement,
# en complément de la directive du reasoning_system.
DM_CREATOR_COOLDOWN = 7200  # 2h

# Garde-fou anti-ping de masse sur les prises de parole proactives : Wally peut
# mentionner un membre (<@id>) mais jamais @everyone/@here ni un rôle entier.
_ALLOWED_MENTIONS = discord.AllowedMentions(everyone=False, roles=False, users=True)

# Mots vides pour la comparaison de désirs (Phase 3, dédup à l'écriture).
_DESIRE_STOPWORDS = frozenset(
    {"le", "la", "les", "un", "une", "des", "de", "du", "et", "ou", "que",
     "qui", "est", "sur", "pour", "dans", "par", "pas", "ce", "ça", "il",
     "je", "me", "mon", "ma", "mes", "si", "en", "au", "aux", "the", "and"}
)


def _desire_tokens(text: str) -> set[str]:
    if not text:
        return set()
    cleaned = re.sub(r"[^\w\s]", " ", text.lower(), flags=re.UNICODE)
    return {t for t in cleaned.split() if len(t) >= 3 and t not in _DESIRE_STOPWORDS}


def _same_desire(a: str, b: str, threshold: float = 0.5) -> bool:
    """True si deux désirs expriment la même intention (Jaccard de tokens ≥ seuil).
    Robuste aux paraphrases qui partagent les mots porteurs (entités, verbes), là
    où la similarité caractère échoue. Isolé pour pouvoir évoluer (cf. spec)."""
    ta, tb = _desire_tokens(a), _desire_tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= threshold


class ActionDispatcher:
    def __init__(
        self,
        bot=None,
        persona_manager=None,
        fact_store=None,
        feed=None,
        twitch_bot=None,
        gate=None,
    ) -> None:
        self._bot = bot
        self._twitch_bot = twitch_bot
        self._persona = persona_manager
        self._facts = fact_store
        self._feed = feed
        # Gate de sollicitation owner (un seul fil à la fois). None → pas de gate.
        self._gate = gate
        self._last_focus_ts: float = 0.0
        self._last_dm_ts: float = 0.0

    def _owner_id(self) -> str:
        for b in (self._bot, self._twitch_bot):
            cfg = getattr(b, "config", None)
            oid = getattr(getattr(cfg, "bot", None), "owner_discord_id", "")
            if isinstance(oid, str) and oid:
                return oid
        return ""

    def _self_name(self) -> str:
        for b in (self._bot, self._twitch_bot):
            cfg = getattr(b, "config", None)
            nm = getattr(getattr(cfg, "bot", None), "name", "")
            if isinstance(nm, str) and nm:
                return nm
        return "Wally"

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

        # Si le stream est live, préférer Twitch au lieu de Discord.
        twitch_bot = self._twitch_bot
        if twitch_bot is not None and twitch_bot._stream_info.get("live"):
            try:
                await twitch_bot.twitch_api.send_message(text=message)
                logger.info("Cognitive SPEAK → Twitch (stream live) : {}", message[:80])
                _ch = (twitch_bot._stream_info.get("user_login")
                       or twitch_bot._stream_info.get("user_name") or "stream")
                self._log_speak("twitch", _ch, message)
                if self._feed:
                    self._feed.publish({"type": "SPEAK", "channel": "twitch", "detail": message})
                return
            except Exception as e:
                logger.warning("SPEAK Twitch failed, fallback Discord: {}", e)

        if self._bot is None:
            logger.debug("SPEAK supprimé: bot non disponible (channel={})", channel_id)
            return
        try:
            channel = self._bot.get_channel(int(channel_id))
            if channel:
                await channel.send(message, allowed_mentions=_ALLOWED_MENTIONS)
                logger.info("Cognitive SPEAK → canal {} : {}", channel_id, message[:80])
                self._record_self_message(str(channel_id), message)
                guild = getattr(getattr(channel, "guild", None), "name", None)
                chan = getattr(channel, "name", None) or "dm"
                self._log_speak("discord", f"{guild}/{chan}" if guild else chan, message)
                _speaks = getattr(self._bot, "_wally_recent_speaks", None)
                if _speaks is not None:
                    _speaks[int(channel_id)] = message
                if self._feed:
                    self._feed.publish({"type": "SPEAK", "channel": channel_id, "detail": message})
            else:
                logger.warning("SPEAK: canal {} introuvable", channel_id)
        except Exception as e:
            logger.error("SPEAK failed: {}", e)

    def _log_speak(self, platform: str, conv_channel: str, message: str) -> None:
        """Trace un SPEAK cognitif comme message_out dans le conv_log du canal.

        Sans ça, un message spontané réellement envoyé n'apparaît dans AUCUN log
        de canal (seulement, indirectement, dans le brain) — invisible pour le
        débogage chronologique. kind='cognitive' le distingue d'une réponse réactive.
        """
        clog = getattr(self._bot, "conv_log", None) or getattr(self._twitch_bot, "conv_log", None)
        if clog is None:
            return
        try:
            from bot.core.conversation_log import new_trace_id
            clog.log(platform, conv_channel, "message_out",
                     trace_id=new_trace_id("cognitive"), kind="cognitive",
                     author=self._self_name(), content=message)
        except Exception as e:  # noqa: BLE001 — ne jamais faire crasher la boucle cognitive
            logger.warning("conv_log SPEAK échoué: {}", e)

    def _record_self_message(self, channel_id: str, message: str) -> None:
        """Enregistre un message sortant SPONTANÉ de Wally dans la mémoire de contexte.

        Le chemin réactif (`handlers._respond`) lit cette mémoire pour bâtir le
        contexte de conversation. Sans cet enregistrement, les messages de la boucle
        cognitive (SPEAK / DM) restent invisibles au chemin réactif : Wally oublie
        ses propres questions spontanées et les nie quand on lui répond.
        """
        memory = getattr(self._bot, "memory", None)
        if memory is None:
            return
        try:
            memory.append_prelude(channel_id, self._self_name(), message)
            memory.append_message(channel_id, self._self_name(), message, platform="discord")
        except Exception as e:  # noqa: BLE001 — ne jamais faire crasher la boucle cognitive
            logger.warning("Enregistrement contexte message spontané échoué: {}", e)

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
        owner_id = self._owner_id()
        if not owner_id:
            logger.warning("DM impossible: owner non configuré (owner_discord_id vide)")
            return
        if user_id != owner_id:
            logger.warning("DM non autorisé vers {} (réservé au créateur)", user_id)
            return
        # Un seul fil de sollicitation owner à la fois : si un MP attend déjà sa
        # réponse, on ne superpose pas une nouvelle sollicitation.
        if self._gate is not None and self._gate.is_blocked():
            logger.info("Cognitive DM supprimé (sollicitation owner déjà en attente)")
            if self._feed:
                self._feed.publish({
                    "type": "DM_SUPPRESSED",
                    "reason": "sollicitation owner déjà en attente de réponse",
                    "message": message[:300],
                })
            return
        # Anti-harcèlement : pas de DM créateur proactif rapproché (relance d'un
        # sujet en attente). Le reasoning_system décourage déjà ; ceci est le filet.
        now = time.monotonic()
        if self._last_dm_ts and (now - self._last_dm_ts) < DM_CREATOR_COOLDOWN:
            mins = (now - self._last_dm_ts) / 60
            logger.info("Cognitive DM supprimé (cooldown {:.0f}min)", mins)
            if self._feed:
                self._feed.publish({
                    "type": "DM_SUPPRESSED",
                    "reason": f"cooldown {int(mins)}min/{DM_CREATOR_COOLDOWN // 60}min",
                    "message": message[:300],
                })
            return
        try:
            try:
                user = await self._bot.fetch_user(int(user_id))
            except Exception as e:
                logger.warning("dm: utilisateur {} introuvable: {}", user_id, e)
                return
            sent = await user.send(message)
            self._last_dm_ts = now
            if self._gate is not None:
                self._gate.mark_sent()
            logger.info("Cognitive DM → {} : {}", user_id, message[:80])
            channel = getattr(sent, "channel", None)
            if channel is not None:
                self._record_self_message(str(channel.id), message)
            if self._feed:
                self._feed.publish({"type": "DM", "target": "créateur", "message": message[:300]})
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
                # Dédup sémantique à l'écriture (Phase 3) : si un désir actif
                # exprime déjà la même intention, on le RAFRAÎCHIT (support++ +
                # last_seen) au lieu d'en empiler un paraphrasé de plus.
                existing = await self._facts.search_by_category(
                    FactCategory.DESIRE, status=FactStatus.ACTIVE, limit=25
                )
                dup = next(
                    (d for d in existing if _same_desire(content, d.content)), None
                )
                if dup is not None and dup.id is not None:
                    await self._facts.confirm(dup.id)
                    logger.info("ACT create_desire: doublon fusionné → #{} ({})", dup.id, content[:50])
                    if self._feed:
                        self._feed.publish({"type": "ACT", "detail": f"desire fusionné: {content[:300]}"})
                else:
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

        elif act_name == "drop_desire" and self._facts:
            # Clore un désir résolu / caduc (Phase 3). Accepte un id explicite ou
            # une description (on archive le désir actif le plus proche).
            raw_id = args.get("desire_id")
            desc = (args.get("description") or "").strip()
            target_id: int | None = None
            if raw_id is not None:
                try:
                    target_id = int(raw_id)
                except (TypeError, ValueError):
                    target_id = None
            if target_id is None and desc:
                actives = await self._facts.search_by_category(
                    FactCategory.DESIRE, status=FactStatus.ACTIVE, limit=25
                )
                match = next((d for d in actives if _same_desire(desc, d.content)), None)
                target_id = match.id if match else None
            if target_id is not None:
                await self._facts.set_status(target_id, FactStatus.ARCHIVED)
                logger.info("ACT drop_desire: #{} archivé", target_id)
                if self._feed:
                    self._feed.publish({"type": "ACT", "detail": f"drop_desire #{target_id}"})
            else:
                logger.warning("ACT drop_desire: aucun désir cible ({!r}/{!r})", raw_id, desc[:50])

        elif act_name == "doubt_memory" and self._facts:
            # Marquer un souvenir comme non vérifié / hallucination probable
            # (Phase 3) : needs_review + confiance / 2. id explicite ou description
            # (recherche FTS dans la mémoire propre de Wally).
            raw_id = args.get("fact_id")
            desc = (args.get("description") or "").strip()
            target_id = None
            if raw_id is not None:
                try:
                    target_id = int(raw_id)
                except (TypeError, ValueError):
                    target_id = None
            if target_id is None and desc:
                hits = await self._facts.search_fts("wally:self", desc, limit=1)
                target_id = hits[0][0].id if hits else None
            if target_id is not None:
                await self._facts.doubt(target_id)
                logger.info("ACT doubt_memory: #{} marqué needs_review", target_id)
                if self._feed:
                    self._feed.publish({"type": "ACT", "detail": f"doubt_memory #{target_id}"})
            else:
                logger.warning("ACT doubt_memory: aucune cible ({!r}/{!r})", raw_id, desc[:50])

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
            # Planification temporelle (#A3) : un délai relatif `in_minutes` pose une
            # échéance (UTC naïf, cohérent avec get_due_facts) → le rappel reviendra
            # à la conscience le moment venu via le tick cognitif. Borné à 7 jours.
            scheduled_at = None
            raw_minutes = args.get("in_minutes")
            if raw_minutes is not None:
                try:
                    mins = int(raw_minutes)
                except (TypeError, ValueError):
                    mins = 0
                if mins > 0:
                    from datetime import timedelta
                    scheduled_at = datetime.utcnow() + timedelta(minutes=min(mins, 7 * 24 * 60))
            await self._facts.add(AtomicFact(
                user_id="wally:self",
                content=note,
                category=cat,
                source="note_to_self",
                confidence=1.0,
                scheduled_at=scheduled_at,
                created_at=now,
                last_seen_at=now,
            ))
            logger.info(
                "ACT note_to_self ({}): {}{}", kind, note[:60],
                f" [dans {raw_minutes} min]" if scheduled_at else "",
            )
            if self._feed:
                self._feed.publish({"type": "ACT", "detail": f"note ({kind}): {note[:300]}"})

        elif act_name == "set_focus" and self._facts:
            focus = (args.get("focus") or "").strip()
            if not focus:
                return
            # Cooldown : pas plus d'un set_focus toutes les 10 min.
            now_mono = time.monotonic()
            if now_mono - self._last_focus_ts < 600:
                logger.debug("set_focus ignoré (cooldown 10 min)")
                return
            # Récupérer le focus actuel pour la garde de similarité.
            old = await self._facts.get_latest_by_source("wally:self", "focus")
            # Similarité : refuser si la reformulation est quasi identique (≥ 75%).
            if old is not None and old.content:
                _ws = re.compile(r"\s+")
                na = _ws.sub(" ", focus.strip().lower())[:300]
                nb = _ws.sub(" ", old.content.strip().lower())[:300]
                if difflib.SequenceMatcher(None, na, nb).ratio() >= 0.85:
                    logger.debug("set_focus ignoré (trop similaire : '{}')", old.content[:60])
                    return
            self._last_focus_ts = now_mono
            # Une seule préoccupation active à la fois : archive la précédente.
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

        elif act_name == "note_emote" and self._facts:
            emote = (args.get("emote") or "").strip().strip(":")
            usage = (args.get("usage") or "").strip()
            if not emote or not usage:
                return
            # Une seule note active par emote : archive la précédente sur la même
            # emote (son usage peut se préciser au fil des explications du créateur).
            existing = await self._facts.get_by_user(
                "wally:emotes", categories=[FactCategory.PREF]
            )
            for f in existing:
                if f.id is not None and f.content.lower().startswith(f"{emote.lower()} →"):
                    await self._facts.set_status(f.id, FactStatus.ARCHIVED)
            await self._facts.add(AtomicFact(
                user_id="wally:emotes",
                content=f"{emote} → {usage}",
                category=FactCategory.PREF,
                source="emote_note",
                confidence=1.0,
                created_at=now,
                last_seen_at=now,
            ))
            logger.info("ACT note_emote: {} → {}", emote, usage[:50])
            if self._feed:
                self._feed.publish({"type": "ACT", "detail": f"emote apprise : :{emote}:"})

        elif act_name == "code_fix":
            self_fix = getattr(self._bot, "self_fix", None) if self._bot else None
            if self_fix is None:
                logger.warning(
                    "ACT code_fix: SelfFix non disponible (BRIDGE_SECRET non configuré)"
                )
                return
            goal = args.get("goal", "").strip()
            if not goal:
                logger.warning("ACT code_fix ignoré: goal vide")
                return
            from bot.intelligence.self_fix import UpgradeRequest
            asyncio.create_task(self_fix.request_upgrade(UpgradeRequest(goal=goal)))
            logger.info("ACT code_fix: demande d'auto-modif — {}", goal[:60])
            if self._feed:
                self._feed.publish({"type": "ACT", "detail": f"auto-modif : {goal[:60]}"})

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
