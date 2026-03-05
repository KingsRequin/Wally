# bot/core/prompts.py
from __future__ import annotations

EMOTION_THRESHOLD = 0.4

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

LANGUAGE_LABELS: dict[str, str] = {
    "fr": "français",
    "en": "English",
    "es": "español",
    "de": "Deutsch",
    "it": "italiano",
    "pt": "português",
    "nl": "Nederlands",
    "ru": "русский",
    "ja": "日本語",
    "zh": "中文",
}

CONTEXT_HEADER = (
    "\n--- Contexte de la conversation (messages récents, plusieurs auteurs) ---\n"
    "{context}\n"
    "--- Fin du contexte ---"
)


class PromptBuilder:
    def __init__(self, system_prompt: str):
        self._base = system_prompt.strip()

    def build_system_prompt(
        self,
        emotion_state: dict[str, float],
        language: str,
        memory_context: str = "",
    ) -> str:
        parts = [self._base]

        # Language directive
        lang_label = LANGUAGE_LABELS.get(language, language)
        parts.append(f"\nRéponds toujours en {lang_label} dans cette conversation.")

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

    @staticmethod
    def format_event_message(template: str, **kwargs) -> str:
        return template.format(**{k: v for k, v in kwargs.items()})
