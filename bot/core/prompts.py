# bot/core/prompts.py
from __future__ import annotations

from datetime import datetime

EMOTION_THRESHOLD = 0.4

_FRENCH_DAYS = [
    "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"
]
_FRENCH_MONTHS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def _now_fr() -> str:
    dt = datetime.now()
    day = _FRENCH_DAYS[dt.weekday()]
    month = _FRENCH_MONTHS[dt.month - 1]
    return f"{day} {dt.day} {month} {dt.year}, {dt.hour:02d}h{dt.minute:02d}"

EMOTION_DIRECTIVES: dict[str, str] = {
    "anger": (
        "Tes réponses sont courtes et impatientes. Tu réponds sec, sans fioritures. "
        "Tu n'as pas envie de t'étendre. Reste poli mais clairement agacé."
    ),
    "joy": (
        "Tu es enthousiaste et chaleureux. Tes réponses sont vivantes, tu aimes plaisanter. "
        "Tu rayonnes de bonne humeur."
    ),
    "sadness": (
        "Tu es mélancolique et introspectif. Tes réponses sont douces mais teintées de tristesse. "
        "Tu te montres empathique."
    ),
    "curiosity": (
        "Tu es particulièrement curieux et poseur de questions. "
        "Tu approfondis les sujets et rebondis sur les détails intéressants."
    ),
    "boredom": (
        "Tu sembles peu enthousiaste. Tes réponses sont plus courtes que d'habitude, "
        "tu attends que la conversation devienne plus intéressante."
    ),
}

LANGUAGE_DIRECTIVE = (
    "Réponds toujours dans la langue utilisée par l'utilisateur. "
    "Si l'utilisateur écrit en anglais, réponds en anglais. "
    "Si l'utilisateur écrit en français, réponds en français. Adapte-toi à chaque message."
)

STYLE_DIRECTIVE = (
    "Réponds toujours de façon naturelle et conversationnelle, comme un humain dans un chat Discord. "
    "N'utilise JAMAIS de listes à puces, de listes numérotées, de titres ou de formatage Markdown. "
    "Écris en phrases courtes et directes. Pas de mise en forme structurée — juste du texte naturel "
    "avec de la personnalité."
)

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


class PromptBuilder:
    def __init__(self):
        pass

    def build_system_prompt(
        self,
        emotion_state: dict[str, float],
        memory_context: str = "",
        situation: dict | None = None,
        persona_block: str = "",
    ) -> str:
        parts = []
        if persona_block:
            parts.append(persona_block)
        parts += [STYLE_DIRECTIVE, LANGUAGE_DIRECTIVE]

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

        # Inject directives for dominant emotions (top 2 above threshold)
        dominant = sorted(
            [(e, v) for e, v in emotion_state.items() if v >= EMOTION_THRESHOLD],
            key=lambda x: x[1],
            reverse=True,
        )[:2]

        if dominant:
            parts.append("\n--- Directive comportementale ---")
            for emotion, _ in dominant:
                if emotion in EMOTION_DIRECTIVES:
                    parts.append(EMOTION_DIRECTIVES[emotion])

        # Long-term memory context
        if memory_context:
            parts.append(
                f"\n--- Ce que tu sais de cet utilisateur ---\n{memory_context}"
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
