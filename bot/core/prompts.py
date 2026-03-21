# bot/core/prompts.py
from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

_PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "persona", "prompts")


def load_prompt(name: str, fallback: str = "") -> str:
    """Charge un prompt système depuis bot/persona/prompts/{name}.md.

    Retourne `fallback` si le fichier est absent ou illisible.
    """
    from loguru import logger  # import local pour éviter les imports circulaires

    path = os.path.normpath(os.path.join(_PROMPTS_DIR, f"{name}.md"))
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                return content
            logger.warning("Prompt file empty: {f}", f=path)
    except FileNotFoundError:
        logger.warning("Prompt file missing: {f}", f=path)
    except Exception as exc:
        logger.warning("Prompt file read error {f}: {e}", f=path, e=exc)
    return fallback

_TZ = ZoneInfo("Europe/Paris")

_FRENCH_DAYS = [
    "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"
]
_FRENCH_MONTHS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def _now_fr() -> str:
    dt = datetime.now(_TZ)
    day = _FRENCH_DAYS[dt.weekday()]
    month = _FRENCH_MONTHS[dt.month - 1]
    return f"{day} {dt.day} {month} {dt.year}, {dt.hour:02d}h{dt.minute:02d}"


CONTEXT_HEADER = (
    "\n--- Contexte de la conversation (messages récents, plusieurs auteurs) ---\n"
    "{context}\n"
    "--- Fin du contexte ---"
)

PRELUDE_HEADER = (
    "\n--- Discussion récente dans le canal (avant ta mention) ---\n"
    "{context}\n"
    "--- Fin de la discussion ---"
)


def _get_tier(value: float) -> str | None:
    """Retourne le palier émotionnel pour une valeur donnée."""
    if value >= 0.7:
        return "high"
    if value >= 0.4:
        return "mid"
    if value >= 0.2:
        return "low"
    return None


class PromptBuilder:
    def __init__(self):
        pass

    def build_system_prompt(
        self,
        emotion_state: dict[str, float],
        memory_context: str = "",
        global_memory_context: str = "",
        situation: dict | None = None,
        persona_block: str = "",
        emotion_directives: dict[str, str] | None = None,
        weekday_directives: dict[str, str] | None = None,
        composite_directives: dict[str, str] | None = None,
    ) -> str:
        parts = []
        if persona_block:
            parts.append(persona_block)

        # Situational context (platform, channel, datetime)
        if situation:
            lines = ["\n--- Contexte situationnel ---"]
            if platform := situation.get("platform"):
                lines.append(f"Plateforme : {platform}")
            if server := situation.get("server"):
                lines.append(f"Serveur : {server}")
            if channel := situation.get("channel"):
                lines.append(f"Salon : {channel}")
            if streamer := situation.get("streamer"):
                lines.append(f"Chaîne Twitch : {streamer}")
            lines.append(f"Date et heure : {_now_fr()}")
            parts.append("\n".join(lines))

        # Inject weekday directive
        if weekday_directives:
            day_name = _FRENCH_DAYS[datetime.now(_TZ).weekday()]
            if day_name in weekday_directives:
                parts.append("\n--- Directive temporelle ---")
                parts.append(weekday_directives[day_name])

        # Inject directives for dominant emotions (top 2 above 0.2, tiered)
        # With composite override when both emotions are >= 0.4 and pair is known
        directives = emotion_directives if emotion_directives is not None else {}
        dominant = sorted(
            [(e, v) for e, v in emotion_state.items() if v >= 0.2],
            key=lambda x: x[1],
            reverse=True,
        )[:2]

        if dominant and directives:
            composite_used = False
            if (
                composite_directives
                and len(dominant) >= 2
                and dominant[0][1] >= 0.4
                and dominant[1][1] >= 0.4
            ):
                composite_key = "_".join(sorted([dominant[0][0], dominant[1][0]]))
                if composite_key in composite_directives:
                    parts.append("\n--- Directive comportementale ---")
                    parts.append(composite_directives[composite_key])
                    composite_used = True

            if not composite_used:
                parts.append("\n--- Directive comportementale ---")
                for emotion, value in dominant:
                    tier = _get_tier(value)
                    key = f"{emotion}_{tier}"
                    if key in directives:
                        parts.append(directives[key])

        # Long-term memory context
        if memory_context:
            parts.append(
                f"\n--- Ce que tu sais de cet utilisateur ---\n{memory_context}"
            )

        # Global community memory
        if global_memory_context:
            parts.append(
                f"\n--- Connaissances générales (communauté) ---\n{global_memory_context}"
            )

        return "\n".join(parts)

    def build_context_block(self, messages: list[dict]) -> str:
        if not messages:
            return ""
        lines = [f"[{m['author']}]: {m['content']}" for m in messages]
        return CONTEXT_HEADER.format(context="\n".join(lines))

    def build_prelude_block(self, messages: list[dict]) -> str:
        if not messages:
            return ""
        lines = [f"[{m['author']}]: {m['content']}" for m in messages]
        return PRELUDE_HEADER.format(context="\n".join(lines))

    @staticmethod
    def format_event_message(template: str, **kwargs) -> str:
        return template.format(**{k: v for k, v in kwargs.items()})
