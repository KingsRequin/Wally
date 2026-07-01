from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from bot.intelligence.identity import render_identity


@dataclass
class MonologueResult:
    text: str
    thought_fact_id: int


class InnerMonologue:
    def __init__(self, llm, fact_store, prompts_dir: str | Path) -> None:
        self._llm = llm
        self._facts = fact_store
        self._system = render_identity((Path(prompts_dir) / "inner_monologue_system.md").read_text(encoding="utf-8"))

    async def generate(self, context: "AttentionContext") -> MonologueResult:
        user_msg = self._format_context(context)
        text = await self._llm.complete(self._system, [{"role": "user", "content": user_msg}])

        from bot.intelligence.memory.facts import AtomicFact, FactCategory
        now = datetime.now(timezone.utc)
        thought = AtomicFact(
            user_id="wally:self",
            content=text,
            category=FactCategory.THOUGHT,
            confidence=1.0,
            created_at=now,
            last_seen_at=now,
        )
        fact_id = await self._facts.add(thought)
        logger.debug("Monologue intérieur stocké en pensée #{}", fact_id)
        return MonologueResult(text=text, thought_fact_id=fact_id)

    def _format_context(self, ctx) -> str:
        lines: list[str] = [
            f"**Heure :** {ctx.time_of_day}",
            f"**État émotionnel :** {ctx.emotion_state}",
        ]
        if ctx.active_desires:
            lines.append("**Désirs actifs :** " + " ; ".join(
                (f"#{d.id} {d.content}" if getattr(d, "id", None) is not None else d.content)
                for d in ctx.active_desires[:3]))
        if ctx.active_goals:
            lines.append("**Objectifs :** " + " ; ".join(g.content for g in ctx.active_goals[:3]))
        if ctx.recent_thoughts:
            lines.append(f"**Dernière pensée :** {ctx.recent_thoughts[0].content[:300]}")
        if ctx.recent_interactions:
            lines.append("**Interactions récentes :**")
            for msg in ctx.recent_interactions[-5:]:
                lines.append(
                    f"  [{msg.get('channel', '?')}] {msg.get('author', '?')}: "
                    f"{msg.get('content', '')[:100]}"
                )
        if getattr(ctx, "spontaneous_outreach", None):
            lines.append("**Tes messages spontanés restés sans réponse :**")
            for o in ctx.spontaneous_outreach:
                mins = max(1, o.get("seconds_since", 0) // 60)
                lines.append(
                    f"  canal {o.get('channel', '?')} : {o.get('unanswered', 0)} message(s) "
                    f"envoyé(s), aucune réponse depuis ~{mins} min."
                )
        return "\n".join(lines)
