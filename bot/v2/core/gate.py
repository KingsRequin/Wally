# bot.v2/core/gate.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from bot.core.llm.base import BaseLLMClient
from bot.v2.core.memory.facts import AtomicFact, FactCategory, SQLiteFactStore

_DEFAULT_PROMPTS_DIR = Path(__file__).parent.parent / "persona" / "prompts"


_GATE_SCHEMA = {
    "type": "object",
    "properties": {
        "decision":      {"type": "string", "enum": ["RESPOND", "IGNORE", "REACT", "DEFER"]},
        "emoji":         {"type": ["string", "null"]},
        "defer_seconds": {"type": ["integer", "null"]},
        "reason":        {"type": ["string", "null"]},
    },
    "required": ["decision"],
    "additionalProperties": False,
}

_FALLBACK_SYSTEM = (
    "Tu es le filtre de réponse de Wally. Retourne une décision: RESPOND, IGNORE, REACT ou DEFER."
)


@dataclass
class GateDecision:
    decision:      str             # RESPOND | IGNORE | REACT | DEFER
    emoji:         str | None = None
    defer_seconds: int | None = None
    reason:        str | None = None


class ResponseGate:
    """Décide comment Wally réagit à chaque message entrant.

    Appelé avant toute génération de réponse. Utilise deepseek-v4-flash,
    thinking disabled, pour minimiser la latence (<1s).
    """

    def __init__(
        self,
        llm: BaseLLMClient,
        fact_store: SQLiteFactStore,
        prompts_dir: str | Path = _DEFAULT_PROMPTS_DIR,
    ) -> None:
        self._llm = llm
        self._fact_store = fact_store
        self._system = self._load_system(prompts_dir)

    @staticmethod
    def _load_system(prompts_dir: str | Path) -> str:
        path = Path(prompts_dir) / "gate_system.md"
        try:
            content = path.read_text(encoding="utf-8").strip()
            if content:
                return content
            logger.warning("gate_system.md est vide : {p}", p=path)
        except FileNotFoundError:
            logger.warning("gate_system.md introuvable : {p}", p=path)
        return _FALLBACK_SYSTEM

    async def decide(
        self,
        message_content: str,
        author_user_id: str,
        emotion_state: dict[str, float],
        relationship_facts: list[AtomicFact],
        active_desires: list[AtomicFact],
        is_ignored: bool = False,
    ) -> GateDecision:
        """Retourne la décision de Wally pour ce message."""
        if is_ignored:
            return GateDecision(decision="IGNORE", reason="utilisateur marqué comme ignoré")

        dominant_emotion, dominant_value = max(
            emotion_state.items(), key=lambda x: x[1], default=("boredom", 0.0)
        )
        context_parts = [
            f"Message reçu : {message_content[:500]}",
            f"Émotion dominante : {dominant_emotion} ({dominant_value:.2f})",
        ]
        if relationship_facts:
            rel_summary = " | ".join(f.content for f in relationship_facts[:3])
            context_parts.append(f"Relation connue : {rel_summary}")
        if active_desires:
            desire_summary = " | ".join(f.content for f in active_desires[:2])
            context_parts.append(f"Désirs actifs de Wally : {desire_summary}")

        user_msg = "\n".join(context_parts)

        try:
            result = await self._llm.complete_structured(
                system_prompt=self._system,
                messages=[{"role": "user", "content": user_msg}],
                schema=_GATE_SCHEMA,
                schema_name="gate_decision",
                purpose="gate",
            )
            decision = GateDecision(
                decision=result.get("decision", "RESPOND"),
                emoji=result.get("emoji"),
                defer_seconds=result.get("defer_seconds"),
                reason=result.get("reason"),
            )
            if decision.decision == "IGNORE":
                reason_str = decision.reason or "aucune raison spécifiée"
                await self._fact_store.add(AtomicFact(
                    user_id=author_user_id,
                    content=f"Wally a choisi d'ignorer ce message — {reason_str}",
                    category=FactCategory.EMOTION,
                    confidence=0.9,
                    source="gate",
                ))
            return decision

        except Exception as e:
            logger.warning("ResponseGate.decide() failed, fallback RESPOND: {e}", e=e)
            return GateDecision(decision="RESPOND")
