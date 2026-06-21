from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from bot.v2.core.meta_agent import MetaDecision, parse_decisions


@dataclass
class ReasoningResult:
    thought_text: str                    # la pensée privée (reasoning_content)
    thought_fact_id: int | None
    decisions: list[MetaDecision] = field(default_factory=list)


class ReasoningAgent:
    """Reasoning unifié : un seul appel LLM qui *pense* (raisonnement privé) ET
    *décide* (tags d'action publics).

    Fusion d'InnerMonologue (qui pensait) et de MetaAgent (qui décidait) en un
    appel `complete_with_reasoning` :
    - `reasoning` (reasoning_content / `<think>`) = la pensée privée → stockée en
      THOUGHT, jamais montrée à l'utilisateur.
    - `content` = la sortie publique = uniquement des tags d'action → parsés via
      `parse_decisions`.
    """

    def __init__(self, llm, fact_store, prompts_dir: str | Path) -> None:
        self._llm = llm
        self._facts = fact_store
        self._system = (Path(prompts_dir) / "reasoning_system.md").read_text(encoding="utf-8")

    async def reason(self, context) -> ReasoningResult:
        user_msg = self._format_context(context)
        content, reasoning = await self._llm.complete_with_reasoning(
            self._system, [{"role": "user", "content": user_msg}]
        )

        # La pensée privée = le raisonnement ; à défaut (serveur sans
        # reasoning_content), on retombe sur le content pour ne pas perdre la trace.
        thought_text = reasoning or content
        thought_fact_id: int | None = None
        if thought_text:
            from bot.v2.core.memory.facts import AtomicFact, FactCategory
            now = datetime.now(timezone.utc)
            thought = AtomicFact(
                user_id="wally:self",
                content=thought_text,
                category=FactCategory.THOUGHT,
                confidence=1.0,
                created_at=now,
                last_seen_at=now,
            )
            thought_fact_id = await self._facts.add(thought)
            logger.debug("Reasoning : pensée stockée #{}", thought_fact_id)

        # Le content (tags) porte les décisions. parse_decisions retombe sur
        # [THINK] si content est vide.
        decisions = parse_decisions(content)
        if "SPEAK" in content and not any(d.action == "SPEAK" for d in decisions):
            logger.warning("ReasoningAgent: intention SPEAK non parsée — content brut : {}", content[:300])
        logger.debug("ReasoningAgent: {} décision(s) — {}", len(decisions), [d.action for d in decisions])

        return ReasoningResult(
            thought_text=thought_text,
            thought_fact_id=thought_fact_id,
            decisions=decisions,
        )

    def _format_context(self, ctx) -> str:
        lines: list[str] = [
            f"**Heure :** {ctx.time_of_day}",
            f"**État émotionnel :** {ctx.emotion_state}",
        ]
        if ctx.active_desires:
            lines.append("**Désirs actifs :** " + " ; ".join(d.content for d in ctx.active_desires[:3]))
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
