from fastapi import APIRouter, Request

public_router = APIRouter()


@public_router.get("/journal")
async def list_journal(request: Request, limit: int = 30) -> dict:
    """Liste les N dernières entrées du journal archivé."""
    state = request.app.state.wally
    entries = await state.db.get_journal_entries(limit=limit)
    return {"entries": entries}
