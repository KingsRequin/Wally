# bot/dashboard/routes/memory.py
# Phase 2 — Gestion mémoire mem0 + trust scores
# Tous les endpoints retournent 501 Not Implemented.
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

_NOT_IMPL = JSONResponse(
    {"detail": "Memory management not implemented (Phase 2)"},
    status_code=501,
)


@router.api_route("/memory/{path:path}", methods=["GET", "POST", "DELETE"])
async def memory_stub(path: str):
    return _NOT_IMPL
