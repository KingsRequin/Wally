"""OverlayNarrator — décide de ce qui monte à l'écran, et à quel rythme.

Le risque de ce projet est produit, pas technique : un compagnon qui commente
sans arrêt devient insupportable, et un overlay ne se scrolle pas. Le budget de
parole est donc un **mécanisme qui refuse**, pas une consigne dans un prompt.

Deux garde-fous, dans cet ordre :

1. **Rien hors live.** En dehors d'un stream, personne ne regarde : on ne
   dépense ni appel LLM ni bulle.
2. **Un intervalle minimal**, vérifié AVANT de condenser — inutile de payer un
   appel pour un texte qu'on jetterait.

Les pensées internes de Wally sont longues et introspectives ; l'overlay veut
quelques mots. La condensation passe par le modèle rapide (mesuré ~1,3 s sur ce
format), pas par une troncature qui couperait au milieu d'une idée.
"""
from __future__ import annotations

import random
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from bot.intelligence.prompts import load_prompt

# Intervalle minimal entre deux bulles de pensée. Elles occupent l'écran quand
# il ne se passe rien : plus fréquentes qu'une réaction, mais loin d'être
# continues.
_MIN_THOUGHT_INTERVAL_S = 90.0

# Un événement de stream mérite son propre créneau : quand un raid tombe, se
# taire parce qu'une pensée vient de passer serait absurde. Court, car ces
# événements sont rares et attendus par le public.
_MIN_EVENT_INTERVAL_S = 20.0

# Événements sur lesquels l'avatar s'emballe en plus de la bulle. Repérage par
# mot-clé sur la description déjà rédigée en français par StreamFeed.
_STRONG_EVENT_HINTS = ("raid", "sub", "abonn", "bits", "cheer", "don")

# Au-delà, la condensation a échoué à faire court : on préfère se taire plutôt
# que d'afficher un pavé illisible en petit.
_MAX_BUBBLE_CHARS = 90

# Au-delà de ce délai sans être vu, un habitué qui revient mérite un mot.
_RETURN_AFTER_DAYS = 7

# Durée par défaut d'un sondage. Peut être demandée plus longue.
_POLL_DEFAULT_S = 10

# Plafond du mode test hors live : au-delà, ce n'est plus un réglage,
# c'est un live fantôme qu'on a oublié de couper.
_MAX_FORCE_LIVE_MIN = 120

_EVENT_SYSTEM = load_prompt(
    "overlay_event",
    fallback=(
        "Réagis à cet événement du stream en 3 à 8 MOTS, adressés aux SPECTATEURS. "
        "Une seule idée, ton naturel. Réponds uniquement par la phrase, ou RIEN."
    ),
    render=False,
)

_CONDENSE_SYSTEM = load_prompt(
    "overlay_thought",
    fallback=(
        "Condense cette pensée en 3 à 8 MOTS, à la première personne, ton naturel. "
        "Une seule idée. Pas de ponctuation lourde, pas de guillemets. "
        "Réponds uniquement par la phrase."
    ),
    render=False,
)


class OverlayNarrator:
    """Filtre et condense ce que Wally montre au public pendant un live."""

    def __init__(
        self,
        overlay_feed,
        llm,
        is_live: Callable[[], bool],
        min_interval_s: float = _MIN_THOUGHT_INTERVAL_S,
        event_interval_s: float = _MIN_EVENT_INTERVAL_S,
        stream_status: Optional[Callable[[], dict]] = None,
    ) -> None:
        self._feed = overlay_feed
        self._llm = llm
        self._is_live = is_live
        self._min_interval = min_interval_s
        self._event_interval = event_interval_s
        # Statut du live ({live, title, category, viewers, started_at}) pour les
        # widgets qui ont besoin de données réelles (uptime).
        self._stream_status = stream_status
        self._greeted: set[str] = set()
        self._was_live: bool = False
        self._force_until: float = 0.0
        self._poll: Optional[dict] = None
        self._last_bubble_at: float = 0.0
        self._last_event_at: float = 0.0

    # ── budget ────────────────────────────────────────────────────────────

    def force_live(self, minutes: float) -> float:
        """Mode test : fait comme si un live était en cours, pour régler l'overlay
        sans attendre un vrai stream.

        L'échéance est obligatoire — un mode test oublié ferait parler Wally dans
        le vide, à un appel LLM la bulle. `minutes <= 0` coupe immédiatement.
        """
        if minutes <= 0:
            self._force_until = 0.0
            logger.info("Overlay: mode test coupé")
            return 0.0
        minutes = min(minutes, _MAX_FORCE_LIVE_MIN)
        self._force_until = time.monotonic() + minutes * 60
        logger.info("Overlay: mode test actif {m:.0f} min", m=minutes)
        return minutes

    def force_live_remaining(self) -> float:
        """Minutes restantes de mode test (0 s'il est inactif)."""
        return max(0.0, (self._force_until - time.monotonic()) / 60)

    def is_active(self) -> bool:
        """Vrai si l'overlay doit réagir : vrai live, ou mode test en cours."""
        return self._live()

    def _live(self) -> bool:
        if time.monotonic() < self._force_until:
            # Le mode test suit le même chemin qu'un vrai live, remise à zéro
            # des saluts comprise : c'est ce qu'on veut tester.
            if not self._was_live:
                self.reset_live()
            self._was_live = True
            return True
        try:
            live = bool(self._is_live())
        except Exception:  # noqa: BLE001 — une sonde cassée ne doit pas parler
            return False
        # Le process tourne des semaines d'affilée : sans cette remise à zéro,
        # les saluts du premier live vaudraient pour tous les suivants. La
        # transition est détectée ici plutôt que câblée sur un événement, pour
        # rester juste même si l'événement de démarrage est manqué.
        if live and not self._was_live:
            self.reset_live()
        self._was_live = live
        return live

    def _may_speak(self) -> bool:
        """Vrai si un live est en cours et que le délai minimal est écoulé."""
        if not self._live():
            return False
        return (time.monotonic() - self._last_bubble_at) >= self._min_interval

    def _may_react(self) -> bool:
        """Budget des événements, distinct de celui des pensées : un raid ne doit
        pas être avalé parce qu'une pensée vient de passer."""
        if not self._live():
            return False
        return (time.monotonic() - self._last_event_at) >= self._event_interval

    def _mark_spoken(self) -> None:
        self._last_bubble_at = time.monotonic()

    # ── pensées ───────────────────────────────────────────────────────────

    async def on_thought(self, text: str) -> Optional[str]:
        """Publie une pensée condensée, si le budget le permet.

        Retourne le texte affiché, ou None si rien n'a été publié.
        """
        if not (text or "").strip() or not self._may_speak():
            return None

        # Réserve le créneau avant l'appel : deux pensées quasi simultanées ne
        # doivent pas passer toutes les deux pendant que la première condense.
        self._mark_spoken()
        self._feed.thinking(True)
        try:
            short = await self._condense(text)
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            logger.debug("OverlayNarrator: condensation échouée: {e}", e=exc)
            short = None

        if not short:
            self._feed.thinking(False)
            return None
        self._feed.think_aloud(short)
        return short

    # ── événements du stream ──────────────────────────────────────────────

    async def on_stream_event(self, description: str) -> Optional[str]:
        """Réagit à un événement du live (raid, sub, changement de jeu…).

        `description` arrive déjà rédigée en français par `StreamFeed`.
        """
        description = (description or "").strip()
        if not description or not self._may_react():
            return None

        self._last_event_at = time.monotonic()
        # L'avatar s'emballe tout de suite sur les gros moments : la réaction
        # visuelle est immédiate, la bulle arrive après la condensation.
        if any(hint in description.lower() for hint in _STRONG_EVENT_HINTS):
            self._feed.react("stream_event")

        self._feed.thinking(True)
        try:
            short = await self._condense(description, system=_EVENT_SYSTEM)
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            logger.debug("OverlayNarrator: réaction échouée: {e}", e=exc)
            short = None

        if not short:
            self._feed.thinking(False)
            return None
        # Une réaction consomme aussi le budget des pensées : sinon une bulle de
        # pensée pourrait s'empiler juste derrière.
        self._mark_spoken()
        self._feed.say(short, mode="speech")
        return short

    # ── widgets ───────────────────────────────────────────────────────────

    # Widgets connus. Le résultat est tiré ICI et non dans le navigateur : c'est
    # ce qui permet à Wally de commenter son propre tirage — et de tricher.
    _WIDGETS = ("coinflip", "dice", "counter", "wheel", "countdown", "gauge",
                "pinned", "uptime", "poll")

    def show_widget(
        self, widget: str, comment: str = "", result=None, **extra
    ) -> bool:
        """Affiche un widget décidé par Wally, avec son commentaire.

        Retourne False si le widget est inconnu, hors live, ou si les données
        manquent — auquel cas rien n'est publié.
        """
        widget = (widget or "").strip()
        if widget not in self._WIDGETS or not self._live():
            return False

        params: dict = {}
        if widget == "coinflip":
            params["result"] = result if result in ("heads", "tails") else random.choice(
                ("heads", "tails")
            )
        elif widget == "dice":
            try:
                value = int(result)
            except (TypeError, ValueError):
                value = random.randint(1, 6)
            params["result"] = max(1, min(6, value))
        elif widget == "counter":
            params["text"] = str(result or comment)[:40]

        elif widget == "wheel":
            options = [str(o).strip()[:24] for o in (extra.get("options") or []) if str(o).strip()]
            if len(options) < 2:
                return False  # une roue à une case n'a aucun intérêt
            options = options[:8]
            # L'index gagnant est décidé ici : Wally peut donc le forcer.
            try:
                index = int(result)
            except (TypeError, ValueError):
                index = random.randrange(len(options))
            params = {"options": options, "index": max(0, min(len(options) - 1, index))}

        elif widget == "countdown":
            try:
                seconds = int(result)
            except (TypeError, ValueError):
                return False
            params = {"seconds": max(1, min(600, seconds))}
            if extra.get("done"):
                params["done"] = str(extra["done"])[:20]

        elif widget == "gauge":
            try:
                percent = float(result)
            except (TypeError, ValueError):
                return False
            params = {"percent": max(0.0, min(100.0, percent)),
                      "label": str(extra.get("label") or comment)[:40]}

        elif widget == "pinned":
            text = str(extra.get("text") or "").strip()
            if not text:
                return False
            params = {"author": str(extra.get("author") or "")[:24], "text": text[:160]}

        elif widget == "poll":
            # Le sondage n'est pas un affichage ponctuel : il ouvre un dépouillement
            # vivant, alimenté par le chat. D'où la délégation à start_poll.
            question = str(extra.get("question") or comment).strip()
            options = [str(o) for o in (extra.get("options") or [])]
            try:
                seconds = int(extra.get("seconds") or result or _POLL_DEFAULT_S)
            except (TypeError, ValueError):
                seconds = _POLL_DEFAULT_S
            if not self.start_poll(question, options, seconds=seconds):
                return False
            # start_poll a déjà publié le widget ; le commentaire ferait doublon
            # avec la question affichée.
            return True

        elif widget == "uptime":
            label = self._uptime_label()
            if not label:
                return False  # pas de live daté : rien à afficher
            params = {"text": label}
            widget = "counter"  # même rendu, données calculées ici

        self._feed.widget(widget, **params)
        # Le commentaire accompagne le widget : c'est lui qui fait le personnage,
        # pas l'animation. Il consomme le budget des bulles.
        if comment:
            self._mark_spoken()
            self._feed.say(comment, mode="speech")
        return True

    # ── saluts (widget 9) ─────────────────────────────────────────────────

    async def on_chat_message(
        self, author: str, text: str, days_since: Optional[float] = None
    ) -> None:
        """Une ligne de chat arrive : compte un éventuel vote, puis salue.

        Le salut se déclenche à la PREMIÈRE prise de parole d'une personne
        pendant le live — on ne détecte pas les arrivées silencieuses, et un
        viewer qui ne parle jamais n'a rien à faire à l'écran.

        ⚠️ `days_since` doit être mesuré par l'appelant AVANT que le message ne
        rafraîchisse `memory_users`, sinon tout le monde paraît « vu à l'instant »
        et plus personne n'est jamais salué.
        """
        author = (author or "").strip()
        if not author:
            return
        self._count_vote(author, text)
        await self._maybe_greet(author, days_since)

    async def _maybe_greet(self, author: str, days: Optional[float]) -> None:
        key = author.lower()
        # Une seule fois par personne et par live, sinon il resaluerait à chaque
        # message.
        if key in self._greeted or not self._may_react():
            return
        self._greeted.add(key)

        if days is None:
            kind = f"{author} débarque pour la première fois"
        elif days >= _RETURN_AFTER_DAYS:
            kind = f"{author} revient après {int(days)} jours d'absence"
        else:
            return  # habitué vu récemment : rien à signaler

        self._last_event_at = time.monotonic()
        self._feed.thinking(True)
        try:
            short = await self._condense(kind, system=_EVENT_SYSTEM)
        except Exception as exc:  # noqa: BLE001
            logger.debug("OverlayNarrator: salut échoué: {e}", e=exc)
            short = None
        if not short:
            self._feed.thinking(False)
            return
        self._mark_spoken()
        self._feed.say(short, mode="speech")

    def reset_live(self) -> None:
        """Remet à zéro l'état lié à un live (saluts déjà faits, sondage)."""
        self._greeted.clear()
        self._poll = None

    # ── sondage (widget 6) ────────────────────────────────────────────────

    def start_poll(
        self, question: str, options: list[str], seconds: int = _POLL_DEFAULT_S
    ) -> bool:
        """Ouvre un sondage : les viewers votent en tapant le numéro dans le chat."""
        question = (question or "").strip()
        options = [str(o).strip()[:24] for o in (options or []) if str(o).strip()][:4]
        if not question or len(options) < 2 or not self._live():
            return False
        seconds = max(5, min(120, int(seconds or _POLL_DEFAULT_S)))
        self._poll = {
            "question": question[:80],
            "options": options,
            "votes": {},                      # votant → index (un vote par personne)
            "ends_at": time.monotonic() + seconds,
        }
        self._publish_poll(seconds)
        return True

    def _count_vote(self, author: str, text: str) -> None:
        poll = self._poll
        if not poll:
            return
        if time.monotonic() > poll["ends_at"]:
            self._poll = None
            return
        # Un vote = le seul chiffre du message. « 1 » compte, « j'ai 2 chats » non.
        token = (text or "").strip()
        if not token.isdigit():
            return
        index = int(token) - 1
        if not 0 <= index < len(poll["options"]):
            return
        voter = author.lower()
        if poll["votes"].get(voter) == index:
            return  # déjà ce vote : rien de neuf à publier
        poll["votes"][voter] = index          # un changement d'avis remplace
        self._publish_poll(max(1, int(poll["ends_at"] - time.monotonic())))

    def _publish_poll(self, seconds_left: int) -> None:
        poll = self._poll
        if not poll:
            return
        tally = [0] * len(poll["options"])
        for index in poll["votes"].values():
            tally[index] += 1
        self._feed.widget(
            "poll",
            question=poll["question"],
            options=poll["options"],
            tally=tally,
            seconds=seconds_left,
            duration=seconds_left + 4,        # laisse le résultat à l'écran
        )

    def _uptime_label(self) -> Optional[str]:
        """« en live depuis 3h12 », calculé depuis le statut du stream.

        Un viewer demande la durée dans le chat, le compteur s'affiche quelques
        secondes puis disparaît — il n'est pas permanent à l'écran.
        """
        if self._stream_status is None:
            return None
        try:
            started = (self._stream_status() or {}).get("started_at")
        except Exception:  # noqa: BLE001
            return None
        if not started:
            return None
        try:
            begin = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
            elapsed = datetime.now(timezone.utc) - begin
        except (TypeError, ValueError):
            return None
        minutes = max(0, int(elapsed.total_seconds() // 60))
        if minutes < 60:
            return f"en live depuis {minutes} min"
        return f"en live depuis {minutes // 60}h{minutes % 60:02d}"

    async def _condense(self, text: str, system: Optional[str] = None) -> Optional[str]:
        raw = await self._llm.complete(
            system or _CONDENSE_SYSTEM,
            [{"role": "user", "content": text}],
            purpose="overlay_thought",
        )
        short = " ".join((raw or "").split()).strip('"').strip()
        # Le prompt répond RIEN quand la pensée n'a aucun intérêt pour un
        # spectateur — se taire est une réponse valide.
        if not short or short.upper().rstrip(".") == "RIEN":
            return None
        if len(short) > _MAX_BUBBLE_CHARS:
            logger.debug("OverlayNarrator: condensation trop longue ({n} car)", n=len(short))
            return None
        return short
