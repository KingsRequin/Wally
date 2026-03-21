# bot/dashboard/routes/sse.py
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from loguru import logger

public_router = APIRouter()
admin_router = APIRouter()

# Fan-out broadcast pour les logs SSE.
# Chaque connexion SSE ajoute une Queue à cette liste.
# Le sink loguru itère sur list(_log_queues) pour thread-safety (copie avant itération).
_log_queues: list[asyncio.Queue] = []
_sink_id: int | None = None


def broadcast_event(data: dict) -> None:
    """Envoie un événement structuré à tous les clients SSE connectés.

    Distingué des log entries par la présence du champ 'type'.
    """
    for q in list(_log_queues):
        try:
            q.put_nowait(data)
        except Exception:
            pass


def _log_sink(message) -> None:
    """Sink loguru — appelé de manière synchrone depuis le thread de logging.

    Itère sur une copie de _log_queues pour éviter RuntimeError si la liste est
    modifiée (append/remove) depuis le thread asyncio en parallèle.
    """
    record = message.record
    entry = {
        "level": record["level"].name,
        "message": record["message"],
        "time": record["time"].strftime("%H:%M:%S"),
    }
    for q in list(_log_queues):
        try:
            q.put_nowait(entry)
        except Exception:
            pass  # Queue pleine — log ignoré silencieusement


def setup_log_sink() -> None:
    """Enregistre le sink loguru une seule fois (idempotent)."""
    global _sink_id
    if _sink_id is None:
        _sink_id = logger.add(_log_sink)


@public_router.get("/sse/emotions")
async def sse_emotions(request: Request):
    """SSE flux d'émotions — push toutes les 5s depuis EmotionEngine en mémoire.

    Source de vérité : emotion.get_state() — état live avec décroissance en cours.
    PAS de lecture DB.
    """
    state = request.app.state.wally

    async def generate():
        try:
            tick = 0
            while True:
                data = json.dumps(state.emotion.get_state())
                yield f"data: {data}\n\n"
                await asyncio.sleep(5)
                tick += 1
                if tick % 3 == 0:  # keepalive toutes les 15s
                    yield ": keepalive\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _find_latest_log() -> Path | None:
    """Retourne le fichier app.log le plus récemment modifié sous logs/*/."""
    logs_root = Path("logs")
    if not logs_root.exists():
        return None
    candidates = sorted(
        logs_root.glob("*/app.log"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _parse_log_line(line: str) -> dict | None:
    """Parse une ligne loguru au format HH:MM:SS | LEVEL | source | message."""
    parts = line.split(" | ", 3)
    if len(parts) < 2:
        return None
    level = parts[1].strip()
    if level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        return None
    message = parts[3].strip() if len(parts) >= 4 else (parts[2].strip() if len(parts) == 3 else "")
    return {"time": parts[0].strip(), "level": level, "message": message}


@admin_router.get("/logs/history")
async def log_history(request: Request, lines: int = 200):
    """Retourne les dernières lignes du fichier log courant.

    Lit dynamiquement le app.log le plus récent (résout le bug des logs
    affichés depuis >2h : le fichier cherché est toujours le plus récent,
    quelle que soit la date de démarrage du bot).
    """
    log_path = _find_latest_log()
    if log_path is None:
        return {"entries": [], "file": None}
    try:
        text = await asyncio.to_thread(log_path.read_text, encoding="utf-8", errors="replace")
        all_lines = text.splitlines()
        recent = all_lines[-lines:] if len(all_lines) > lines else all_lines
        entries = [e for line in recent if (e := _parse_log_line(line)) is not None]
        return {"entries": entries, "file": str(log_path)}
    except Exception as exc:
        logger.warning("Failed to read log history: {e}", e=exc)
        return {"entries": [], "file": str(log_path)}


@admin_router.get("/sse/logs")
async def sse_logs(request: Request):
    """SSE flux de logs loguru en temps réel (admin uniquement).

    Architecture fan-out : chaque connexion crée une Queue(maxsize=100).
    Keepalive toutes les 15s pour éviter les timeouts proxy.
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _log_queues.append(queue)

    async def generate():
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(msg)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            try:
                _log_queues.remove(queue)
            except ValueError:
                pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
