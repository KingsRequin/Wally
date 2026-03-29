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

_MEMORY_RECALL_DIRECTIVE = load_prompt("memory_recall_directive")

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


def assemble_memory_context(parts: list[tuple[int, str]], max_tokens: int) -> str:
    """Assemble memory context respecting token budget.

    parts: list of (priority, text) tuples. Lower priority number = higher importance.
    max_tokens: estimated token budget (len(text) / 4).
    Returns assembled string, truncated to budget.
    """
    sorted_parts = sorted(parts, key=lambda p: p[0])
    result_parts: list[str] = []
    used_tokens = 0.0
    for _priority, text in sorted_parts:
        if not text or not text.strip():
            continue
        estimated = len(text) / 4
        if used_tokens + estimated > max_tokens:
            remaining = int((max_tokens - used_tokens) * 4)
            if remaining > 50:
                result_parts.append(text[:remaining])
            break
        result_parts.append(text)
        used_tokens += estimated
    return "\n".join(result_parts)


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


def _get_tier_fluid(value: float) -> tuple[str, float] | None:
    """Return tier with blend factor for fluid transitions.

    Returns (tier, 1.0) for pure tiers, ("low_mid", blend) or ("mid_high", blend)
    for transition zones (+/-0.05 around boundaries 0.4 and 0.7).
    Returns None if below 0.2.
    """
    if value < 0.2:
        return None
    # Transition zone around 0.4 (low/mid boundary)
    if 0.35 <= value < 0.45:
        blend = (value - 0.35) / 0.1
        if blend >= 1.0:
            return ("mid", 1.0)
        return ("low_mid", blend)
    # Transition zone around 0.7 (mid/high boundary)
    if 0.65 <= value < 0.75:
        blend = (value - 0.65) / 0.1
        if blend >= 1.0:
            return ("high", 1.0)
        return ("mid_high", blend)
    # Pure tiers
    if value >= 0.75:
        return ("high", 1.0)
    if value >= 0.45:
        return ("mid", 1.0)
    if value >= 0.2:
        return ("low", 1.0)
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
        relationship_context: str = "",
        secondary_directives: dict[str, str] | None = None,
        active_secondaries: list[tuple[str, float]] | None = None,
        mood_state: dict[str, float] | None = None,
        persistent_notes: list[dict] | None = None,
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
            if situation.get("stream_live"):
                cat = situation.get("stream_category") or "inconnue"
                title = situation.get("stream_title") or ""
                viewers = situation.get("stream_viewers", 0)
                lines.append(f"Stream EN DIRECT : {cat}")
                if title:
                    lines.append(f"Titre du stream : {title}")
                lines.append(f"Viewers : {viewers}")
            lines.append(f"Date et heure : {_now_fr()}")
            parts.append("\n".join(lines))

        # Inject weekday directive
        if weekday_directives:
            day_name = _FRENCH_DAYS[datetime.now(_TZ).weekday()]
            if day_name in weekday_directives:
                parts.append("\n--- Directive temporelle ---")
                parts.append(weekday_directives[day_name])

        # Inject directives for dominant emotions (top 2 above 0.2, tiered)
        # Priority: secondary emotions > composite pairs > atomic with fluid transitions
        directives = emotion_directives if emotion_directives is not None else {}
        dominant = sorted(
            [(e, v) for e, v in emotion_state.items() if v >= 0.2],
            key=lambda x: x[1],
            reverse=True,
        )[:2]

        directive_injected = False

        # 1) Secondary emotions (highest priority)
        if active_secondaries and secondary_directives:
            for sec_name, sec_intensity in active_secondaries:
                if sec_intensity >= 0.4:
                    sec_tier = _get_tier(sec_intensity)
                    sec_key = f"{sec_name}_{sec_tier}"
                    if sec_key in secondary_directives:
                        parts.append("\n--- Directive comportementale ---")
                        parts.append(secondary_directives[sec_key])
                        directive_injected = True
                        break

        # 2) Composite directives (pair of dominant emotions)
        if not directive_injected and dominant and directives:
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
                    directive_injected = True

        # 3) Atomic directives with fluid transitions
        if not directive_injected and dominant and directives:
            parts.append("\n--- Directive comportementale ---")
            for emotion, value in dominant:
                fluid = _get_tier_fluid(value)
                if fluid is None:
                    continue
                tier, blend = fluid
                # Transition zone: combine two tier directives
                if "_" in tier and blend < 1.0:
                    low_tier, high_tier = tier.split("_")
                    low_key = f"{emotion}_{low_tier}"
                    high_key = f"{emotion}_{high_tier}"
                    if low_key in directives and high_key in directives:
                        parts.append(directives[low_key])
                        parts.append(f"(tendance : {directives[high_key]})")
                    elif low_key in directives:
                        parts.append(directives[low_key])
                    elif high_key in directives:
                        parts.append(directives[high_key])
                else:
                    # Pure tier (or blend == 1.0 which means fully transitioned)
                    pure_tier = tier.split("_")[-1] if "_" in tier else tier
                    key = f"{emotion}_{pure_tier}"
                    if key in directives:
                        parts.append(directives[key])

        # Long-term memory context
        if memory_context:
            parts.append(
                f"\n--- Ce que tu sais de cet utilisateur ---\n{memory_context}"
            )
            if _MEMORY_RECALL_DIRECTIVE:
                parts.append(_MEMORY_RECALL_DIRECTIVE)

        # Trust/love relationship context (separate from semantic memories)
        if relationship_context:
            parts.append(f"\n--- Relation ---\n{relationship_context}")

        # Global community memory
        if global_memory_context:
            parts.append(
                f"\n--- Connaissances générales (communauté) ---\n{global_memory_context}"
            )

        # Persistent notes (written by the LLM itself for long-term retention)
        if persistent_notes:
            lines = ["\n--- Notes persistantes ---"]
            for note in persistent_notes:
                lines.append(f"**{note['title']}** : {note['content']}")
            parts.append("\n".join(lines))

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
