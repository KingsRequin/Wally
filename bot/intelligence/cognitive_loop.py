from __future__ import annotations

import asyncio
import difflib
import random
import re
import time

from loguru import logger

from bot.intelligence.identity import bot_name

TICK_ACTIVE = 30       # < 10 min depuis dernière activité : cognition de fond vive
TICK_MODERATE = 120    # < 1h : il se détend, encore engagé
TICK_IDLE = 300        # > 1h : plancher du vagabondage idle (5 min)
TICK_IDLE_MAX = 3600   # plafond du vagabondage idle (1h)

# Après une réponse directe dans un canal, Wally ne relance pas de SPEAK proactif
# avant ce délai : il a déjà eu son tour, un SPEAK ne ferait que récapituler /
# ressasser une conversation close (bug du "repost" cognitif).
REPLY_SPEAK_COOLDOWN = 600  # 10 min

# Nombre de ressassements consécutifs d'un focus avant de le laisser mourir.
RUMINATION_LIMIT = 2

_WS_RE = re.compile(r"\s+")


def _too_similar(a: str, b: str) -> bool:
    """True si deux pensées sont quasi identiques (anti-rumination).

    Normalise (lower, strip, espaces collés) ; True si égales, ou si le ratio de
    similarité SequenceMatcher >= 0.92 sur les 400 premiers caractères.
    """
    if not a or not b:
        return False
    na = _WS_RE.sub(" ", a.strip().lower())
    nb = _WS_RE.sub(" ", b.strip().lower())
    if na == nb:
        return True
    return difflib.SequenceMatcher(None, na[:400], nb[:400]).ratio() >= 0.92


class CognitiveLoop:
    def __init__(
        self,
        attention_agent,
        reasoning_agent,
        action_dispatcher,
        emotion_engine=None,
        feed=None,
        speakable_channels: set[str] | None = None,
        conv_log=None,
        fact_store=None,
        progress_judge=None,
    ) -> None:
        self._attention = attention_agent
        self._reasoning = reasoning_agent
        self._dispatcher = action_dispatcher
        self._emotion = emotion_engine
        self._feed = feed
        # Journalise les décisions cognitives non publiées sur le feed —
        # surtout les SPEAK *supprimés* (avec la raison), invisibles autrement.
        self._conv_log = conv_log
        self._facts = fact_store
        self._progress_judge = progress_judge
        # Anti-rumination sémantique : nombre de ressassements consécutifs du focus.
        self._focus_rumination_count = 0
        # Canaux textuels de l'annuaire où Wally peut parler proactivement.
        self._speakable_channels = speakable_channels or set()
        self._last_activity_ts: float = 0.0
        self._last_tick_activity_ts: float = 0.0
        # Activité qui VISE Wally (mention, réponse, DM, vocal) — distincte de la
        # perception passive plein-canal. La cadence vive (TICK_ACTIVE) ne se
        # déclenche que sur celle-ci : sinon ~90 pensées/h sur du vagabondage
        # déclenché par du bruit de canal qui ne le concerne pas (Phase 2c).
        self._last_relevant_activity_ts: float = 0.0
        # Fenêtre glissante des dernières pensées émises → anti-rumination
        # robuste : une reformulation du même thème étalée sur plusieurs ticks
        # (qui échappe à la comparaison au seul tick précédent) est rattrapée en
        # confrontant la nouvelle pensée à TOUTES les pensées récentes.
        self._recent_thoughts: list[str] = []
        self._recent_interactions: list[dict] = []
        # Conscience sociale : par canal, suivi des messages spontanés de Wally
        # restés sans réponse → injecté dans le monologue pour qu'il se régule
        # lui-même (un humain n'insiste pas auprès de qui l'ignore).
        # {channel_id: {"last_ts": monotonic, "unanswered": int}}
        self._spontaneous: dict[str, dict] = {}
        # Historique des 5 derniers SPEAKs envoyés → injecté dans le contexte
        # cognitif pour éviter les répétitions dans la même session.
        self._recent_speaks: list[dict] = []
        # Dernière réponse directe de Wally par canal (monotonic) — un SPEAK
        # proactif est supprimé s'il suit de trop près une vraie réponse.
        self._last_reply: dict[str, float] = {}
        self._task: asyncio.Task | None = None
        self._running = False

    def notify_activity(
        self, channel_id: int, author: str, content: str,
        message_id: str | None = None, is_dm: bool = False,
        relevant: bool = False,
    ) -> None:
        self._last_activity_ts = time.monotonic()
        # Un DM ou un message qui mentionne Wally le VISE directement → cadence
        # vive. La perception passive d'un canal (relevant=False) ne réveille pas
        # la cognition rapide : elle reste perçue (recent_interactions) mais le
        # tick suit la cadence idle.
        if relevant or is_dm:
            self._last_relevant_activity_ts = self._last_activity_ts
        # Quelqu'un a parlé dans ce canal → ses messages spontanés y ont reçu
        # une suite : on remet le compteur « sans réponse » à zéro.
        st = self._spontaneous.get(str(channel_id))
        if st is not None:
            st["unanswered"] = 0
        self._recent_interactions.append({
            "channel": str(channel_id),
            "author": author,
            # Garde le message large : le rendu (reasoning_agent._one_line, 220)
            # ajoute l'ellipse « … » au point de troncature. Couper trop court ici
            # masquerait la fin et ferait croire à un message incomplet.
            "content": content[:500],
            "message_id": message_id,
            "is_dm": is_dm,
            "ts": self._last_activity_ts,
        })
        if len(self._recent_interactions) > 20:
            self._recent_interactions = self._recent_interactions[-20:]

    def notify_reply(self, channel_id, content: str | None = None,
                     author: str | None = None) -> None:
        """Wally vient de répondre directement dans ce canal (via les handlers).

        Deux rôles :
        1. Anti-récap court terme : `_last_reply` supprime un SPEAK proactif dans
           les minutes qui suivent (REPLY_SPEAK_COOLDOWN).
        2. **Anti-répétition** : inscrit la réponse de Wally dans
           `_recent_interactions` pour que le flux cognitif voie la conversation
           COMPLÈTE (question + réponse de Wally). Sans ça, le cognitif ne voit
           que les messages des autres et croit qu'une question déjà traitée est
           restée sans réponse → il y re-répond spontanément (bug du doublon).
        """
        self._last_reply[str(channel_id)] = time.monotonic()
        # Wally vient de répondre à quelqu'un qui l'a sollicité → conversation
        # active qui le concerne : on garde la cadence vive.
        self._last_relevant_activity_ts = time.monotonic()
        if content:
            self._recent_interactions.append({
                "channel": str(channel_id),
                "author": author or bot_name(),
                "content": content[:500],
                "message_id": None,
                "ts": time.monotonic(),
                "is_self": True,
            })
            if len(self._recent_interactions) > 20:
                self._recent_interactions = self._recent_interactions[-20:]

    def _log_cog(self, event_type: str, **fields) -> None:
        """Journalise un événement cognitif dans logs/conversations/cognitive/brain/."""
        if self._conv_log is not None:
            self._conv_log.log("cognitive", "brain", event_type, **fields)

    def _tick_interval(self) -> int:
        # Cadence basée sur l'activité qui VISE Wally, pas la perception passive :
        # un canal qui bouge sans le concerner ne le fait plus penser toutes les
        # 30 s (Phase 2c).
        elapsed = time.monotonic() - self._last_relevant_activity_ts
        if elapsed < 600:
            return TICK_ACTIVE
        if elapsed < 3600:
            return TICK_MODERATE
        # Seul/idle : l'esprit vagabonde par à-coups irréguliers (effet naturel),
        # pas sur une horloge fixe. Intervalle aléatoire 5 min – 1 h, mais l'ennui
        # raccourcit le plafond (Phase 1b) : plus Wally s'ennuie, plus vite il
        # vagabonde pour chercher de la stimulation. ennui=0 → plage complète ;
        # ennui=1 → toujours 5 min.
        boredom = 0.0
        if self._emotion is not None:
            try:
                boredom = float(self._emotion.get_state().get("boredom", 0.0))
            except Exception:
                boredom = 0.0
        hi = int(TICK_IDLE + (TICK_IDLE_MAX - TICK_IDLE) * (1.0 - min(1.0, max(0.0, boredom))))
        return random.randint(TICK_IDLE, max(TICK_IDLE, hi))

    async def _expire_focus(self) -> None:
        """Archive le focus actif ressassé → `preoccupation` redevient None au
        prochain tick, et l'amorce de nouveauté reprend la main."""
        if self._facts is None:
            return
        try:
            focus = await self._facts.get_latest_by_source("wally:self", "focus")
            fid = getattr(focus, "id", None) if focus else None
            if fid is not None:
                from bot.intelligence.memory.facts import FactStatus
                await self._facts.set_status(fid, FactStatus.ARCHIVED)
                logger.info("CognitiveLoop : focus ressassé expiré (#{})", fid)
        except Exception as e:
            logger.warning("_expire_focus a échoué : {}", e)

    async def _tick(self) -> None:
        # Pas de nouvelle activité depuis le dernier tick → cognition « idle » :
        # Wally pense quand même, mais à partir d'une amorce de nouveauté (souvenir,
        # but, désir, émotion, heure) pour vagabonder sans ruminer le même contexte.
        is_idle = (self._last_activity_ts == self._last_tick_activity_ts)
        self._last_tick_activity_ts = self._last_activity_ts
        try:
            now = time.monotonic()
            emotion_state = self._emotion.get_state() if self._emotion is not None else {}
            spontaneous = [
                {"channel": ch, "unanswered": st["unanswered"], "seconds_since": int(now - st["last_ts"])}
                for ch, st in self._spontaneous.items()
                if st["unanswered"] > 0
            ]
            context = await self._attention.build_context(
                emotion_state, self._recent_interactions, spontaneous=spontaneous, idle=is_idle,
                recent_speaks=list(self._recent_speaks),
            )
            if self._feed:
                if is_idle:
                    self._feed.publish({
                        "type": "ATTN",
                        "target": "—",
                        "content_snippet": (getattr(context, "idle_seed", None) or "(vagabondage)")[:160],
                    })
                else:
                    _last = self._recent_interactions[-1] if self._recent_interactions else {}
                    self._feed.publish({
                        "type": "ATTN",
                        "target": _last.get("author", "—"),
                        "content_snippet": (_last.get("content") or "")[:160],
                    })
            result = await self._reasoning.reason(context)
            # Anti-rumination sémantique : le juge classe la pensée fraîche face au
            # focus et aux pensées récentes. RESSASSE → on ne publie pas, on archive
            # la pensée déjà stockée (sinon elle ré-amorce la boucle via recent_thoughts),
            # et on rapproche le focus de sa mort. Fallback lexical si le juge échoue.
            verdict = None
            if self._progress_judge is not None and result.thought_text:
                try:
                    verdict = await self._progress_judge.judge(
                        result.thought_text,
                        getattr(context, "preoccupation", None),
                        self._recent_thoughts,
                    )
                except Exception as e:
                    logger.warning("ThoughtProgressJudge a échoué, fallback lexical : {}", e)
                    verdict = None

            if verdict == "RESSASSE":
                from bot.intelligence.memory.facts import FactStatus
                if self._facts is not None and result.thought_fact_id:
                    try:
                        await self._facts.set_status(result.thought_fact_id, FactStatus.ARCHIVED)
                    except Exception as e:
                        logger.warning("Archivage pensée ressassée échoué : {}", e)
                self._focus_rumination_count += 1
                self._log_cog(
                    "think_skipped",
                    reason="ressassement (juge de progression)",
                    thought=(result.thought_text or "")[:200],
                )
                if self._focus_rumination_count >= RUMINATION_LIMIT:
                    await self._expire_focus()
                    self._focus_rumination_count = 0
                return

            # Fallback lexical : juge absent ou en échec → ancien filtre 0.92.
            if verdict is None and result.thought_text and any(
                _too_similar(result.thought_text, t) for t in self._recent_thoughts
            ):
                logger.debug("CognitiveLoop: pensée quasi identique (fenêtre récente), repos")
                self._log_cog(
                    "think_skipped",
                    reason="pensée quasi identique à une pensée récente",
                    thought=(result.thought_text or "")[:200],
                )
                return

            # PROGRESSE / DIVAGUE → la pensée vit ; le focus repart de zéro.
            self._focus_rumination_count = 0
            self._recent_thoughts.append(result.thought_text)
            if len(self._recent_thoughts) > 6:
                self._recent_thoughts = self._recent_thoughts[-6:]
            if self._feed:
                self._feed.publish({"type": "THINK", "text": result.thought_text})
            decisions = result.decisions
            if self._feed:
                self._feed.publish({"type": "DECIDE", "actions": [d.action for d in decisions]})
            # Routage SPEAK spontané : Wally peut viser N'IMPORTE QUEL canal
            # textuel de l'annuaire (choix proactif : un meme → #memes, etc.) OU
            # un canal récemment actif. Si le channel_id sort de ce périmètre
            # (souvent halluciné en cognition de fond), on le redirige vers le
            # dernier canal réellement actif ; sans aucun canal connu, on n'envoie
            # rien (pas de vide).
            known_channels = self._speakable_channels | {i["channel"] for i in self._recent_interactions}
            last_channel = self._recent_interactions[-1]["channel"] if self._recent_interactions else None
            for decision in decisions:
                if decision.action == "SLEEP" and getattr(decision, "sleep_seconds", None):
                    await asyncio.sleep(min(decision.sleep_seconds, 3600))
                    continue
                if decision.action == "SPEAK":
                    # 0. Canal silencieux depuis >2h en mode idle → ne pas crier dans le vide.
                    #    Il peut continuer à THINK, mais pas à broadcaster vers personne.
                    elapsed_since_activity = now - self._last_activity_ts
                    if is_idle and self._last_activity_ts > 0 and elapsed_since_activity > 7200:
                        logger.info(
                            "CognitiveLoop: SPEAK supprimé (idle + silence {:.0f}min)",
                            elapsed_since_activity / 60,
                        )
                        self._log_cog(
                            "speak_suppressed", channel=str(decision.channel_id),
                            reason="idle+silence>2h", message=(decision.message or "")[:200],
                        )
                        continue
                    # 1. Redirection canal inconnu (hallucination LLM) — AVANT le cooldown
                    if decision.channel_id not in known_channels:
                        if last_channel:
                            logger.debug(
                                "CognitiveLoop: SPEAK canal {} inconnu → redirigé vers {}",
                                decision.channel_id, last_channel,
                            )
                            decision.channel_id = last_channel
                        else:
                            logger.info("SPEAK abandonné : aucun canal actif où parler")
                            continue
                    if decision.channel_id is None:
                        continue
                    # 2. Cooldown progressif : 0 sans réponse → ok
                    #    1 sans réponse → 5 min, 2 → 15 min, 3+ → bloqué
                    ch_key = str(decision.channel_id)
                    ch_st = self._spontaneous.get(ch_key, {})
                    unanswered = ch_st.get("unanswered", 0)
                    since_last = now - ch_st.get("last_ts", 0.0)
                    if unanswered >= 3:
                        logger.info("CognitiveLoop: SPEAK bloqué ({} sans réponse)", unanswered)
                        self._log_cog(
                            "speak_suppressed", channel=ch_key,
                            reason=f"{unanswered} messages sans réponse",
                            message=(decision.message or "")[:200],
                        )
                        continue
                    cooldown = 300 if unanswered == 1 else 900 if unanswered == 2 else 0
                    if cooldown and since_last < cooldown:
                        logger.info("CognitiveLoop: SPEAK bloqué (cooldown {}s/{}, {} sans réponse)", int(since_last), cooldown, unanswered)
                        self._log_cog(
                            "speak_suppressed", channel=ch_key,
                            reason=f"cooldown {int(since_last)}s/{cooldown}s ({unanswered} sans réponse)",
                            message=(decision.message or "")[:200],
                        )
                        continue
                    # 3. Anti-redondance : Wally vient de répondre directement dans
                    #    ce canal → un SPEAK proactif ne ferait que récapituler une
                    #    conversation close. On le supprime.
                    last_reply = self._last_reply.get(ch_key, 0.0)
                    if last_reply and (now - last_reply) < REPLY_SPEAK_COOLDOWN:
                        logger.info(
                            "CognitiveLoop: SPEAK supprimé (réponse directe il y a {:.0f}s dans ce canal)",
                            now - last_reply,
                        )
                        self._log_cog(
                            "speak_suppressed", channel=ch_key,
                            reason=f"réponse directe il y a {int(now - last_reply)}s (anti-récap)",
                            message=(decision.message or "")[:200],
                        )
                        continue
                await self._dispatcher.dispatch(decision)
                # Mémorise un message spontané pour la conscience sociale : tant
                # que personne n'y répond, le compteur grimpe et le prochain
                # monologue verra qu'il parle dans le vide.
                if decision.action == "SPEAK" and decision.channel_id:
                    st = self._spontaneous.setdefault(
                        str(decision.channel_id), {"last_ts": now, "unanswered": 0}
                    )
                    st["last_ts"] = time.monotonic()
                    st["unanswered"] += 1
                    self._recent_speaks.append({
                        "channel": str(decision.channel_id),
                        "content": (decision.message or "")[:200],
                        "ts": time.time(),
                    })
                    if len(self._recent_speaks) > 5:
                        self._recent_speaks = self._recent_speaks[-5:]
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("CognitiveLoop tick error: {}", e)

    async def _run(self) -> None:
        logger.info("CognitiveLoop démarrée")
        while self._running:
            interval = self._tick_interval()
            await asyncio.sleep(interval)
            if not self._running:
                break
            await self._tick()

    def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("CognitiveLoop task créée (tick adaptatif 30s/2min/5min)")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("CognitiveLoop arrêtée")
