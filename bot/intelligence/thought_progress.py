from __future__ import annotations

from pathlib import Path

from loguru import logger

VERDICTS = frozenset({"PROGRESSE", "RESSASSE", "DIVAGUE"})


class ThoughtProgressJudge:
    """Classe une pensée fraîche face au focus et aux pensées récentes :
    PROGRESSE / RESSASSE / DIVAGUE. Sert l'anti-rumination sémantique."""

    def __init__(self, llm, prompts_dir: str | Path) -> None:
        self._llm = llm
        self._system = (Path(prompts_dir) / "thought_progress_judge.md").read_text(
            encoding="utf-8"
        )

    async def judge(
        self, thought_text: str, focus: str | None, recent_thoughts: list[str]
    ) -> str:
        recents = "\n".join(f"- {t[:300]}" for t in (recent_thoughts or [])[-6:])
        user_msg = (
            f"PRÉOCCUPATION DU MOMENT :\n{focus or '(aucune)'}\n\n"
            f"DERNIÈRES PENSÉES :\n{recents or '(aucune)'}\n\n"
            f"NOUVELLE PENSÉE À JUGER :\n{thought_text}"
        )
        reply = await self._llm.complete(
            self._system, [{"role": "user", "content": user_msg}]
        )
        upper = (reply or "").upper()
        for verdict in ("RESSASSE", "DIVAGUE", "PROGRESSE"):
            if verdict in upper:
                return verdict
        logger.debug("ThoughtProgressJudge : verdict illisible '{}' → PROGRESSE", reply)
        return "PROGRESSE"
