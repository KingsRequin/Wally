# Image Generation & Gallery — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add image generation via OpenAI Images API, a public gallery with flame votes, web chat slash commands, Discord `/wally imagine`, and an OBS overlay for Twitch `!image`.

**Architecture:** Extends the existing modular monolith — new method on `OpenAIClient`, new DB tables in `database.py`, new route file `gallery.py`, new cog `imagine.py`, overlay HTML page, and frontend additions to `app.js`. All wired via existing DI pattern through `AppState`.

**Tech Stack:** Python 3.11+, FastAPI, aiosqlite, OpenAI Images API, discord.py 2.x, twitchio 2.x, Animate.css (CDN), vanilla JS.

**Spec:** `docs/superpowers/specs/2026-03-21-image-generation-gallery-design.md`

---

### Task 1: Config dataclasses (`ImageGenerationConfig` + `OverlayImageConfig`)

**Files:**
- Modify: `bot/config.py:78-95` (add dataclasses + Config fields + load/save)

- [ ] **Step 1: Add `ImageGenerationConfig` dataclass**

After `WebChatConfig` (line ~83), add:

```python
@dataclass
class ImageGenerationConfig:
    model: str = "gpt-image-1.5"
    quality: str = "medium"
    size: str = "1024x1024"
    background: str = "auto"
    format: str = "png"
    daily_limit: int = -1
    per_user_limit: int = 5
```

- [ ] **Step 2: Add `OverlayImageConfig` dataclass**

```python
@dataclass
class OverlayImageConfig:
    command: str = "!image"
    display_duration: int = 15
    animation_in: str = "fadeIn"
    animation_out: str = "fadeOut"
    animation_duration: float = 1.0
    random_filter: str = "all"
    enabled: bool = True
```

- [ ] **Step 3: Add fields to `Config` dataclass**

Add after `web_chat` field (line ~95):

```python
    image_generation: ImageGenerationConfig = field(default_factory=ImageGenerationConfig)
    overlay_image: OverlayImageConfig = field(default_factory=OverlayImageConfig)
```

- [ ] **Step 4: Update `Config.load()` to parse new sections**

In `Config.load()` (around line 130), add before the return:

```python
image_generation = ImageGenerationConfig(**raw.get("image_generation", {}))
overlay_image = OverlayImageConfig(**raw.get("overlay_image", {}))
```

Pass these to the `Config(...)` constructor call.

- [ ] **Step 5: Update `Config.save()` to serialize new sections**

In `Config.save()` (around line 145), add to the `data` dict:

```python
"image_generation": asdict(self.image_generation),
"overlay_image": asdict(self.overlay_image),
```

- [ ] **Step 6: Add default config to `config.yaml`**

Append the new sections to the existing `config.yaml`:

```yaml
image_generation:
  model: "gpt-image-1.5"
  quality: "medium"
  size: "1024x1024"
  background: "auto"
  format: "png"
  daily_limit: -1
  per_user_limit: 5

overlay_image:
  command: "!image"
  display_duration: 15
  animation_in: "fadeIn"
  animation_out: "fadeOut"
  animation_duration: 1.0
  random_filter: "all"
  enabled: true
```

- [ ] **Step 7: Commit**

```bash
git add bot/config.py config.yaml
git commit -m "feat(config): add ImageGenerationConfig and OverlayImageConfig"
```

---

### Task 2: Database tables + CRUD methods

**Files:**
- Modify: `bot/db/database.py:13-210` (SCHEMA) and append methods

- [ ] **Step 1: Add `gallery_images` and `gallery_votes` tables to SCHEMA**

Append to the `SCHEMA` string (before the closing `"""`):

```sql
CREATE TABLE IF NOT EXISTS gallery_images (
    id TEXT PRIMARY KEY,
    title TEXT,
    prompt TEXT NOT NULL,
    revised_prompt TEXT,
    username TEXT NOT NULL,
    user_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    file_path TEXT NOT NULL,
    model TEXT NOT NULL,
    quality TEXT NOT NULL,
    size TEXT NOT NULL,
    cost_usd REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_gallery_created ON gallery_images(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_gallery_user ON gallery_images(username);

CREATE TABLE IF NOT EXISTS gallery_votes (
    image_id TEXT NOT NULL REFERENCES gallery_images(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (image_id, user_id)
);
```

- [ ] **Step 2: Enable foreign keys in `Database.create()`**

Add **immediately after** `aiosqlite.connect()` (line 219) and **before** `executescript(SCHEMA)` (line 220):

```python
await conn.execute("PRAGMA foreign_keys = ON")
```

This must be set before schema creation for `ON DELETE CASCADE` to work on `gallery_votes`.

- [ ] **Step 3: Add `insert_gallery_image()` method**

```python
async def insert_gallery_image(
    self, id: str, title: str | None, prompt: str, revised_prompt: str | None,
    username: str, user_id: str, platform: str, file_path: str,
    model: str, quality: str, size: str, cost_usd: float,
) -> None:
    await self._conn.execute(
        "INSERT INTO gallery_images (id, title, prompt, revised_prompt, username, user_id, platform, file_path, model, quality, size, cost_usd) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (id, title, prompt, revised_prompt, username, user_id, platform, file_path, model, quality, size, cost_usd),
    )
    await self._conn.commit()
```

- [ ] **Step 4: Add `delete_gallery_image()` method**

```python
async def delete_gallery_image(self, image_id: str) -> bool:
    cursor = await self._conn.execute("DELETE FROM gallery_images WHERE id = ?", (image_id,))
    await self._conn.commit()
    return cursor.rowcount > 0
```

- [ ] **Step 5: Add `get_gallery_images()` method with pagination + sort + search**

```python
async def get_gallery_images(
    self, search: str | None = None, sort_by: str = "date",
    user_filter: str | None = None, limit: int = 20, offset: int = 0,
) -> list[dict]:
    base = (
        "SELECT g.*, COALESCE(v.votes, 0) AS votes "
        "FROM gallery_images g "
        "LEFT JOIN (SELECT image_id, COUNT(*) AS votes FROM gallery_votes GROUP BY image_id) v "
        "ON g.id = v.image_id"
    )
    conditions, params = [], []
    if search:
        conditions.append("(g.prompt LIKE ? OR g.username LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])
    if user_filter:
        conditions.append("g.username = ?")
        params.append(user_filter)
    if conditions:
        base += " WHERE " + " AND ".join(conditions)
    if sort_by == "votes":
        base += " ORDER BY votes DESC, g.created_at DESC"
    else:
        base += " ORDER BY g.created_at DESC"
    base += " LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cursor = await self._conn.execute(base, params)
    rows = await cursor.fetchall()
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in rows]
```

- [ ] **Step 6: Add `get_gallery_image()` method**

```python
async def get_gallery_image(self, image_id: str) -> dict | None:
    cursor = await self._conn.execute(
        "SELECT g.*, COALESCE(v.votes, 0) AS votes "
        "FROM gallery_images g "
        "LEFT JOIN (SELECT image_id, COUNT(*) AS votes FROM gallery_votes GROUP BY image_id) v "
        "ON g.id = v.image_id "
        "WHERE g.id = ?",
        (image_id,),
    )
    row = await cursor.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cursor.description]
    return dict(zip(cols, row))
```

- [ ] **Step 7: Add `toggle_gallery_vote()` method**

```python
async def toggle_gallery_vote(self, image_id: str, user_id: str) -> bool:
    cursor = await self._conn.execute(
        "SELECT 1 FROM gallery_votes WHERE image_id = ? AND user_id = ?",
        (image_id, user_id),
    )
    exists = await cursor.fetchone()
    if exists:
        await self._conn.execute(
            "DELETE FROM gallery_votes WHERE image_id = ? AND user_id = ?",
            (image_id, user_id),
        )
        await self._conn.commit()
        return False
    else:
        await self._conn.execute(
            "INSERT INTO gallery_votes (image_id, user_id) VALUES (?, ?)",
            (image_id, user_id),
        )
        await self._conn.commit()
        return True
```

- [ ] **Step 8: Add `update_gallery_title()` method**

```python
async def update_gallery_title(self, image_id: str, title: str) -> None:
    await self._conn.execute(
        "UPDATE gallery_images SET title = ? WHERE id = ?", (title, image_id),
    )
    await self._conn.commit()
```

- [ ] **Step 9: Add limit-checking methods**

```python
async def get_user_image_count_today(self, user_id: str) -> int:
    cursor = await self._conn.execute(
        "SELECT COUNT(*) FROM gallery_images WHERE user_id = ? AND date(created_at) = date('now')",
        (user_id,),
    )
    row = await cursor.fetchone()
    return row[0] if row else 0

async def get_total_image_count_today(self) -> int:
    cursor = await self._conn.execute(
        "SELECT COUNT(*) FROM gallery_images WHERE date(created_at) = date('now')",
    )
    row = await cursor.fetchone()
    return row[0] if row else 0
```

- [ ] **Step 10: Add `get_random_gallery_image()` method**

```python
async def get_random_gallery_image(self, filter_mode: str = "all") -> dict | None:
    if filter_mode == "top":
        # Weighted random: images with more votes are more likely to be selected
        query = (
            "SELECT g.*, v.votes "
            "FROM gallery_images g "
            "JOIN (SELECT image_id, COUNT(*) AS votes FROM gallery_votes GROUP BY image_id) v "
            "ON g.id = v.image_id "
            "ORDER BY RANDOM() * 1.0 / (v.votes + 1) LIMIT 1"
        )
    elif filter_mode == "recent":
        query = (
            "SELECT g.*, 0 AS votes FROM gallery_images g "
            "WHERE g.created_at >= datetime('now', '-2 days') "
            "ORDER BY RANDOM() LIMIT 1"
        )
    else:
        query = (
            "SELECT g.*, COALESCE(v.votes, 0) AS votes "
            "FROM gallery_images g "
            "LEFT JOIN (SELECT image_id, COUNT(*) AS votes FROM gallery_votes GROUP BY image_id) v "
            "ON g.id = v.image_id "
            "ORDER BY RANDOM() LIMIT 1"
        )
    cursor = await self._conn.execute(query)
    row = await cursor.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cursor.description]
    return dict(zip(cols, row))
```

- [ ] **Step 11: Add `get_gallery_images_for_date()` method**

```python
async def get_gallery_images_for_date(self, date_str: str) -> list[dict]:
    cursor = await self._conn.execute(
        "SELECT g.*, COALESCE(v.votes, 0) AS votes "
        "FROM gallery_images g "
        "LEFT JOIN (SELECT image_id, COUNT(*) AS votes FROM gallery_votes GROUP BY image_id) v "
        "ON g.id = v.image_id "
        "WHERE date(g.created_at) = ? ORDER BY g.created_at DESC",
        (date_str,),
    )
    rows = await cursor.fetchall()
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in rows]
```

- [ ] **Step 12: Add `has_voted()` helper**

```python
async def has_voted(self, image_id: str, user_id: str) -> bool:
    cursor = await self._conn.execute(
        "SELECT 1 FROM gallery_votes WHERE image_id = ? AND user_id = ?",
        (image_id, user_id),
    )
    return await cursor.fetchone() is not None
```

- [ ] **Step 13: Commit**

```bash
git add bot/db/database.py
git commit -m "feat(db): add gallery_images and gallery_votes tables with CRUD methods"
```

---

### Task 3: `OpenAIClient.generate_image()` + `IMAGE_COSTS` + `estimate_image_cost()`

**Files:**
- Modify: `bot/core/openai_client.py:26-40` (add IMAGE_COSTS) and append methods

- [ ] **Step 1: Add `IMAGE_COSTS` constant**

After `MODEL_COSTS` (around line 38), add:

```python
IMAGE_COSTS: dict[str, dict[tuple[str, str], float]] = {
    "gpt-image-1.5": {
        ("low", "1024x1024"): 0.009,
        ("low", "1024x1536"): 0.013,
        ("low", "1536x1024"): 0.013,
        ("medium", "1024x1024"): 0.034,
        ("medium", "1024x1536"): 0.05,
        ("medium", "1536x1024"): 0.05,
        ("high", "1024x1024"): 0.133,
        ("high", "1024x1536"): 0.20,
        ("high", "1536x1024"): 0.20,
    },
    "gpt-image-1": {
        ("low", "1024x1024"): 0.011,
        ("low", "1024x1536"): 0.016,
        ("low", "1536x1024"): 0.016,
        ("medium", "1024x1024"): 0.042,
        ("medium", "1024x1536"): 0.063,
        ("medium", "1536x1024"): 0.063,
        ("high", "1024x1024"): 0.167,
        ("high", "1024x1536"): 0.25,
        ("high", "1536x1024"): 0.25,
    },
    "gpt-image-1-mini": {
        ("low", "1024x1024"): 0.005,
        ("low", "1024x1536"): 0.0075,
        ("low", "1536x1024"): 0.0075,
        ("medium", "1024x1024"): 0.019,
        ("medium", "1024x1536"): 0.0285,
        ("medium", "1536x1024"): 0.0285,
        ("high", "1024x1024"): 0.076,
        ("high", "1024x1536"): 0.114,
        ("high", "1536x1024"): 0.114,
    },
}

DATA_GALLERY_DIR = Path("data/gallery")
```

Add `from pathlib import Path` to imports if not present. Add `import uuid, base64` to imports.

- [ ] **Step 2: Add `estimate_image_cost()` static method**

```python
@staticmethod
def estimate_image_cost(model: str, quality: str, size: str) -> float:
    model_costs = IMAGE_COSTS.get(model)
    if not model_costs:
        return 0.25  # fallback: max known price
    cost = model_costs.get((quality, size))
    if cost is not None:
        return cost
    return max(model_costs.values())  # fallback: highest price for this model
```

- [ ] **Step 3: Add `generate_image()` method on `OpenAIClient`**

```python
async def generate_image(self, prompt: str, sender_id: str | None = None) -> dict:
    cfg = self._config.image_generation
    model = cfg.model
    quality = cfg.quality
    size = cfg.size

    # Check limits
    if cfg.daily_limit != -1:
        today_total = await self._db.get_total_image_count_today()
        if today_total >= cfg.daily_limit:
            raise ValueError("Limite quotidienne de génération d'images atteinte.")
    if cfg.per_user_limit != -1 and sender_id:
        user_today = await self._db.get_user_image_count_today(sender_id)
        if user_today >= cfg.per_user_limit:
            raise ValueError("Tu as atteint ta limite d'images pour aujourd'hui.")

    # Ensure gallery dir exists
    DATA_GALLERY_DIR.mkdir(parents=True, exist_ok=True)

    # Generate with retry
    last_error = None
    for attempt in range(3):
        try:
            response = await self._client.images.generate(
                model=model,
                prompt=prompt,
                n=1,
                size=size,
                quality=quality,
                background=cfg.background,
                response_format="b64_json",
            )
            break
        except RateLimitError as e:
            last_error = e
            logger.warning("Image rate limit, attempt {a}/3: {e}", a=attempt + 1, e=e)
            await asyncio.sleep(2 ** attempt)
        except APIStatusError as e:
            if e.status_code == 400:
                raise ValueError("Prompt refusé par la modération OpenAI.") from e
            if e.status_code >= 500:
                last_error = e
                logger.warning("Image API 5xx, attempt {a}/3: {e}", a=attempt + 1, e=e)
                await asyncio.sleep(2 ** attempt)
            else:
                raise
    else:
        logger.error("Image generation failed after 3 attempts: {e}", e=last_error)
        raise RuntimeError("Échec de la génération d'image après 3 tentatives.")

    # Decode and save
    image_data = base64.b64decode(response.data[0].b64_json)
    file_ext = cfg.format if cfg.format in ("png", "jpeg", "webp") else "png"
    file_id = str(uuid.uuid4())
    file_name = f"{file_id}.{file_ext}"
    file_path = DATA_GALLERY_DIR / file_name
    file_path.write_bytes(image_data)

    # Cost
    cost_usd = self.estimate_image_cost(model, quality, size)
    await self._db.log_cost(model, 0, 0, cost_usd, purpose="image_generation", user_id=sender_id)

    revised = getattr(response.data[0], "revised_prompt", None)

    return {
        "file_id": file_id,
        "file_name": file_name,
        "file_path": str(file_path),
        "cost_usd": cost_usd,
        "revised_prompt": revised,
        "model": model,
        "quality": quality,
        "size": size,
    }
```

Add `import asyncio` to imports if not present.

- [ ] **Step 4: Commit**

```bash
git add bot/core/openai_client.py
git commit -m "feat(openai): add generate_image() with IMAGE_COSTS and retry logic"
```

---

### Task 4: AppState + overlay image queue

**Files:**
- Modify: `bot/dashboard/state.py` (add field)
- Modify: `bot/main.py:250-270` (init queue + assign)

- [ ] **Step 1: Add `overlay_image_queue` field to `AppState`**

In `bot/dashboard/state.py`, add import `import asyncio` and add field after `overlay_visible`:

```python
    overlay_image_queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=1))
```

- [ ] **Step 2: Commit**

```bash
git add bot/dashboard/state.py
git commit -m "feat(state): add overlay_image_queue to AppState"
```

---

### Task 5: Gallery API routes (`bot/dashboard/routes/gallery.py`)

**Files:**
- Create: `bot/dashboard/routes/gallery.py`
- Modify: `bot/dashboard/app.py:81-105` (register routes + overlay-image route)

- [ ] **Step 1: Create `bot/dashboard/routes/gallery.py`**

```python
import asyncio
import json
import os
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
    cost = state.openai_client.estimate_image_cost(m, q, s)
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
    # Check if current user has voted
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
    # Path traversal protection
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
    # Delete file
    file_path = DATA_GALLERY_DIR / Path(image["file_path"]).name
    if file_path.exists():
        file_path.unlink()
    else:
        logger.warning("Gallery file already missing: {p}", p=file_path)
    # Delete DB entry (cascades votes)
    await state.db.delete_gallery_image(image_id)
    return {"status": "deleted"}
```

- [ ] **Step 2: Register routes in `bot/dashboard/app.py`**

Add import and include_router calls. After the existing route imports (around line 82):

```python
from bot.dashboard.routes import gallery
```

In the public routes section:
```python
app.include_router(gallery.public_router, prefix="/api/public")
```

In the admin routes section:
```python
app.include_router(gallery.admin_router, prefix="/api/admin")
```

- [ ] **Step 3: Add `/overlay-image` route in `app.py`**

After the existing `/overlay` route (around line 133):

```python
@app.get("/overlay-image")
async def overlay_image_page():
    return FileResponse(
        "bot/dashboard/static/overlay_image.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )
```

- [ ] **Step 4: Create `bot/dashboard/static/loading_gifs/` directory**

```bash
mkdir -p bot/dashboard/static/loading_gifs
touch bot/dashboard/static/loading_gifs/.gitkeep
```

- [ ] **Step 5: Commit**

```bash
git add bot/dashboard/routes/gallery.py bot/dashboard/app.py bot/dashboard/static/loading_gifs/.gitkeep
git commit -m "feat(gallery): add gallery API routes with vote, title edit, SSE overlay, admin delete"
```

---

### Task 6: Admin config endpoints for image generation + overlay

**Files:**
- Modify: `bot/dashboard/routes/admin.py:19-142` (add config sections to GET + POST)

- [ ] **Step 1: Add new config sections to `GET /config`**

In the return dict of `get_config()` (around line 28), add:

```python
"image_generation": asdict(cfg.image_generation),
"overlay_image": asdict(cfg.overlay_image),
```

- [ ] **Step 2: Add merge logic in `POST /config`**

In the `POST /config` handler, add blocks for the new sections. After the existing twitch_events handling:

```python
# Image generation config
if "image_generation" in body:
    d = body["image_generation"]
    ig = cfg.image_generation
    if "model" in d:
        ig.model = str(d["model"])
    if "quality" in d:
        val = str(d["quality"])
        if val not in ("low", "medium", "high", "auto"):
            raise HTTPException(400, "quality must be low/medium/high/auto")
        ig.quality = val
    if "size" in d:
        val = str(d["size"])
        if val not in ("1024x1024", "1024x1536", "1536x1024", "auto"):
            raise HTTPException(400, "size must be 1024x1024/1024x1536/1536x1024/auto")
        ig.size = val
    if "background" in d:
        ig.background = str(d["background"])
    if "format" in d:
        val = str(d["format"])
        if val not in ("png", "jpeg", "webp"):
            raise HTTPException(400, "format must be png/jpeg/webp")
        ig.format = val
    if "daily_limit" in d:
        ig.daily_limit = int(d["daily_limit"])
    if "per_user_limit" in d:
        ig.per_user_limit = int(d["per_user_limit"])

# Overlay image config
if "overlay_image" in body:
    d = body["overlay_image"]
    oi = cfg.overlay_image
    if "command" in d:
        oi.command = str(d["command"])
    if "display_duration" in d:
        val = int(d["display_duration"])
        if not (5 <= val <= 60):
            raise HTTPException(400, "display_duration must be 5-60")
        oi.display_duration = val
    if "animation_in" in d:
        oi.animation_in = str(d["animation_in"])
    if "animation_out" in d:
        oi.animation_out = str(d["animation_out"])
    if "animation_duration" in d:
        val = float(d["animation_duration"])
        if not (0.5 <= val <= 3.0):
            raise HTTPException(400, "animation_duration must be 0.5-3.0")
        oi.animation_duration = val
    if "random_filter" in d:
        val = str(d["random_filter"])
        if val not in ("all", "top", "recent"):
            raise HTTPException(400, "random_filter must be all/top/recent")
        oi.random_filter = val
    if "enabled" in d:
        oi.enabled = bool(d["enabled"])
```

- [ ] **Step 3: Add overlay-image test trigger endpoint**

```python
@router.post("/overlay-image/test")
async def test_overlay_image(request: Request):
    state = request.app.state.wally
    image = await state.db.get_random_gallery_image(state.config.overlay_image.random_filter)
    if not image:
        raise HTTPException(404, "No images in gallery to test")
    payload = {
        "image_url": f"/api/public/gallery/{image['id']}/image",
        "title": image.get("title") or "",
        "username": image["username"],
        "display_duration": state.config.overlay_image.display_duration,
    }
    try:
        state.overlay_image_queue.put_nowait(payload)
    except asyncio.QueueFull:
        raise HTTPException(429, "An image is already being displayed")
    return {"status": "triggered", "image_id": image["id"]}
```

Add `import asyncio` to imports if not present.

- [ ] **Step 4: Commit**

```bash
git add bot/dashboard/routes/admin.py
git commit -m "feat(admin): add image generation and overlay config endpoints"
```

---

### Task 7: Web chat slash commands + `/imagine` handler

**Files:**
- Modify: `bot/dashboard/routes/chat.py:105-155` (command detection, /imagine handler)

- [ ] **Step 1: Refactor command detection in WebSocket handler**

Replace the existing `/scan` exact match check (around line 120) with the new pattern. Place it **after** the cooldown check (after line 134, `user.last_message = now`), so slash commands respect the cooldown:

```python
            # ── Slash commands ──
            if content.startswith("/"):
                command, _, args = content.partition(" ")
                args = args.strip()
                if command == "/imagine":
                    asyncio.create_task(_handle_imagine(state, ws, user, args))
                    continue
                elif command == "/scan":
                    asyncio.create_task(_handle_scan(state, ws, user, args or None))
                    continue
                else:
                    await _send_to(ws, {"type": "system", "content": f"Commande inconnue : {command}"})
                    continue
```

Remove the old `if content.lower() == "/scan":` check (line 120-122).

Note: both `_handle_imagine` and `_handle_scan` use `asyncio.create_task()` to avoid blocking the message loop (consistent with the existing `/scan` pattern). The argument order is `(state, ws, user, ...)` matching the existing `_handle_scan` signature.

- [ ] **Step 2: Update `_handle_scan()` signature**

Change `_handle_scan` to accept an optional `query` parameter (keeping existing arg order `state, ws, user`):

```python
async def _handle_scan(state, ws, user, query: str | None = None):
```

If `query` is not None, filter the messages query to search for the query term. The existing full-scan behavior is preserved when `query` is None.

- [ ] **Step 3: Add `_handle_imagine()` function**

```python
async def _handle_imagine(state: "AppState", ws, user, prompt: str):
    if not prompt:
        await _send_to(ws, {"type": "system", "content": "Usage : /imagine <description de l'image>"})
        return

    import uuid as _uuid
    msg_id = str(_uuid.uuid4())

    # Send "generating" embed to all connected clients
    await _broadcast({
        "type": "image_generating",
        "id": msg_id,
        "prompt": prompt,
        "loading_gif": "/api/public/loading-gif",
        "username": user.username,
        "avatar_url": user.avatar_url,
    })

    try:
        sender_id = f"discord:{user.discord_id}"

        # Generate image
        result = await state.openai_client.generate_image(prompt, sender_id)

        # Generate short title via LLM
        title = await state.openai_client.complete_secondary(
            "Tu es un assistant. Génère un titre court et créatif (max 6 mots) pour cette image. "
            "Réponds UNIQUEMENT avec le titre, rien d'autre.",
            [{"role": "user", "content": f"Image générée à partir du prompt : {prompt}"}],
            purpose="image_title",
        )
        title = title.strip().strip('"').strip("'")[:100]

        # Insert in gallery
        await state.db.insert_gallery_image(
            id=result["file_id"],
            title=title,
            prompt=prompt,
            revised_prompt=result.get("revised_prompt"),
            username=user.username,
            user_id=sender_id,
            platform="web",
            file_path=result["file_name"],
            model=result["model"],
            quality=result["quality"],
            size=result["size"],
            cost_usd=result["cost_usd"],
        )

        # Memory
        try:
            await state.memory.add("web", sender_id, f"{user.username} a généré une image : {title}")
        except Exception as e:
            logger.warning("Failed to add image memory: {e}", e=e)

        # Broadcast result embed to all connected clients
        await _broadcast({
            "type": "image_result",
            "id": msg_id,
            "image_id": result["file_id"],
            "title": title,
            "prompt": prompt,
            "image_url": f"/api/public/gallery/{result['file_id']}/image",
            "username": user.username,
            "avatar_url": user.avatar_url,
            "created_at": __import__("datetime").datetime.now().isoformat(),
            "votes": 0,
            "user_voted": False,
        })

    except ValueError as e:
        # Cancel the generating embed for all clients
        await _broadcast({"type": "image_cancelled", "id": msg_id, "error": str(e)})
    except Exception as e:
        logger.error("Image generation failed in web chat: {e}", e=e)
        await _broadcast({"type": "image_cancelled", "id": msg_id, "error": "Erreur lors de la génération de l'image."})
```

- [ ] **Step 4: Add WebSocket handlers for vote and edit_title actions**

In the message loop, add handling for new message types:

```python
if msg_type == "vote":
    image_id = data.get("image_id")
    if image_id:
        voted = await state.db.toggle_gallery_vote(image_id, f"discord:{user.discord_id}")
        await _send_to(ws, {"type": "vote_result", "image_id": image_id, "voted": voted})
    continue

if msg_type == "edit_title":
    image_id = data.get("image_id")
    title = data.get("title", "").strip()
    if image_id and title and len(title) <= 100:
        image = await state.db.get_gallery_image(image_id)
        if image and image["user_id"] == f"discord:{user.discord_id}":
            await state.db.update_gallery_title(image_id, title)
            await _broadcast({"type": "title_updated", "image_id": image_id, "title": title})
    continue
```

- [ ] **Step 5: Commit**

```bash
git add bot/dashboard/routes/chat.py
git commit -m "feat(chat): add /imagine slash command and refactor /scan with query support"
```

---

### Task 8: Discord `/wally imagine` command + persistent views

**Files:**
- Create: `bot/discord/commands/imagine.py`
- Modify: `bot/discord/bot.py:54-75` (load cog + register persistent view)

- [ ] **Step 1: Create `bot/discord/commands/imagine.py`**

```python
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger


class GalleryView(discord.ui.View):
    def __init__(self, image_id: str, creator_id: int, db):
        super().__init__(timeout=None)
        self.add_item(FlameButton(image_id, db))
        self.add_item(EditTitleButton(image_id, creator_id, db))


class FlameButton(discord.ui.Button):
    def __init__(self, image_id: str, db):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            emoji="🔥",
            label="0",
            custom_id=f"gallery_vote:{image_id}",
        )
        self.image_id = image_id
        self.db = db

    async def callback(self, interaction: discord.Interaction):
        user_id = f"discord:{interaction.user.id}"
        voted = await self.db.toggle_gallery_vote(self.image_id, user_id)
        image = await self.db.get_gallery_image(self.image_id)
        votes = image["votes"] if image else 0
        self.label = str(votes)
        self.style = discord.ButtonStyle.danger if voted else discord.ButtonStyle.secondary
        await interaction.response.edit_message(view=self.view)


class EditTitleButton(discord.ui.Button):
    def __init__(self, image_id: str, creator_id: int, db):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            emoji="✏️",
            custom_id=f"gallery_edit:{image_id}",
        )
        self.image_id = image_id
        self.creator_id = creator_id
        self.db = db

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.creator_id:
            await interaction.response.send_message("Seul le créateur peut modifier le titre.", ephemeral=True)
            return
        modal = EditTitleModal(self.image_id, self.db)
        await interaction.response.send_modal(modal)


class EditTitleModal(discord.ui.Modal):
    new_title = discord.ui.TextInput(
        label="Nouveau titre",
        placeholder="Titre de l'image...",
        max_length=100,
        required=True,
    )

    def __init__(self, image_id: str, db):
        super().__init__(title="Modifier le titre")
        self.image_id = image_id
        self.db = db

    async def on_submit(self, interaction: discord.Interaction):
        await self.db.update_gallery_title(self.image_id, self.new_title.value.strip())
        embed = interaction.message.embeds[0] if interaction.message and interaction.message.embeds else None
        if embed:
            embed.title = self.new_title.value.strip()
            await interaction.response.edit_message(embed=embed)
        else:
            await interaction.response.send_message("Titre mis à jour.", ephemeral=True)


class ImagineCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="imagine", description="Génère une image à partir d'un prompt")
    @app_commands.describe(prompt="Description de l'image à générer")
    async def imagine(self, interaction: discord.Interaction, prompt: str):
        await interaction.response.defer(thinking=True)
        try:
            sender_id = f"discord:{interaction.user.id}"

            # Generate image
            result = await self.bot.openai.generate_image(prompt, sender_id)

            # Generate short title
            title = await self.bot.openai.complete_secondary(
                "Tu es un assistant. Génère un titre court et créatif (max 6 mots) pour cette image. "
                "Réponds UNIQUEMENT avec le titre, rien d'autre.",
                [{"role": "user", "content": f"Image générée à partir du prompt : {prompt}"}],
                purpose="image_title",
            )
            title = title.strip().strip('"').strip("'")[:100]

            # Insert in gallery
            await self.bot.db.insert_gallery_image(
                id=result["file_id"],
                title=title,
                prompt=prompt,
                revised_prompt=result.get("revised_prompt"),
                username=interaction.user.display_name,
                user_id=sender_id,
                platform="discord",
                file_path=result["file_name"],
                model=result["model"],
                quality=result["quality"],
                size=result["size"],
                cost_usd=result["cost_usd"],
            )

            # Memory
            try:
                await self.bot.memory.add(
                    "discord", sender_id,
                    f"{interaction.user.display_name} a généré une image : {title}",
                )
            except Exception as e:
                logger.warning("Failed to add image memory: {e}", e=e)

            # Build embed
            from datetime import datetime
            embed = discord.Embed(
                title=title,
                description=f"*{prompt}*",
                color=discord.Color.from_str("#ffdd00"),
                timestamp=datetime.now(),
            )
            ext = result["file_name"].rsplit(".", 1)[-1]
            attach_name = f"image.{ext}"
            file = discord.File(result["file_path"], filename=attach_name)
            embed.set_image(url=f"attachment://{attach_name}")
            embed.set_footer(text=f"Par {interaction.user.display_name}")

            view = GalleryView(result["file_id"], interaction.user.id, self.bot.db)
            await interaction.followup.send(embed=embed, file=file, view=view)

        except ValueError as e:
            await interaction.followup.send(f"❌ {e}")
        except Exception as e:
            logger.error("Error in /wally imagine: {e}", e=e)
            await interaction.followup.send("❌ Une erreur s'est produite lors de la génération.")
```

- [ ] **Step 2: Register cog + persistent view in `bot/discord/bot.py`**

In `setup_hook()`, add after the existing cog imports:

```python
from bot.discord.commands.imagine import ImagineCog, GalleryView
```

After the existing `add_cog()` calls:
```python
await self.add_cog(ImagineCog(self))
```

For persistent view support, add a `Cog.listener` in `ImagineCog` (in `imagine.py`) that handles persistent button interactions. This avoids overriding `on_interaction` on the Bot class:

```python
# In ImagineCog class:
@commands.Cog.listener()
async def on_interaction(self, interaction: discord.Interaction):
    if interaction.type != discord.InteractionType.component:
        return
    custom_id = interaction.data.get("custom_id", "")
    if not (custom_id.startswith("gallery_vote:") or custom_id.startswith("gallery_edit:")):
        return
    image_id = custom_id.split(":", 1)[1]
    if custom_id.startswith("gallery_vote:"):
        user_id = f"discord:{interaction.user.id}"
        voted = await self.bot.db.toggle_gallery_vote(image_id, user_id)
        image = await self.bot.db.get_gallery_image(image_id)
        votes = image["votes"] if image else 0
        # Update the button label on the message
        view = GalleryView(image_id, 0, self.bot.db)
        view.children[0].label = str(votes)
        view.children[0].style = discord.ButtonStyle.danger if voted else discord.ButtonStyle.secondary
        await interaction.response.edit_message(view=view)
    elif custom_id.startswith("gallery_edit:"):
        image = await self.bot.db.get_gallery_image(image_id)
        if not image:
            await interaction.response.send_message("Image introuvable.", ephemeral=True)
            return
        creator_discord_id = int(image["user_id"].replace("discord:", ""))
        if interaction.user.id != creator_discord_id:
            await interaction.response.send_message("Seul le créateur peut modifier le titre.", ephemeral=True)
            return
        modal = EditTitleModal(image_id, self.bot.db)
        await interaction.response.send_modal(modal)
```

This approach is safer — it uses `Cog.listener()` which does not interfere with the Bot's internal interaction dispatch.

- [ ] **Step 3: Commit**

```bash
git add bot/discord/commands/imagine.py bot/discord/bot.py
git commit -m "feat(discord): add /wally imagine command with persistent flame/edit buttons"
```

---

### Task 9: Twitch `!image` handler

**Files:**
- Modify: `bot/twitch/handlers.py:30-50` (add command detection early in pipeline)

- [ ] **Step 1: Add `!image` detection in `handle_message()`**

After the dashboard counter increment (around line 35) and before the ignore-self check, add:

```python
# Overlay image command
overlay_cfg = bot.config.overlay_image
if overlay_cfg.enabled and content.strip().lower() == overlay_cfg.command.lower():
    ds = getattr(bot, "dashboard_state", None)
    if ds is not None:
        image = await bot.db.get_random_gallery_image(overlay_cfg.random_filter)
        if image:
            payload = {
                "image_url": f"/api/public/gallery/{image['id']}/image",
                "title": image.get("title") or "",
                "username": image["username"],
                "display_duration": overlay_cfg.display_duration,
                "animation_in": overlay_cfg.animation_in,
                "animation_out": overlay_cfg.animation_out,
                "animation_duration": overlay_cfg.animation_duration,
            }
            try:
                ds.overlay_image_queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass  # Image already being displayed
    return  # Don't process further
```

Add `import asyncio` to imports if not present.

- [ ] **Step 2: Commit**

```bash
git add bot/twitch/handlers.py
git commit -m "feat(twitch): add configurable !image overlay command"
```

---

### Task 10: OBS Overlay HTML page

**Files:**
- Create: `bot/dashboard/static/overlay_image.html`

- [ ] **Step 1: Create the overlay page**

```html
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>Wally Image Overlay</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/animate.css/4.1.1/animate.min.css">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: transparent; overflow: hidden; width: 100vw; height: 100vh; display: flex; align-items: center; justify-content: center; }
  #image-container { display: none; max-width: 90vw; max-height: 90vh; }
  #image-container img { max-width: 100%; max-height: 90vh; object-fit: contain; border: 3px solid #ffffff; box-shadow: 4px 4px 0px #ffffff; }
</style>
</head>
<body>
<div id="image-container">
  <img id="overlay-img" src="" alt="">
</div>
<script>
(function() {
  const container = document.getElementById('image-container');
  const img = document.getElementById('overlay-img');
  let hideTimeout = null;

  const sse = new EventSource('/api/public/sse/overlay-image');

  sse.addEventListener('show_image', function(e) {
    const data = JSON.parse(e.data);
    const animIn = data.animation_in || 'fadeIn';
    const animOut = data.animation_out || 'fadeOut';
    const duration = (data.display_duration || 15) * 1000;
    const animDuration = (data.animation_duration || 1) + 's';

    if (hideTimeout) { clearTimeout(hideTimeout); hideTimeout = null; }

    img.src = data.image_url;
    container.style.display = 'block';
    container.style.setProperty('--animate-duration', animDuration);
    container.className = 'animate__animated animate__' + animIn;

    hideTimeout = setTimeout(function() {
      container.className = 'animate__animated animate__' + animOut;
      container.addEventListener('animationend', function handler() {
        container.style.display = 'none';
        container.className = '';
        img.src = '';
        container.removeEventListener('animationend', handler);
      });
    }, duration);
  });

  sse.onerror = function() {
    setTimeout(function() { location.reload(); }, 5000);
  };
})();
</script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add bot/dashboard/static/overlay_image.html
git commit -m "feat(overlay): add OBS image overlay page with Animate.css animations"
```

---

### Task 11: Journal integration

**Files:**
- Modify: `bot/core/journal.py` (add gallery section to journal prompt)

- [ ] **Step 1: Add gallery images of the day to journal content**

Find the section where the journal prompt is built (where messages and emotion data are assembled). Add a gallery section:

```python
# Gallery images of the day
from datetime import date
today_images = await db.get_gallery_images_for_date(date.today().isoformat())
if today_images:
    gallery_lines = []
    for img in today_images:
        title = img.get("title") or "Sans titre"
        gallery_lines.append(f"- \"{title}\" par {img['username']} ({img['votes']} 🔥)")
    gallery_block = "**Galerie du jour** : {} images\n{}".format(len(today_images), "\n".join(gallery_lines))
else:
    gallery_block = ""
```

Include `gallery_block` in the user message sent to the LLM for journal generation.

- [ ] **Step 2: Commit**

```bash
git add bot/core/journal.py
git commit -m "feat(journal): include daily gallery images in journal prompt"
```

---

### Task 12: Frontend — Gallery tab + sidebar + styles

**Files:**
- Modify: `bot/dashboard/static/index.html` (add sidebar entries + tab content divs)
- Modify: `bot/dashboard/static/style.css` (add gallery styles)
- Modify: `bot/dashboard/static/app.js` (add gallery tab logic, slash commands, overlay admin tab)

This is the largest task. Break into sub-steps.

- [ ] **Step 1: Add sidebar entries in `index.html`**

In `nav-public` (after the chat/journal entries), add:
```html
<a class="sidebar-item" data-tab="gallery" onclick="showTab('gallery')" href="javascript:void(0)" aria-label="Galerie">
  <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/></svg>
  <span>Galerie</span>
</a>
```

In `nav-admin` (add a new overlay tab), add:
```html
<a class="sidebar-item" data-tab="admin-overlays" onclick="showTab('admin-overlays')" href="javascript:void(0)" aria-label="Overlays">
  <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
  <span>Overlays</span>
</a>
```

- [ ] **Step 2: Add tab content div for gallery in `index.html`**

Add a `<div id="tab-gallery" class="tab-content">` with a container for the gallery grid, search bar, sort/filter controls. This div will be populated dynamically by `app.js`.

```html
<div id="tab-gallery" class="tab-content">
  <h2>Galerie</h2>
  <div class="gallery-controls">
    <input type="text" id="gallery-search" placeholder="Rechercher..." class="neo-input">
    <select id="gallery-sort" class="neo-select">
      <option value="date">Par date</option>
      <option value="votes">Par flammes 🔥</option>
    </select>
    <select id="gallery-user-filter" class="neo-select">
      <option value="">Tous les utilisateurs</option>
    </select>
  </div>
  <div id="gallery-grid" class="gallery-grid"></div>
  <button id="gallery-load-more" class="neo-btn" style="display:none" onclick="loadMoreGallery()">Charger plus</button>
</div>
```

Add `<div id="tab-admin-overlays" class="tab-content">` for the overlay admin tab (populated by JS).

- [ ] **Step 3: Add gallery CSS in `style.css`**

```css
/* Gallery grid */
.gallery-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; margin-top: 16px; }
.gallery-card { background: #1a1a1a; border: 3px solid #ffffff; box-shadow: 4px 4px 0px #ffffff; overflow: hidden; cursor: pointer; transition: box-shadow 0.15s; }
.gallery-card:hover { box-shadow: 2px 2px 0px #ffffff; }
.gallery-card img { width: 100%; aspect-ratio: 1; object-fit: cover; border-bottom: 3px solid #ffffff; }
.gallery-card-info { padding: 12px; }
.gallery-card-title { font-weight: 800; font-size: 1rem; color: #ffffff; margin-bottom: 4px; }
.gallery-card-prompt { color: #aaaaaa; font-size: 0.85rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gallery-card-meta { display: flex; justify-content: space-between; align-items: center; margin-top: 8px; color: #aaaaaa; font-size: 0.8rem; }
.gallery-card-footer { display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; border-top: 3px solid #ffffff; }

/* Flame button */
.flame-btn { background: none; border: 2px solid #ffffff; color: #aaaaaa; padding: 4px 10px; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 4px; box-shadow: 2px 2px 0px #ffffff; transition: all 0.15s; }
.flame-btn:hover { box-shadow: 0px 0px 0px #ffffff; transform: translate(2px, 2px); }
.flame-btn.active { color: #ff3333; border-color: #ff3333; box-shadow: 2px 2px 0px #ff3333; }

/* Gallery controls */
.gallery-controls { display: flex; gap: 12px; flex-wrap: wrap; }

/* Lightbox */
.gallery-lightbox { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.9); z-index: 1000; display: flex; align-items: center; justify-content: center; }
.gallery-lightbox img { max-width: 90vw; max-height: 85vh; object-fit: contain; border: 3px solid #ffffff; box-shadow: 4px 4px 0px #ffffff; }
.gallery-lightbox-close { position: absolute; top: 20px; right: 20px; color: #ffffff; font-size: 2rem; cursor: pointer; font-weight: 900; }

/* Slash command autocomplete */
.slash-autocomplete { position: absolute; bottom: 100%; left: 0; right: 0; background: #1a1a1a; border: 3px solid #ffffff; box-shadow: 4px 4px 0px #ffffff; display: none; z-index: 100; }
.slash-autocomplete.visible { display: block; }
.slash-item { padding: 10px 14px; cursor: pointer; display: flex; gap: 8px; align-items: baseline; }
.slash-item:hover, .slash-item.selected { background: #2a2a2a; }
.slash-item-name { font-weight: 800; color: #ffffff; }
.slash-item-desc { color: #aaaaaa; font-size: 0.85rem; }

/* Image embed in chat */
.chat-image-embed { background: #1a1a1a; border: 3px solid #ffffff; box-shadow: 4px 4px 0px #ffffff; margin: 8px 0; overflow: hidden; max-width: 400px; }
.chat-image-embed img { width: 100%; }
.chat-image-embed .embed-info { padding: 10px; }
.chat-image-embed .embed-title { font-weight: 800; color: #ffdd00; }
.chat-image-embed .embed-prompt { color: #aaaaaa; font-style: italic; font-size: 0.85rem; }
.chat-image-embed .embed-actions { display: flex; gap: 8px; padding: 8px 10px; border-top: 2px solid #333; }
```

- [ ] **Step 4: Add gallery JavaScript logic in `app.js`**

Add the following functions (append to `app.js`):

1. `loadGallery(reset)` — fetches `/api/public/gallery` with current search/sort/filter, renders cards
2. `loadMoreGallery()` — increment offset, fetch next page, append
3. `renderGalleryCard(image)` — creates card HTML with image, title, prompt, flame button, admin delete
4. `openLightbox(imageId)` — shows full-screen modal with image details
5. `toggleFlame(imageId)` — POST to vote endpoint, update UI
6. `deleteGalleryImage(imageId)` — admin DELETE with confirmation toast
7. Event listeners on search input (debounced), sort select, user filter select

In `showTab()`, add:
```javascript
if (tabId === 'gallery') loadGallery(true);
if (tabId === 'admin-overlays') loadOverlayConfig();
```

- [ ] **Step 5: Add slash command autocomplete in `app.js`**

Add to the chat input area:

1. `SLASH_COMMANDS` constant array with `{name, description, adminOnly}` entries
2. `onChatInputKeyup()` listener — if starts with `/`, show popup, filter commands
3. Keyboard navigation (up/down arrows, Tab to select, Enter to send)
4. `renderSlashPopup(filtered)` — renders the autocomplete popup
5. `hideSlashPopup()` — hides it

- [ ] **Step 6: Add chat embed rendering for `/imagine` results**

In the WebSocket message handler, add cases for `image_generating`, `image_result`, `vote_result`, `title_updated`:

1. `image_generating` → render loading embed with GIF
2. `image_result` → replace loading embed with final image embed + flame button + edit button
3. `vote_result` → update flame count on the relevant embed
4. `title_updated` → update title on the relevant embed

- [ ] **Step 7: Add overlay admin tab in `app.js`**

`loadOverlayConfig()` function:
1. Fetch current config from `/api/admin/config`
2. Render two sections: Emotion overlay (toggle) + Image overlay (all config fields)
3. Save handler calls `POST /api/admin/config` with the overlay sections
4. Test button calls `POST /api/admin/overlay-image/test`
5. Animate.css animation list for select dropdowns (hardcoded list of common animations)

- [ ] **Step 8: Commit**

```bash
git add bot/dashboard/static/index.html bot/dashboard/static/style.css bot/dashboard/static/app.js
git commit -m "feat(frontend): add gallery tab, slash commands, overlay admin, lightbox, flame votes"
```

---

### Task 13: Final integration + smoke test

- [ ] **Step 1: Verify config loads correctly**

```bash
cd /opt/stacks/wally-ai && python -c "from bot.config import Config; c = Config.load(); print(c.image_generation); print(c.overlay_image)"
```

Expected: prints both config objects with default values.

- [ ] **Step 2: Verify database tables are created**

```bash
cd /opt/stacks/wally-ai && python -c "
import asyncio
from bot.db.database import Database
async def test():
    db = await Database.create('data/wally.db')
    cursor = await db._conn.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'gallery%'\")
    print(await cursor.fetchall())
asyncio.run(test())
"
```

Expected: `[('gallery_images',), ('gallery_votes',)]`

- [ ] **Step 3: Verify import chain**

```bash
cd /opt/stacks/wally-ai && python -c "
from bot.core.openai_client import OpenAIClient, IMAGE_COSTS
from bot.dashboard.routes.gallery import public_router, admin_router
from bot.discord.commands.imagine import ImagineCog, GalleryView
print('All imports OK')
"
```

- [ ] **Step 4: Test the dashboard starts**

```bash
docker compose up -d
```

Check logs for errors:
```bash
docker compose logs wally --tail=50
```

Expected: no import errors, dashboard accessible on port 8080.

- [ ] **Step 5: Manual smoke test**

1. Open dashboard → verify Gallery tab appears in sidebar
2. Open admin mode → verify Overlays tab appears
3. Open `/overlay-image` URL → verify blank transparent page loads
4. Check gallery API: `curl http://localhost:8080/api/public/gallery` → should return `{"images": [], "count": 0}`

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "feat: image generation, gallery, votes, overlay — complete integration"
```
