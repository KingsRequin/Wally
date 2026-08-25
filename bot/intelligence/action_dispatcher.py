from __future__ import annotations

import asyncio
import difflib
import re
import time
from datetime import datetime

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


def _peremption_desir(texte: str) -> datetime | None:
    """Échéance d'un désir daté, ou None s'il est durable.

    Réutilise `_compute_expiry` du fact_extractor : son garde-fou force déjà un TTL
    dès qu'un marqueur temporel apparaît dans le texte (« ce soir », « aujourd'hui »,
    « demain », « ce week-end »). C'est exactement ce qu'il fallait ici, et il ne
    manquait que l'appel : les 156 désirs actifs du 2026-08-09 avaient tous
    `expires_at = NULL`, dont six « lire le blog Hytale aujourd'hui à 16h » encore
    vivants un mois après l'heure dite.

    Best-effort : une erreur ici ne doit jamais empêcher d'enregistrer le désir.
    """
    try:
        from bot.intelligence.fact_extractor import _compute_expiry

        return _compute_expiry(None, texte, datetime.utcnow())
    except Exception as e:  # noqa: BLE001 — jamais bloquant
        logger.warning("péremption de désir non calculée: {!r}", e)
        return None


def _same_desire(a: str, b: str, threshold: float = 0.5) -> bool:
    """True si deux désirs expriment la même intention (Jaccard de tokens ≥ seuil).
    Robuste aux paraphrases qui partagent les mots porteurs (entités, verbes), là
    où la similarité caractère échoue. Isolé pour pouvoir évoluer (cf. spec)."""
    ta, tb = _desire_tokens(a), _desire_tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= threshold


class ActionDispatcher:
    # Défauts de CLASSE, et pas seulement d'`__init__` : plusieurs appelants
    # (dont des tests) construisent un dispatcher par `__new__` ou n'appellent
    # `_act` que directement. Un compteur de journal ne doit jamais faire lever
    # l'action qu'il observe.
    _thought_id: str | None = None
    _act_events: int = 0
    _motif_refus: str | None = None

    def __init__(
        self,
        bot=None,
        persona_manager=None,
        fact_store=None,
        feed=None,
        twitch_bot=None,
        gate=None,
        speak_guard=None,
        overlay_narrator=None,
        image_initiative=None,
    ) -> None:
        # Overlay de stream : Wally DÉCIDE d'afficher un widget, il n'exécute pas
        # une commande. C'est ce qui lui permet de refuser, de commenter, ou de
        # proposer de lui-même — un widget télécommandé serait un gadget.
        self._overlay_narrator = overlay_narrator
        # Génération d'image de sa propre initiative : l'objet ne génère rien, il
        # dit seulement où et à quelle cadence Wally a le droit d'y aller. Le
        # MÊME objet sert au prompt de cognition — deux listes divergeraient.
        self._image_initiative = image_initiative
        self._bot = bot
        self._twitch_bot = twitch_bot
        self._persona = persona_manager
        self._facts = fact_store
        self._feed = feed
        # Gate de sollicitation owner (un seul fil à la fois). None → pas de gate.
        self._gate = gate
        # Filet anti-message-inutile avant envoi spontané. None → pas de filtre.
        self._speak_guard = speak_guard
        self._last_focus_ts: float = 0.0
        self._last_dm_ts: float = 0.0
        # Identité de la pensée en cours de dispatch, agrafée aux ACT qu'elle
        # produit. `dispatch` est attendu (`await`) décision par décision par
        # l'unique boucle cognitive : un seul dispatch est en vol à la fois.
        self._thought_id: str | None = None
        # Compteur d'ACT réellement publiés, pour repérer les actions décidées
        # qui s'éteignent en silence (cf. `_publish_act`).
        self._act_events: int = 0
        # Motif du dernier refus d'ACT, quand la branche le connaît (cf.
        # `_dispatch_act`). Remis à None à chaque dispatch.
        self._motif_refus: str | None = None
        # Références fortes des tâches détachées : la boucle asyncio n'en garde
        # qu'une référence FAIBLE, donc le GC peut annuler une tâche en cours.
        # Le motif est appliqué partout ailleurs (`cognitive_loop`, `emotion`,
        # `fact_extractor`) ; ce fichier était le seul à s'en passer.
        self._bg_tasks: set[asyncio.Task] = set()

    def _fire(self, coro) -> asyncio.Task:
        """Détache une coroutine en gardant sa référence et en loguant son échec."""
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)

        def _fini(t: asyncio.Task) -> None:
            self._bg_tasks.discard(t)
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                # Sans ça, l'exception n'apparaît qu'au ramassage, sous la forme
                # « Task exception was never retrieved » — hors de loguru.
                logger.warning("Tâche détachée du dispatcher en échec: {e}", e=exc)

        task.add_done_callback(_fini)
        return task

    def _publish_act(self, label: str, body: str) -> None:
        """Event ACT avec snippet (≤300) + texte complet (full, ≤2000) →
        dépliable côté site (#observability A5).

        Point de passage UNIQUE des ACT publiés : c'est ce qui permet de savoir,
        à la sortie de `_act`, si l'action a laissé une trace ou s'est éteinte en
        silence. Les branches qui publiaient leur event à la main y échappaient,
        et c'est exactement le trou qu'on mesurait à 20 % — 66 actions décidées,
        56 journalisées, sans qu'on sache lesquelles ni pourquoi.
        """
        # Compté même sans feed : ce compteur dit « l'action est allée au bout »,
        # pas « le site l'a vue ». Sans feed, toutes les actions passaient
        # sinon pour rejetées.
        self._act_events += 1
        if not self._feed:
            return
        full = f"{label}{body}"
        self._feed.publish({
            "type": "ACT", "detail": full[:300], "full": full[:2000],
            "thought_id": self._thought_id,
        })

    def _note_overlay_refus(self, widget: str, extra: dict) -> None:
        """Consigne le refus opposé à une initiative, pour qu'il le lise.

        Deux refus possibles, et ils ne se disent pas pareil : une partie du
        même type tourne déjà, ou personne n'a demandé celle-ci. Le second est
        le seul que cette voie puisse rencontrer sur un overlay vierge — c'est
        lui qui ferme les ouvertures spontanées de bingo.

        `notify=False` : perception PASSIVE, comme le reste du flux du stream.
        Un refus ne doit surtout pas réveiller la cadence — ce serait rendre
        payante l'insistance qu'on cherche justement à calmer.
        """
        narrator = self._overlay_narrator
        try:
            occupe = (narrator.game_already_running(widget, **extra)
                      or narrator.refus_faute_de_demande(widget, **extra))
        except Exception as exc:  # noqa: BLE001 — un diagnostic ne casse pas un tick
            logger.warning("ACT show_overlay: état de l'overlay illisible: {e!r}", e=exc)
            return
        if not occupe:
            return
        logger.info("ACT show_overlay: {w} refusé — {m}", w=widget, m=occupe[:70])
        try:
            from bot.core.stream_feed import active_stream_feed

            feed = active_stream_feed()
            if feed is not None:
                feed.record(occupe, notify=False)
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            logger.debug("ACT show_overlay: refus non consigné: {e!r}", e=exc)

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

    # Actions que `_act` sait exécuter. Sert au DIAGNOSTIC, jamais au routage :
    # la liste de vérité reste la chaîne de `elif`, et cette copie ne fait que
    # distinguer « outil inconnu » de « outil connu resté silencieux ».
    _ACTIONS_CONNUES = frozenset({
        "show_overlay", "cancel_overlay", "create_memory", "create_goal",
        "create_desire", "advance_goal", "fulfill_goal", "drop_desire",
        "doubt_memory", "react", "dm", "note_to_self", "set_focus",
        "reflect_self", "note_relation", "note_emote", "code_fix",
        "generate_image",
    })

    # Actions qui n'ont, par construction, aucun ACT à publier : leur trace vit
    # ailleurs (event REACT/DM du feed). Les compter comme rejetées ferait du
    # bruit permanent dans le journal.
    _ACTIONS_SANS_TRACE_ACT = frozenset({"react", "dm"})

    async def dispatch(self, decision: MetaDecision) -> None:
        action = decision.action
        self._thought_id = getattr(decision, "thought_id", None)
        try:
            if action == "THINK":
                pass
            elif action == "SPEAK":
                await self._speak(decision.channel_id, decision.message)
            elif action == "ACT":
                await self._dispatch_act(decision)
            elif action == "EVOLVE":
                await self._evolve(decision.section or "", decision.change or "")
            elif action == "SLEEP":
                pass  # handled by CognitiveLoop
            else:
                logger.warning("ActionDispatcher: action inconnue '{}'", action)
                self._journal_act_rejected(action, {}, "action inconnue du dispatcher")
        finally:
            self._thought_id = None

    async def _dispatch_act(self, decision: MetaDecision) -> None:
        """Exécute un ACT et consigne ceux qui n'ont laissé AUCUNE trace.

        20 % des actions décidées disparaissaient sans un mot — 66 décidées, 56
        journalisées — et rien ne disait si c'était un refus, un outil inconnu
        ou une branche qui s'était tue sur un argument manquant. On ne mesure
        pas l'intention ici : on constate simplement qu'aucun ACT n'est sorti,
        ce qui est vrai quelle qu'en soit la cause.
        """
        act_name = decision.act_name or ""
        args = decision.act_args or {}
        avant = self._act_events
        # Motif POSÉ par la branche qui refuse, quand elle sait pourquoi.
        # « action silencieuse (argument manquant, doublon ou refus) » suffit à
        # dire qu'il ne s'est rien passé, jamais à dire quoi faire : sur une
        # action qui coûte de l'argent (`generate_image`), la différence entre
        # « plafond du jour atteint » et « salon interdit » est toute
        # l'information. Écrit ici, lu plus bas, remis à None à chaque dispatch.
        self._motif_refus = None
        try:
            await self._act(act_name, args)
        except Exception as exc:
            self._journal_act_rejected(act_name, args, f"exception : {exc}")
            raise
        if self._act_events != avant:
            # Seul un ACT qui a laissé une trace entre dans sa conscience de
            # soi. `_ACTIONS_SANS_TRACE_ACT` (react, dm) est délibérément
            # EXCLU ici : ces deux-là avalent leur exception et repartent en
            # silence, les compter d'office lui ferait croire qu'il a réagi ou
            # écrit alors qu'il n'a rien fait. Ils se signalent eux-mêmes, à
            # l'endroit où ils ont réellement abouti.
            self._note_acte_abouti(act_name)
        if self._act_events != avant or act_name in self._ACTIONS_SANS_TRACE_ACT:
            return
        if not act_name:
            motif = "nom d'action absent"
        elif act_name not in self._ACTIONS_CONNUES:
            motif = "outil inconnu"
        elif self._service_manquant(act_name):
            motif = f"service indisponible ({self._service_manquant(act_name)})"
        else:
            motif = self._motif_refus or "action silencieuse (argument manquant, doublon ou refus)"
        self._journal_act_rejected(act_name, args, motif)

    def _service_manquant(self, act_name: str) -> str:
        """Le service dont dépend cette action et qui n'est pas câblé, ou ""."""
        if act_name in ("show_overlay", "cancel_overlay") and not self._overlay_narrator:
            return "overlay_narrator"
        if act_name == "code_fix" and getattr(self._bot, "self_fix", None) is None:
            return "self_fix"
        if act_name == "generate_image" and self._image_initiative is None:
            return "image_initiative"
        if act_name not in ("show_overlay", "cancel_overlay", "react", "dm",
                            "code_fix", "generate_image") and not self._facts:
            return "fact_store"
        return ""

    def _note_acte_abouti(self, act_name: str) -> None:
        """Inscrit un ACT qui est allé au bout dans la trace de ses propres actes.

        Seul le NOM de l'action y entre, jamais ses arguments : une note ou un
        souvenir portent du texte libre, et ce bloc part dans tous ses prompts,
        canaux confondus (cf. `self_trace`, § confidentialité).

        Ce qui touche l'overlay est écarté : son effet est déjà tracé par
        `OverlayFeed`, en plus précis (« affiché le widget bingo »). La liste
        est celle de `self_trace` — deux copies finiraient par diverger.
        """
        from bot.core.self_trace import OUTILS_TRACES_AILLEURS, note_act

        if not act_name or act_name in OUTILS_TRACES_AILLEURS:
            return
        note_act(f"tu as agi de ta propre initiative : « {act_name} »")

    def _journal_act_rejected(self, act_name: str, args: dict, motif: str) -> None:
        """Consigne une action décidée qui n'a rien produit. Ne lève jamais."""
        from bot.core.audit_log import conv_log_of, journal

        logger.info("ACT {a} sans effet — {m}", a=act_name or "?", m=motif)
        journal(
            conv_log_of(self._bot, self._twitch_bot), "cognitive", "brain",
            "act_rejected", thought_id=self._thought_id, act_name=act_name,
            reason=motif, args=sorted(args or {}),
        )

    async def _speak(self, channel_id: str | None, message: str | None) -> None:
        if not channel_id or not message:
            return

        # Auto-audit avant envoi : tuer les SPEAK clairement inutiles/redondants.
        if not await self._passes_guard(message, self._recent_self_speak(channel_id)):
            return

        # La cognition ne s'exprime jamais sur Twitch de sa propre initiative :
        # un SPEAK spontané reste sur Discord. Sur Twitch, Wally ne parle que sur
        # mention (chemin réactif twitch/handlers).
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
            logger.error("SPEAK failed: {!r}", e)

    async def _passes_guard(self, message: str, context: str = "", kind: str = "SPEAK") -> bool:
        """Filtre anti-message-inutile. True si on peut envoyer (ou pas de guard).

        Fail-open à tous les étages : pas de guard, ou erreur → on envoie.
        """
        if self._speak_guard is None:
            return True
        try:
            ok, reason = await self._speak_guard.worth_sending(message, context=context)
        except Exception as e:  # noqa: BLE001 — jamais bloquer la boucle
            logger.warning("SpeakGuard: erreur inattendue → envoi ({!r})", e)
            return True
        if ok:
            return True
        logger.info("{} auto-supprimé (guard) : {} — {}", kind, message[:80], reason)
        if self._feed:
            self._feed.publish({
                "type": f"{kind}_SUPPRESSED",
                "reason": f"auto-audit : {reason}",
                "message": message[:300],
            })
        return False

    def _recent_self_speak(self, channel_id: str | None) -> str:
        """Dernier message spontané de Wally dans ce canal — sert de contexte au
        guard pour repérer la redondance. Chaîne vide si rien/indisponible."""
        speaks = getattr(self._bot, "_wally_recent_speaks", None)
        if not speaks or channel_id is None:
            return ""
        try:
            last = speaks.get(int(channel_id))
        except (TypeError, ValueError):
            return ""
        return f"Dernier message de Wally ici : {last}" if last else ""

    def _log_speak(self, platform: str, conv_channel: str, message: str) -> None:
        """Trace un SPEAK cognitif comme message_out dans le conv_log du canal.

        Sans ça, un message spontané réellement envoyé n'apparaît dans AUCUN log
        de canal (seulement, indirectement, dans le brain) — invisible pour le
        débogage chronologique. kind='cognitive' le distingue d'une réponse réactive.
        """
        # Passe par `journal()` et non par `clog.log()` en direct : c'est lui
        # qui masque les secrets à l'écriture, et lui qui alimente la trace de
        # ses propres actes. Un SPEAK écrit à la main échappait aux deux —
        # Wally ne savait pas qu'il venait de prendre la parole tout seul.
        from bot.core.audit_log import journal
        from bot.core.conversation_log import new_trace_id

        clog = getattr(self._bot, "conv_log", None) or getattr(self._twitch_bot, "conv_log", None)
        journal(clog, platform, conv_channel, "message_out",
                trace_id=new_trace_id("cognitive"), kind="cognitive",
                author=self._self_name(), content=message)

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
            logger.warning("Enregistrement contexte message spontané échoué: {!r}", e)

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
                logger.warning("react: message {} introuvable: {!r}", message_id, e)
                return
            # Idempotence : si Wally a DÉJÀ une réaction sur ce message, il ne
            # réagit pas une seconde fois. Source de vérité = Discord lui-même
            # (reaction.me), donc pas d'état à maintenir et survit aux reboots.
            # Évite les rechutes en boucle sur un message figé pendant l'ennui.
            try:
                already = any(getattr(r, "me", False) for r in (message.reactions or []))
            except TypeError:
                already = False
            if already:
                logger.debug("react ignoré: déjà réagi au msg {}", message_id)
                return
            await message.add_reaction(emoji)
            logger.info("Cognitive REACT {} → msg {}", emoji, message_id)
            # Après `add_reaction`, jamais avant : une réaction refusée par
            # Discord ne doit pas lui faire croire qu'il a réagi.
            self._note_acte_abouti(f"react {emoji}")
            if self._feed:
                self._feed.publish({
                    "type": "REACT", "emoji": emoji, "channel": str(channel_id),
                    "detail": f"a réagi {emoji}",
                })
        except Exception as e:
            logger.warning("react failed: {!r}", e)

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
        # Auto-audit : dernier filet contre le DM créateur inutile (le « rapport
        # que personne n'a demandé »). Placé après les gardes gratuites pour ne
        # dépenser l'appel LLM que sur un message réellement sur le point de partir.
        if not await self._passes_guard(message, kind="DM"):
            return
        try:
            try:
                user = await self._bot.fetch_user(int(user_id))
            except Exception as e:
                logger.warning("dm: utilisateur {} introuvable: {!r}", user_id, e)
                return
            from bot.discord.message_split import send_chunked

            # Rapport/long message : découpé en plusieurs messages (limite Discord
            # 2000 car.), sur des frontières propres, envoyés dans l'ordre.
            sent = await send_chunked(user, message)
            self._last_dm_ts = now
            if self._gate is not None:
                self._gate.mark_sent()
            logger.info("Cognitive DM → {} : {}", user_id, message[:80])
            # Ni le destinataire ni le texte : un DM reste privé, et ce bloc
            # part aussi dans ses prompts publics.
            self._note_acte_abouti("dm")
            channel = getattr(sent, "channel", None)
            if channel is not None:
                self._record_self_message(str(channel.id), message)
            if self._feed:
                self._feed.publish({"type": "DM", "target": "créateur", "message": message[:300], "full": message[:2000]})
        except Exception as e:
            logger.warning("DM failed: {!r}", e)

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

    async def _generate_image(self, args: dict) -> None:
        """Fabrique une image et la poste — de sa PROPRE initiative.

        Jusqu'ici, une image n'existait que si quelqu'un tapait `/wally imagine`.
        Wally pouvait vouloir illustrer une remarque ou alimenter un fil de
        memes sans avoir aucun moyen de le faire : il devait solliciter un
        humain. C'est la seule voie qui part de LUI.

        Trois gardes, dans cet ordre : les arguments, la politique
        (`ImageInitiative` — salon ouvert, plafond du jour, délai), puis l'API.
        Le motif d'un refus est POSÉ (`_motif_refus`) et lui est rendu par sa
        propre trace : sans ça, il redemanderait la même image à chaque tick
        sans jamais comprendre pourquoi rien n'arrive.

        Ne lève jamais : une image ratée ne casse pas un tick cognitif.
        """
        from bot.core.self_trace import note_act

        initiative = self._image_initiative
        if initiative is None or self._bot is None:
            logger.debug("ACT generate_image ignoré : initiative ou bot absent")
            return
        channel_id = str(args.get("channel_id") or "").strip()
        prompt = str(args.get("prompt") or "").strip()
        # Sa phrase à lui, facultative : l'image est le message, le texte
        # l'accompagne. Pas de SpeakGuard ici — il juge l'utilité d'un TEXTE et
        # tuerait une légende de trois mots posée sur une image qui, elle, porte
        # tout le propos.
        comment = str(args.get("comment") or "").strip()[:400]
        message_id = str(args.get("message_id") or "").strip()
        if not channel_id or not prompt:
            self._motif_refus = "channel_id ou prompt manquant"
            logger.warning("ACT generate_image : channel_id ou prompt manquant")
            return

        motif = await initiative.refus(channel_id)
        if motif:
            self._motif_refus = motif
            logger.info("ACT generate_image refusé — {m}", m=motif)
            # PASSIF, comme le refus d'overlay : il le lit au tick suivant dans
            # « ce que tu viens de faire », donc il sait qu'il a essayé et
            # pourquoi ça n'a pas abouti. Aucun `notify_*` : un refus ne réveille
            # pas la cadence, sinon insister deviendrait payant.
            note_act(f"tu as voulu poster une image mais tu n'as pas pu : {motif}")
            return

        client = getattr(self._bot, "image_client", None)
        config = getattr(self._bot, "config", None)
        db = getattr(self._bot, "db", None)
        if client is None or config is None or db is None:
            self._motif_refus = "client d'image, config ou base indisponible"
            logger.warning("ACT generate_image : image_client/config/db absent")
            return
        try:
            channel = self._bot.get_channel(int(channel_id))
        except (TypeError, ValueError):
            channel = None
        if channel is None:
            self._motif_refus = f"canal {channel_id} introuvable"
            logger.warning("ACT generate_image : canal {c} introuvable", c=channel_id)
            return

        auteur = initiative.auteur_id()
        try:
            result = await client.generate_image(prompt, config.image_generation, auteur)
        except ValueError as exc:
            # Quota de l'image_client, ou prompt refusé par l'API (400). Un motif
            # métier, pas une panne : il doit le LIRE, pas le retrouver en logs.
            self._motif_refus = f"génération refusée : {exc}"
            logger.info("ACT generate_image refusé par l'API: {e!r}", e=exc)
            note_act(f"tu as voulu poster une image mais la génération a été refusée : {exc}")
            return
        except Exception as exc:  # noqa: BLE001 — un tick cognitif ne crashe pas
            self._motif_refus = "génération en échec"
            logger.error("ACT generate_image : génération échouée: {e!r}", e=exc)
            return

        # Rangée en galerie AVANT l'envoi : l'argent est dépensé, le fichier
        # existe, et c'est cette ligne qui porte le plafond du jour et le délai
        # (`get_last_image_ts`). Un envoi Discord raté ne doit pas rendre la
        # dépense invisible — sinon il réessaierait aussitôt.
        try:
            await db.insert_gallery_image(
                id=result["file_id"],
                title=(comment or prompt)[:100],
                prompt=prompt,
                revised_prompt=result.get("revised_prompt"),
                username=self._self_name(),
                user_id=auteur,
                platform="discord",
                file_path=result["file_name"],
                model=result["model"],
                quality=result["quality"],
                size=result["size"],
                cost_usd=result["cost_usd"],
            )
        except Exception as exc:  # noqa: BLE001 — la galerie ne bloque pas l'envoi
            logger.warning("ACT generate_image : insertion galerie échouée: {e!r}", e=exc)

        ext = str(result["file_name"]).rsplit(".", 1)[-1]
        try:
            reference = None
            if message_id:
                # Répondre au post qui lui a donné l'idée. Best-effort : un
                # message effacé ou hors du canal ne doit pas annuler l'envoi.
                try:
                    reference = await channel.fetch_message(int(message_id))
                except Exception as exc:  # noqa: BLE001
                    logger.debug("generate_image : message {m} introuvable: {e!r}",
                                 m=message_id, e=exc)
            fichier = discord.File(result["file_path"], filename=f"image.{ext}")
            await channel.send(
                content=comment or None, file=fichier,
                allowed_mentions=_ALLOWED_MENTIONS, reference=reference,
            )
        except Exception as exc:  # noqa: BLE001
            self._motif_refus = "envoi Discord en échec"
            logger.error("ACT generate_image : envoi échoué: {e!r}", e=exc)
            return

        nom_canal = getattr(channel, "name", None) or channel_id
        logger.info("ACT generate_image → {c} : {p}", c=nom_canal, p=prompt[:80])
        self._publish_act(f"generate_image {nom_canal}: ", comment or prompt)
        # Le chemin réactif lit cette mémoire pour bâtir son contexte : sans
        # ça, il nierait avoir posté l'image dont on lui parle deux minutes plus
        # tard. Le marqueur `[a envoyé une image]` est celui du reste du projet.
        trace = f"[a envoyé une image] {comment}".strip()
        self._record_self_message(channel_id, trace)
        guild = getattr(getattr(channel, "guild", None), "name", None)
        self._log_speak("discord", f"{guild}/{nom_canal}" if guild else str(nom_canal), trace)

    async def _act(self, act_name: str, args: dict) -> None:
        from bot.intelligence.memory.facts import AtomicFact, FactCategory, FactStatus

        # UTC NAÏF : cette date part dans des `AtomicFact`, et `facts.py`
        # comme `AtomicFact` écrivent en `utcnow()`. Le format aware faisait
        # cohabiter deux écritures dans la même colonne — toute soustraction
        # directe entre les deux lève `TypeError`. Le canari de démarrage a
        # remonté 111 lignes venues d'ici après la migration du 2026-08-10.
        now = datetime.utcnow()

        if act_name == "show_overlay" and self._overlay_narrator:
            widget = str(args.get("widget") or "").strip()
            comment = str(args.get("comment") or "").strip()
            # Le filtre des `None` est le même que sur l'autre chemin de cet
            # outil (`run_overlay_tool`) : un `"left_value": null` produisait
            # ici `float(None)`, capté comme « données manquantes » — un
            # diagnostic trompeur.
            extra = {k: v for k, v in args.items()
                     if k not in ("widget", "comment", "result") and v is not None}
            # Personne ne l'a sollicité ici : c'est une initiative. L'adversaire
            # du chifoumi vient toujours de l'appelant — sur ce chemin il n'y en
            # a pas, et le modèle ne doit pas pouvoir en désigner un.
            extra.pop("opponent", None)
            # Même règle pour la demande : `show_widget` n'ouvre un jeu qui dure
            # que si un humain l'a réclamé, et ce chemin est précisément celui
            # où personne ne l'a fait. Retiré des arguments du modèle, sinon il
            # lui suffirait de l'écrire pour lever la garde.
            extra.pop("sollicite", None)
            shown = self._overlay_narrator.show_widget(
                widget, comment, result=args.get("result"), **extra
            )
            if shown:
                logger.info("ACT show_overlay: {w} ({c})", w=widget, c=comment[:40])
                self._publish_act(f"show_overlay {widget}: ", comment)
            else:
                # Cette voie est un aller simple : aucun retour ne remonte au
                # modèle, contrairement à l'outil de conversation. Un refus
                # d'écraser une partie en cours resterait donc muet, et c'est
                # PAR ICI qu'ont été ouverts les trois bingos du 2026-08-13. On
                # le consigne dans le flux du stream — perception passive, sans
                # `notify` — pour qu'il le LISE au tick suivant.
                self._note_overlay_refus(widget, extra)

        elif act_name == "generate_image":
            await self._generate_image(args)

        elif act_name == "cancel_overlay" and self._overlay_narrator:
            # Sans cette action, la cognition pouvait OUVRIR un bingo mais jamais
            # le refermer. Le 2026-08-10, on lui a demandé trois fois d'annuler —
            # dans le chat Twitch puis en vocal — et il a raisonné juste :
            # « il n'y a pas de commande "annuler" dans mes widgets ». Il avait
            # raison, et il a relancé un bingo deux minutes plus tard.
            # Le bloc d'état de l'overlay annonçait pourtant `cancel_overlay`
            # depuis toujours : la promesse existait, pas le moyen de la tenir.
            cible = str(args.get("target") or "tout").strip().lower()
            resultat = self._overlay_narrator.cancel(cible)
            annules = resultat.get("cancelled") or []
            if resultat.get("unknown"):
                logger.info("ACT cancel_overlay: cible inconnue « {c} »", c=cible)
            elif annules:
                logger.info("ACT cancel_overlay: {a}", a=", ".join(annules))
                self._publish_act("cancel_overlay: ", ", ".join(annules))
            else:
                # La liste vide est une réponse, pas un échec : il n'y avait rien.
                logger.info("ACT cancel_overlay: rien à annuler ({c})", c=cible)

        elif act_name == "create_memory" and self._facts:
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
                self._publish_act("create_memory: ", content)

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
                self._publish_act("create_goal: ", desc)

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
                    self._publish_act("desire fusionné: ", content)
                else:
                    await self._facts.add(AtomicFact(
                        user_id="wally:self",
                        content=content,
                        category=FactCategory.DESIRE,
                        confidence=0.8,
                        created_at=now,
                        last_seen_at=now,
                        expires_at=_peremption_desir(content),
                    ))
                    logger.info("ACT create_desire: {}", content[:60])
                    self._publish_act("create_desire: ", content)

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
                self._publish_act(f"advance_goal #{goal_id}: ", step)

        elif act_name == "fulfill_goal" and self._facts:
            goal_id = self._coerce_goal_id(act_name, args.get("goal_id"))
            if goal_id is None:
                return
            await self._facts.set_status(goal_id, FactStatus.FULFILLED)
            logger.info("ACT fulfill_goal: #{} accompli", goal_id)
            self._publish_act("fulfill_goal #", str(goal_id))

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
                self._publish_act("drop_desire #", str(target_id))
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
                self._publish_act("doubt_memory #", str(target_id))
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
            # Dédup sémantique pour les notes qui atterrissent dans les désirs
            # (reminder/question → DESIRE), au même titre que create_desire : un
            # désir déjà présent est rafraîchi au lieu d'empiler un paraphrasé de
            # plus. On NE dédupe PAS une note à échéance explicite (in_minutes) :
            # c'est une intention datée précise, pas du bruit.
            if cat == FactCategory.DESIRE and scheduled_at is None:
                existing = await self._facts.search_by_category(
                    FactCategory.DESIRE, status=FactStatus.ACTIVE, limit=25
                )
                dup = next(
                    (d for d in existing if _same_desire(note, d.content)), None
                )
                if dup is not None and dup.id is not None:
                    await self._facts.confirm(dup.id)
                    logger.info(
                        "ACT note_to_self ({}): doublon fusionné → #{} ({})",
                        kind, dup.id, note[:50],
                    )
                    self._publish_act(f"note fusionnée ({kind}): ", note)
                    return
            # Péremption des désirs datés — le second chemin, qui manquait.
            # `create_desire` appelle `_peremption_desir` depuis le 2026-08-09,
            # mais `note_to_self` en kind=question/reminder atterrit AUSSI en
            # DESIRE et ne l'appelait pas : au 2026-08-20, 14 désirs actifs
            # portaient un marqueur temporel sans échéance — « demain midi », ou
            # « le 14 juillet » cinq semaines après la date.
            #
            # Sauf quand `scheduled_at` est posé : là, l'échéance EXPLICITE est
            # l'intention. Une péremption déduite du texte pourrait tomber avant
            # elle (« ce soir » → fin de journée) et tuer le rappel avant qu'il
            # ne revienne à la conscience. Même arbitrage que la dédup ci-dessus.
            peremption = (
                _peremption_desir(note)
                if cat == FactCategory.DESIRE and scheduled_at is None
                else None
            )
            await self._facts.add(AtomicFact(
                user_id="wally:self",
                content=note,
                category=cat,
                source="note_to_self",
                confidence=1.0,
                scheduled_at=scheduled_at,
                expires_at=peremption,
                created_at=now,
                last_seen_at=now,
            ))
            logger.info(
                "ACT note_to_self ({}): {}{}", kind, note[:60],
                f" [dans {raw_minutes} min]" if scheduled_at else "",
            )
            self._publish_act(f"note ({kind}): ", note)

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
            self._publish_act("focus: ", focus)

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
            self._publish_act("récit de soi : ", narrative)

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
            self._publish_act("opinion sur ", f"{about} — {opinion}")

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
            self._publish_act("emote apprise : ", f":{emote}: → {usage}")

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
            # `_fire` et non `create_task` nu : une demande d'auto-modification
            # est censée être publiée systématiquement, or le GC pouvait annuler
            # la tâche avant sa fin, sans le moindre log.
            self._fire(self_fix.request_upgrade(UpgradeRequest(goal=goal)))
            logger.info("ACT code_fix: demande d'auto-modif — {}", goal[:60])
            self._publish_act("auto-modif : ", goal)

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
            logger.warning("EVOLVE {}: {!r}", section, e)
