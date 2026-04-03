from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

public_router = APIRouter()


@public_router.get("/journal")
async def list_journal(request: Request, limit: int = 30) -> dict:
    """Liste les N dernières entrées du journal archivé."""
    state = request.app.state.wally
    entries = await state.db.get_journal_entries(limit=limit)
    # Expose chart availability as a boolean flag (path is internal)
    for entry in entries:
        cp = entry.pop("chart_path", None)
        entry["has_chart"] = bool(cp and Path(cp).exists())
    return {"entries": entries}


@public_router.get("/journal/{date}/chart")
async def get_journal_chart(date: str, request: Request):
    """Retourne le PNG du graphe d'émotions pour une entrée de journal."""
    # Validate date format to prevent path traversal
    import re
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise HTTPException(status_code=400, detail="Format de date invalide")

    chart_file = Path("data/journal_charts") / f"{date}.png"
    if not chart_file.exists():
        raise HTTPException(status_code=404, detail="Graphe non disponible")
    return FileResponse(str(chart_file), media_type="image/png")
