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

import asyncio
import json
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

_VOICE_SYSTEM = load_prompt(
    "overlay_voice",
    fallback=(
        "Tu es le compagnon d'overlay d'un stream Twitch. Le streamer vient de "
        "te parler À VOIX HAUTE pendant son live.\n"
        "S'il te demande d'afficher quelque chose (pile ou face, dé, roue, "
        "sondage, texte…), APPELLE l'outil show_overlay — c'est le seul moyen "
        "que ça apparaisse à l'écran. N'annonce jamais un affichage sans l'avoir "
        "appelé.\n"
        "Ta réponse écrite est une bulle lue par les SPECTATEURS, jamais par le "
        "streamer qui ne voit pas son overlay : 3 à 8 MOTS, une seule idée. "
        "Si tu n'as rien à ajouter, réponds RIEN."
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


OVERLAY_TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "show_overlay",
        "description": (
            "Affiche un widget sur l'overlay du stream, quand on te le demande ou "
            "que l'envie te prend. Ne fonctionne QUE pendant un live — hors live "
            "l'outil te le dira, et tu pourras le dire simplement. C'est toi qui "
            "décides : tu peux refuser si on t'en demande trop, commenter le "
            "résultat, et même forcer le tirage pour tricher. ⚠️ L'overlay est vu "
            "par les SPECTATEURS, pas par le streamer : ton `comment` s'adresse à "
            "eux. Ne prétends jamais avoir affiché quelque chose sans appeler cet "
            "outil."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "widget": {
                    "type": "string",
                    "enum": ["coinflip", "dice", "wheel", "countdown", "gauge",
                             "pinned", "uptime", "counter", "poll", "stats", "versus",
                             "bingo"],
                    "description": (
                        "coinflip = pile ou face · dice = un dé · wheel = la roue "
                        "tranche entre 2-8 options · countdown = compte à rebours "
                        "· gauge = jauge 0-100 · pinned = met en avant un message "
                        "du chat · uptime = durée du live (calculée pour toi) · "
                        "counter = un texte bref · poll = sondage, le chat vote en "
                        "tapant le numéro · stats = les chiffres d'un joueur · "
                        "versus = compare deux joueurs sur une valeur"
                    ),
                },
                "comment": {
                    "type": "string",
                    "description": "Ta réplique, quelques mots — c'est elle qu'on lit, pas l'animation.",
                },
                "result": {
                    "type": "string",
                    "description": (
                        "Résultat imposé, optionnel : 'heads'/'tails', un chiffre "
                        "de dé, l'index gagnant de la roue, les secondes du compte "
                        "à rebours, le pourcentage de la jauge. Omets-le pour un tirage au sort."
                    ),
                },
                "options": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Les choix, pour wheel (2-8) ou poll (2-4).",
                },
                "question": {"type": "string", "description": "La question, pour poll."},
                "seconds": {"type": "integer", "description": "Durée d'un sondage (10 par défaut, 120 max)."},
                "count": {"type": "integer", "description": "Nombre de dés à lancer, pour dice (1 par défaut, 4 max)."},
                "cells": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Pour bingo : 4 à 9 pronostics courts sur ce qui va arriver pendant le live.",
                },
                "check": {"type": "integer", "description": "Pour bingo : numéro de la case (0 = la première) que tu viens de voir se réaliser."},
                "player": {"type": "string", "description": "Le pseudo, pour stats."},
                "lines": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Pour stats : 1 à 4 lignes déjà rédigées, ex. « Rang : Diamant 3 », « Kills : 82 522 ».",
                },
                "label": {"type": "string", "description": "L'intitulé, pour gauge et versus (ex. « Kills »)."},
                "left_name": {"type": "string", "description": "Premier joueur comparé, pour versus."},
                "left_value": {"type": "number", "description": "Sa valeur chiffrée, pour versus."},
                "right_name": {"type": "string", "description": "Second joueur comparé, pour versus."},
                "right_value": {"type": "number", "description": "Sa valeur chiffrée, pour versus."},
                "text": {"type": "string", "description": "Le message mis en avant, pour pinned."},
                "author": {"type": "string", "description": "L'auteur du message, pour pinned."},
            },
            "required": ["widget"],
        },
    },
}


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
        stream_feed=None,
    ) -> None:
        self._feed = overlay_feed
        self._llm = llm
        self._is_live = is_live
        self._min_interval = min_interval_s
        self._event_interval = event_interval_s
        # Statut du live ({live, title, category, viewers, started_at}) pour les
        # widgets qui ont besoin de données réelles (uptime).
        self._stream_status = stream_status
        # Le résultat d'un sondage y est consigné : c'est ce qui le rend
        # visible dans le prompt, donc répondable.
        self._stream_feed = stream_feed
        self._greeted: set[str] = set()
        self._was_live: bool = False
        self._force_until: float = 0.0
        self._poll: Optional[dict] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._last_poll: Optional[dict] = None
        # Grille du bingo (widget 20) : vit le temps d'un live.
        self._bingo: Optional[dict] = None
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

    async def on_stream_event(
        self, description: str, *, show_thinking: bool = True
    ) -> Optional[str]:
        """Réagit à un événement du live (raid, sub, changement de jeu…).

        `description` arrive déjà rédigée en français par `StreamFeed`.

        `show_thinking=False` pour les sources où le silence est le cas normal
        — le vocal capte tout, y compris le jeu et les conversations qui ne le
        concernent pas. Y annoncer une réflexion à chaque phrase produirait des
        trois-points sans bulle à longueur de live.
        """
        description = (description or "").strip()
        if not description or not self._may_react():
            return None

        self._last_event_at = time.monotonic()
        # L'avatar s'emballe tout de suite sur les gros moments : la réaction
        # visuelle est immédiate, la bulle arrive après la condensation.
        if any(hint in description.lower() for hint in _STRONG_EVENT_HINTS):
            self._feed.react("stream_event")

        if show_thinking:
            self._feed.thinking(True)
        try:
            short = await self._condense(description, system=_EVENT_SYSTEM)
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            logger.debug("OverlayNarrator: réaction échouée: {e}", e=exc)
            short = None

        if not short:
            if show_thinking:
                self._feed.thinking(False)
            return None
        # Une réaction consomme aussi le budget des pensées : sinon une bulle de
        # pensée pourrait s'empiler juste derrière.
        self._mark_spoken()
        self._feed.say(short, mode="speech")
        return short

    # ── voix ──────────────────────────────────────────────────────────────

    async def on_voice_request(self, speaker: str, text: str) -> Optional[str]:
        """Le streamer s'adresse à Wally en vocal et lui demande un affichage.

        Le chemin des réactions (`on_stream_event`) ne sait que condenser du
        texte : sans outil, une demande d'affichage produisait des trois-points
        puis rien. Ici le modèle peut réellement appeler `show_overlay`.
        """
        text = (text or "").strip()
        if not text or not self._may_react():
            return None
        self._last_event_at = time.monotonic()
        self._feed.thinking(True)

        shown: list[dict] = []

        async def _execute(name: str, arguments: str) -> str:
            if name != "show_overlay":
                return json.dumps({"status": "unknown_tool"})
            try:
                args = json.loads(arguments or "{}")
            except json.JSONDecodeError:
                return json.dumps({"status": "error", "message": "arguments illisibles"})
            extra = {k: v for k, v in args.items()
                     if k not in ("widget", "comment", "result") and v is not None}
            out = self.show_widget(
                str(args.get("widget") or ""), str(args.get("comment") or ""),
                result=args.get("result"), **extra,
            )
            if out is None:
                return json.dumps({"status": "rejected",
                                   "message": "widget inconnu ou données manquantes"})
            shown.append(out)
            return json.dumps({"status": "ok", **{k: str(v) for k, v in out.items()}})

        try:
            reply, _ = await self._llm.complete_with_tools(
                system_prompt=_VOICE_SYSTEM,
                messages=[{"role": "user", "content": f"{speaker} (à voix haute) : {text}"}],
                tools=[OVERLAY_TOOL_SPEC],
                tool_executor=_execute,
                purpose="overlay_voice",
            )
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            logger.warning("Overlay: demande vocale échouée: {e}", e=exc)
            self._feed.thinking(False)
            return None

        short = " ".join((reply or "").split()).strip('"').strip()
        if not short or short.upper().rstrip(".") == "RIEN":
            # Un widget a pu s'afficher sans qu'il ait à commenter.
            self._feed.thinking(False)
            return None
        if len(short) > _MAX_BUBBLE_CHARS:
            short = short[:_MAX_BUBBLE_CHARS].rsplit(" ", 1)[0]
        self._mark_spoken()
        self._feed.say(short, mode="speech")
        return short

    # ── widgets ───────────────────────────────────────────────────────────

    # Widgets connus. Le résultat est tiré ICI et non dans le navigateur : c'est
    # ce qui permet à Wally de commenter son propre tirage — et de tricher.
    _WIDGETS = ("coinflip", "dice", "counter", "wheel", "countdown", "gauge",
                "pinned", "uptime", "poll", "stats", "versus", "bingo",
                "prediction")

    def show_widget(
        self, widget: str, comment: str = "", result=None, **extra
    ) -> Optional[dict]:
        """Affiche un widget décidé par Wally, avec son commentaire.

        Retourne les paramètres publiés — dont le tirage — pour que l'appelant
        SACHE ce qui s'affiche : « lance un dé » doit pouvoir répondre le
        résultat, pas « c'est à l'écran ». None si le widget est inconnu, hors
        live, ou si les données manquent : rien n'est alors publié.
        """
        widget = (widget or "").strip()
        if widget not in self._WIDGETS or not self._live():
            return None

        params: dict = {}
        if widget == "coinflip":
            params["result"] = result if result in ("heads", "tails") else random.choice(
                ("heads", "tails")
            )
        elif widget == "dice":
            # Plusieurs dés d'un coup : « lance deux dés » donnait un seul dé à
            # l'écran, et Wally annonçait deux valeurs inventées.
            try:
                count = int(extra.get("count") or 1)
            except (TypeError, ValueError):
                count = 1
            count = max(1, min(4, count))
            values: list[int] = []
            if result is not None and count == 1:
                try:
                    values = [max(1, min(6, int(result)))]
                except (TypeError, ValueError):
                    values = []
            if not values:
                values = [random.randint(1, 6) for _ in range(count)]
            params["results"] = values
            params["result"] = values[0]   # compat : un seul dé reste un entier
        elif widget == "counter":
            params["text"] = str(result or comment)[:40]

        elif widget == "wheel":
            options = [str(o).strip()[:24] for o in (extra.get("options") or []) if str(o).strip()]
            if len(options) < 2:
                return None  # une roue à une case n'a aucun intérêt
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
                return None
            params = {"seconds": max(1, min(600, seconds))}
            if extra.get("done"):
                params["done"] = str(extra["done"])[:20]

        elif widget == "gauge":
            try:
                percent = float(result)
            except (TypeError, ValueError):
                return None
            params = {"percent": max(0.0, min(100.0, percent)),
                      "label": str(extra.get("label") or comment)[:40]}

        elif widget == "pinned":
            text = str(extra.get("text") or "").strip()
            if not text:
                return None
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
                return None
            # start_poll a déjà publié le widget ; le commentaire ferait doublon
            # avec la question affichée.
            return {"widget": "poll", "question": question, "options": options,
                    "seconds": seconds}

        elif widget == "bingo":
            # Deux gestes sur le même widget : ouvrir la grille, ou cocher une
            # case. Le distinguer par la présence de `cells` évite d'exposer deux
            # outils au modèle pour une seule idée.
            cells = [str(c).strip()[:34] for c in (extra.get("cells") or []) if str(c).strip()]
            if cells:
                if not self.start_bingo(cells):
                    return None
                return {"widget": "bingo", "cells": self._bingo["cells"]}
            checked = self.check_bingo(extra.get("check"))
            if checked is None:
                return None
            return checked

        elif widget == "stats":
            # Les chiffres viennent de l'outil Apex, pas d'ici : Wally les a lus
            # avant d'appeler, on se contente de les mettre en forme.
            lines = [str(l).strip()[:34] for l in (extra.get("lines") or []) if str(l).strip()]
            if not lines:
                return None
            params = {"player": str(extra.get("player") or "")[:24],
                      "lines": lines[:4]}

        elif widget == "versus":
            try:
                left_value = float(extra.get("left_value"))
                right_value = float(extra.get("right_value"))
            except (TypeError, ValueError):
                return None      # sans chiffres, il n'y a rien à comparer
            left_name = str(extra.get("left_name") or "").strip()[:14]
            right_name = str(extra.get("right_name") or "").strip()[:14]
            if not left_name or not right_name:
                return None
            params = {
                "label": str(extra.get("label") or comment)[:24],
                "left_name": left_name, "left_value": left_value,
                "right_name": right_name, "right_value": right_value,
            }

        elif widget == "uptime":
            label = self._uptime_label()
            if not label:
                return None  # pas de live daté : rien à afficher
            params = {"text": label}
            widget = "counter"  # même rendu, données calculées ici

        self._feed.widget(widget, **params)
        # Le commentaire accompagne le widget : c'est lui qui fait le personnage,
        # pas l'animation. Il consomme le budget des bulles.
        if comment:
            # La bulle s'efface pendant un widget : la publier la ferait surgir à
            # contretemps, une fois le widget parti. Le créneau reste consommé —
            # une pensée ne doit pas s'empiler juste derrière.
            self._mark_spoken()
        return {"widget": widget, **params}

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
        """Remet à zéro l'état lié à un live (saluts, sondage, bingo)."""
        self._greeted.clear()
        self._poll = None
        self._bingo = None

    def show_prediction(self, bet: str, *, outcome: str = "",
                        right: int = 0, total: int = 0) -> bool:
        """Montre un pari : à son ouverture, puis à son verdict.

        Contrairement aux compteurs, ce widget n'est PAS rationné : un pari est
        rare et c'est son verdict qui fait le sel. Le rater serait pire que de
        déranger.
        """
        if not self._live():
            return False
        self._last_event_at = time.monotonic()
        self._feed.widget("prediction", bet=str(bet)[:90], outcome=outcome,
                          right=int(right), total=int(total))
        return True

    def show_counter(self, text: str) -> bool:
        """Montre un compteur qui vient de monter, si le budget le permet.

        Silencieux en cas de refus : le compteur a déjà été incrémenté en base,
        c'est l'AFFICHAGE qu'on rationne — un gag qui tombe dix fois en deux
        minutes ne doit pas monopoliser l'écran.
        """
        if not self._may_react():
            return False
        self._last_event_at = time.monotonic()
        self._feed.widget("counter", text=str(text)[:40])
        return True

    # ── bingo du stream (widget 20) ───────────────────────────────────────

    def start_bingo(self, cells: list[str]) -> bool:
        """Ouvre une grille de bingo pour le live.

        Jusqu'à 9 cases, en grille de trois colonnes : un widget occupe toute la
        zone et fait s'effacer l'avatar comme la bulle, il n'a personne à ménager.
        """
        cells = [str(c).strip()[:34] for c in (cells or []) if str(c).strip()][:9]
        if len(cells) < 2 or not self._live():
            return False
        self._bingo = {"cells": cells, "done": [False] * len(cells)}
        self._feed.widget("bingo", cells=cells, done=list(self._bingo["done"]))
        logger.info("Overlay: bingo ouvert ({n} cases)", n=len(cells))
        return True

    def check_bingo(self, index) -> Optional[dict]:
        """Coche une case. Retourne None si rien n'a changé — le widget ne doit
        pas réapparaître pour une case déjà cochée."""
        bingo = self._bingo
        if not bingo:
            return None
        try:
            i = int(index)
        except (TypeError, ValueError):
            return None
        if not 0 <= i < len(bingo["cells"]) or bingo["done"][i]:
            return None
        bingo["done"][i] = True
        full = all(bingo["done"])
        self._feed.widget("bingo", cells=bingo["cells"], done=list(bingo["done"]),
                          just=i, full=full, duration=12)
        logger.info("Overlay: bingo — « {c} » cochée{f}",
                    c=bingo["cells"][i], f=" (grille complète)" if full else "")
        return {"widget": "bingo", "checked": bingo["cells"][i], "full": full}

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
        # Clôture planifiée : sans elle, le dépouillement s'effacerait sans
        # jamais annoncer de gagnant, et Wally ne saurait pas quoi répondre si on
        # lui demande le résultat.
        self._schedule_poll_close(seconds)
        return True

    def _schedule_poll_close(self, seconds: int) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._poll_task = None      # hors boucle (tests synchrones)
            return
        self._poll_task = loop.create_task(self._close_poll_after(seconds))

    async def _close_poll_after(self, seconds: int) -> None:
        try:
            await asyncio.sleep(seconds)
            self.close_poll()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            logger.warning("Overlay: clôture du sondage en erreur: {e}", e=exc)

    def close_poll(self) -> Optional[dict]:
        """Termine le sondage : gagnant à l'écran, résultat retenu.

        Le résultat est aussi consigné dans le flux du stream, sans réveiller le
        narrateur : c'est ce qui le rend visible dans le prompt, donc répondable
        quand quelqu'un demande « alors, ça a donné quoi ? ».
        """
        poll = self._poll
        if not poll:
            return None
        tally = [0] * len(poll["options"])
        for index in poll["votes"].values():
            tally[index] += 1
        total = sum(tally)
        best = max(range(len(tally)), key=lambda i: tally[i]) if total else None
        # Égalité en tête : il n'y a pas de gagnant à désigner.
        tied = total > 0 and tally.count(tally[best]) > 1
        result = {
            "question": poll["question"],
            "options": list(poll["options"]),
            "tally": tally,
            "total": total,
            "winner": None if (best is None or tied) else poll["options"][best],
            "tied": tied,
        }
        self._last_poll = result
        self._poll = None
        self._feed.widget(
            "poll",
            question=poll["question"],
            options=poll["options"],
            tally=tally,
            seconds=0,
            final=True,
            winner=-1 if (best is None or tied) else best,
            duration=8,          # le résultat reste lisible avant de s'effacer
        )
        feed = self._stream_feed
        if feed is None:
            from bot.core.stream_feed import active_stream_feed
            feed = active_stream_feed()
        if feed is not None:
            try:
                feed.record(self.poll_result_line(), notify=False)
            except Exception as exc:  # noqa: BLE001 — jamais bloquant
                logger.debug("Overlay: résultat du sondage non consigné: {e}", e=exc)
        logger.info("Overlay: sondage clos — {r}", r=self.poll_result_line())
        return result

    def poll_result_line(self) -> str:
        """Le dernier résultat, en une phrase — vide s'il n'y en a jamais eu."""
        r = self._last_poll
        if not r:
            return ""
        if not r["total"]:
            return f"Sondage « {r['question']} » : personne n'a voté."
        detail = ", ".join(
            f"{o} {n}" for o, n in zip(r["options"], r["tally"])
        )
        if r["tied"]:
            return f"Sondage « {r['question']} » : égalité ({detail})."
        return (f"Sondage « {r['question']} » : {r['winner']} l'emporte "
                f"({detail}, {r['total']} votes).")

    def _count_vote(self, author: str, text: str) -> None:
        poll = self._poll
        if not poll:
            return
        if time.monotonic() > poll["ends_at"]:
            self.close_poll()      # la tâche a pu être manquée : on clôt ici
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
