# Public UI Multi-Tabs SPA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refondre `public-ui/` en SPA multi-onglets (Statut, Chat, Galerie, Journal, À propos) avec glassmorphisme dark, animations CSS, et avatar GIF d'émotion en live.

**Architecture:** Vanilla JS ES modules avec hash-router. Chaque onglet est un module `tabs/*.js` qui exporte `mount(el)` et optionnellement `unmount()`. L'état des émotions est partagé via `app.js` (objet `emotions` + pub/sub `onEmotionUpdate`). Deux nouveaux endpoints backend publics : `/api/public/journal` et `/api/public/memory/me`.

**Tech Stack:** Vanilla JS (ES modules, no bundler), CSS variables + keyframes, FastAPI (backend), aiosqlite, Qdrant via QdrantMemoryStore.

---

## File Map

**Backend — nouveaux fichiers :**
- `bot/dashboard/routes/journal.py` — route publique GET /api/public/journal
- `bot/db/database.py` — ajout méthode `get_journal_entries(limit)`
- `bot/dashboard/routes/chat.py` — ajout route GET /api/public/memory/me
- `bot/dashboard/app.py` — enregistrement du router journal

**Frontend — réécriture complète :**
- `public-ui/index.html` — shell HTML, nav onglets, blobs, modal
- `public-ui/style.css` — variables, blobs, glassmorphisme, tous composants
- `public-ui/app.js` — router hash, SSE émotions, pub/sub, modal
- `public-ui/tabs/status.js` — onglet Statut
- `public-ui/tabs/chat.js` — onglet Chat (auth Discord OAuth, avatar GIF, 3 colonnes)
- `public-ui/tabs/gallery.js` — onglet Galerie
- `public-ui/tabs/journal.js` — onglet Journal (frise + entrée en dessous)
- `public-ui/tabs/about.js` — onglet À propos

**Tests :**
- `tests/dashboard/test_public_journal.py`
- `tests/dashboard/test_public_memory_me.py`

---

## Task 1: Endpoint GET /api/public/journal

**Files:**
- Create: `bot/dashboard/routes/journal.py`
- Modify: `bot/db/database.py`
- Modify: `bot/dashboard/app.py`
- Create: `tests/dashboard/test_public_journal.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/dashboard/test_public_journal.py
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_list_journal_returns_entries(async_client):
    entries = [
        {"date": "2026-04-03", "content": "Journée animée.", "word_count": 342, "created_at": "2026-04-03T23:00:00"},
        {"date": "2026-04-02", "content": "Journée calme.", "word_count": 231, "created_at": "2026-04-02T23:00:00"},
    ]
    async_client.app.state.wally.db.get_journal_entries = AsyncMock(return_value=entries)
    resp = await async_client.get("/api/public/journal")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["entries"]) == 2
    assert data["entries"][0]["date"] == "2026-04-03"

@pytest.mark.asyncio
async def test_list_journal_limit_param(async_client):
    async_client.app.state.wally.db.get_journal_entries = AsyncMock(return_value=[])
    resp = await async_client.get("/api/public/journal?limit=5")
    assert resp.status_code == 200
    async_client.app.state.wally.db.get_journal_entries.assert_called_once_with(limit=5)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/dashboard/test_public_journal.py -v 2>&1 | head -40
```
Expected: FAIL — ImportError ou 404.

- [ ] **Step 3: Ajouter `get_journal_entries` dans `bot/db/database.py`**

Trouver la classe `Database` et ajouter la méthode après les méthodes journal existantes :

```python
async def get_journal_entries(self, limit: int = 30) -> list[dict]:
    """Retourne les N dernières entrées du journal archivé."""
    async with aiosqlite.connect(self.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT date, content, word_count, created_at FROM journal_archive ORDER BY date DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
```

- [ ] **Step 4: Créer `bot/dashboard/routes/journal.py`**

```python
from fastapi import APIRouter, Request

public_router = APIRouter()


@public_router.get("/journal")
async def list_journal(request: Request, limit: int = 30) -> dict:
    """Liste les N dernières entrées du journal archivé."""
    state = request.app.state.wally
    entries = await state.db.get_journal_entries(limit=limit)
    return {"entries": entries}
```

- [ ] **Step 5: Enregistrer le router dans `bot/dashboard/app.py`**

Lire `bot/dashboard/app.py`, repérer les imports de routes existants (ex: `from .routes import gallery`), puis ajouter en dessous :

```python
from .routes import journal as journal_routes
```

Et parmi les `app.include_router(...)` pour les routes publiques :

```python
app.include_router(journal_routes.public_router, prefix="/api/public")
```

- [ ] **Step 6: Run test**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/dashboard/test_public_journal.py -v
```
Expected: PASS (2 tests).

- [ ] **Step 7: Commit**

```bash
git add bot/dashboard/routes/journal.py bot/db/database.py bot/dashboard/app.py tests/dashboard/test_public_journal.py
git commit -m "feat(public-api): GET /api/public/journal — liste journal_archive"
```

---

## Task 2: Endpoint GET /api/public/memory/me

**Files:**
- Modify: `bot/dashboard/routes/chat.py`
- Create: `tests/dashboard/test_public_memory_me.py`

- [ ] **Step 1: Lire `bot/dashboard/routes/chat.py`** pour comprendre la structure existante et localiser `_extract_user_id_from_jwt`.

- [ ] **Step 2: Write the failing test**

```python
# tests/dashboard/test_public_memory_me.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

VALID_JWT_PAYLOAD = {"user_id": "discord:123456789"}

@pytest.mark.asyncio
async def test_memory_me_returns_data(async_client):
    from bot.dashboard.routes import chat as chat_routes
    memory_records = [
        MagicMock(text="Aime la musique", category="PREF"),
        MagicMock(text="S'appelle Nocturne", category="FAIT"),
    ]
    async_client.app.state.wally.memory.store.get_all = AsyncMock(return_value=memory_records)
    async_client.app.state.wally.db.get_trust_score = AsyncMock(return_value=0.7)
    async_client.app.state.wally.db.get_love_score = AsyncMock(return_value=0.5)

    with patch.object(chat_routes, "_extract_user_id_from_jwt", return_value="discord:123456789"):
        resp = await async_client.get("/api/public/memory/me", headers={"Authorization": "Bearer faketoken"})

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["facts"]) == 1
    assert len(data["preferences"]) == 1
    assert data["relation"]["trust"] == pytest.approx(0.7)

@pytest.mark.asyncio
async def test_memory_me_unauthenticated(async_client):
    from bot.dashboard.routes import chat as chat_routes
    with patch.object(chat_routes, "_extract_user_id_from_jwt", return_value=None):
        resp = await async_client.get("/api/public/memory/me")
    assert resp.status_code == 401
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/dashboard/test_public_memory_me.py -v 2>&1 | head -30
```
Expected: FAIL — 404 (route inexistante).

- [ ] **Step 4: Ajouter la route dans `bot/dashboard/routes/chat.py`**

Après avoir relu le fichier, ajouter à la fin du `public_router` (ou créer ce router s'il n'existe pas) :

```python
@public_router.get("/memory/me")
async def get_my_memory(request: Request) -> dict:
    """Retourne les souvenirs et scores de relation de l'utilisateur connecté."""
    user_id = _extract_user_id_from_jwt(request)
    if not user_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Authentication required")

    state = request.app.state.wally
    records = await state.memory.store.get_all(user_id)

    facts = [r.text for r in records if r.category in ("FAIT", "LANG")]
    preferences = [r.text for r in records if r.category == "PREF"]

    # Extraire platform et raw_id depuis "discord:123"
    parts = user_id.split(":", 1)
    platform = parts[0] if len(parts) == 2 else "discord"
    raw_id = parts[1] if len(parts) == 2 else user_id

    trust = await state.db.get_trust_score(platform, raw_id)
    love = await state.db.get_love_score(platform, raw_id)

    return {
        "facts": facts,
        "preferences": preferences,
        "relation": {"trust": round(trust, 3), "love": round(love, 3)},
    }
```

- [ ] **Step 5: Run test**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/dashboard/test_public_memory_me.py -v
```
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add bot/dashboard/routes/chat.py tests/dashboard/test_public_memory_me.py
git commit -m "feat(public-api): GET /api/public/memory/me — souvenirs + relation JWT"
```

---

## Task 3: index.html + style.css (shell + styles globaux)

**Files:**
- Modify: `public-ui/index.html`
- Modify: `public-ui/style.css`

- [ ] **Step 1: Réécrire `public-ui/index.html`**

```html
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Wally</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap">
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <div class="blob blob-1"></div>
  <div class="blob blob-2"></div>
  <div class="blob blob-3"></div>

  <div class="app-shell">
    <nav class="tab-nav">
      <div class="tab-nav-inner">
        <button class="tab-btn active" data-tab="status">
          <span class="tab-icon">●</span> Statut
        </button>
        <button class="tab-btn" data-tab="chat">
          <span class="tab-icon">◎</span> Chat
        </button>
        <button class="tab-btn" data-tab="gallery">
          <span class="tab-icon">◫</span> Galerie
        </button>
        <button class="tab-btn" data-tab="journal">
          <span class="tab-icon">◈</span> Journal
        </button>
        <button class="tab-btn" data-tab="about">
          <span class="tab-icon">◇</span> À propos
        </button>
      </div>
    </nav>

    <main id="tab-content"></main>
  </div>

  <div class="modal-overlay" id="modal-overlay">
    <div class="modal-box" id="modal-box">
      <button class="modal-close" id="modal-close">✕</button>
      <img class="modal-img" id="modal-img" src="" alt="">
      <div class="modal-caption" id="modal-caption"></div>
    </div>
  </div>

  <script type="module" src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Réécrire `public-ui/style.css`**

```css
/* ── Variables ── */
:root {
  --bg: #0a0a0f;
  --surface: rgba(255,255,255,0.04);
  --surface-hover: rgba(255,255,255,0.07);
  --border: rgba(255,255,255,0.09);
  --text: rgba(255,255,255,0.87);
  --text-muted: rgba(255,255,255,0.4);
  --accent: #06b6d4;
  --radius: 16px;
  --radius-sm: 12px;

  --c-anger: #ef4444;
  --c-joy: #eab308;
  --c-curiosity: #22c55e;
  --c-sadness: #3b82f6;
  --c-boredom: #a855f7;
}

/* ── Reset ── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'Inter', system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  overflow-x: hidden;
}

/* ── Blobs ── */
.blob {
  position: fixed;
  border-radius: 50%;
  pointer-events: none;
  z-index: 0;
}
.blob-1 {
  width: 500px; height: 500px;
  top: -100px; left: -100px;
  background: radial-gradient(circle, rgba(6,182,212,0.12) 0%, transparent 70%);
  animation: blob1 13s ease-in-out infinite;
}
.blob-2 {
  width: 400px; height: 400px;
  bottom: -80px; right: -80px;
  background: radial-gradient(circle, rgba(168,85,247,0.1) 0%, transparent 70%);
  animation: blob2 10s ease-in-out infinite;
}
.blob-3 {
  width: 300px; height: 300px;
  top: 50%; left: 50%;
  background: radial-gradient(circle, rgba(6,182,212,0.06) 0%, transparent 70%);
  animation: blob3 8s ease-in-out infinite;
}
@keyframes blob1 { 0%,100%{transform:translate(0,0)} 50%{transform:translate(60px,40px)} }
@keyframes blob2 { 0%,100%{transform:translate(0,0)} 50%{transform:translate(-50px,-30px)} }
@keyframes blob3 { 0%,100%{transform:translate(-50%,-50%) scale(1)} 50%{transform:translate(-50%,-50%) scale(1.2)} }

/* ── Layout ── */
.app-shell {
  position: relative;
  z-index: 1;
  max-width: 1100px;
  margin: 0 auto;
  padding: 20px 16px;
}

/* ── Tab nav ── */
.tab-nav {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  backdrop-filter: blur(20px);
  margin-bottom: 16px;
  overflow: hidden;
}
.tab-nav-inner {
  display: flex;
  gap: 2px;
  padding: 6px;
}
.tab-btn {
  flex: 1;
  padding: 10px 16px;
  font-size: 0.82rem;
  font-weight: 500;
  color: var(--text-muted);
  background: transparent;
  border: none;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}
.tab-btn:hover { background: var(--surface-hover); color: var(--text); }
.tab-btn.active { background: rgba(6,182,212,0.12); color: var(--accent); }
.tab-icon { font-size: 0.7rem; }

/* ── Tab content ── */
#tab-content { animation: fadeIn 0.3s ease both; }
@keyframes fadeIn { from{opacity:0;transform:translateY(6px)} to{opacity:1;transform:translateY(0)} }

/* ── Glass card ── */
.glass {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  backdrop-filter: blur(20px);
}
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 18px;
  animation: fadeUp 0.4s ease both;
}
@keyframes fadeUp { from{opacity:0;transform:translateY(12px)} to{opacity:1;transform:translateY(0)} }

/* ── Status tab ── */
.status-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
.card-label { font-size: 0.72rem; color: var(--text-muted); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.06em; }
.card-value { font-size: 1.4rem; font-weight: 700; }
.card-sub { font-size: 0.75rem; color: var(--text-muted); margin-top: 4px; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
.dot-on { background: #22c55e; box-shadow: 0 0 6px #22c55e; }
.dot-off { background: rgba(255,255,255,0.2); }

/* Emotion bars */
.emo-bars { display: flex; flex-direction: column; gap: 6px; }
.emo-row { display: flex; align-items: center; gap: 8px; font-size: 0.75rem; }
.emo-name { width: 70px; color: var(--text-muted); }
.emo-track { flex: 1; height: 5px; background: rgba(255,255,255,0.08); border-radius: 3px; overflow: hidden; }
.emo-fill { height: 100%; border-radius: 3px; transition: width 0.6s ease; }
.emo-pct { width: 32px; text-align: right; color: var(--text-muted); font-size: 0.7rem; }

/* ── Chat tab ── */
.chat-layout {
  display: grid;
  grid-template-columns: 220px 1fr 240px;
  grid-template-rows: 1fr auto;
  height: calc(100vh - 160px);
  min-height: 500px;
  gap: 12px;
}
.chat-wally-col {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  overflow: hidden;
}
.wally-avatar { width: 140px; height: 140px; object-fit: contain; border-radius: 12px; }
.wally-emotion-label { font-size: 0.78rem; color: var(--accent); font-weight: 600; text-transform: capitalize; }
.wally-online { display: flex; align-items: center; gap: 6px; font-size: 0.72rem; color: rgba(255,255,255,0.4); }
.chat-messages-col {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.chat-user-bar {
  display: flex; align-items: center; gap: 10px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}
.chat-user-avatar { width: 28px; height: 28px; border-radius: 50%; }
.chat-user-name { font-size: 0.82rem; font-weight: 600; flex: 1; }
.chat-logout { font-size: 0.72rem; color: var(--text-muted); cursor: pointer; padding: 4px 10px; border: 1px solid var(--border); border-radius: 6px; background: transparent; color: var(--text-muted); transition: all 0.2s; }
.chat-logout:hover { background: rgba(255,255,255,0.06); color: var(--text); }
.messages-list { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 10px; }
.bubble { max-width: 75%; padding: 10px 14px; border-radius: 14px; font-size: 0.85rem; line-height: 1.5; animation: msgIn 0.25s ease both; }
@keyframes msgIn { from{opacity:0;transform:translateY(8px)} to{opacity:1;transform:translateY(0)} }
.bubble-bot { background: rgba(6,182,212,0.12); border: 1px solid rgba(6,182,212,0.2); align-self: flex-start; }
.bubble-user { background: rgba(99,102,241,0.15); border: 1px solid rgba(99,102,241,0.25); align-self: flex-end; }
.typing-indicator { display: flex; gap: 4px; align-items: center; padding: 10px 14px; }
.typing-dot { width: 6px; height: 6px; background: var(--accent); border-radius: 50%; animation: typingBounce 1s ease infinite; }
.typing-dot:nth-child(2) { animation-delay: 0.15s; }
.typing-dot:nth-child(3) { animation-delay: 0.3s; }
@keyframes typingBounce { 0%,60%,100%{transform:translateY(0)} 30%{transform:translateY(-6px)} }
.chat-input-row {
  display: flex; gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--border);
}
.chat-input {
  flex: 1; background: rgba(255,255,255,0.05); border: 1px solid var(--border); border-radius: 10px;
  padding: 10px 14px; font-size: 0.85rem; color: var(--text); outline: none;
  transition: border-color 0.2s;
}
.chat-input:focus { border-color: rgba(6,182,212,0.5); }
.chat-send {
  background: var(--accent); border: none; border-radius: 10px; padding: 10px 16px;
  color: #fff; font-weight: 600; cursor: pointer; transition: opacity 0.2s;
}
.chat-send:hover { opacity: 0.85; }
.memory-col {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
  overflow-y: auto;
}
.memory-section-title { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-muted); margin-bottom: 8px; margin-top: 16px; }
.memory-section-title:first-child { margin-top: 0; }
.memory-item { font-size: 0.78rem; color: rgba(255,255,255,0.65); line-height: 1.5; margin-bottom: 5px; padding-left: 8px; border-left: 2px solid rgba(255,255,255,0.08); }
.relation-score { display: flex; justify-content: space-between; font-size: 0.78rem; margin-bottom: 6px; }
.score-label { color: var(--text-muted); }
.score-value { color: var(--accent); font-weight: 600; }

/* Chat login gate */
.chat-login {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  min-height: 400px; gap: 20px; text-align: center;
}
.chat-login-avatar { width: 100px; height: 100px; border-radius: 50%; animation: pulse 2.5s ease-in-out infinite; }
@keyframes pulse { 0%,100%{transform:scale(1)} 50%{transform:scale(1.05)} }
.discord-btn {
  display: flex; align-items: center; gap: 10px;
  background: #5865f2; border: none; border-radius: 10px;
  padding: 12px 24px; color: #fff; font-size: 0.9rem; font-weight: 600;
  cursor: pointer; text-decoration: none; transition: opacity 0.2s;
}
.discord-btn:hover { opacity: 0.9; }

/* ── Gallery tab ── */
.gallery-filters { display: flex; gap: 8px; margin-bottom: 16px; }
.filter-btn {
  padding: 7px 16px; background: transparent; border: 1px solid var(--border);
  border-radius: 8px; font-size: 0.8rem; color: var(--text-muted); cursor: pointer; transition: all 0.2s;
}
.filter-btn.active { border-color: var(--accent); color: var(--accent); background: rgba(6,182,212,0.08); }
.gallery-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 10px;
}
.gallery-item {
  aspect-ratio: 1;
  border-radius: var(--radius-sm);
  overflow: hidden;
  cursor: pointer;
  position: relative;
  animation: fadeIn 0.4s ease both;
  transition: transform 0.2s;
}
.gallery-item:hover { transform: scale(1.03); }
.gallery-item img { width: 100%; height: 100%; object-fit: cover; display: block; }
.gallery-overlay {
  position: absolute; inset: 0;
  background: rgba(0,0,0,0.65);
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 4px; padding: 8px;
  opacity: 0; transition: opacity 0.2s;
}
.gallery-item:hover .gallery-overlay { opacity: 1; }
.gallery-prompt { font-size: 0.65rem; color: rgba(255,255,255,0.85); text-align: center; line-height: 1.3; }
.gallery-votes { font-size: 0.7rem; color: var(--accent); font-weight: 600; }
.load-more {
  width: 100%; margin-top: 16px; padding: 12px;
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-sm);
  color: var(--text-muted); cursor: pointer; font-size: 0.82rem; transition: all 0.2s;
}
.load-more:hover { background: var(--surface-hover); color: var(--text); }

/* ── Journal tab ── */
.tl-scroll { overflow-x: auto; scrollbar-width: none; }
.tl-scroll::-webkit-scrollbar { display: none; }
.tl-row {
  display: flex; align-items: center;
  min-width: max-content;
  padding: 20px 8px 16px;
  position: relative;
}
.tl-row::before {
  content: ''; position: absolute;
  top: 50%; left: 8px; right: 8px;
  height: 1px; background: rgba(255,255,255,0.1);
  transform: translateY(-50%);
}
.tl-item {
  display: flex; flex-direction: column; align-items: center; gap: 8px;
  padding: 0 22px; cursor: pointer; position: relative;
}
.tl-dot {
  width: 12px; height: 12px; border-radius: 50%;
  border: 2px solid rgba(255,255,255,0.2);
  background: var(--bg); z-index: 2;
  transition: all 0.2s; flex-shrink: 0;
}
.tl-item:hover .tl-dot { border-color: var(--accent); transform: scale(1.3); }
.tl-item.active .tl-dot {
  border-color: var(--accent); background: var(--accent);
  transform: scale(1.3);
  box-shadow: 0 0 10px rgba(6,182,212,0.6);
}
.tl-date { font-size: 0.65rem; color: var(--text-muted); white-space: nowrap; transition: color 0.2s; }
.tl-item.active .tl-date { color: var(--accent); font-weight: 600; }
.tl-item:hover .tl-date { color: rgba(255,255,255,0.6); }

.entry-area { margin-top: 4px; min-height: 100px; }
.entry-card {
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(6,182,212,0.2);
  border-radius: 14px; overflow: hidden;
  animation: fadeIn 0.3s cubic-bezier(0.34,1.4,0.64,1) both;
}
.entry-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 18px; border-bottom: 1px solid rgba(255,255,255,0.05);
}
.entry-date-text { font-size: 0.9rem; font-weight: 700; }
.entry-sub-text { font-size: 0.7rem; color: var(--text-muted); margin-top: 2px; }
.badges { display: flex; gap: 5px; flex-wrap: wrap; }
.badge { padding: 3px 9px; border-radius: 20px; font-size: 0.67rem; font-weight: 500; border: 1px solid; }
.entry-body { padding: 16px 18px; font-size: 0.86rem; color: rgba(255,255,255,0.65); line-height: 1.75; }
.entry-body p { margin-bottom: 10px; }
.entry-body p:last-child { margin-bottom: 0; }

/* ── About tab ── */
.pipeline {
  display: flex; align-items: center; gap: 0;
  flex-wrap: wrap; margin-bottom: 20px;
}
.pipe-step {
  display: flex; align-items: center; gap: 0;
  cursor: pointer;
}
.pipe-node {
  padding: 8px 16px; border-radius: 8px; font-size: 0.8rem; font-weight: 600;
  border: 1px solid; transition: all 0.2s;
}
.pipe-arrow { font-size: 1rem; color: rgba(255,255,255,0.2); padding: 0 4px; }
.pipe-detail {
  background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07);
  border-radius: var(--radius-sm); padding: 16px 20px;
  font-size: 0.85rem; color: rgba(255,255,255,0.7); line-height: 1.6;
  animation: fadeIn 0.25s ease both;
  margin-bottom: 24px;
}
.pillars-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.pillar-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: 18px;
  animation: fadeUp 0.4s ease both;
}
.pillar-title { font-size: 0.9rem; font-weight: 700; margin-bottom: 6px; }
.pillar-desc { font-size: 0.8rem; color: rgba(255,255,255,0.55); line-height: 1.5; }

/* ── Modal ── */
.modal-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.85);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000; opacity: 0; pointer-events: none; transition: opacity 0.2s;
}
.modal-overlay.open { opacity: 1; pointer-events: auto; }
.modal-box {
  background: rgba(15,15,22,0.97); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 12px;
  max-width: 90vw; max-height: 90vh; position: relative;
}
.modal-close {
  position: absolute; top: 12px; right: 12px;
  background: rgba(255,255,255,0.08); border: none; border-radius: 6px;
  color: var(--text); width: 28px; height: 28px; cursor: pointer; font-size: 0.8rem;
}
.modal-img { max-width: 80vw; max-height: 75vh; border-radius: 10px; display: block; }
.modal-caption { font-size: 0.78rem; color: var(--text-muted); margin-top: 10px; text-align: center; }

/* ── Misc ── */
.empty-state { text-align: center; padding: 40px; color: var(--text-muted); font-size: 0.85rem; }
```

- [ ] **Step 3: Vérifier visuellement** en ouvrant http://localhost:PORT/

- [ ] **Step 4: Commit**

```bash
git add public-ui/index.html public-ui/style.css
git commit -m "feat(public-ui): index.html shell + style.css glassmorphisme complet"
```

---

## Task 4: app.js — Router + SSE + module loader

**Files:**
- Modify: `public-ui/app.js`

- [ ] **Step 1: Réécrire `public-ui/app.js`**

```javascript
// public-ui/app.js
import { mount as mountStatus, unmount as unmountStatus } from './tabs/status.js';
import { mount as mountChat, unmount as unmountChat } from './tabs/chat.js';
import { mount as mountGallery, unmount as unmountGallery } from './tabs/gallery.js';
import { mount as mountJournal, unmount as unmountJournal } from './tabs/journal.js';
import { mount as mountAbout, unmount as unmountAbout } from './tabs/about.js';

// ── Shared emotion state ──
export const emotions = { anger: 0, joy: 0, curiosity: 0, sadness: 0, boredom: 0 };
const emotionListeners = [];
export function onEmotionUpdate(fn) { emotionListeners.push(fn); }
function notifyEmotions() { emotionListeners.forEach(fn => fn({ ...emotions })); }

// ── SSE emotions ──
function connectSSE() {
  const es = new EventSource('/api/public/sse/emotions');
  es.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      Object.assign(emotions, data);
      notifyEmotions();
    } catch (_) {}
  };
  es.onerror = () => setTimeout(connectSSE, 5000);
}
connectSSE();

// ── Modal ──
const overlay = document.getElementById('modal-overlay');
const modalImg = document.getElementById('modal-img');
const modalCaption = document.getElementById('modal-caption');
document.getElementById('modal-close').addEventListener('click', closeModal);
overlay.addEventListener('click', (e) => { if (e.target === overlay) closeModal(); });

export function openModal(src, caption) {
  modalImg.src = src;
  modalImg.alt = caption || '';
  modalCaption.textContent = caption || '';
  overlay.classList.add('open');
}
function closeModal() { overlay.classList.remove('open'); }

// ── Router ──
const TABS = {
  status:  { mount: mountStatus,  unmount: unmountStatus },
  chat:    { mount: mountChat,    unmount: unmountChat },
  gallery: { mount: mountGallery, unmount: unmountGallery },
  journal: { mount: mountJournal, unmount: unmountJournal },
  about:   { mount: mountAbout,   unmount: unmountAbout },
};

let currentTab = null;

function route() {
  const hash = location.hash.slice(1) || 'status';
  const tabName = TABS[hash] ? hash : 'status';

  // Unmount previous
  if (currentTab && TABS[currentTab] && TABS[currentTab].unmount) {
    TABS[currentTab].unmount();
  }

  // Update nav buttons
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });

  const content = document.getElementById('tab-content');
  content.style.animation = 'none';
  content.offsetHeight; // reflow
  content.style.animation = '';

  TABS[tabName].mount(content);
  currentTab = tabName;
}

// Nav button clicks
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    location.hash = btn.dataset.tab;
  });
});

window.addEventListener('hashchange', route);
route();
```

- [ ] **Step 2: Vérifier dans le navigateur** que la navigation entre onglets fonctionne (chaque onglet doit afficher quelque chose, même si les modules ne font que `el.textContent = 'status'` pour l'instant).

- [ ] **Step 3: Commit**

```bash
git add public-ui/app.js
git commit -m "feat(public-ui): app.js router hash + SSE émotions + modal"
```

---

## Task 5: Onglet Statut

**Files:**
- Create: `public-ui/tabs/status.js`

- [ ] **Step 1: Créer `public-ui/tabs/status.js`**

```javascript
// public-ui/tabs/status.js
import { emotions, onEmotionUpdate } from '../app.js';

let _pollInterval = null;
let _container = null;

const EMO_COLORS = {
  anger: '#ef4444', joy: '#eab308', curiosity: '#22c55e',
  sadness: '#3b82f6', boredom: '#a855f7'
};
const EMO_LABELS = {
  anger: 'Colère', joy: 'Joie', curiosity: 'Curiosité',
  sadness: 'Tristesse', boredom: 'Ennui'
};

function formatUptime(seconds) {
  if (!seconds) return '—';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function dominant(emo) {
  return Object.entries(emo).sort((a, b) => b[1] - a[1])[0][0];
}

function buildEmoBar(name, value) {
  const row = document.createElement('div');
  row.className = 'emo-row';

  const label = document.createElement('span');
  label.className = 'emo-name';
  label.textContent = EMO_LABELS[name];
  row.appendChild(label);

  const track = document.createElement('div');
  track.className = 'emo-track';
  const fill = document.createElement('div');
  fill.className = 'emo-fill';
  fill.style.width = (value * 100).toFixed(1) + '%';
  fill.style.background = EMO_COLORS[name];
  track.appendChild(fill);
  row.appendChild(track);

  const pct = document.createElement('span');
  pct.className = 'emo-pct';
  pct.textContent = Math.round(value * 100) + '%';
  row.appendChild(pct);

  return { row, fill, pct };
}

function renderStatus(el, status, stream) {
  el.textContent = '';

  const grid = document.createElement('div');
  grid.className = 'status-grid';

  // Card: Connexions
  const cardConn = document.createElement('div');
  cardConn.className = 'card';
  const connLabel = document.createElement('div');
  connLabel.className = 'card-label';
  connLabel.textContent = 'Connexions';
  cardConn.appendChild(connLabel);

  const discordLine = document.createElement('div');
  discordLine.style.marginBottom = '6px';
  const discordDot = document.createElement('span');
  discordDot.className = 'dot ' + (status.discord_connected ? 'dot-on' : 'dot-off');
  discordLine.appendChild(discordDot);
  discordLine.appendChild(document.createTextNode('Discord'));
  cardConn.appendChild(discordLine);

  const twitchLine = document.createElement('div');
  const twitchDot = document.createElement('span');
  twitchDot.className = 'dot ' + (status.twitch_connected ? 'dot-on' : 'dot-off');
  twitchLine.appendChild(twitchDot);
  twitchLine.appendChild(document.createTextNode('Twitch'));
  cardConn.appendChild(twitchLine);

  const uptimeLine = document.createElement('div');
  uptimeLine.className = 'card-sub';
  uptimeLine.style.marginTop = '10px';
  uptimeLine.textContent = 'Uptime : ' + formatUptime(status.uptime_seconds);
  cardConn.appendChild(uptimeLine);

  grid.appendChild(cardConn);

  // Card: Messages
  const cardMsg = document.createElement('div');
  cardMsg.className = 'card';
  const msgLabel = document.createElement('div');
  msgLabel.className = 'card-label';
  msgLabel.textContent = 'Messages traités';
  cardMsg.appendChild(msgLabel);
  const msgVal = document.createElement('div');
  msgVal.className = 'card-value';
  msgVal.textContent = (status.messages_processed || 0).toLocaleString('fr');
  cardMsg.appendChild(msgVal);
  const msgSub = document.createElement('div');
  msgSub.className = 'card-sub';
  msgSub.textContent = 'Discord : ' + (status.discord_messages || 0) + ' · Web : ' + (status.web_messages || 0);
  cardMsg.appendChild(msgSub);
  grid.appendChild(cardMsg);

  // Card: Humeur
  const cardEmo = document.createElement('div');
  cardEmo.className = 'card';
  cardEmo.style.gridColumn = 'span 2';
  const emoLabel = document.createElement('div');
  emoLabel.className = 'card-label';
  emoLabel.textContent = 'Humeur en direct';
  cardEmo.appendChild(emoLabel);

  const domEmo = document.createElement('div');
  domEmo.style.cssText = 'font-size:0.85rem;font-weight:600;margin-bottom:12px;';
  const domName = dominant(emotions);
  domEmo.style.color = EMO_COLORS[domName];
  domEmo.textContent = EMO_LABELS[domName];
  cardEmo.appendChild(domEmo);

  const bars = document.createElement('div');
  bars.className = 'emo-bars';
  bars.id = 'status-emo-bars';
  Object.entries(emotions).forEach(([name, value]) => {
    const { row } = buildEmoBar(name, value);
    bars.appendChild(row);
  });
  cardEmo.appendChild(bars);
  grid.appendChild(cardEmo);

  // Card: Stream
  if (stream) {
    const cardStream = document.createElement('div');
    cardStream.className = 'card';
    const streamLabel = document.createElement('div');
    streamLabel.className = 'card-label';
    streamLabel.textContent = 'Stream Azrael';
    cardStream.appendChild(streamLabel);

    if (stream.live) {
      const liveDot = document.createElement('div');
      liveDot.style.cssText = 'display:flex;align-items:center;gap:6px;margin-bottom:8px;';
      const dot = document.createElement('span');
      dot.className = 'dot dot-on';
      liveDot.appendChild(dot);
      const liveText = document.createElement('span');
      liveText.style.cssText = 'font-size:0.78rem;font-weight:600;color:#22c55e;';
      liveText.textContent = 'En direct';
      liveDot.appendChild(liveText);
      cardStream.appendChild(liveDot);

      const game = document.createElement('div');
      game.className = 'card-sub';
      game.textContent = stream.game || '';
      cardStream.appendChild(game);

      const title = document.createElement('div');
      title.style.cssText = 'font-size:0.78rem;color:rgba(255,255,255,0.5);margin-top:4px;';
      title.textContent = stream.title || '';
      cardStream.appendChild(title);

      const viewers = document.createElement('div');
      viewers.className = 'card-value';
      viewers.style.marginTop = '8px';
      viewers.textContent = (stream.viewer_count || 0).toLocaleString('fr');
      const viewersSub = document.createElement('span');
      viewersSub.style.cssText = 'font-size:0.7rem;font-weight:400;color:rgba(255,255,255,0.4);margin-left:6px;';
      viewersSub.textContent = 'spectateurs';
      viewers.appendChild(viewersSub);
      cardStream.appendChild(viewers);
    } else {
      const offline = document.createElement('div');
      offline.className = 'card-sub';
      offline.textContent = 'Hors ligne';
      cardStream.appendChild(offline);
    }
    grid.appendChild(cardStream);
  }

  el.appendChild(grid);
}

async function fetchAndRender() {
  if (!_container) return;
  const [statusRes, streamRes] = await Promise.all([
    fetch('/api/public/status').then(r => r.json()).catch(() => ({})),
    fetch('/api/public/twitch/stream').then(r => r.json()).catch(() => null),
  ]);
  renderStatus(_container, statusRes, streamRes);
}

export function mount(el) {
  _container = el;
  fetchAndRender();
  _pollInterval = setInterval(fetchAndRender, 30000);

  onEmotionUpdate((emo) => {
    const barsEl = document.getElementById('status-emo-bars');
    if (!barsEl) return;
    barsEl.textContent = '';
    Object.entries(emo).forEach(([name, value]) => {
      const { row } = buildEmoBar(name, value);
      barsEl.appendChild(row);
    });
  });
}

export function unmount() {
  clearInterval(_pollInterval);
  _pollInterval = null;
  _container = null;
}
```

- [ ] **Step 2: Naviguer vers `/#status`** et vérifier que les 4 cartes s'affichent.

- [ ] **Step 3: Commit**

```bash
git add public-ui/tabs/status.js
git commit -m "feat(public-ui): onglet Statut — connexions, messages, émotions, stream"
```

---

## Task 6: Onglet Chat

**Files:**
- Create: `public-ui/tabs/chat.js`

- [ ] **Step 1: Lire `bot/dashboard/static/overlay.html`** pour noter exactement la logique `getAvatarUrl` (dominant emotion > 0.2, tiers 0.4/0.7 → low/mid/high).

- [ ] **Step 2: Créer `public-ui/tabs/chat.js`**

```javascript
// public-ui/tabs/chat.js
import { emotions, onEmotionUpdate } from '../app.js';

let _ws = null;
let _container = null;

function getAvatarUrl(emo) {
  const order = ['anger','joy','curiosity','sadness','boredom'];
  let domEmo = 'curiosity', domVal = 0;
  for (const name of order) {
    if ((emo[name] || 0) > domVal) { domVal = emo[name]; domEmo = name; }
  }
  if (domVal < 0.2) domEmo = 'curiosity';
  const tier = domVal >= 0.7 ? 'high' : domVal >= 0.4 ? 'mid' : 'low';
  return `/static/avatar/emotions/${domEmo}/${tier}.gif`;
}

function getToken() {
  return localStorage.getItem('discord_jwt') || null;
}

function buildLoginGate() {
  const wrap = document.createElement('div');
  wrap.className = 'chat-login glass';
  wrap.style.padding = '40px';

  const img = document.createElement('img');
  img.className = 'chat-login-avatar';
  img.src = getAvatarUrl(emotions);
  img.alt = 'Wally';
  wrap.appendChild(img);

  const title = document.createElement('div');
  title.style.cssText = 'font-size:1.1rem;font-weight:700;';
  title.textContent = 'Parler à Wally';
  wrap.appendChild(title);

  const sub = document.createElement('div');
  sub.style.cssText = 'font-size:0.82rem;color:rgba(255,255,255,0.4);max-width:280px;';
  sub.textContent = 'Connecte-toi avec Discord pour accéder au chat.';
  wrap.appendChild(sub);

  const btn = document.createElement('a');
  btn.className = 'discord-btn';
  btn.href = '/auth/discord';

  const svgNS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(svgNS, 'svg');
  svg.setAttribute('width', '20');
  svg.setAttribute('height', '20');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'currentColor');
  const path = document.createElementNS(svgNS, 'path');
  path.setAttribute('d', 'M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.09 14.09 0 0 0 1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03z');
  svg.appendChild(path);
  btn.appendChild(svg);
  btn.appendChild(document.createTextNode('Continuer avec Discord'));
  wrap.appendChild(btn);

  return wrap;
}

function buildChatLayout(user) {
  const layout = document.createElement('div');
  layout.className = 'chat-layout';

  // ── Colonne Wally ──
  const wallyCol = document.createElement('div');
  wallyCol.className = 'chat-wally-col';

  const avatar = document.createElement('img');
  avatar.className = 'wally-avatar';
  avatar.src = getAvatarUrl(emotions);
  avatar.alt = 'Wally';
  avatar.id = 'chat-wally-avatar';
  wallyCol.appendChild(avatar);

  const emoLabel = document.createElement('div');
  emoLabel.className = 'wally-emotion-label';
  emoLabel.id = 'chat-wally-emo-label';
  const domEmo = Object.entries(emotions).sort((a,b) => b[1]-a[1])[0][0];
  const EMO_LABELS = { anger:'Colère', joy:'Joie', curiosity:'Curiosité', sadness:'Tristesse', boredom:'Ennui' };
  emoLabel.textContent = EMO_LABELS[domEmo] || domEmo;
  wallyCol.appendChild(emoLabel);

  const onlineLine = document.createElement('div');
  onlineLine.className = 'wally-online';
  const onlineDot = document.createElement('span');
  onlineDot.className = 'dot dot-on';
  onlineLine.appendChild(onlineDot);
  onlineLine.appendChild(document.createTextNode('En ligne'));
  wallyCol.appendChild(onlineLine);

  const miniBars = document.createElement('div');
  miniBars.className = 'emo-bars';
  miniBars.id = 'chat-emo-bars';
  miniBars.style.width = '100%';
  miniBars.style.marginTop = '8px';
  const EMO_COLORS = { anger:'#ef4444', joy:'#eab308', curiosity:'#22c55e', sadness:'#3b82f6', boredom:'#a855f7' };
  Object.entries(emotions).forEach(([name, val]) => {
    const row = document.createElement('div');
    row.className = 'emo-row';
    const lbl = document.createElement('span');
    lbl.className = 'emo-name';
    lbl.style.fontSize = '0.65rem';
    lbl.textContent = EMO_LABELS[name];
    row.appendChild(lbl);
    const track = document.createElement('div');
    track.className = 'emo-track';
    const fill = document.createElement('div');
    fill.className = 'emo-fill';
    fill.style.width = (val * 100).toFixed(1) + '%';
    fill.style.background = EMO_COLORS[name];
    track.appendChild(fill);
    row.appendChild(track);
    miniBars.appendChild(row);
  });
  wallyCol.appendChild(miniBars);

  layout.appendChild(wallyCol);

  // ── Colonne messages ──
  const msgCol = document.createElement('div');
  msgCol.className = 'chat-messages-col';

  const userBar = document.createElement('div');
  userBar.className = 'chat-user-bar';
  const userAvatar = document.createElement('img');
  userAvatar.className = 'chat-user-avatar';
  userAvatar.src = user.avatar_url || '/static/default_avatar.png';
  userAvatar.alt = user.username;
  userBar.appendChild(userAvatar);
  const userName = document.createElement('div');
  userName.className = 'chat-user-name';
  userName.textContent = user.username;
  userBar.appendChild(userName);
  const logoutBtn = document.createElement('button');
  logoutBtn.className = 'chat-logout';
  logoutBtn.textContent = 'Déconnexion';
  logoutBtn.addEventListener('click', () => {
    localStorage.removeItem('discord_jwt');
    mount(_container);
  });
  userBar.appendChild(logoutBtn);
  msgCol.appendChild(userBar);

  const msgList = document.createElement('div');
  msgList.className = 'messages-list';
  msgList.id = 'chat-messages';
  msgCol.appendChild(msgList);

  const inputRow = document.createElement('div');
  inputRow.className = 'chat-input-row';
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'chat-input';
  input.id = 'chat-input';
  input.placeholder = 'Écrire à Wally…';
  const sendBtn = document.createElement('button');
  sendBtn.className = 'chat-send';
  sendBtn.textContent = 'Envoyer';
  inputRow.appendChild(input);
  inputRow.appendChild(sendBtn);
  msgCol.appendChild(inputRow);
  layout.appendChild(msgCol);

  // ── Colonne mémoire ──
  const memCol = document.createElement('div');
  memCol.className = 'memory-col';
  memCol.id = 'chat-memory-col';
  const memLoading = document.createElement('div');
  memLoading.className = 'empty-state';
  memLoading.textContent = 'Chargement…';
  memCol.appendChild(memLoading);
  layout.appendChild(memCol);

  // ── WebSocket ──
  const token = getToken();
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  _ws = new WebSocket(`${proto}://${location.host}/ws/chat?token=${token}`);

  _ws.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      if (data.type === 'typing') {
        showTyping(msgList);
      } else if (data.type === 'message') {
        removeTyping(msgList);
        addBubble(msgList, data.content, 'bot');
      }
    } catch (_) {}
  };

  function sendMessage() {
    const text = input.value.trim();
    if (!text || _ws.readyState !== WebSocket.OPEN) return;
    addBubble(msgList, text, 'user');
    _ws.send(JSON.stringify({ type: 'message', content: text }));
    input.value = '';
  }

  sendBtn.addEventListener('click', sendMessage);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') sendMessage(); });

  // Load memory sidebar
  fetch('/api/public/memory/me', {
    headers: { 'Authorization': 'Bearer ' + token }
  })
    .then(r => r.ok ? r.json() : null)
    .then(data => renderMemorySidebar(memCol, data))
    .catch(() => renderMemorySidebar(memCol, null));

  return layout;
}

function addBubble(list, text, who) {
  const bubble = document.createElement('div');
  bubble.className = 'bubble bubble-' + who;
  bubble.textContent = text;
  list.appendChild(bubble);
  list.scrollTop = list.scrollHeight;
}

let _typingEl = null;
function showTyping(list) {
  if (_typingEl) return;
  _typingEl = document.createElement('div');
  _typingEl.className = 'bubble bubble-bot typing-indicator';
  for (let i = 0; i < 3; i++) {
    const dot = document.createElement('span');
    dot.className = 'typing-dot';
    _typingEl.appendChild(dot);
  }
  list.appendChild(_typingEl);
  list.scrollTop = list.scrollHeight;
}
function removeTyping(list) {
  if (_typingEl) { list.removeChild(_typingEl); _typingEl = null; }
}

function renderMemorySidebar(col, data) {
  col.textContent = '';

  if (!data) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = 'Mémoire indisponible';
    col.appendChild(empty);
    return;
  }

  const EMO_LABELS_FR = { anger:'Colère', joy:'Joie', curiosity:'Curiosité', sadness:'Tristesse', boredom:'Ennui' };

  // Relation
  const relTitle = document.createElement('div');
  relTitle.className = 'memory-section-title';
  relTitle.textContent = 'Relation';
  col.appendChild(relTitle);

  const trustRow = document.createElement('div');
  trustRow.className = 'relation-score';
  const tLabel = document.createElement('span');
  tLabel.className = 'score-label';
  tLabel.textContent = 'Confiance';
  const tVal = document.createElement('span');
  tVal.className = 'score-value';
  tVal.textContent = Math.round((data.relation?.trust || 0) * 100) + '%';
  trustRow.appendChild(tLabel);
  trustRow.appendChild(tVal);
  col.appendChild(trustRow);

  const loveRow = document.createElement('div');
  loveRow.className = 'relation-score';
  const lLabel = document.createElement('span');
  lLabel.className = 'score-label';
  lLabel.textContent = 'Affinité';
  const lVal = document.createElement('span');
  lVal.className = 'score-value';
  lVal.textContent = Math.round((data.relation?.love || 0) * 100) + '%';
  loveRow.appendChild(lLabel);
  loveRow.appendChild(lVal);
  col.appendChild(loveRow);

  // Facts
  if (data.facts && data.facts.length > 0) {
    const factsTitle = document.createElement('div');
    factsTitle.className = 'memory-section-title';
    factsTitle.textContent = 'Faits';
    col.appendChild(factsTitle);
    data.facts.slice(0, 8).forEach(text => {
      const item = document.createElement('div');
      item.className = 'memory-item';
      item.textContent = text;
      col.appendChild(item);
    });
  }

  // Prefs
  if (data.preferences && data.preferences.length > 0) {
    const prefsTitle = document.createElement('div');
    prefsTitle.className = 'memory-section-title';
    prefsTitle.textContent = 'Préférences';
    col.appendChild(prefsTitle);
    data.preferences.slice(0, 8).forEach(text => {
      const item = document.createElement('div');
      item.className = 'memory-item';
      item.textContent = text;
      col.appendChild(item);
    });
  }
}

export function mount(el) {
  _container = el;
  el.textContent = '';

  const token = getToken();
  if (!token) {
    el.appendChild(buildLoginGate());
    return;
  }

  // Decode JWT to get user info (basic, no verify — server validates)
  let user = { username: 'Utilisateur', avatar_url: '' };
  try {
    const payload = JSON.parse(atob(token.split('.')[1]));
    user.username = payload.username || payload.sub || 'Utilisateur';
    user.avatar_url = payload.avatar_url || '';
  } catch (_) {}

  el.appendChild(buildChatLayout(user));

  // Live avatar updates
  onEmotionUpdate((emo) => {
    const avatarEl = document.getElementById('chat-wally-avatar');
    if (avatarEl) avatarEl.src = getAvatarUrl(emo);

    const barsEl = document.getElementById('chat-emo-bars');
    if (barsEl) {
      const EMO_COLORS = { anger:'#ef4444', joy:'#eab308', curiosity:'#22c55e', sadness:'#3b82f6', boredom:'#a855f7' };
      const EMO_LABELS = { anger:'Colère', joy:'Joie', curiosity:'Curiosité', sadness:'Tristesse', boredom:'Ennui' };
      barsEl.textContent = '';
      Object.entries(emo).forEach(([name, val]) => {
        const row = document.createElement('div');
        row.className = 'emo-row';
        const lbl = document.createElement('span');
        lbl.className = 'emo-name';
        lbl.style.fontSize = '0.65rem';
        lbl.textContent = EMO_LABELS[name];
        row.appendChild(lbl);
        const track = document.createElement('div');
        track.className = 'emo-track';
        const fill = document.createElement('div');
        fill.className = 'emo-fill';
        fill.style.width = (val * 100).toFixed(1) + '%';
        fill.style.background = EMO_COLORS[name];
        track.appendChild(fill);
        row.appendChild(track);
        barsEl.appendChild(row);
      });
    }

    const emoLabelEl = document.getElementById('chat-wally-emo-label');
    if (emoLabelEl) {
      const EMO_LABELS = { anger:'Colère', joy:'Joie', curiosity:'Curiosité', sadness:'Tristesse', boredom:'Ennui' };
      const dom = Object.entries(emo).sort((a,b) => b[1]-a[1])[0][0];
      emoLabelEl.textContent = EMO_LABELS[dom] || dom;
    }
  });
}

export function unmount() {
  if (_ws) { _ws.close(); _ws = null; }
  _container = null;
}
```

- [ ] **Step 3: Naviguer vers `/#chat`** — la gate de login doit apparaître. Si un JWT est présent dans localStorage, le layout 3 colonnes doit s'afficher.

- [ ] **Step 4: Commit**

```bash
git add public-ui/tabs/chat.js
git commit -m "feat(public-ui): onglet Chat — login Discord, avatar GIF émotion, mémoire"
```

---

## Task 7: Onglet Galerie

**Files:**
- Create: `public-ui/tabs/gallery.js`

- [ ] **Step 1: Créer `public-ui/tabs/gallery.js`**

```javascript
// public-ui/tabs/gallery.js
import { openModal } from '../app.js';

let _container = null;
let _sort = 'date';
let _offset = 0;
const LIMIT = 24;

function buildGalleryItem(img, delay) {
  const item = document.createElement('div');
  item.className = 'gallery-item';
  item.style.animationDelay = (delay * 0.05) + 's';

  const imgEl = document.createElement('img');
  imgEl.src = img.url;
  imgEl.alt = img.prompt || '';
  imgEl.loading = 'lazy';
  item.appendChild(imgEl);

  const overlay = document.createElement('div');
  overlay.className = 'gallery-overlay';

  const prompt = document.createElement('div');
  prompt.className = 'gallery-prompt';
  prompt.textContent = img.prompt || '';
  overlay.appendChild(prompt);

  const votes = document.createElement('div');
  votes.className = 'gallery-votes';
  votes.textContent = (img.votes || 0) + ' votes';
  overlay.appendChild(votes);

  item.appendChild(overlay);

  item.addEventListener('click', () => openModal(img.url, img.prompt || ''));
  return item;
}

async function loadImages(grid, append) {
  const res = await fetch(`/api/public/gallery?limit=${LIMIT}&offset=${_offset}&sort=${_sort}`)
    .then(r => r.json())
    .catch(() => ({ images: [] }));

  const images = res.images || [];
  if (!append) { grid.textContent = ''; }

  images.forEach((img, i) => {
    grid.appendChild(buildGalleryItem(img, append ? i : _offset + i));
  });

  _offset += images.length;
  return images.length === LIMIT;
}

export function mount(el) {
  _container = el;
  _offset = 0;
  el.textContent = '';

  const wrap = document.createElement('div');

  // Filters
  const filters = document.createElement('div');
  filters.className = 'gallery-filters';

  const filterDefs = [
    { label: 'Récentes', value: 'date' },
    { label: 'Populaires', value: 'votes' },
  ];

  filterDefs.forEach(({ label, value }) => {
    const btn = document.createElement('button');
    btn.className = 'filter-btn' + (value === _sort ? ' active' : '');
    btn.textContent = label;
    btn.addEventListener('click', () => {
      _sort = value;
      _offset = 0;
      filters.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      loadImages(grid, false).then(hasMore => {
        loadMoreBtn.style.display = hasMore ? '' : 'none';
      });
    });
    filters.appendChild(btn);
  });
  wrap.appendChild(filters);

  // Grid
  const grid = document.createElement('div');
  grid.className = 'gallery-grid';
  wrap.appendChild(grid);

  // Load more
  const loadMoreBtn = document.createElement('button');
  loadMoreBtn.className = 'load-more';
  loadMoreBtn.textContent = 'Charger plus';
  loadMoreBtn.addEventListener('click', () => {
    loadImages(grid, true).then(hasMore => {
      loadMoreBtn.style.display = hasMore ? '' : 'none';
    });
  });
  wrap.appendChild(loadMoreBtn);

  loadImages(grid, false).then(hasMore => {
    loadMoreBtn.style.display = hasMore ? '' : 'none';
  });

  el.appendChild(wrap);
}

export function unmount() {
  _container = null;
}
```

- [ ] **Step 2: Naviguer vers `/#gallery`** et vérifier que la grille s'affiche.

- [ ] **Step 3: Commit**

```bash
git add public-ui/tabs/gallery.js
git commit -m "feat(public-ui): onglet Galerie — grille, filtres, lightbox modal"
```

---

## Task 8: Onglet Journal

**Files:**
- Create: `public-ui/tabs/journal.js`

- [ ] **Step 1: Créer `public-ui/tabs/journal.js`**

```javascript
// public-ui/tabs/journal.js

let _container = null;

const MONTH_SHORT = ['jan','fév','mar','avr','mai','jun','jul','aoû','sep','oct','nov','déc'];
const EMO_COLORS = { anger:'#ef4444', joy:'#eab308', curiosity:'#22c55e', sadness:'#3b82f6', boredom:'#a855f7' };

function formatDateShort(dateStr) {
  const d = new Date(dateStr + 'T00:00:00');
  return d.getDate() + ' ' + MONTH_SHORT[d.getMonth()];
}

function formatDateLong(dateStr) {
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('fr-FR', { weekday:'long', day:'numeric', month:'long', year:'numeric' });
}

function detectEmoBadges(content) {
  const badges = [];
  const patterns = [
    { key: 'anger',    color: EMO_COLORS.anger,    label: 'Colère' },
    { key: 'joy',      color: EMO_COLORS.joy,       label: 'Joie' },
    { key: 'curiosity',color: EMO_COLORS.curiosity, label: 'Curiosité' },
    { key: 'sadness',  color: EMO_COLORS.sadness,   label: 'Tristesse' },
    { key: 'boredom',  color: EMO_COLORS.boredom,   label: 'Ennui' },
  ];
  patterns.forEach(p => {
    const re = new RegExp(p.label, 'i');
    if (re.test(content)) badges.push(p);
  });
  return badges;
}

function renderEntryCard(entry) {
  const card = document.createElement('div');
  card.className = 'entry-card';

  const header = document.createElement('div');
  header.className = 'entry-header';

  const left = document.createElement('div');
  const dateEl = document.createElement('div');
  dateEl.className = 'entry-date-text';
  dateEl.textContent = formatDateLong(entry.date);
  left.appendChild(dateEl);
  const subEl = document.createElement('div');
  subEl.className = 'entry-sub-text';
  subEl.textContent = (entry.word_count || 0) + ' mots · généré à 23h00';
  left.appendChild(subEl);
  header.appendChild(left);

  const badges = document.createElement('div');
  badges.className = 'badges';
  const detectedBadges = detectEmoBadges(entry.content || '');
  detectedBadges.forEach(b => {
    const span = document.createElement('span');
    span.className = 'badge';
    span.textContent = b.label;
    span.style.color = b.color;
    span.style.borderColor = b.color.replace(')', ',0.3)').replace('rgb', 'rgba');
    span.style.background = b.color.replace(')', ',0.08)').replace('rgb', 'rgba');
    badges.appendChild(span);
  });
  header.appendChild(badges);
  card.appendChild(header);

  const body = document.createElement('div');
  body.className = 'entry-body';
  const paragraphs = (entry.content || '').split('\n\n').filter(Boolean);
  paragraphs.forEach(text => {
    const p = document.createElement('p');
    p.textContent = text;
    body.appendChild(p);
  });
  if (!paragraphs.length) {
    const p = document.createElement('p');
    p.textContent = entry.content || '';
    body.appendChild(p);
  }
  card.appendChild(body);
  return card;
}

export function mount(el) {
  _container = el;
  el.textContent = '';

  fetch('/api/public/journal?limit=30')
    .then(r => r.json())
    .then(data => {
      const entries = data.entries || [];
      if (!entries.length) {
        const empty = document.createElement('div');
        empty.className = 'empty-state glass';
        empty.style.padding = '40px';
        empty.textContent = 'Aucune entrée de journal pour l\'instant.';
        el.appendChild(empty);
        return;
      }

      const wrap = document.createElement('div');
      wrap.className = 'glass';
      wrap.style.padding = '20px';

      // Timeline scroll
      const tlScroll = document.createElement('div');
      tlScroll.className = 'tl-scroll';

      const tlRow = document.createElement('div');
      tlRow.className = 'tl-row';

      const entryArea = document.createElement('div');
      entryArea.className = 'entry-area';

      let activeItem = null;

      entries.forEach((entry, idx) => {
        const isLast = idx === 0; // entries are DESC — first = most recent
        const item = document.createElement('div');
        item.className = 'tl-item' + (isLast ? ' active' : '');

        const dot = document.createElement('div');
        dot.className = 'tl-dot';
        item.appendChild(dot);

        const dateEl = document.createElement('div');
        dateEl.className = 'tl-date';
        dateEl.textContent = formatDateShort(entry.date) + (isLast ? ' ✦' : '');
        item.appendChild(dateEl);

        item.addEventListener('click', () => {
          if (activeItem) activeItem.classList.remove('active');
          item.classList.add('active');
          activeItem = item;
          entryArea.textContent = '';
          entryArea.appendChild(renderEntryCard(entry));
        });

        tlRow.appendChild(item);

        if (isLast) {
          activeItem = item;
          entryArea.appendChild(renderEntryCard(entry));
        }
      });

      tlScroll.appendChild(tlRow);
      wrap.appendChild(tlScroll);
      wrap.appendChild(entryArea);
      el.appendChild(wrap);

      // Scroll timeline to end (most recent = last visually? entries are DESC so idx=0 is first in DOM)
      // We want to scroll to the rightmost item (which is the last appended, i.e. oldest)
      // Actually entries are DESC so idx=0 = most recent = first in DOM = leftmost — already visible
      // No scroll needed
    })
    .catch(() => {
      const err = document.createElement('div');
      err.className = 'empty-state';
      err.textContent = 'Impossible de charger le journal.';
      el.appendChild(err);
    });
}

export function unmount() {
  _container = null;
}
```

**Note :** Les entrées arrivent en ordre DESC (plus récent en premier). Le premier item (idx=0) correspond au jour le plus récent et est actif par défaut. Pour afficher les entrées chronologiquement de gauche (ancien) à droite (récent), inverser le tableau avant de render : remplacer `entries.forEach` par `[...entries].reverse().forEach` si l'ordre visuel chronologique est préféré, avec `const isLast = idx === entries.length - 1`.

Version avec ordre chronologique (ancien → récent, dernier actif à droite) :

```javascript
// Dans mount(), remplacer entries.forEach par :
const orderedEntries = [...entries].reverse(); // ancien → récent
orderedEntries.forEach((entry, idx) => {
  const isLast = idx === orderedEntries.length - 1;
  // ... même code ...
  dateEl.textContent = formatDateShort(entry.date) + (isLast ? ' ✦' : '');
  // ...
  if (isLast) {
    activeItem = item;
    entryArea.appendChild(renderEntryCard(entry));
  }
});

// Après avoir ajouté le wrap au DOM, scroll vers la droite :
setTimeout(() => { tlScroll.scrollLeft = tlScroll.scrollWidth; }, 50);
```

Utiliser cette version (ordre chronologique, scroll à droite) — plus naturelle.

- [ ] **Step 2: Naviguer vers `/#journal`** — la frise doit s'afficher avec le dernier point actif.

- [ ] **Step 3: Commit**

```bash
git add public-ui/tabs/journal.js
git commit -m "feat(public-ui): onglet Journal — frise chronologique + entrée en dessous"
```

---

## Task 9: Onglet À propos

**Files:**
- Create: `public-ui/tabs/about.js`

- [ ] **Step 1: Créer `public-ui/tabs/about.js`**

```javascript
// public-ui/tabs/about.js

const PIPELINE_STEPS = [
  {
    label: 'Message',
    color: '#06b6d4',
    detail: 'Un message arrive de Discord ou Twitch. Il est normalisé, tagué avec la plateforme, l\'auteur, et le canal source.'
  },
  {
    label: 'Mémoire',
    color: '#a855f7',
    detail: 'Wally consulte sa mémoire vectorielle (Qdrant) pour trouver des souvenirs pertinents sur l\'utilisateur : faits, préférences, historique. Les scores de relation (confiance, affinité) sont aussi injectés.'
  },
  {
    label: 'Émotions',
    color: '#ef4444',
    detail: 'L\'état émotionnel actuel (5 émotions : colère, joie, curiosité, tristesse, ennui) influence le ton de la réponse. Les émotions décroissent naturellement dans le temps et varient selon les interactions.'
  },
  {
    label: 'Personnalité',
    color: '#eab308',
    detail: 'Les blocs de personnalité SOUL, IDENTITY, VOICE et COMPOSITES sont assemblés en prompt système. Des directives comportementales adaptées à l\'émotion dominante sont injectées dynamiquement.'
  },
  {
    label: 'LLM',
    color: '#22c55e',
    detail: 'Le modèle de langage (Claude ou GPT) génère une réponse en tenant compte de tout le contexte : mémoire, émotions, personnalité, historique de conversation, et instructions cibles.'
  },
  {
    label: 'Réponse',
    color: '#3b82f6',
    detail: 'La réponse est envoyée via l\'adaptateur approprié (Discord ou Twitch). En parallèle, les faits importants sont extraits et sauvegardés en mémoire pour les prochaines interactions.'
  },
];

const PILLARS = [
  {
    title: 'Mémoire vectorielle',
    color: '#a855f7',
    desc: 'Wally se souvient de chaque utilisateur à long terme grâce à Qdrant. Faits, préférences, historique — tout est encodé en embeddings et retrouvé par similarité sémantique.'
  },
  {
    title: 'Émotions en direct',
    color: '#ef4444',
    desc: 'Cinq émotions coexistent et fluctuent en temps réel. Elles influencent le ton des réponses, déclenchent des comportements spéciaux, et sont visibles sur l\'overlay OBS.'
  },
  {
    title: 'Personnalité profonde',
    color: '#eab308',
    desc: 'Une personnalité construite sur des blocs : âme, identité, voix, exemples. Les combinaisons d\'émotions créent des états composites avec des comportements uniques.'
  },
  {
    title: 'Journal quotidien',
    color: '#22c55e',
    desc: 'Chaque soir, Wally rédige un journal intime résumant sa journée : interactions marquantes, état émotionnel, pensées. Une mémoire narrative qui enrichit sa cohérence.'
  },
];

export function mount(el) {
  el.textContent = '';

  const wrap = document.createElement('div');

  // ── Pipeline ──
  const pipeTitle = document.createElement('h3');
  pipeTitle.style.cssText = 'font-size:0.75rem;text-transform:uppercase;letter-spacing:0.08em;color:rgba(255,255,255,0.4);margin-bottom:16px;';
  pipeTitle.textContent = 'Pipeline de traitement';
  wrap.appendChild(pipeTitle);

  const pipelineEl = document.createElement('div');
  pipelineEl.className = 'pipeline';

  const detailEl = document.createElement('div');
  detailEl.className = 'pipe-detail';

  let activeStep = null;

  PIPELINE_STEPS.forEach((step, i) => {
    const stepWrap = document.createElement('div');
    stepWrap.className = 'pipe-step';

    const node = document.createElement('div');
    node.className = 'pipe-node';
    node.textContent = step.label;
    node.style.borderColor = step.color + '66';
    node.style.color = step.color;
    node.style.background = step.color + '11';

    node.addEventListener('click', () => {
      if (activeStep) {
        activeStep.style.background = activeStep._origBg;
        activeStep.style.boxShadow = '';
      }
      node._origBg = step.color + '11';
      node.style.background = step.color + '22';
      node.style.boxShadow = '0 0 12px ' + step.color + '44';
      activeStep = node;
      detailEl.textContent = '';
      detailEl.style.borderColor = step.color + '44';
      detailEl.appendChild(document.createTextNode(step.detail));
      detailEl.style.animation = 'none';
      detailEl.offsetHeight;
      detailEl.style.animation = '';
    });

    stepWrap.appendChild(node);

    if (i < PIPELINE_STEPS.length - 1) {
      const arrow = document.createElement('span');
      arrow.className = 'pipe-arrow';
      arrow.textContent = '→';
      stepWrap.appendChild(arrow);
    }

    pipelineEl.appendChild(stepWrap);

    if (i === 0) {
      node.click(); // Activate first step by default
    }
  });

  wrap.appendChild(pipelineEl);
  wrap.appendChild(detailEl);

  // ── Pillars ──
  const pillarsTitle = document.createElement('h3');
  pillarsTitle.style.cssText = 'font-size:0.75rem;text-transform:uppercase;letter-spacing:0.08em;color:rgba(255,255,255,0.4);margin-bottom:16px;';
  pillarsTitle.textContent = 'Les piliers de Wally';
  wrap.appendChild(pillarsTitle);

  const pillarsGrid = document.createElement('div');
  pillarsGrid.className = 'pillars-grid';

  PILLARS.forEach((pillar, i) => {
    const card = document.createElement('div');
    card.className = 'pillar-card';
    card.style.animationDelay = (i * 0.08) + 's';

    const titleEl = document.createElement('div');
    titleEl.className = 'pillar-title';
    titleEl.style.color = pillar.color;
    titleEl.textContent = pillar.title;
    card.appendChild(titleEl);

    const descEl = document.createElement('div');
    descEl.className = 'pillar-desc';
    descEl.textContent = pillar.desc;
    card.appendChild(descEl);

    pillarsGrid.appendChild(card);
  });

  wrap.appendChild(pillarsGrid);
  el.appendChild(wrap);
}

export function unmount() {}
```

- [ ] **Step 2: Naviguer vers `/#about`** — pipeline cliquable et grille des piliers doivent s'afficher.

- [ ] **Step 3: Commit**

```bash
git add public-ui/tabs/about.js
git commit -m "feat(public-ui): onglet À propos — pipeline interactif + piliers"
```

---

## Task 10: Vérification finale

**Files:** tous les fichiers modifiés

- [ ] **Step 1: Vérifier que tous les onglets fonctionnent**

```bash
# Ouvrir le navigateur sur http://localhost:<PORT>/
# Naviguer sur chaque onglet : /#status, /#chat, /#gallery, /#journal, /#about
# Vérifier :
# - Status : 4 cartes visibles, barres émotions animées
# - Chat : login gate si pas de JWT, layout 3 colonnes si authentifié
# - Gallery : grille d'images ou empty state
# - Journal : frise avec dernier point actif, entrée affichée en dessous
# - About : pipeline cliquable avec détail, 4 cartes piliers
```

- [ ] **Step 2: Vérifier les nouveaux endpoints backend**

```bash
curl http://localhost:<PORT>/api/public/journal?limit=5
# → {"entries": [...]}

curl -H "Authorization: Bearer <jwt>" http://localhost:<PORT>/api/public/memory/me
# → {"facts": [...], "preferences": [...], "relation": {"trust": ..., "love": ...}}
```

- [ ] **Step 3: Lancer les tests backend**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/dashboard/test_public_journal.py tests/dashboard/test_public_memory_me.py -v
```
Expected: PASS (4 tests).

- [ ] **Step 4: Commit final (si changements restants)**

```bash
git add -p
git commit -m "feat(public-ui): refonte multi-onglets SPA complète"
```
