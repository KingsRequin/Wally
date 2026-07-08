"""Veilleur read-only : un digest périphérique de l'activité récente du serveur.

3e brique du projet sous-agents. Volontairement modeste : il ne double PAS la
perception passive (message par message) ni la consolidation nocturne. Il comble
un trou précis — pendant que Wally vagabonde mentalement, il n'a aucune vue
synthétique de « ce qui bruisse sur le serveur cette dernière heure ».

Un appel LLM au plus par heure (throttle interne), lecture seule, jamais d'action.
Le digest est offert à la cognition comme UNE amorce de vagabondage parmi d'autres
(émergent, pas de proba forcée) via l'AttentionAgent.
"""
from __future__ import annotations

import time
from pathlib import Path

from loguru import logger

_REFRESH_INTERVAL_S = 3600  # 1 h
_WINDOW_S = 3600            # activité de la dernière heure
_MIN_MESSAGES = 4          # en dessous, on considère le serveur calme
_MAX_MESSAGES = 80          # borne le prompt
_MAX_CONTENT = 200          # tronque chaque message


class ServerWatcher:
    def __init__(self, db, llm, prompts_dir: str | Path,
                 channel_names: dict[str, str] | None = None) -> None:
        self._db = db
        self._llm = llm
        self._names = channel_names or {}
        self._system = (Path(prompts_dir) / "server_watch.md").read_text(
            encoding="utf-8"
        )
        self._digest: str = ""
        self._last_refresh_ts: float = 0.0

    def current(self) -> str:
        """Dernier digest connu (chaîne vide si serveur calme / jamais rafraîchi)."""
        return self._digest

    async def maybe_refresh(self) -> None:
        """Rafraîchit au plus une fois par heure. Ne lève jamais."""
        now = time.time()
        if self._last_refresh_ts and (now - self._last_refresh_ts) < _REFRESH_INTERVAL_S:
            return
        self._last_refresh_ts = now  # armé avant l'appel : un échec ne martèle pas
        try:
            await self._refresh(now)
        except Exception as e:  # noqa: BLE001 — jamais bloquant pour la cognition
            logger.warning("ServerWatcher: refresh échoué: {}", e)

    async def _refresh(self, now: float) -> None:
        messages = await self._db.get_messages_since(now - _WINDOW_S)
        if len(messages) < _MIN_MESSAGES:
            self._digest = ""
            return
        transcript = self._render(messages[-_MAX_MESSAGES:])
        reply = await self._llm.complete(
            self._system, [{"role": "user", "content": transcript}]
        )
        self._digest = (reply or "").strip()

    def _render(self, messages: list[dict]) -> str:
        lines = []
        for m in messages:
            chan = self._names.get(str(m.get("channel_id")), m.get("channel_id"))
            content = (m.get("content") or "")[:_MAX_CONTENT]
            lines.append(f"[#{chan}] {m.get('author')}: {content}")
        return "\n".join(lines)
