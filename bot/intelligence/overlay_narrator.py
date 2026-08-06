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

import time
from collections.abc import Callable
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
    ) -> None:
        self._feed = overlay_feed
        self._llm = llm
        self._is_live = is_live
        self._min_interval = min_interval_s
        self._event_interval = event_interval_s
        self._last_bubble_at: float = 0.0
        self._last_event_at: float = 0.0

    # ── budget ────────────────────────────────────────────────────────────

    def _live(self) -> bool:
        try:
            return bool(self._is_live())
        except Exception:  # noqa: BLE001 — une sonde cassée ne doit pas parler
            return False

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
