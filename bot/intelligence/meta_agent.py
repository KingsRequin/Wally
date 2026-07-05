from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from bot.intelligence.identity import render_identity

_THINK_RE = re.compile(r"\[THINK\]")
# Deux passes pour SPEAK :
#  1. Message ENTRE GUILLEMETS (forme canonique du prompt) : le terminateur est le
#     guillemet fermant + `]`, ce qui tolère un `]` À L'INTÉRIEUR du message. Sans
#     ça, une citation `[¹](<url>)` coupait le message au `]` du marqueur (« …facile [¹ »).
#  2. Repli non-guillemeté : `(.+?)` non gourmand jusqu'au `]` — pour les messages nus.
_SPEAK_QUOTED_RE = re.compile(r'\[SPEAK\s+(\d+)\s+["“«\'](.+?)["”»\']\s*\]', re.DOTALL)
_SPEAK_RE = re.compile(r'\[SPEAK\s+(\d+)\s+(.+?)\s*\]', re.DOTALL)
_ACT_RE = re.compile(r"\[ACT\s+(\w+)\s+(\{.*?\})\]", re.DOTALL)

_QUOTE_PAIRS = (('"', '"'), ('“', '”'), ('«', '»'), ("'", "'"))


def _strip_quotes(s: str) -> str:
    s = s.strip()
    for open_q, close_q in _QUOTE_PAIRS:
        if len(s) >= 2 and s.startswith(open_q) and s.endswith(close_q):
            return s[1:-1].strip()
    return s
_EVOLVE_RE = re.compile(r'\[EVOLVE\s+(\w+)\s+"([^"]+)"\]', re.DOTALL)
_SLEEP_RE = re.compile(r"\[SLEEP\s+(\d+)\]")


@dataclass
class MetaDecision:
    action: str  # "THINK" | "SPEAK" | "ACT" | "EVOLVE" | "SLEEP"
    channel_id: str | None = None
    message: str | None = None
    act_name: str | None = None
    act_args: dict = field(default_factory=dict)
    section: str | None = None
    change: str | None = None
    sleep_seconds: int | None = None


def parse_decisions(text: str) -> list[MetaDecision]:
    decisions: list[MetaDecision] = []

    for _ in _THINK_RE.finditer(text):
        decisions.append(MetaDecision(action="THINK"))

    # Passe 1 (prioritaire) : messages entre guillemets, `]` interne toléré.
    speak_spans: list[tuple[int, int]] = []
    for m in _SPEAK_QUOTED_RE.finditer(text):
        decisions.append(MetaDecision(
            action="SPEAK", channel_id=m.group(1), message=m.group(2).strip()
        ))
        speak_spans.append(m.span())
    # Passe 2 (repli) : messages nus, sauf ceux déjà captés en passe 1 (même position).
    for m in _SPEAK_RE.finditer(text):
        if any(s0 <= m.start() < s1 for s0, s1 in speak_spans):
            continue
        decisions.append(MetaDecision(
            action="SPEAK", channel_id=m.group(1), message=_strip_quotes(m.group(2))
        ))

    for m in _ACT_RE.finditer(text):
        try:
            args = json.loads(m.group(2))
        except json.JSONDecodeError:
            args = {}
        decisions.append(MetaDecision(action="ACT", act_name=m.group(1), act_args=args))

    for m in _EVOLVE_RE.finditer(text):
        decisions.append(MetaDecision(action="EVOLVE", section=m.group(1), change=m.group(2)))

    for m in _SLEEP_RE.finditer(text):
        decisions.append(MetaDecision(action="SLEEP", sleep_seconds=int(m.group(1))))

    if not decisions:
        decisions.append(MetaDecision(action="THINK"))

    return decisions


class MetaAgent:
    def __init__(self, llm, prompts_dir: str | Path) -> None:
        self._llm = llm
        self._system = render_identity((Path(prompts_dir) / "meta_agent_system.md").read_text(encoding="utf-8"))

    async def decide(self, monologue_text: str) -> list[MetaDecision]:
        response = await self._llm.complete(
            self._system,
            [{"role": "user", "content": monologue_text}],
        )
        decisions = parse_decisions(response)
        # Observabilité #3 : le modèle a voulu parler mais le tag n'a pas été
        # reconnu → on le rend visible au lieu de le perdre silencieusement.
        if "SPEAK" in response and not any(d.action == "SPEAK" for d in decisions):
            logger.warning("MetaAgent: intention SPEAK non parsée — réponse brute : {}", response[:300])
        logger.debug("MetaAgent: {} décision(s) — {}", len(decisions), [d.action for d in decisions])
        return decisions
