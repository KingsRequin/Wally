from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from bot.v2.core.evolution_log import EvolutionEntry, EvolutionLog

SECTION_GUARDRAILS: dict[str, dict] = {
    "SOUL":       {"max_change_percent": 0.20, "max_evolutions_per_day": 1},
    "EMOTIONS":   {"max_change_percent": 0.15, "max_evolutions_per_day": 1},
    "WEEKDAYS":   {"max_change_percent": 1.0,  "max_evolutions_per_day": 1},
    "COMPOSITES": {"max_change_percent": 1.0,  "max_evolutions_per_day": 1},
}

SECTION_FILES: dict[str, str] = {
    "SOUL":       "SOUL.md",
    "EMOTIONS":   "EMOTIONS.md",
    "WEEKDAYS":   "WEEKDAYS.md",
    "COMPOSITES": "COMPOSITES.md",
}


class PersonaManagerError(Exception):
    pass


class PersonaManager:
    def __init__(
        self,
        persona_dir: str | Path,
        evolution_log: EvolutionLog,
        llm,
        persona_service=None,
    ) -> None:
        self._dir = Path(persona_dir)
        self._log = evolution_log
        self._llm = llm
        self._persona = persona_service

    async def evolve(self, section: str, change_description: str) -> str:
        """Modify a persona section via LLM with daily guardrails. Returns new content."""
        guardrails = SECTION_GUARDRAILS.get(section)
        if guardrails is None:
            raise PersonaManagerError(f"Unknown section: {section}")

        # Guard: accumulated change percent from prior evolutions (durable, log-based)
        pct = self._log.change_percent_today(section)
        if pct >= guardrails["max_change_percent"]:
            raise PersonaManagerError(
                f"Section {section} already changed {pct:.0%} today "
                f"(max {guardrails['max_change_percent']:.0%})"
            )

        # Guard: evolutions per day — log-based so restart-resilient
        count = self._log.count_today(section)
        if count >= guardrails["max_evolutions_per_day"]:
            raise PersonaManagerError(
                f"Section {section} already evolved {count}x today "
                f"(max {guardrails['max_evolutions_per_day']})"
            )

        filepath = self._dir / SECTION_FILES[section]
        current = filepath.read_text(encoding="utf-8")
        before_len = len(current)

        system = (
            f"Tu es Wally. Tu modifies ta propre section persona '{section}' de façon chirurgicale.\n"
            f"Consigne : {change_description}\n\n"
            "Règles :\n"
            "- Garde l'essence et le style existants\n"
            "- Change minimum 1 ligne, maximum selon les garde-fous du jour\n"
            "- Retourne UNIQUEMENT le nouveau contenu complet du fichier\n"
            "- Pas de commentaires, pas de markdown supplémentaire en dehors du contenu"
        )
        new_content = await self._llm.complete(
            system,
            [{"role": "user", "content": current}],
        )
        after_len = len(new_content)

        change_ratio = abs(after_len - before_len) / max(before_len, 1)
        if pct + change_ratio > guardrails["max_change_percent"]:
            raise PersonaManagerError(
                f"Proposed change ({change_ratio:.0%}) exceeds daily budget for {section}"
            )

        filepath.write_text(new_content, encoding="utf-8")

        self._log.append(EvolutionEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            section=section,
            before_len=before_len,
            after_len=after_len,
            reason=change_description,
        ))
        logger.info(
            "Persona {} evolved: {}→{} chars ({})",
            section, before_len, after_len, change_description[:60],
        )

        if self._persona is not None:
            self._persona.reload()

        return new_content
