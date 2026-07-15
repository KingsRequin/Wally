from __future__ import annotations

import asyncio
import difflib
import random
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from loguru import logger

from bot.intelligence.identity import bot_name
from bot.intelligence.social_rhythm import R_REF

TICK_ACTIVE = 30       # < 10 min depuis dernière activité : cognition de fond vive
TICK_MODERATE = 120    # < 1h : il se détend, encore engagé
TICK_IDLE = 300        # > 1h : plancher du vagabondage idle (5 min)
TICK_IDLE_MAX = 3600   # plafond du vagabondage idle (1h)


def _speak_pass_probability(receptivity: float) -> float:
    """Proba de laisser passer un SPEAK spontané. ≥ R_REF → 1.0 (journée normale,
    aucun frein) ; en-dessous, décroît linéairement → nuits quasi silencieuses.
    Aucun seuil horaire : `receptivity` sort des stats apprises."""
    if receptivity >= R_REF:
        return 1.0
    return max(0.0, receptivity / R_REF)


def _now_paris() -> datetime:
    return datetime.now(ZoneInfo("Europe/Paris"))

# Après une réponse directe dans un canal, Wally ne relance pas de SPEAK proactif
# avant ce délai : il a déjà eu son tour, un SPEAK ne ferait que récapituler /
# ressasser une conversation close (bug du "repost" cognitif).
REPLY_SPEAK_COOLDOWN = 600  # 10 min

# Nombre de ressassements consécutifs d'un focus avant de le laisser mourir.
RUMINATION_LIMIT = 2

# Boucle de feedback émotion→action→résultat (#A6) : les émotions de Wally
# réagissent à l'issue sociale de ses prises de parole spontanées, comme un
# humain. Magnitudes volontairement faibles (le moteur décroît + sature) ; ce
# sont des constantes de réactivité (cf. facteurs de suppression d'emotion.py),
# pas des seuils comportementaux appris (ça, c'est le rôle de SocialRhythm).
SOCIAL_FEEDBACK_JOY = 0.1     # on lui répond → bouffée de joie
SOCIAL_IGNORED_ANGER = 0.05  # ignoré malgré l'insistance → agacement (une fois)

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
        social_rhythm=None,
        web_search=None,
        web_search_cooldown_s: float = 2700.0,
        bedroom_channel_id: int | str | None = None,
        spontaneous_channel_speak_enabled: bool = False,
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
        # Rythme social appris (SocialRhythm). None → aucun frein, cadence inchangée.
        self._social_rhythm = social_rhythm
        # Recherche web déclenchée par la cognition (chantier B self-model). None →
        # capacité absente. Cooldown anti-boucle + horodatage du dernier appel.
        self._web_search = web_search
        self._web_search_cooldown_s = web_search_cooldown_s
        # -inf et pas 0.0 : time.monotonic() compte depuis le BOOT DE LA MACHINE,
        # pas depuis le démarrage du process. 0.0 signifierait « recherché au
        # boot » (donc sous cooldown pendant 45 min après chaque reboot hôte) au
        # lieu de « jamais » — -inf rend l'écart infini, donc jamais sous cooldown.
        self._web_search_cooldown_ts = float("-inf")
        # Anti-rumination sémantique : nombre de ressassements consécutifs du focus.
        self._focus_rumination_count = 0
        # Canaux textuels de l'annuaire où Wally peut parler proactivement.
        self._speakable_channels = speakable_channels or set()
        # Salon « chambre » : cible UNIQUE de toute prise de parole spontanée.
        # None → routage historique (dernier canal actif). Stocké en str pour
        # coller au format des channel_id manipulés ici.
        self._bedroom_channel_id = str(bedroom_channel_id) if bedroom_channel_id else None
        # Prise de parole spontanée dans les canaux. False → Wally pense (THINK,
        # feed) mais ne broadcaste plus ses pensées de sa propre initiative ;
        # seuls un rappel dû (forced_seed) ou un ACT (DM owner…) franchissent.
        self._spontaneous_channel_speak_enabled = spontaneous_channel_speak_enabled
        self._last_activity_ts: float = 0.0
        self._last_tick_activity_ts: float = 0.0
        # Activité qui VISE Wally (mention, réponse, DM, vocal) — distincte de la
        # perception passive plein-canal. La cadence vive (TICK_ACTIVE) ne se
        # déclenche que sur celle-ci : sinon ~90 pensées/h sur du vagabondage
        # déclenché par du bruit de canal qui ne le concerne pas (Phase 2c).
        # -inf et pas 0.0 : time.monotonic() compte depuis le BOOT DE LA MACHINE,
        # pas depuis le démarrage du process. 0.0 signifierait « activité
        # pertinente au boot » (donc cadence vive pendant 1h après chaque reboot
        # hôte) au lieu de « jamais » — -inf rend l'écart infini, donc idle direct.
        self._last_relevant_activity_ts: float = float("-inf")
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
        relevant: bool = False, user_key: str | None = None,
    ) -> None:
        self._last_activity_ts = time.monotonic()
        # Vivacité du créneau courant (signal ambient du rythme social) — best-effort.
        if self._social_rhythm is not None:
            try:
                self._social_rhythm.record_incoming(_now_paris())
            except Exception as e:  # noqa: BLE001
                logger.warning("SocialRhythm.record_incoming: {}", e)
        # Un DM ou un message qui mentionne Wally le VISE directement → cadence
        # vive. La perception passive d'un canal (relevant=False) ne réveille pas
        # la cognition rapide : elle reste perçue (recent_interactions) mais le
        # tick suit la cadence idle.
        if relevant or is_dm:
            self._last_relevant_activity_ts = self._last_activity_ts
        # Quelqu'un a parlé dans ce canal → ses messages spontanés y ont reçu
        # une suite : c'est une RÉPONSE → issue d'engagement positive, puis on
        # remet le compteur « sans réponse » à zéro.
        st = self._spontaneous.get(str(channel_id))
        if st is not None and st.get("unanswered", 0) > 0:
            if self._social_rhythm is not None:
                try:
                    self._social_rhythm.record_spontaneous_outcome(True, _now_paris())
                except Exception as e:  # noqa: BLE001
                    logger.warning("SocialRhythm outcome(+): {}", e)
            # Feedback émotionnel positif (#A6) : on lui a répondu → un peu de joie.
            if self._emotion is not None:
                try:
                    self._emotion.apply_delta("joy", SOCIAL_FEEDBACK_JOY)
                except Exception as e:  # noqa: BLE001 — jamais bloquant
                    logger.warning("apply_delta(joy) social feedback: {}", e)
            st["unanswered"] = 0
            # Nouvel épisode d'engagement : la pénalité d'abandon pourra se reposer.
            st["penalized"] = False
        self._recent_interactions.append({
            "channel": str(channel_id),
            "author": author,
            # Garde le message large : le rendu (reasoning_agent._one_line, 220)
            # ajoute l'ellipse « … » au point de troncature. Couper trop court ici
            # masquerait la fin et ferait croire à un message incomplet.
            "content": content[:500],
            "message_id": message_id,
            "is_dm": is_dm,
            # "platform:raw_id" de l'auteur → enrichissement mémoire (#A1). None
            # pour les sources qui ne l'exposent pas (rétro-compat).
            "user_key": user_key,
            "ts": self._last_activity_ts,
        })
        if len(self._recent_interactions) > 20:
            self._recent_interactions = self._recent_interactions[-20:]

    def notify_event(
        self, channel_id, description: str, relevant: bool = False,
    ) -> None:
        """Perception d'un événement Discord HORS message (#A2) : réaction sur un
        message, arrivée/départ d'un membre… Le « cerveau » V2 ne percevait que le
        texte ; ces signaux lui échappaient entièrement.

        L'événement entre dans `_recent_interactions` (marqué `is_event`) comme une
        ligne descriptive auto-suffisante → build_context le voit et le reasoning
        le rend dans le bon canal. `relevant=True` (ex. réaction sur un message de
        Wally) réveille la cadence vive ; un événement passif (arrivée serveur) ne
        fait que rafraîchir l'activité, laissant la cognition décider seule.
        """
        self._last_activity_ts = time.monotonic()
        if relevant:
            self._last_relevant_activity_ts = self._last_activity_ts
        self._recent_interactions.append({
            "channel": str(channel_id),
            "author": "(événement)",
            "content": description[:500],
            "message_id": None,
            "is_dm": False,
            "user_key": None,
            "is_event": True,
            "ts": self._last_activity_ts,
        })
        if len(self._recent_interactions) > 20:
            self._recent_interactions = self._recent_interactions[-20:]

    def _penalize_if_ignored(self, st: dict) -> None:
        """Feedback émotionnel négatif (#A6) : un canal qui ignore les relances de
        Wally pique sa colère — UNE seule fois par épisode (le drapeau `penalized`
        évite l'accumulation à chaque tick ; il est remis à zéro quand on lui
        répond enfin, cf. notify_activity)."""
        if st.get("penalized"):
            return
        st["penalized"] = True
        if self._emotion is not None:
            try:
                self._emotion.apply_delta("anger", SOCIAL_IGNORED_ANGER)
            except Exception as e:  # noqa: BLE001 — jamais bloquant
                logger.warning("apply_delta(anger) social feedback: {}", e)

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
        # Réceptivité basse (nuit/creux appris) → plafond allongé : Wally vagabonde
        # plus lentement quand l'audience est absente. Aucun seuil horaire codé.
        if self._social_rhythm is not None:
            try:
                r = self._social_rhythm.receptivity(_now_paris())
                hi = int(hi * (1.0 + 2.0 * (1.0 - max(0.0, min(1.0, r)))))
            except Exception:  # noqa: BLE001
                pass
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

    async def _maybe_web_search(self, context, result):
        """Si la pensée demande une recherche web et que les gardes passent :
        exécute la recherche, injecte le résultat dans le contexte, et relance UNE
        2e passe de raisonnement. Sinon renvoie le `result` initial inchangé.

        Ne fait jamais planter le tick : toute erreur → on garde la 1re pensée.
        Une seule recherche par tick (appelé une fois, sans boucle, depuis _tick).
        """
        if self._web_search is None:
            return result
        ws = next(
            (d for d in result.decisions
             if d.action == "ACT" and d.act_name == "web_search"),
            None,
        )
        if ws is None:
            return result
        query = (ws.act_args or {}).get("query")
        if not query or not isinstance(query, str):
            return result
        now = time.monotonic()
        if now - self._web_search_cooldown_ts < self._web_search_cooldown_s:
            logger.debug("web_search cognitif ignoré (cooldown)")
            return result
        if not self._web_search.available:
            return result
        try:
            if await self._web_search.is_quota_exceeded():
                logger.info("web_search cognitif ignoré (quota Tavily dépassé)")
                return result
        except Exception as e:  # noqa: BLE001
            logger.warning("is_quota_exceeded: {}", e)
            return result
        # Armer le cooldown AVANT l'appel : même un échec compte, pour ne pas
        # marteler Tavily en boucle sur une erreur répétée.
        self._web_search_cooldown_ts = now
        try:
            finding = await self._web_search.search(query, platform="discord")
        except Exception as e:  # noqa: BLE001
            logger.warning("web_search cognitif a échoué: {}", e)
            return result
        if self._feed:
            self._feed.publish({
                "type": "ACT", "name": "web_search",
                "content_snippet": query[:160],
            })
        context.web_finding = f"{query} → {finding}"
        logger.debug("web_search cognitif : 2e passe de raisonnement sur « {} »", query[:60])
        try:
            return await self._reasoning.reason(context)
        except Exception as e:  # noqa: BLE001
            logger.warning("web_search 2e passe échouée, pensée initiale conservée: {}", e)
            return result

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
            # Rappels programmés arrivés à échéance (#A3) : ils reviennent à la
            # conscience comme amorce prioritaire, puis sont désarmés pour ne pas
            # se redéclencher à chaque tick.
            forced_seed = None
            if self._facts is not None:
                try:
                    due = await self._facts.get_due_facts(datetime.utcnow())
                except Exception as e:  # noqa: BLE001 — jamais bloquant
                    logger.warning("get_due_facts: {}", e)
                    due = []
                if due:
                    fact = due[0]
                    forced_seed = (
                        f"Un rappel que tu t'étais fixé est arrivé : {fact.content}"
                    )
                    fid = getattr(fact, "id", None)
                    if fid is not None:
                        try:
                            await self._facts.clear_schedule(fid)
                        except Exception as e:  # noqa: BLE001
                            logger.warning("clear_schedule: {}", e)
            context = await self._attention.build_context(
                emotion_state, self._recent_interactions, spontaneous=spontaneous, idle=is_idle,
                recent_speaks=list(self._recent_speaks),
                forced_seed=forced_seed,
            )
            if self._feed:
                rss_art = getattr(context, "rss_stimulus", None)
                if rss_art:
                    self._feed.publish({
                        "type": "RSS",
                        "feed": rss_art.get("feed_name", ""),
                        "content_snippet": (rss_art.get("title") or "")[:160],
                        "link": rss_art.get("link", ""),
                    })
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
            result = await self._maybe_web_search(context, result)
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

            # La pensée vit. Cadence du compteur de ressassement selon le verdict :
            #  - DIVAGUE : vrai changement de sujet → le fil repart de zéro.
            #  - juge absent (fallback lexical) : comportement legacy, reset.
            #  - PROGRESSE : le fil continue, MAIS le capital de ressassement
            #    accumulé n'est PAS effacé. Sinon une reformulation jugée à tort
            #    « PROGRESSE » (le juge se fait berner par les mots qui changent)
            #    resette tout et le focus devient immortel — c'est la boucle des
            #    11h sur « anti-inférence ». Le compteur est donc cumulatif sur la
            #    vie du fil : R,P,R le tue au 2e ressassement.
            if verdict != "PROGRESSE":
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
            if self._bedroom_channel_id:
                known_channels = known_channels | {self._bedroom_channel_id}
            last_channel = self._recent_interactions[-1]["channel"] if self._recent_interactions else None
            for decision in decisions:
                if decision.action == "SLEEP" and getattr(decision, "sleep_seconds", None):
                    await asyncio.sleep(min(decision.sleep_seconds, 3600))
                    continue
                if decision.action == "SPEAK":
                    # Coupure de la parole spontanée : Wally garde sa vie mentale
                    # (THINK/feed) mais n'exprime plus ses pensées de sa propre
                    # initiative dans un canal. Exception : un rappel programmé
                    # arrivé à échéance (forced_seed) — service demandé, pas un
                    # monologue. Les DM owner passent par un ACT, pas un SPEAK.
                    if not self._spontaneous_channel_speak_enabled and forced_seed is None:
                        self._log_cog(
                            "speak_suppressed", channel=str(decision.channel_id),
                            reason="parole spontanée désactivée (config)",
                            message=(decision.message or "")[:200],
                        )
                        continue
                    # Redirection « chambre » : toute prise de parole spontanée
                    # part dans le salon dédié de Wally, jamais dans le canal
                    # courant (les réponses aux mentions passent par les handlers,
                    # pas par ici). C'est son espace d'expression → les gardes
                    # « ne crie pas dans le vide » (silence idle, messages sans
                    # réponse) n'ont pas de sens ici et sont sautées ; l'anti-
                    # redite et l'amortisseur de rythme social restent actifs.
                    to_bedroom = self._bedroom_channel_id is not None
                    if to_bedroom:
                        decision.channel_id = self._bedroom_channel_id
                    # 0. Canal silencieux depuis >2h en mode idle → ne pas crier dans le vide.
                    #    Il peut continuer à THINK, mais pas à broadcaster vers personne.
                    elapsed_since_activity = now - self._last_activity_ts
                    if not to_bedroom and is_idle and self._last_activity_ts > 0 and elapsed_since_activity > 7200:
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
                    #    Sauté pour la chambre : c'est son journal, pas un canal
                    #    public à ne pas spammer.
                    ch_key = str(decision.channel_id)
                    if not to_bedroom:
                        ch_st = self._spontaneous.get(ch_key, {})
                        unanswered = ch_st.get("unanswered", 0)
                        since_last = now - ch_st.get("last_ts", 0.0)
                        if unanswered >= 3:
                            # Canal qui ignore Wally → issue d'engagement négative.
                            if self._social_rhythm is not None:
                                try:
                                    self._social_rhythm.record_spontaneous_outcome(False, _now_paris())
                                except Exception:  # noqa: BLE001
                                    pass
                            # Feedback émotionnel (#A6) : l'agacement monte, une fois.
                            self._penalize_if_ignored(ch_st)
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
                    # 4. Amortisseur appris : aux heures/jours où l'audience est
                    #    peu réceptive (stats SocialRhythm), la parole spontanée ne
                    #    passe que probabilistiquement. Au-dessus de R_REF : aucun frein.
                    if self._social_rhythm is not None:
                        try:
                            r = self._social_rhythm.receptivity(_now_paris())
                        except Exception:  # noqa: BLE001
                            r = 1.0
                        if random.random() >= _speak_pass_probability(r):
                            logger.info("CognitiveLoop: SPEAK amorti (réceptivité {:.2f})", r)
                            self._log_cog(
                                "speak_suppressed", channel=str(decision.channel_id),
                                reason=f"réceptivité apprise {r:.2f}",
                                message=(decision.message or "")[:200],
                            )
                            continue
                    # 5. Anti-redite : un message-source d'un canal peu actif reste
                    #    "saillant" des heures ; sans garde, Wally re-commente la
                    #    même observation en boucle (cf. Bloodshade, 2 messages
                    #    jumeaux à 10h d'écart). Blocage DUR (le rappel textuel au
                    #    LLM ne suffit pas) : quasi-identité à un SPEAK récent → skip.
                    if decision.message and any(
                        _too_similar(decision.message, sp.get("content", ""))
                        for sp in self._recent_speaks
                    ):
                        logger.info("CognitiveLoop: SPEAK supprimé (redite d'un message spontané récent)")
                        self._log_cog(
                            "speak_suppressed", channel=str(decision.channel_id),
                            reason="redite d'un message spontané récent",
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
                        # Message COMPLET : la relecture (reasoning_agent) applique
                        # elle-même `_one_line` (ellipse « … » explicite). Pré-tronquer
                        # ici donnait à Wally une phrase coupée net qu'il prenait pour
                        # de l'auto-censure et ruminait — cf. boucle « j'ai fini par con… ».
                        "content": decision.message or "",
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
