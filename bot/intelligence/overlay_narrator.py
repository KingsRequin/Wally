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
import re
import time
import unicodedata
from collections import deque
from urllib.parse import quote
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from bot.core.apex.tool import APEX_OVERLAY_TOOL
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

# Les coups du chifoumi, en français. Au niveau du MODULE parce que le schéma
# d'outil (plus bas) doit s'en servir : deux listes divergeraient, et c'est
# précisément ce qui est arrivé — l'enum en anglais faisait retomber la triche
# sur un tirage au hasard.
_RPS_MOVES = ("pierre", "feuille", "ciseaux")

# Plafond du mode test hors live : au-delà, ce n'est plus un réglage,
# c'est un live fantôme qu'on a oublié de couper.
_MAX_FORCE_LIVE_MIN = 120

# Les mentions en tête d'un message adressé au bot. Uniquement en TÊTE : un
# « @toto » en fin de phrase appartient à la phrase, pas à l'interpellation.
_ADDRESS_RE = re.compile(r"^(?:\s*@[\w_]+[\s,:!]*)+", re.UNICODE)


def _strip_address(text: str) -> str:
    """Le message sans l'interpellation qui le précède.

    « @WallyTeBully d » → « d ». C'est ce qui permet de jouer une lettre, un
    vote ou un coup en s'adressant à Wally, ce que tout le monde fait
    naturellement sur Twitch.
    """
    return _ADDRESS_RE.sub("", text or "").strip()


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
                             "bingo", "meme", "rps", "hangman", "goal", "talkers"],
                    "description": (
                        "coinflip = pile ou face · dice = un dé · wheel = la roue "
                        "tranche entre 2-8 options · countdown = compte à rebours "
                        "· gauge = jauge 0-100 · pinned = met en avant un message "
                        "du chat · uptime = durée du live (calculée pour toi) · "
                        "counter = un texte bref · poll = sondage, le chat vote en "
                        "tapant le numéro · stats = les chiffres d'un joueur · "
                        "versus = compare deux joueurs sur une valeur · "
                        "meme = une image de la communauté · "
                        "rps = chifoumi, le chat vote contre toi · "
                        "bingo = une grille de pronostics sur le live · "
                        "hangman = le pendu — TU choisis le mot et tu lances "
                        "dans la foulée, le chat propose ensuite des lettres, "
                        "une par message · "
                        "goal = un objectif de follows/subs/bits qui se remplit "
                        "tout seul · talkers = le podium des plus bavards"
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
                        "de dé, l'index gagnant de la roue. Omets-le pour un "
                        "tirage au sort. (Pour la durée d'un compte à rebours, "
                        "utilise `seconds` ; pour la jauge, `percent`.)"
                    ),
                },
                "options": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Les choix, pour wheel (2-8) ou poll (2-4).",
                },
                "question": {"type": "string", "description": "La question, pour poll."},
                "seconds": {"type": "integer", "description": (
                    "Une durée en secondes : celle d'un sondage (10 par défaut, "
                    "120 max) ou celle d'un compte à rebours (600 max). Pour un "
                    "minuteur, c'est ce paramètre qu'il faut remplir."
                )},
                "percent": {"type": "number", "description": "Pour gauge : le remplissage, de 0 à 100."},
                "count": {"type": "integer", "description": "Nombre de dés à lancer, pour dice (1 par défaut, 4 max)."},
                "cells": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Pour bingo : 4 à 9 pronostics courts sur ce qui va arriver pendant le live.",
                },
                "check": {"type": "string", "description": "Pour bingo : la case qui vient de se réaliser — son numéro (0 = la première) ou quelques mots de son intitulé."},
                "target": {"type": "integer", "description": "Pour goal : le nombre à atteindre."},
                "kind": {"type": "string", "enum": ["follow", "sub", "bits"], "description": "Pour goal : ce qu'on compte."},
                "about": {"type": "string", "description": "Pour meme : de quoi tu veux qu'il parle. Omets-le pour un tirage au hasard."},
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
                "word": {"type": "string", "description": (
                    "Pour hangman : le mot à deviner, 3 à 16 lettres. C'est TOI "
                    "qui le choisis, tout seul, dans le même appel — ne demande "
                    "jamais qu'on t'en propose un, c'est le principe du jeu que "
                    "les autres le devinent. Prends-le dans l'univers de la "
                    "chaîne (un jeu, une légende Apex, une expression maison). "
                    "Sans lui rien ne se lance, et ne le répète JAMAIS dans le "
                    "chat : tu ruinerais la partie."
                )},
                "hint": {"type": "string", "description": (
                    "Pour hangman : un indice court. Donne-le ici sans crainte — "
                    "il reste caché et n'apparaît à l'écran qu'à deux essais "
                    "restants. Ne l'écris donc pas dans le chat au lancement."
                )},
                "done": {"type": "string", "description": "Pour countdown : le texte affiché quand le compte à rebours arrive à zéro."},
                "close": {
                    "type": "boolean",
                    "description": (
                        "Pour rps : clôt la manche en cours au lieu d'en ouvrir "
                        "une. Sers-t'en pour trancher toi-même, ou pour libérer "
                        "un chifoumi resté ouvert."
                    ),
                },
                "move": {
                    "type": "string",
                    # En FRANÇAIS : c'est ce que `_RPS_MOVES` compare. Un enum en
                    # anglais faisait retomber la triche sur un tirage au hasard,
                    # Wally annonçant un coup et l'overlay en affichant un autre.
                    "enum": list(_RPS_MOVES),
                    "description": "Pour rps avec close : le coup que TU joues. Omets-le pour un tirage honnête.",
                },
            },
            "required": ["widget"],
        },
    },
}


# Narrateur actif, pour que `prompts.py` puisse lire l'état de l'overlay sans
# qu'on ait à faire descendre le narrateur jusque-là. Même patron que
# `stream_feed.activate()` — l'injection de dépendance s'arrête au bot Discord.
_active_narrator: "OverlayNarrator | None" = None


def current_overlay_state_block() -> Optional[str]:
    """Ce qui tourne sur l'overlay, prêt à injecter au prompt. None si rien."""
    if _active_narrator is None:
        return None
    try:
        return _active_narrator.current_state_block() or None
    except Exception as exc:  # noqa: BLE001 — un bloc de contexte ne casse pas un prompt
        logger.debug("Overlay: bloc d'état illisible: {e}", e=exc)
        return None


# Ce qu'on peut annuler. Constante de module : le spec de l'outil en a besoin
# avant que la classe ne soit définie, et les deux doivent rester d'accord —
# une cible acceptée par l'enum mais inconnue de `cancel()` répondrait
# « rien en cours » sur une demande pourtant valide.
CANCEL_TARGETS = ("ecran", "bingo", "pendu", "sondage", "chifoumi",
                  "objectif", "tout")


CANCEL_TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "cancel_overlay",
        "description": (
            "Retire quelque chose de l'overlay du stream : ce qui est affiché à "
            "l'instant, ou une partie en cours qu'on abandonne. Sers-t'en quand "
            "on te demande d'annuler ou d'enlever un truc — et de toi-même quand "
            "une partie traîne sans que personne y joue. Tu peux refuser, comme "
            "pour le reste. ⚠️ Un abandon ne donne PAS de résultat : un sondage "
            "annulé n'est pas dépouillé, un chifoumi annulé n'a pas de gagnant — "
            "ne les annonce pas. N'affirme jamais avoir annulé sans appeler cet "
            "outil : il te dira s'il y avait vraiment quelque chose."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "enum": list(CANCEL_TARGETS),
                    "description": (
                        "ecran = ce qui est affiché maintenant (un meme, un "
                        "message épinglé, un compteur) sans toucher aux parties "
                        "en cours · bingo · pendu · sondage · chifoumi · "
                        "objectif = la partie correspondante est abandonnée · "
                        "tout = l'écran ET toutes les parties. Dans le doute "
                        "entre « enlève ce qui est affiché » et « annule le "
                        "bingo », choisis la cible précise."
                    ),
                },
                "comment": {
                    "type": "string",
                    "description": "Ta réplique, quelques mots. Facultatif.",
                },
            },
            "required": ["target"],
        },
    },
}


LAST_CLIP_TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "show_last_clip",
        "description": (
            "Rejoue le DERNIER clip de la chaîne sur l'overlay du stream, quand "
            "on te le demande. La vidéo est MUETTE et reste à l'écran le temps "
            "du clip. Tu n'as pas vu ce clip — l'outil te rend son titre et qui "
            "l'a créé, commente à partir de ça et n'invente pas ce qu'il "
            "contient. N'affirme jamais l'avoir lancé sans appeler cet outil, "
            "et ne décrète pas non plus que c'est impossible sans l'avoir "
            "appelé : c'est lui qui sait si l'overlay répond."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "author": {
                    "type": "string",
                    "description": (
                        "Qui a fait le clip, si on te le précise (« le dernier "
                        "clip d'azra »). Un surnom suffit. Laisse vide pour le "
                        "dernier clip de la chaîne, qui que ce soit."
                    ),
                },
                "comment": {
                    "type": "string",
                    "description": "Ta réplique, quelques mots. Facultatif.",
                },
            },
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
        memes=None,
        last_clip: Optional[Callable] = None,
        apex=None,
    ) -> None:
        self._feed = overlay_feed
        self._llm = llm
        # Service Apex, pour les panneaux dont la donnée se récupère en ligne.
        self._apex = apex
        self._is_live = is_live
        self._min_interval = min_interval_s
        self._event_interval = event_interval_s
        # Statut du live ({live, title, category, viewers, started_at}) pour les
        # widgets qui ont besoin de données réelles (uptime).
        self._stream_status = stream_status
        # Le résultat d'un sondage y est consigné : c'est ce qui le rend
        # visible dans le prompt, donc répondable.
        self._stream_feed = stream_feed
        self._memes = memes
        # Fournisseur ASYNC du dernier clip (Helix). Injecté : le narrateur ne
        # connaît pas l'API Twitch, et `show_widget` est synchrone.
        self._last_clip = last_clip
        self._greeted: set[str] = set()
        self._was_live: bool = False
        self._force_until: float = 0.0
        self._poll: Optional[dict] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._last_poll: Optional[dict] = None
        # Grille du bingo (widget 20) : vit le temps d'un live.
        self._bingo: Optional[dict] = None
        # Chifoumi en cours (widget « le chat contre Wally »).
        self._rps: Optional[dict] = None
        self._rps_task: Optional[asyncio.Task] = None
        # Pendu en cours. Le mot reste ICI : l'overlay ne reçoit que les
        # lettres trouvées, sinon les viewers le liraient à l'écran.
        self._hangman: Optional[dict] = None
        # Dernier rappel du bingo : il se fait oublier entre deux cases.
        self._bingo_reminded_at: float = 0.0
        # Objectif du live (follows / subs / bits), rempli par les
        # événements réels plutôt que par un chiffre saisi à la main.
        self._goal: Optional[dict] = None
        # Dernières bulles dites : sert à ne pas répéter la même chose.
        self._recent_bubbles: deque = deque(maxlen=8)
        # Messages du chat par personne depuis le début du live : sert au
        # classement des bavards, à la demande.
        self._talkers: dict = {}
        self._last_bubble_at: float = 0.0
        self._last_event_at: float = 0.0

    def activate(self) -> None:
        """S'enregistre comme narrateur lu par `current_overlay_state_block()`."""
        global _active_narrator
        _active_narrator = self

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

    @staticmethod
    def _key_words(text: str) -> set:
        """Mots porteurs d'une réplique, pour comparer deux bulles entre elles."""
        folded = unicodedata.normalize("NFD", (text or "").lower())
        folded = "".join(c for c in folded if unicodedata.category(c) != "Mn")
        return {w for w in re.findall(r"[a-z]+", folded) if len(w) > 3}

    def _is_repeat(self, text: str) -> bool:
        """Vrai si Wally vient de dire à peu près la même chose.

        Plusieurs sources produisent des réactions voisines — un salut, une vague
        de follows, un changement d'audience se ressemblent tous. Sans garde, il
        répète « du monde arrive » toute la soirée.
        """
        words = self._key_words(text)
        if len(words) < 2:
            return False
        for previous in self._recent_bubbles:
            common = words & previous
            if not common:
                continue
            # Deux répliques qui partagent l'essentiel de leurs mots porteurs
            # disent la même chose, quelle qu'en soit la tournure.
            if len(common) / min(len(words), len(previous)) >= 0.6:
                return True
        return False

    def _remember_bubble(self, text: str) -> None:
        words = self._key_words(text)
        if words:
            self._recent_bubbles.append(words)

    # ── pensées ───────────────────────────────────────────────────────────

    async def on_thought(self, text: str) -> Optional[str]:
        """Publie une pensée condensée, si le budget le permet.

        Retourne le texte affiché, ou None si rien n'a été publié.
        """
        if not (text or "").strip():
            return None
        if not self._may_speak():
            # Distinguer les deux refus : « pas de live » et « trop tôt » n'ont
            # pas la même correction.
            logger.info("Overlay: pensée retenue ({r})",
                        r="hors live" if not self._live() else "intervalle non écoulé")
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
        if self._is_repeat(short):
            logger.info("Overlay: pensée écartée (déjà dite) — « {t} »", t=short)
            self._feed.thinking(False)
            return None
        # Après le test, pas avant : sinon les logs comptent des bulles jetées.
        logger.info("Overlay: pensée affichée — « {t} »", t=short)
        self._remember_bubble(short)
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
        if self._is_repeat(short):
            logger.info("Overlay: réplique écartée (déjà dite) — « {t} »", t=short)
            # N'éteindre que ce qu'on a allumé. Le vocal passif passe ici à chaque
            # phrase entendue avec `show_thinking=False` ; un `thinking(False)`
            # non apparié efface la bulle affichée deux secondes plus tôt.
            if show_thinking:
                self._feed.thinking(False)
            return None
        self._mark_spoken()
        self._remember_bubble(short)
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
        # PAS de budget ici : on le lui demande. Le budget existe pour brider ce
        # que Wally dit de lui-même — l'appliquer à une sollicitation directe
        # revient à l'ignorer. Vu en live : trois personnes parlant en continu
        # saturaient le budget par le vocal passif, et « Wally, lance un dé »
        # tombait dans le vide.
        if not text or not self._live():
            return None
        self._last_event_at = time.monotonic()
        self._feed.thinking(True)

        shown: list[dict] = []

        async def _execute(name: str, arguments: str) -> str:
            if name not in ("show_overlay", "cancel_overlay", "show_last_clip", "show_apex"):
                return json.dumps({"status": "unknown_tool"})
            try:
                args = json.loads(arguments or "{}")
            except json.JSONDecodeError:
                return json.dumps({"status": "error", "message": "arguments illisibles"})
            if name == "show_apex":
                out = await self.show_apex(
                    str(args.get("panel") or ""), str(args.get("player") or "")[:32],
                    str(args.get("comment") or ""),
                )
                if out is None:
                    return json.dumps({"status": "nothing", "message": (
                        "Rien affiché : donnée Apex indisponible ou pas de live. "
                        "Dis-le simplement, ne prétends pas l'avoir montré."
                    )})
                return json.dumps({"status": "ok", **out})
            if name == "show_last_clip":
                auteur = str(args.get("author") or "").strip()[:40] or None
                out = await self.play_last_clip(auteur)
                if out is None:
                    de_qui = f" clippé par {auteur}" if auteur else ""
                    return json.dumps({"status": "nothing", "message": (
                        f"Aucun clip récent{de_qui}. Dis-le, n'en invente pas un."
                    )})
                return json.dumps({"status": "ok", **{k: str(v) for k, v in out.items()},
                                   "message": "Tu ne l'as pas vu : ne raconte pas "
                                              "ce qu'il contient."})
            if name == "cancel_overlay":
                # « Wally, annule le bingo » arrive par le vocal bien plus
                # souvent que par le chat : sans cet outil ici, la demande
                # tombait dans le vide alors même qu'on la lui adressait.
                result = self.cancel(str(args.get("target") or ""))
                done = result.get("cancelled") or []
                if not done:
                    return json.dumps({"status": "nothing", "message": (
                        "Rien à annuler, ce n'était pas en cours. Dis-le, "
                        "ne prétends pas l'avoir retiré."
                    )})
                return json.dumps({"status": "ok", "cancelled": ", ".join(done)})
            extra = {k: v for k, v in args.items()
                     if k not in ("widget", "comment", "result") and v is not None}
            out = self.show_widget(
                str(args.get("widget") or ""), str(args.get("comment") or ""),
                result=args.get("result"), **extra,
            )
            if out is None:
                # La consigne compte autant que le statut : sur un refus sec,
                # le modèle paraphrasait le compte rendu — « l'outil me répond
                # que… » s'est retrouvé en toutes lettres sur l'overlay public.
                return json.dumps({"status": "rejected", "message": (
                    "Rien affiché : widget inconnu ou données manquantes. Ne "
                    "parle NI de l'outil NI du paramètre — réagis en quelques "
                    "mots, ou réponds RIEN."
                )})
            shown.append(out)
            return json.dumps({"status": "ok", **{k: str(v) for k, v in out.items()}})

        try:
            reply, _ = await self._llm.complete_with_tools(
                system_prompt=_VOICE_SYSTEM,
                messages=[{"role": "user", "content": f"{speaker} (à voix haute) : {text}"}],
                tools=[OVERLAY_TOOL_SPEC, CANCEL_TOOL_SPEC, LAST_CLIP_TOOL_SPEC, APEX_OVERLAY_TOOL],
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
        if self._is_repeat(short):
            logger.info("Overlay: réplique écartée (déjà dite) — « {t} »", t=short)
            self._feed.thinking(False)
            return None
        self._mark_spoken()
        self._remember_bubble(short)
        self._feed.say(short, mode="speech")
        return short

    # ── widgets ───────────────────────────────────────────────────────────

    # Widgets connus. Le résultat est tiré ICI et non dans le navigateur : c'est
    # ce qui permet à Wally de commenter son propre tirage — et de tricher.
    # C'est aussi la source du self-model : tout ce que Wally sait montrer.
    _WIDGETS = ("coinflip", "dice", "counter", "wheel", "countdown", "gauge",
                "pinned", "uptime", "poll", "stats", "versus", "bingo",
                "prediction", "meme", "rps", "hangman", "quote", "goal",
                "talkers", "clip", "wave")

    # Sous-ensemble que `show_widget` sait rendre. `quote`, `prediction` et
    # `clip` sont déclenchés ailleurs (`show_quote`, `show_prediction`,
    # `show_clip`) avec des données qu'un appel générique n'a pas : les laisser
    # passer ici publiait une carte VIDE, et `_overlay_outcome` répondait
    # « c'est à l'écran » — Wally annonçait une citation qui n'existait pas.
    _DIRECT_WIDGETS = tuple(
        w for w in _WIDGETS if w not in ("quote", "prediction", "clip", "wave")
    )

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
        if widget not in self._DIRECT_WIDGETS or not self._live():
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
            # `seconds` d'abord, `result` en repli. Devant « un minuteur de 10
            # secondes », le modèle remplit `seconds` — c'est le nom évident, et
            # le schéma l'expose par ailleurs pour le sondage. En n'acceptant
            # que `result`, ce widget refusait toute demande formulée
            # naturellement : vu en live le 2026-08-07, deux appels, deux refus.
            # `poll` accepte déjà les deux, c'est le motif qu'on reprend.
            try:
                seconds = int(extra.get("seconds") if extra.get("seconds") is not None
                              else result)
            except (TypeError, ValueError):
                return None
            seconds = max(1, min(600, seconds))
            # `duration` explicite : sans elle, `OverlayFeed` posait son défaut de
            # 10 s et un compte à rebours de 2 minutes disparaissait de l'écran
            # au bout de dix secondes, son `setInterval` coupé par clearWidgets().
            params = {"seconds": seconds, "duration": seconds + 3}
            if extra.get("done"):
                params["done"] = str(extra["done"])[:20]

        elif widget == "gauge":
            # Même classe de défaut que le compte à rebours : « percent » est le
            # mot que le modèle lit dans la description, il le renvoie tel quel.
            try:
                percent = float(extra.get("percent") if extra.get("percent") is not None
                                else result)
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

        elif widget == "talkers":
            shown = self.show_talkers()
            if shown is None:
                return None
            return shown

        elif widget == "goal":
            # Distinct de `gauge` : celle-ci se remplit toute seule, l'autre
            # attend un pourcentage donné à la main.
            if not self.open_goal(str(extra.get("label") or comment or ""),
                                  extra.get("target"), str(extra.get("kind") or "")):
                return None
            return {"widget": "goal", **self._goal}

        elif widget == "hangman":
            if not self.start_hangman(str(extra.get("word") or ""),
                                      str(extra.get("hint") or comment or "")):
                return None
            return {"widget": "hangman", "letters": len(set(
                c for c in self._fold(str(extra.get("word"))) if c.isalpha()))}

        elif widget == "rps":
            # Deux gestes : ouvrir la manche, ou la trancher (rare — la clôture
            # est planifiée, mais Wally peut vouloir couper court).
            if extra.get("close"):
                return self.close_rps(str(extra.get("move") or ""))
            try:
                seconds = int(extra.get("seconds") or result or 15)
            except (TypeError, ValueError):
                seconds = 15
            if not self.start_rps(seconds):
                return None
            return {"widget": "rps", "seconds": seconds}

        elif widget == "meme":
            # L'image est choisie ICI : Wally ne la voit pas, il ne connaît que
            # sa description — c'est elle qui lui permet de commenter juste.
            library = self._memes
            if library is None:
                return None
            chosen = library.pick(str(extra.get("about") or comment or ""))
            if chosen is None:
                return None
            params = {"src": f"/api/public/meme/{quote(chosen['name'])}",
                      "caption": chosen["description"][:70]}
            self._feed.widget("meme", **params)
            return {"widget": "meme", **chosen}

        elif widget == "bingo":
            # Deux gestes sur le même widget : ouvrir la grille, ou cocher une
            # case. Le distinguer par la présence de `cells` évite d'exposer deux
            # outils au modèle pour une seule idée.
            cells = [str(c).strip()[:34] for c in (extra.get("cells") or []) if str(c).strip()]
            if cells:
                if not self.start_bingo(cells):
                    return None
                return {"widget": "bingo", "cells": self._bingo["cells"]}
            if extra.get("check") is not None:
                checked = self.check_bingo(extra.get("check"))
                if checked is None:
                    return None
                return checked
            # Ni cases ni coche : on redemande simplement la grille. Elle ne
            # reste pas à l'écran, et sans ça on ne pouvait pas la revoir.
            return self.show_bingo()

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

    async def show_apex(
        self, panel: str, player: str = "", comment: str = "",
        requester: Optional[str] = None,
    ) -> Optional[dict]:
        """Affiche un panneau de données Apex réelles. None si rien à montrer.

        Méthode à part — et asynchrone — pour la même raison que `play_last_clip` :
        la donnée vient du réseau, ce que `show_widget` (synchrone) ne peut pas
        faire. Le modèle ne fournit aucun chiffre, il nomme un panneau.
        """
        if self._apex is None or not self._live():
            return None
        try:
            data = await self._apex.build_panel(panel, player, requester=requester)
        except Exception as exc:  # noqa: BLE001 — un panneau raté ne casse rien
            logger.warning("Overlay: panneau Apex {p} échoué: {e}", p=panel, e=exc)
            return None
        if not data:
            return None
        params = {k: v for k, v in data.items() if k != "kind"}
        self._feed.widget(data["kind"], **params)
        if comment:
            # Même règle que `show_widget` : la bulle s'efface derrière un widget,
            # mais le créneau reste consommé pour qu'une pensée ne s'empile pas.
            self._mark_spoken()
        return {"widget": data["kind"], "player": str(params.get("player") or "")}

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
        if author:
            key = author.strip()
            self._talkers[key] = self._talkers.get(key, 0) + 1
        self.maybe_remind_bingo()
        # Les trois compteurs attendent un message NU : une lettre seule, un
        # chiffre seul, un nom de coup. Or on répond à un bot en le mentionnant —
        # « @WallyTeBully d ». Le 2026-08-07, deux parties de pendu n'ont ainsi
        # enregistré aucune lettre. On retire l'interpellation ici, une fois pour
        # les trois, plutôt que dans chacun.
        played = _strip_address(text)
        self._count_vote(author, played)
        self._count_rps(author, played)
        self._count_hangman(author, played)
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
        # Deux arrivées rapprochées produisent deux « du monde arrive » quasi
        # identiques : c'est le cas que `_is_repeat` a été écrit pour couvrir.
        # Et sans `_remember_bubble`, la bulle suivante n'était pas dédupliquée
        # contre le salut non plus.
        if self._is_repeat(short):
            logger.info("Overlay: salut écarté (déjà dit) — « {t} »", t=short)
            self._feed.thinking(False)
            return
        self._mark_spoken()
        self._remember_bubble(short)
        self._feed.say(short, mode="speech")

    def reset_live(self) -> None:
        """Remet à zéro l'état lié à un live (saluts, sondage, bingo)."""
        self._greeted.clear()
        self._poll = None
        self._bingo = None
        self._bingo_reminded_at = 0.0
        self._goal = None
        self._recent_bubbles.clear()
        self._talkers.clear()
        self._rps = None
        self._hangman = None

    # ── annulation ────────────────────────────────────────────────────────

    def cancel(self, target: str) -> dict:
        """Retire ce qui est à l'écran, ou abandonne une partie en cours.

        Un ABANDON, pas une clôture : un sondage annulé ne dépouille pas et un
        chifoumi annulé ne rend pas de verdict. Passer par `close_poll()` ferait
        annoncer un gagnant à une manche qu'on vient justement d'interrompre.

        Volontairement insensible au live : on annule aussi — et surtout — quand
        le stream vient de se couper avec un bingo resté ouvert.

        Retourne ce qui a RÉELLEMENT été annulé. La liste vide est la réponse
        utile : elle permet de dire « il n'y avait pas de bingo » au lieu de
        laisser croire que quelque chose a été retiré.
        """
        target = (target or "").strip().lower()
        if target not in CANCEL_TARGETS:
            return {"target": target, "cancelled": [], "unknown": True}

        everything = target == "tout"
        done: list[str] = []

        if (everything or target == "bingo") and self._bingo:
            self._bingo = None
            self._bingo_reminded_at = 0.0
            done.append("bingo")
        if (everything or target == "pendu") and self._hangman:
            self._hangman = None
            done.append("pendu")
        if (everything or target == "objectif") and self._goal:
            self._goal = None
            done.append("objectif")
        if (everything or target == "sondage") and self._poll:
            self._poll = None
            self._cancel_task("_poll_task")
            done.append("sondage")
        if (everything or target == "chifoumi") and self._rps:
            self._rps = None
            self._cancel_task("_rps_task")
            done.append("chifoumi")

        # L'écran est nettoyé dès qu'on annule quoi que ce soit : abandonner le
        # bingo en laissant sa grille affichée n'aurait aucun sens.
        if target in ("ecran", "tout") or done:
            self._feed.clear()
            if target in ("ecran", "tout"):
                done.append("ecran")

        logger.info("Overlay: annulation « {t} » — {d}",
                    t=target, d=", ".join(done) or "rien en cours")
        return {"target": target, "cancelled": done}

    def _cancel_task(self, attr: str) -> None:
        """Coupe une clôture planifiée. Sans ça, le `sleep` en cours rouvrirait
        le dépouillement d'un sondage qu'on vient d'abandonner."""
        task = getattr(self, attr, None)
        if task is not None:
            task.cancel()
            setattr(self, attr, None)

    def current_state_block(self) -> str:
        """Ce qui tourne sur l'overlay, pour le prompt. Vide s'il n'y a rien.

        ⚠️ Perception PASSIVE, comme `StreamFeed` : aucun `notify_*` derrière,
        donc ce bloc ne réveille jamais la cadence vive ni une prise de parole.
        Un bingo ouvert ferait sinon parler Wally en boucle pendant tout le live.
        """
        if not self._live():
            return ""
        lines: list[str] = []
        if self._bingo:
            done = sum(1 for d in self._bingo["done"] if d)
            lines.append(f"Bingo : {done}/{len(self._bingo['cells'])} cases cochées.")
        if self._hangman:
            game = self._hangman
            remaining = len({c for c in game["word"] if c.isalpha()} - game["found"])
            # SANS le mot ni l'indice : ce bloc part dans le prompt, et tout le
            # reste du widget s'applique à ne jamais laisser fuir le mot. Le
            # compte des lettres suffit à animer la partie.
            lines.append(
                f"Pendu en cours : {remaining} lettres restent à trouver, "
                f"{self._HANGMAN_MAX_MISSES - len(game['missed'])} essais avant "
                "la fin. Les messages d'une seule lettre sont des propositions, "
                "comptées automatiquement — n'y réponds pas une par une."
            )
        if self._goal:
            goal = self._goal
            lines.append(f"Objectif « {goal['label']} » : {goal['count']}/{goal['target']}.")
        if self._poll:
            lines.append(f"Sondage en cours : « {self._poll['question']} ».")
        if self._rps:
            lines.append("Chifoumi ouvert, le chat vote son coup.")
        if lines:
            lines.append("Tu peux annuler ce qui traîne avec `cancel_overlay`.")
        if self.force_live_remaining() > 0:
            # Le seul cas où `stream_live` ment par omission : il dira « pas de
            # live », ce qui est vrai, et Wally en concluait que ses outils
            # d'overlay ne marchaient pas — il refusait d'afficher un clip sans
            # même appeler l'outil. En vrai live, cette ligne serait redondante.
            lines.insert(0, (
                "Mode test : aucun live ne tourne, mais ton overlay répond "
                "quand même et tes outils d'overlay marchent. Personne d'autre "
                "que ton créateur ne le voit — ne dis pas au chat qu'on est en "
                "stream."
            ))
        if not lines:
            return ""
        return "\n--- Sur ton overlay ---\n" + "\n".join(lines)

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

    def show_quote(self, author: str, text: str, *, age: str = "") -> bool:
        """Affiche une réplique citée. `age` situe le moment (« hier », « mardi »)."""
        if not self._live() or not text:
            return False
        self._last_event_at = time.monotonic()
        self._feed.widget("quote", author=str(author)[:24], text=str(text)[:160],
                          age=str(age)[:24], duration=12)
        return True

    # Paliers auxquels un compteur mérite un mot. Au-delà de 100, tous les 100 :
    # un gag qui atteint 300 n'a pas besoin d'être commenté à 310.
    _COUNTER_MILESTONES = (10, 25, 50, 100)

    @classmethod
    def is_counter_milestone(cls, count: int) -> bool:
        return count in cls._COUNTER_MILESTONES or (count > 100 and count % 100 == 0)

    async def on_counter_milestone(self, label: str, count: int) -> Optional[str]:
        """Fait commenter un compteur qui atteint un palier.

        Un chiffre qui monte tout seul finit par ne plus rien dire ; c'est la
        remarque qui fait le gag. Rare par construction — seulement aux paliers.

        Rationné par le budget des BULLES, pas par celui des événements : les
        appelants font `show_counter()` puis ce commentaire dans la foulée, or
        le compteur vient de consommer le budget événement. Le tester ici
        refusait le palier à tous les coups — sauf quand le compteur lui-même
        avait été refusé, exactement à l'envers.
        """
        if not self.is_counter_milestone(count) or not self._may_speak():
            return None
        # Réserve le créneau avant l'appel, comme `on_thought`.
        self._mark_spoken()
        try:
            short = await self._condense(
                f"Le compteur « {label} » vient d'atteindre {count}.",
                system=_EVENT_SYSTEM,
            )
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            logger.debug("Overlay: commentaire de palier échoué: {e}", e=exc)
            return None
        if not short:
            return None
        if self._is_repeat(short):
            logger.info("Overlay: palier écarté (déjà dit) — « {t} »", t=short)
            return None
        self._remember_bubble(short)
        self._feed.say(short, mode="speech")
        logger.info("Overlay: palier {n} sur « {l} » — {t}", n=count, l=label, t=short)
        return short

    def maybe_remind_bingo(self, every_s: float = 600.0) -> bool:
        """Remontre la grille de temps en temps.

        Sans rappel, elle n'apparaît qu'aux cases cochées : les viewers arrivés
        entre-temps ne savent pas qu'une partie est en cours.
        """
        if not self._bingo or not self._may_react():
            return False
        now = time.monotonic()
        if now - self._bingo_reminded_at < every_s:
            return False
        self._bingo_reminded_at = now
        self._feed.widget("bingo", cells=self._bingo["cells"],
                          done=list(self._bingo["done"]), duration=10)
        return True

    # Ce qu'un objectif peut compter, et le nom qu'on lui donne à l'écran.
    _GOAL_KINDS = {"follow": "follows", "sub": "abonnements", "bits": "bits"}

    def open_goal(self, label: str, target: int, kind: str) -> bool:
        """Ouvre un objectif alimenté par les vrais événements du live."""
        kind = (kind or "").strip().lower()
        try:
            target = int(target)
        except (TypeError, ValueError):
            return False
        if kind not in self._GOAL_KINDS or target < 1 or not self._live():
            return False
        self._goal = {"label": " ".join((label or "").split())[:40] or self._GOAL_KINDS[kind],
                      "target": min(target, 100000), "kind": kind, "count": 0}
        self._publish_goal()
        logger.info("Overlay: objectif « {l} » — {n} {k}",
                    l=self._goal["label"], n=target, k=kind)
        return True

    def record_goal_event(self, kind: str, amount: int = 1) -> bool:
        """Incrémente l'objectif si l'événement le concerne.

        Appelé depuis les événements Twitch : c'est ce qui remplit la jauge
        toute seule, au lieu d'un chiffre qu'il faudrait redonner à la main.
        """
        goal = self._goal
        if not goal or goal["kind"] != (kind or "").lower():
            return False
        goal["count"] += max(1, int(amount or 1))
        self._publish_goal()
        if goal["count"] >= goal["target"]:
            logger.info("Overlay: objectif « {l} » atteint", l=goal["label"])
            self._goal = None
        return True

    def _publish_goal(self) -> None:
        goal = self._goal
        if not goal:
            return
        percent = min(100.0, goal["count"] * 100.0 / goal["target"])
        self._feed.widget(
            "gauge", percent=percent,
            label=f"{goal['label']} · {goal['count']}/{goal['target']}",
            duration=10,
        )

    def show_talkers(self, top: int = 3) -> Optional[dict]:
        """Classement des plus bavards du chat depuis le début du live.

        Purement mécanique : rien n'est interprété, donc rien ne peut être
        inventé. Sur demande seulement — un classement permanent inciterait au
        spam.
        """
        if not self._live() or not self._talkers:
            return None
        ranking = sorted(self._talkers.items(), key=lambda kv: (-kv[1], kv[0]))[:max(1, top)]
        # Même forme des deux côtés : l'exécuteur d'outil fait `str(v)` sur ce
        # qu'on renvoie, et Wally lisait « [('alice', 12), ...] ».
        rows = [{"name": n, "count": c} for n, c in ranking]
        self._feed.widget("talkers", rows=rows, duration=10)
        return {"widget": "talkers", "rows": rows}

    # Un embed n'est accepté que s'il vient bien de Twitch : cette URL part
    # dans le `src` d'une iframe côté navigateur.
    _CLIP_EMBED_PREFIX = "https://clips.twitch.tv/embed?"

    # Marge de chargement : sans elle, le widget s'efface au moment précis où la
    # vidéo finit — voire avant qu'elle n'ait démarré.
    _CLIP_LOAD_MARGIN_S = 3.0

    # Le fichier vidéo part dans un `<video src>` : on n'accepte que du https
    # servi par Twitch ou son CDN. Le nom de distribution CloudFront change
    # d'un clip à l'autre, d'où le suffixe plutôt qu'une liste figée.
    _CLIP_VIDEO_HOSTS = (".cloudfront.net", ".twitch.tv", ".twitchcdn.net")

    @classmethod
    def _is_clip_video(cls, url: str) -> bool:
        if not url.startswith("https://"):
            return False
        host = url[len("https://"):].split("/", 1)[0].split("?", 1)[0].lower()
        return any(host.endswith(suffix) for suffix in cls._CLIP_VIDEO_HOSTS)

    @classmethod
    def _clip_duration(cls, duration) -> float:
        """Temps d'affichage : la durée du clip, plus la marge de chargement."""
        try:
            seconds = float(duration)
        except (TypeError, ValueError):
            seconds = 0.0
        # Un clip Twitch fait 60 s au plus ; la borne protège d'une valeur
        # aberrante qui figerait l'overlay.
        return max(1.0, min(60.0, seconds or 30.0)) + cls._CLIP_LOAD_MARGIN_S

    def show_clip(self, title: str, author: str, *, embed_url: str = "",
                  video_url: str = "", duration: float = 0.0) -> bool:
        """Montre un clip. Trois niveaux, du meilleur au moins bon :

        1. `video_url` — le fichier vidéo, joué par une balise `<video muted>`.
           C'est le seul mode qui démarre TOUT SEUL : le player Twitch en
           iframe refuse l'autoplay dans un overlay (« style visibility »,
           faux positif non corrigé côté Twitch).
        2. `embed_url` — le player officiel. S'affiche, mais attend un clic.
           Sert de filet si l'API GraphQL non officielle change.
        3. la carte texte, quand on n'a ni l'un ni l'autre.

        Pas soumis au budget : clipper est un geste rare, et le signaler
        récompense celui qui l'a fait — c'est tout l'intérêt.
        """
        if not self._live():
            return False
        params: dict = {"title": str(title)[:80], "author": str(author)[:24]}
        embed_url = str(embed_url or "")
        video_url = str(video_url or "")
        if self._is_clip_video(video_url):
            params["video"] = video_url
            params["duration"] = self._clip_duration(duration)
        elif embed_url.startswith(self._CLIP_EMBED_PREFIX):
            params["embed"] = embed_url
            params["duration"] = self._clip_duration(duration)
        else:
            params["duration"] = 10
        self._last_event_at = time.monotonic()
        self._feed.widget("clip", **params)
        return True

    async def play_last_clip(self, creator: Optional[str] = None) -> Optional[dict]:
        """Rejoue le dernier clip de la chaîne. None s'il n'y en a pas.

        `creator` restreint au clippeur demandé — le filtrage appartient au
        fournisseur, seul à parler à Helix.

        Le fournisseur est injecté plutôt qu'appelé d'ici : `show_widget` est
        synchrone et n'a aucun moyen d'interroger une API externe, alors que
        « affiche le dernier clip » en dépend entièrement.
        """
        if self._last_clip is None or not self._live():
            return None
        try:
            clip = await self._last_clip(creator)
        except Exception as exc:  # noqa: BLE001 — une API muette ne casse rien
            logger.warning("Overlay: dernier clip introuvable : {e}", e=exc)
            return None
        if not clip:
            return None
        title = str(clip.get("title") or "un clip")
        author = str(clip.get("creator_name") or "quelqu'un")
        embed = str(clip.get("embed_url") or "")
        video = str(clip.get("video_url") or "")
        if not self.show_clip(title, author, embed_url=embed, video_url=video,
                              duration=clip.get("duration") or 0.0):
            return None
        # « joué » veut dire : ça démarre tout seul. L'iframe s'affiche mais
        # attend un clic — Wally ne doit pas annoncer une lecture dans ce cas.
        played = self._is_clip_video(video)
        logger.info(
            "Overlay: clip « {t} » de {a} — {m}", t=title, a=author,
            m="joué" if played else ("player en attente de clic" if embed else "carte seule"),
        )
        return {"widget": "clip", "title": title, "author": author,
                "played": played}

    def show_emote_wave(self, emote: str) -> bool:
        """Signale que le chat spamme le même emote."""
        if not self._may_react():
            return False
        self._last_event_at = time.monotonic()
        self._feed.widget("wave", emote=str(emote)[:30], duration=6)
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

    def show_bingo(self) -> Optional[dict]:
        """Réaffiche la grille en cours, sur demande."""
        if not self._bingo or not self._live():
            return None
        self._bingo_reminded_at = time.monotonic()
        self._feed.widget("bingo", cells=self._bingo["cells"],
                          done=list(self._bingo["done"]), duration=10)
        return {"widget": "bingo", "cells": self._bingo["cells"]}

    def _bingo_index(self, needle) -> Optional[int]:
        """Retrouve une case par son numéro OU par son intitulé.

        Le modèle ne voit pas la grille : lui demander un index de mémoire est
        le meilleur moyen qu'il coche la mauvaise case.
        """
        bingo = self._bingo
        if not bingo:
            return None
        try:
            return int(needle)
        except (TypeError, ValueError):
            pass
        words = [w for w in self._fold(str(needle)).split() if len(w) > 2]
        if not words:
            return None
        for i, cell in enumerate(bingo["cells"]):
            folded = self._fold(cell)
            if all(w in folded for w in words):
                return i
        # À défaut d'une correspondance complète, la case qui partage le plus
        # de mots — « le ping » doit trouver « il blâme le ping ».
        scores = [(sum(1 for w in words if w in self._fold(c)), i)
                  for i, c in enumerate(bingo["cells"])]
        best, index = max(scores)
        return index if best else None

    def check_bingo(self, index) -> Optional[dict]:
        """Coche une case. Retourne None si rien n'a changé — le widget ne doit
        pas réapparaître pour une case déjà cochée."""
        bingo = self._bingo
        if not bingo:
            return None
        i = self._bingo_index(index)
        if i is None:
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

    # ── pendu ─────────────────────────────────────────────────────────────

    _HANGMAN_MAX_MISSES = 6   # tête, corps, deux bras, deux jambes

    @staticmethod
    def _fold(text: str) -> str:
        """Minuscules sans accents : « FLÈCHE » et « fleche » sont le même mot."""
        text = unicodedata.normalize("NFD", (text or "").lower())
        return "".join(c for c in text if unicodedata.category(c) != "Mn")

    def start_hangman(self, word: str, hint: str = "") -> bool:
        """Ouvre une partie. Le mot n'est jamais publié — seules ses lettres le sont."""
        folded = self._fold(word)
        letters = [c for c in folded if c.isalpha()]
        if len(letters) < 3 or len(letters) > 16 or not self._live():
            return False
        self._hangman = {
            "word": folded,
            "display": " ".join(word.split())[:40],
            "hint": " ".join((hint or "").split())[:60],
            "found": set(),
            "missed": [],
        }
        self._publish_hangman()
        logger.info("Overlay: pendu ouvert ({n} lettres)", n=len(set(letters)))
        return True

    def _count_hangman(self, author: str, text: str) -> None:
        """Une proposition = UNE lettre seule. Sinon tout message en contiendrait."""
        game = self._hangman
        if not game:
            return
        token = self._fold(text).strip()
        if len(token) != 1 or not token.isalpha():
            return
        if token in game["found"] or token in game["missed"]:
            return
        if token in game["word"]:
            game["found"].add(token)
            won = all(c in game["found"] for c in game["word"] if c.isalpha())
            self._publish_hangman(last=token, won=won)
            if won:
                logger.info("Overlay: pendu gagné par le chat ({w})", w=game["display"])
                self._hangman = None
            return
        game["missed"].append(token)
        lost = len(game["missed"]) >= self._HANGMAN_MAX_MISSES
        self._publish_hangman(last=token, lost=lost)
        if lost:
            logger.info("Overlay: pendu perdu ({w})", w=game["display"])
            self._hangman = None

    def _publish_hangman(self, last: str = "", won: bool = False, lost: bool = False) -> None:
        game = self._hangman
        if not game:
            return
        # Le mot part lettre par lettre, masquée tant qu'elle n'est pas trouvée.
        mask = [
            (c if (not c.isalpha() or c in game["found"] or won or lost) else "")
            for c in game["word"]
        ]
        # L'indice est un SECOURS, pas une ouverture : le donner au lancement
        # (ce que faisait ce widget) revient à résoudre le pendu à la place du
        # chat. Il n'apparaît qu'à deux essais restants — ou à la fin, où il
        # n'aide plus personne mais dit ce qu'on cherchait.
        en_difficulte = len(game["missed"]) >= self._HANGMAN_MAX_MISSES - 2
        hint = game["hint"] if (en_difficulte or won or lost) else ""
        self._feed.widget(
            "hangman", mask=mask, missed=list(game["missed"]),
            misses=len(game["missed"]), max_misses=self._HANGMAN_MAX_MISSES,
            hint=hint, last=last, won=won, lost=lost,
            word=game["display"] if (won or lost) else "",
            duration=12 if (won or lost) else 10,
        )

    # ── chifoumi : le chat contre Wally ───────────────────────────────────

    _RPS_MOVES = _RPS_MOVES      # alias : les appels internes restent en `self.`
    # Ce que chaque coup bat : sert à trancher sans table de vérité à rallonge.
    _RPS_BEATS = {"pierre": "ciseaux", "feuille": "pierre", "ciseaux": "feuille"}

    def start_rps(self, seconds: int = 15) -> bool:
        """Ouvre un chifoumi : le chat vote, Wally jouera contre la majorité."""
        if not self._live() or self._rps is not None:
            return False
        seconds = max(5, min(60, int(seconds or 15)))
        self._rps = {"votes": {}, "ends_at": time.monotonic() + seconds}
        self._feed.widget("rps", phase="voting", seconds=seconds,
                          tally=[0, 0, 0], duration=seconds + 2)
        self._schedule_rps_close(seconds)
        logger.info("Overlay: chifoumi ouvert ({s}s)", s=seconds)
        return True

    def _schedule_rps_close(self, seconds: int) -> None:
        if self._rps_task is not None:
            self._rps_task.cancel()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._rps_task = None      # hors boucle (tests synchrones)
            return
        self._rps_task = loop.create_task(self._close_rps_after(seconds))

    async def _close_rps_after(self, seconds: int) -> None:
        try:
            await asyncio.sleep(seconds)
            self.close_rps()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            logger.warning("Overlay: clôture du chifoumi en erreur: {e}", e=exc)

    def _count_rps(self, author: str, text: str) -> None:
        """Un vote = le nom du coup, ou son numéro. Un seul par personne."""
        rps = self._rps
        if not rps:
            return
        if time.monotonic() > rps["ends_at"]:
            # Filet symétrique à celui du sondage : si la tâche de clôture a été
            # perdue (ouverture hors boucle asyncio, annulation), `self._rps`
            # restait renseigné pour toujours et `start_rps` refusait TOUTES les
            # manches suivantes jusqu'au prochain live.
            self.close_rps()
            return
        token = " ".join((text or "").lower().split())
        move = None
        if token.isdigit() and 1 <= int(token) <= 3:
            move = self._RPS_MOVES[int(token) - 1]
        else:
            # Le mot doit être SEUL : « pierre » compte, « la pierre du temple » non.
            for name in self._RPS_MOVES:
                if token == name:
                    move = name
                    break
        if move is None:
            return
        voter = author.lower()
        if rps["votes"].get(voter) == move:
            return
        rps["votes"][voter] = move
        tally = [sum(1 for m in rps["votes"].values() if m == n) for n in self._RPS_MOVES]
        self._feed.widget("rps", phase="voting", tally=tally,
                          seconds=max(1, int(rps["ends_at"] - time.monotonic())),
                          duration=8)

    def close_rps(self, wally_move: str = "") -> Optional[dict]:
        """Tranche la manche : le coup majoritaire du chat contre celui de Wally."""
        rps = self._rps
        if not rps:
            return None
        self._rps = None
        tally = [sum(1 for m in rps["votes"].values() if m == n) for n in self._RPS_MOVES]
        if not any(tally):
            self._feed.widget("rps", phase="void", tally=tally, duration=6)
            logger.info("Overlay: chifoumi clos sans vote")
            return {"widget": "rps", "outcome": "void"}
        chat = self._RPS_MOVES[tally.index(max(tally))]
        # Wally peut imposer son coup — c'est ce qui lui permet de tricher.
        mine = wally_move if wally_move in self._RPS_MOVES else random.choice(self._RPS_MOVES)
        if mine == chat:
            outcome = "draw"
        elif self._RPS_BEATS[mine] == chat:
            outcome = "wally"
        else:
            outcome = "chat"
        self._feed.widget("rps", phase="result", tally=tally, chat=chat,
                          mine=mine, outcome=outcome, duration=10)
        logger.info("Overlay: chifoumi — chat {c} / Wally {m} → {o}",
                    c=chat, m=mine, o=outcome)
        return {"widget": "rps", "chat": chat, "mine": mine, "outcome": outcome}

    # ── sondage (widget 6) ────────────────────────────────────────────────

    def start_poll(
        self, question: str, options: list[str], seconds: int = _POLL_DEFAULT_S
    ) -> bool:
        """Ouvre un sondage : les viewers votent en tapant le numéro dans le chat."""
        question = (question or "").strip()
        options = [str(o).strip()[:24] for o in (options or []) if str(o).strip()][:4]
        if not question or len(options) < 2 or not self._live():
            return False
        # Clore celui d'avant avant de l'écraser : sinon ses votes partaient à la
        # poubelle sans gagnant, et `_last_poll` gardait le résultat de l'avant-
        # dernier — que `poll_result_line()` réinjecte dans le prompt. « Alors, ça
        # a donné quoi ? » répondait à côté.
        if self._poll is not None:
            self.close_poll()
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

    # Ce qu'on entend à l'oral pour un vote. Le chat tape « 1 » ; en vocal on dit
    # « un », « le premier », ou simplement « oui » / « non » sur deux options.
    _SPOKEN_NUMBERS = {
        "un": 1, "une": 1, "premier": 1, "premiere": 1, "oui": 1,
        "deux": 2, "second": 2, "seconde": 2, "deuxieme": 2, "non": 2,
        "trois": 3, "troisieme": 3,
        "quatre": 4, "quatrieme": 4,
    }

    def count_spoken_vote(self, author: str, text: str) -> bool:
        """Compte un vote entendu en VOCAL pendant un sondage.

        Plus permissif que le chat : une phrase parlée n'est jamais réduite à un
        chiffre (« bah moi je dis deux »), et la transcription accentue mal. On
        cherche donc un mot de vote dans la phrase, à condition qu'elle soit
        courte — au-delà, « deux » parle sûrement d'autre chose.
        """
        poll = self._poll
        if not poll or time.monotonic() > poll["ends_at"]:
            return False
        words = self._fold(text).split()
        if not words or len(words) > 8:
            return False
        index = None
        for word in words:
            if word.isdigit() and 1 <= int(word) <= len(poll["options"]):
                index = int(word) - 1
                break
            spoken = self._SPOKEN_NUMBERS.get(word)
            if spoken is not None and spoken <= len(poll["options"]):
                index = spoken - 1
                break
        if index is None:
            # Dernier recours : le libellé de l'option, prononcé tel quel.
            for i, option in enumerate(poll["options"]):
                folded = self._fold(option)
                if folded and folded in self._fold(text):
                    index = i
                    break
        if index is None:
            return False
        voter = author.lower()
        if poll["votes"].get(voter) == index:
            return False
        poll["votes"][voter] = index
        self._publish_poll(max(1, int(poll["ends_at"] - time.monotonic())))
        logger.info("Sondage : vote vocal de {a} → {n}", a=author, n=index + 1)
        return True

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
        # En INFO : une pensée qui n'arrive jamais à l'écran est invisible dans
        # les logs, et on ne sait pas si c'est le budget, le « RIEN » ou la
        # longueur qui l'a retenue.
        if not short or short.upper().rstrip(".") == "RIEN":
            logger.info("Overlay: pensée jugée sans intérêt pour le public (RIEN)")
            return None
        if len(short) > _MAX_BUBBLE_CHARS:
            logger.info("Overlay: condensation trop longue ({n} car) : {t}",
                        n=len(short), t=short[:80])
            return None
        return short
