# bot/core/conversation_log.py
"""
Journal structuré du cycle de vie des conversations (JSONL, un fichier par
plateforme/canal/jour).

Objectif : pouvoir diagnostiquer les bugs comportementaux de Wally (réponse en
double, intention annoncée sans action, réponse vide, latence anormale…) sans
avoir à les décrire — il suffit de lire les fichiers ou de lancer le script
d'audit.

Format des fichiers :
    logs/conversations/{platform}/{channel}/{YYYY-MM-DD}.jsonl

Chaque ligne est un événement JSON : ``{ts, type, trace_id, ...}``. Les events
partageant un ``trace_id`` (= id du message déclencheur Discord/Twitch, ou un id
généré pour les events spontanés) racontent le traitement complet d'un message,
du message entrant jusqu'à la réponse envoyée et son post-traitement.

Le logger est conçu pour être appelé depuis les points chauds :
``log()`` est **synchrone et non bloquant** (``put_nowait`` + drop silencieux si
la file sature) — aucun ``await`` requis côté appelant. Une tâche de fond draine
la file et écrit par lots via ``asyncio.to_thread`` : aucune I/O disque n'a lieu
dans l'event loop.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from loguru import logger

_PARIS = ZoneInfo("Europe/Paris")
_UNSAFE = re.compile(r"[^\w.\-]+")
_MAX_FIELD = 8000  # troncature de sécurité par champ texte (évite les fichiers obèses)

_trace_counter = 0


def new_trace_id(prefix: str = "auto") -> str:
    """Génère un trace_id pour un event sans message déclencheur (ex: SPEAK spontané).

    Combine l'horodatage milliseconde et un compteur monotone pour rester unique
    même si deux events sont générés dans la même milliseconde.
    """
    global _trace_counter
    _trace_counter += 1
    return f"{prefix}:{int(time.time() * 1000)}:{_trace_counter}"


def _safe_segment(value: str, fallback: str = "unknown") -> str:
    """Nettoie un identifiant pour en faire un segment de chemin sûr."""
    if not value:
        return fallback
    seg = _UNSAFE.sub("_", str(value)).strip("_")
    return seg[:80] or fallback


class ConversationLogger:
    """File d'attente asynchrone + writer de fond pour les logs de conversation."""

    def __init__(
        self, root: str | Path = "logs/conversations", queue_maxsize: int = 2000
    ) -> None:
        self._root = Path(root)
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=queue_maxsize)
        self._task: asyncio.Task | None = None
        self._running = False
        self._dropped = 0

    # ── API publique ──────────────────────────────────────────────────────────
    def log(self, platform: str, channel: str, event_type: str, /, **fields) -> None:
        """Enfile un événement. Non bloquant ; drop silencieux si la file sature.

        `platform`/`channel`/`event_type` sont *positional-only* (`/`) : les events
        cognitifs passent légitimement un champ métier `channel=` dans `**fields`
        (ex. `_log_cog("speak_suppressed", channel=ch_key)`) — sans le `/`, ce kwarg
        entrerait en collision avec le paramètre structurel `channel` et lèverait
        `TypeError: got multiple values for argument 'channel'`.
        """
        record: dict = {"ts": time.time(), "type": event_type}
        record.update(fields)
        for key, value in list(record.items()):
            if isinstance(value, str) and len(value) > _MAX_FIELD:
                record[key] = value[:_MAX_FIELD] + f"…[+{len(value) - _MAX_FIELD} car.]"
        item = (_safe_segment(platform), _safe_segment(channel), record)
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            self._dropped += 1

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("ConversationLogger started → {root}", root=str(self._root))

    async def stop(self) -> None:
        """Arrêt propre : enfile une sentinelle, flush le reste, attend le writer."""
        if not self._running:
            return
        self._running = False
        try:
            self._queue.put_nowait(None)
        except asyncio.QueueFull:
            await self._queue.put(None)
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("ConversationLogger stop timed out, cancelling writer")
                self._task.cancel()
        if self._dropped:
            logger.warning(
                "ConversationLogger a droppé {n} events (file saturée)", n=self._dropped
            )

    # ── Writer de fond ──────────────────────────────────────────────────────────
    async def _run(self) -> None:
        while True:
            item = await self._queue.get()
            if item is None:  # sentinelle d'arrêt
                self._queue.task_done()
                break
            batch = [item]
            stop = False
            while len(batch) < 200:
                try:
                    nxt = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if nxt is None:
                    self._queue.task_done()
                    stop = True
                    break
                batch.append(nxt)
            try:
                await asyncio.to_thread(self._flush, batch)
            except Exception as exc:  # noqa: BLE001 — le writer ne doit jamais crash
                logger.warning("ConversationLogger flush failed: {e}", e=exc)
            for _ in batch:
                self._queue.task_done()
            if stop:
                break

    def _flush(self, batch: list[tuple]) -> None:
        """Regroupe par fichier et append en JSONL (exécuté hors event loop)."""
        by_file: dict[Path, list[str]] = {}
        for platform, channel, record in batch:
            day = datetime.fromtimestamp(record["ts"], _PARIS).strftime("%Y-%m-%d")
            path = self._root / platform / channel / f"{day}.jsonl"
            by_file.setdefault(path, []).append(json.dumps(record, ensure_ascii=False))
        for path, lines in by_file.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
