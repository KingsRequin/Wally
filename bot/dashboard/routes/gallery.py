import asyncio
import json
import random
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from loguru import logger

from bot.dashboard.routes.chat_auth import decode_jwt, _jwt_secret_raw

public_router = APIRouter()
admin_router = APIRouter()

DATA_GALLERY_DIR = Path("data/gallery")
LOADING_GIFS_DIR = Path("bot/dashboard/static/loading_gifs")

MEDIA_TYPES = {"png": "image/png", "jpeg": "image/jpeg", "jpg": "image/jpeg", "webp": "image/webp"}


def _extract_user_id_from_jwt(request: Request) -> tuple[str, dict] | tuple[None, None]:
    """Returns (user_id, payload) or (None, None). user_id is 'discord:{discord_id}'."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None, None
    token = auth[7:]
    payload = decode_jwt(token, _jwt_secret_raw())
    if not payload:
        return None, None
    return f"discord:{payload['discord_id']}", payload


# --- Public routes ---

@public_router.get("/gallery")
async def list_gallery(
    request: Request,
    search: str | None = None,
    sort_by: str = "date",
    user_filter: str | None = None,
    limit: int = 20,
    offset: int = 0,
):
    state = request.app.state.wally
    images = await state.db.get_gallery_images(search, sort_by, user_filter, limit, offset)
    return {"images": images, "count": len(images)}


@public_router.get("/gallery/estimate-cost")
async def estimate_cost(request: Request, model: str | None = None, quality: str | None = None, size: str | None = None):
    state = request.app.state.wally
    cfg = state.config.image_generation
    m = model or cfg.model
    q = quality or cfg.quality
    s = size or cfg.size
    from bot.core.llm.openai_client import OpenAILLMClient
    cost = OpenAILLMClient.estimate_image_cost(m, q, s)
    return {"cost_usd": cost, "model": m, "quality": q, "size": s}


@public_router.get("/gallery/random")
async def random_image(request: Request, filter: str = "all"):
    state = request.app.state.wally
    image = await state.db.get_random_gallery_image(filter)
    if not image:
        raise HTTPException(status_code=404, detail="No images in gallery")
    return image


@public_router.get("/gallery/{image_id}")
async def get_image_detail(request: Request, image_id: str):
    state = request.app.state.wally
    image = await state.db.get_gallery_image(image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    user_id, _ = _extract_user_id_from_jwt(request)
    user_voted = False
    if user_id:
        user_voted = await state.db.has_voted(image_id, user_id)
    image["user_voted"] = user_voted
    return image


@public_router.get("/gallery/{image_id}/image")
async def serve_image(request: Request, image_id: str):
    state = request.app.state.wally
    image = await state.db.get_gallery_image(image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    file_path = DATA_GALLERY_DIR / Path(image["file_path"]).name
    if not file_path.resolve().is_relative_to(DATA_GALLERY_DIR.resolve()):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    ext = file_path.suffix.lstrip(".")
    media_type = MEDIA_TYPES.get(ext, "application/octet-stream")
    return FileResponse(file_path, media_type=media_type, headers={"Cache-Control": "public, max-age=86400"})


@public_router.post("/gallery/{image_id}/vote")
async def toggle_vote(request: Request, image_id: str):
    user_id, _ = _extract_user_id_from_jwt(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    state = request.app.state.wally
    image = await state.db.get_gallery_image(image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    voted = await state.db.toggle_gallery_vote(image_id, user_id)
    return {"voted": voted}


@public_router.patch("/gallery/{image_id}/title")
async def update_title(request: Request, image_id: str):
    user_id, _ = _extract_user_id_from_jwt(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    state = request.app.state.wally
    image = await state.db.get_gallery_image(image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    if image["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Only the creator can edit the title")
    body = await request.json()
    title = body.get("title", "").strip()
    if not title or len(title) > 100:
        raise HTTPException(status_code=400, detail="Title must be 1-100 characters")
    await state.db.update_gallery_title(image_id, title)
    return {"title": title}


@public_router.get("/loading-gif")
async def random_loading_gif():
    if not LOADING_GIFS_DIR.exists():
        return StreamingResponse(iter([]), status_code=204)
    gifs = [f for f in LOADING_GIFS_DIR.iterdir() if f.suffix.lower() == ".gif"]
    if not gifs:
        return StreamingResponse(iter([]), status_code=204)
    chosen = random.choice(gifs)
    return FileResponse(chosen, media_type="image/gif")


@public_router.get("/sse/overlay-image")
async def sse_overlay_image(request: Request):
    state = request.app.state.wally
    queue = state.overlay_image_queue

    async def event_stream():
        while True:
            try:
                data = await asyncio.wait_for(queue.get(), timeout=30)
                yield f"event: show_image\ndata: {json.dumps(data)}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --- Admin routes ---

@admin_router.delete("/gallery/{image_id}")
async def delete_image(request: Request, image_id: str):
    state = request.app.state.wally
    image = await state.db.get_gallery_image(image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    file_path = DATA_GALLERY_DIR / Path(image["file_path"]).name
    if file_path.exists():
        file_path.unlink()
    else:
        logger.warning("Gallery file already missing: {p}", p=file_path)
    await state.db.delete_gallery_image(image_id)
    return {"status": "deleted"}
