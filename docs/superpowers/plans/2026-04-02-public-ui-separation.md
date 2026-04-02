# Public UI Separation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Séparer le dashboard public (HTML/CSS/JS custom par utilisateur via volume Docker) du panel admin (embarqué dans l'image, toujours à jour).

**Architecture:** Le panel admin déménage de `/` vers `/admin`. La route `/` devient une `SPAStaticFiles` servant `public-ui/` (volume Docker monté). Au premier démarrage, `_maybe_seed_public_ui()` copie le starter kit dans `public-ui/` si vide. Toutes les mises à jour bot préservent `public-ui/`.

**Tech Stack:** FastAPI StaticFiles custom (SPA fallback), Python shutil, pytest + httpx, HTML/CSS/JS vanilla.

---

## Fichiers concernés

| Fichier | Action |
|---|---|
| `bot/dashboard/app.py` | Modifier routing + ajouter SPAStaticFiles + `_maybe_seed_public_ui()` |
| `bot/dashboard/static/public-starter/index.html` | Créer — starter HTML |
| `bot/dashboard/static/public-starter/style.css` | Créer — starter CSS |
| `bot/dashboard/static/public-starter/app.js` | Créer — starter JS |
| `docker-compose.yml` | Ajouter volume `./public-ui:/app/public-ui` |
| `.gitignore` | Ajouter `public-ui/` |
| `PUBLIC_API.md` | Créer — contrat API public documenté |
| `tests/test_dashboard_public_ui.py` | Créer — tests routing + seed |

---

## Task 1 : Infrastructure Docker + gitignore

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.gitignore`

- [ ] **Step 1 : Ajouter le volume public-ui dans docker-compose.yml**

Dans le service `wally`, sous `volumes:`, ajouter après `./config.yaml:/app/config.yaml` :
```yaml
      - ./public-ui:/app/public-ui
```

Le bloc `volumes:` du service wally doit ressembler à :
```yaml
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./config.yaml:/app/config.yaml
      - ./public-ui:/app/public-ui
      - ./.env:/app/.env
      - ./ROADMAP.md:/app/ROADMAP.md:ro
      - ./bot/dashboard/static:/app/bot/dashboard/static:ro
      - /var/run/docker.sock:/var/run/docker.sock
      - /opt/stacks/wally-instances:/opt/stacks/wally-instances
      - /usr/bin/docker:/usr/bin/docker:ro
      - /usr/libexec/docker/cli-plugins/docker-compose:/usr/libexec/docker/cli-plugins/docker-compose:ro
```

- [ ] **Step 2 : Ajouter public-ui/ dans .gitignore**

Ajouter à la fin de `.gitignore` :
```
# Public UI custom (volume Docker, propriété de l'utilisateur)
public-ui/
```

- [ ] **Step 3 : Commit**

```bash
git add docker-compose.yml .gitignore
git commit -m "chore: volume public-ui + gitignore"
```

---

## Task 2 : Tests pour le nouveau routing (TDD — écrire avant l'implémentation)

**Files:**
- Create: `tests/test_dashboard_public_ui.py`

- [ ] **Step 1 : Créer le fichier de tests**

```python
# tests/test_dashboard_public_ui.py
"""Tests pour la séparation Public UI / Admin."""
import time
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock
import pytest
from httpx import AsyncClient, ASGITransport

from bot.dashboard.app import create_dashboard_app, _maybe_seed_public_ui
from bot.dashboard.state import AppState


def _make_state() -> AppState:
    emotion = MagicMock()
    emotion.get_state.return_value = {
        "anger": 0.0, "joy": 0.5, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.1
    }
    db = MagicMock()
    db.get_emotion_snapshots_since = AsyncMock(return_value=[])
    db.insert_emotion_snapshot = AsyncMock()
    db.create_setup_invite = AsyncMock()
    cfg = MagicMock()
    cfg.bot.dashboard_token = "testtoken"
    cfg.bot.cost_alert_threshold = 0
    return AppState(
        config=cfg, db=db, emotion=emotion,
        memory=MagicMock(), persona=MagicMock(),
        primary_llm=MagicMock(), secondary_llm=MagicMock(),
        image_client=MagicMock(), token_manager=MagicMock(),
        twitch_api=None, discord_bot=None, twitch_bot=None,
        start_time=time.time() - 100, message_count=0,
    )


# ── _maybe_seed_public_ui ──────────────────────────────────────────────────────

def test_seed_copies_files_when_target_empty(tmp_path):
    """Copie les fichiers starter si public-ui/ est vide."""
    starter = tmp_path / "starter"
    starter.mkdir()
    (starter / "index.html").write_text("<html>starter</html>")
    (starter / "style.css").write_text("body{}")
    target = tmp_path / "public-ui"
    target.mkdir()

    _maybe_seed_public_ui(starter_dir=starter, public_ui_dir=target)

    assert (target / "index.html").read_text() == "<html>starter</html>"
    assert (target / "style.css").read_text() == "body{}"


def test_seed_does_not_overwrite_existing(tmp_path):
    """Ne touche pas public-ui/ si des fichiers existent déjà."""
    starter = tmp_path / "starter"
    starter.mkdir()
    (starter / "index.html").write_text("<html>starter</html>")
    target = tmp_path / "public-ui"
    target.mkdir()
    (target / "index.html").write_text("<html>custom</html>")

    _maybe_seed_public_ui(starter_dir=starter, public_ui_dir=target)

    assert (target / "index.html").read_text() == "<html>custom</html>"


def test_seed_creates_target_if_missing(tmp_path):
    """Crée public-ui/ s'il n'existe pas du tout."""
    starter = tmp_path / "starter"
    starter.mkdir()
    (starter / "index.html").write_text("<html>starter</html>")
    target = tmp_path / "public-ui"  # n'existe pas

    _maybe_seed_public_ui(starter_dir=starter, public_ui_dir=target)

    assert (target / "index.html").exists()


def test_seed_noop_when_starter_missing(tmp_path):
    """Ne plante pas si le répertoire starter n'existe pas."""
    starter = tmp_path / "starter-missing"
    target = tmp_path / "public-ui"
    target.mkdir()

    _maybe_seed_public_ui(starter_dir=starter, public_ui_dir=target)

    assert not list(target.iterdir())


# ── Routing ────────────────────────────────────────────────────────────────────

@pytest.fixture
def app_with_public_ui(tmp_path, monkeypatch):
    """App avec un public-ui/ temporaire contenant un index.html minimal."""
    public_ui = tmp_path / "public-ui"
    public_ui.mkdir()
    (public_ui / "index.html").write_text("<html><body>public</body></html>")
    (public_ui / "style.css").write_text("body{color:red}")
    monkeypatch.setattr("bot.dashboard.app.PUBLIC_UI_DIR", public_ui)
    return create_dashboard_app(_make_state())


@pytest.fixture
async def client(app_with_public_ui):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_public_ui), base_url="http://test"
    ) as c:
        yield c


async def test_admin_route_returns_html(client):
    """/admin sert le panel admin (index.html embarqué)."""
    r = await client.get("/admin")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


async def test_root_returns_public_ui(client):
    """/ sert public-ui/index.html."""
    r = await client.get("/")
    assert r.status_code == 200
    assert b"public" in r.content


async def test_spa_deep_link_returns_public_ui(client):
    """/une-page retourne public-ui/index.html (SPA fallback)."""
    r = await client.get("/une-page")
    assert r.status_code == 200
    assert b"public" in r.content


async def test_static_asset_served(client):
    """/style.css retourne le fichier CSS de public-ui."""
    r = await client.get("/style.css")
    assert r.status_code == 200
    assert b"color:red" in r.content


async def test_api_not_intercepted_by_spa(client):
    """/api/public/status n'est pas intercepté par le SPA fallback."""
    r = await client.get("/api/public/status")
    assert r.status_code == 200
    assert "uptime_seconds" in r.json()
```

- [ ] **Step 2 : Vérifier que les tests échouent (pas encore implémenté)**

```bash
cd /opt/stacks/wally-ai
python -m pytest tests/test_dashboard_public_ui.py -v 2>&1 | head -30
```

Résultat attendu : `ImportError` ou `FAILED` sur `_maybe_seed_public_ui` et `PUBLIC_UI_DIR`.

---

## Task 3 : Modifier app.py — SPAStaticFiles + routing + seed

**Files:**
- Modify: `bot/dashboard/app.py`

- [ ] **Step 1 : Ajouter import shutil en haut du fichier**

Après `import asyncio`, ajouter :
```python
import shutil
```

- [ ] **Step 2 : Ajouter les constantes PUBLIC_UI_DIR et STARTER_DIR**

Après la ligne `STATIC_DIR = Path(__file__).parent / "static"`, ajouter :
```python
PUBLIC_UI_DIR = Path("public-ui")
STARTER_DIR = STATIC_DIR / "public-starter"
```

- [ ] **Step 3 : Ajouter la classe SPAStaticFiles après NoCacheStaticFiles**

```python
class SPAStaticFiles(StaticFiles):
    """StaticFiles avec fallback vers index.html pour les routes SPA inconnues."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            return response
        except Exception as exc:
            if getattr(exc, "status_code", None) == 404:
                return await super().get_response("index.html", scope)
            raise
```

- [ ] **Step 4 : Ajouter la fonction _maybe_seed_public_ui après SPAStaticFiles**

```python
def _maybe_seed_public_ui(
    starter_dir: Path = STARTER_DIR,
    public_ui_dir: Path = PUBLIC_UI_DIR,
) -> None:
    """Copie le starter kit dans public-ui/ si le dossier est vide ou absent."""
    if not starter_dir.exists():
        return
    if public_ui_dir.exists() and any(public_ui_dir.iterdir()):
        return  # déjà peuplé — ne pas écraser
    public_ui_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(str(starter_dir), str(public_ui_dir), dirs_exist_ok=True)
    logger.info("Public UI seeded from starter kit into {}", public_ui_dir)
```

- [ ] **Step 5 : Appeler _maybe_seed_public_ui dans le lifespan**

Dans la fonction `lifespan`, après le bloc `try` du snapshot initial, ajouter :
```python
        # Seed public-ui/ depuis le starter kit si vide
        try:
            _maybe_seed_public_ui()
        except Exception as exc:
            logger.warning("Failed to seed public-ui: {e}", e=exc)
```

- [ ] **Step 6 : Remplacer la route GET / par GET /admin**

Remplacer :
```python
    @app.get("/")
    async def root():
        html = (STATIC_DIR / "index.html").read_text()
        html = html.replace("style.css?v=6", f"style.css?v={_asset_version}")
        html = html.replace("app.js?v=6", f"app.js?v={_asset_version}")
        html = html.replace("theme.css?v=6", f"theme.css?v={_asset_version}")
        return HTMLResponse(
            html,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "CDN-Cache-Control": "no-store",
                "Cloudflare-CDN-Cache-Control": "no-store",
            },
        )
```

Par :
```python
    @app.get("/admin")
    async def admin_panel():
        html = (STATIC_DIR / "index.html").read_text()
        html = html.replace("style.css?v=6", f"style.css?v={_asset_version}")
        html = html.replace("app.js?v=6", f"app.js?v={_asset_version}")
        html = html.replace("theme.css?v=6", f"theme.css?v={_asset_version}")
        return HTMLResponse(
            html,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "CDN-Cache-Control": "no-store",
                "Cloudflare-CDN-Cache-Control": "no-store",
            },
        )
```

- [ ] **Step 7 : Ajouter le mount SPAStaticFiles AVANT le return app (en dernier)**

Juste avant `return app`, ajouter :
```python
    # Public UI — SPAStaticFiles en dernier (catch-all SPA)
    # Enregistré après tous les routers API pour ne pas intercepter /api/*, /admin, etc.
    if PUBLIC_UI_DIR.exists():
        app.mount(
            "/",
            SPAStaticFiles(directory=str(PUBLIC_UI_DIR), html=True),
            name="public-ui",
        )
```

- [ ] **Step 8 : Lancer les tests unitaires**

```bash
cd /opt/stacks/wally-ai
python -m pytest tests/test_dashboard_public_ui.py -v
```

Résultat attendu : 9 tests PASSED.

- [ ] **Step 9 : Suite complète — vérifier aucune régression**

```bash
python -m pytest tests/ -x -q 2>&1 | tail -5
```

Résultat attendu : 0 erreurs supplémentaires, même compte de tests passants.

- [ ] **Step 10 : Commit**

```bash
git add bot/dashboard/app.py tests/test_dashboard_public_ui.py
git commit -m "feat(dashboard): SPAStaticFiles public-ui + /admin route + seed démarrage"
```

---

## Task 4 : Starter kit — index.html

**Files:**
- Create: `bot/dashboard/static/public-starter/index.html`

- [ ] **Step 1 : Créer le répertoire**

```bash
mkdir -p /opt/stacks/wally-ai/bot/dashboard/static/public-starter
```

- [ ] **Step 2 : Créer index.html**

Créer `bot/dashboard/static/public-starter/index.html` :
```html
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Wally</title>
  <link rel="stylesheet" href="/style.css">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><circle cx='16' cy='16' r='14' fill='%23888' stroke='white' stroke-width='2'/></svg>">
</head>
<body>
  <div class="app">

    <header class="header">
      <div class="header-logo">W</div>
      <div class="header-info">
        <h1 class="header-title">Wally</h1>
        <span class="header-status" id="header-status">Connexion...</span>
      </div>
    </header>

    <main class="main">

      <div class="grid-2">
        <div class="card">
          <div class="card-label">STATUT</div>
          <div class="stat-row">
            <span class="dot offline" id="dot-discord"></span>
            <span id="lbl-discord">Discord</span>
          </div>
          <div class="stat-row">
            <span class="dot offline" id="dot-twitch"></span>
            <span id="lbl-twitch">Twitch</span>
          </div>
          <div class="uptime" id="uptime">—</div>
        </div>

        <div class="card" id="stream-card">
          <div class="card-label">STREAM</div>
          <div id="stream-content"></div>
        </div>
      </div>

      <div class="card">
        <div class="card-label">HUMEUR EN DIRECT</div>
        <div id="emotions-container" class="emotions-grid"></div>
        <div class="emotion-state" id="emotion-state" style="display:none"></div>
      </div>

      <div class="card" id="gallery-card" style="display:none">
        <div class="card-label">GALERIE</div>
        <div id="gallery-grid" class="gallery-grid"></div>
      </div>

    </main>

    <div class="modal-bg" id="modal-bg">
      <div class="modal-img-wrap" id="modal-wrap">
        <img id="modal-img" src="" alt="">
        <p id="modal-caption"></p>
        <button class="modal-close" id="modal-close">fermer</button>
      </div>
    </div>

  </div>
  <script src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 3 : Vérifier**

```bash
python3 -c "from pathlib import Path; p=Path('bot/dashboard/static/public-starter/index.html'); print(p.stat().st_size, 'bytes OK')"
```

---

## Task 5 : Starter kit — style.css

**Files:**
- Create: `bot/dashboard/static/public-starter/style.css`

- [ ] **Step 1 : Créer style.css**

Créer `bot/dashboard/static/public-starter/style.css` :
```css
/* ── Variables — personnalise ici ─────────────────────────────────────────── */
:root {
  --accent:        #06b6d4;
  --bg-body:       #0a0a0f;
  --bg-card:       rgba(255,255,255,0.04);
  --border:        rgba(255,255,255,0.08);
  --text:          rgba(255,255,255,0.87);
  --text-dim:      rgba(255,255,255,0.45);
  --text-muted:    rgba(255,255,255,0.25);
  --radius:        14px;
  --font:          'Inter', system-ui, sans-serif;
  --anger:         #ef4444;
  --joy:           #eab308;
  --curiosity:     #22c55e;
  --sadness:       #3b82f6;
  --boredom:       #a855f7;
}

/* ── Reset ────────────────────────────────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: var(--font);
  background: var(--bg-body);
  color: var(--text);
  min-height: 100dvh;
  line-height: 1.5;
}

/* ── Layout ───────────────────────────────────────────────────────────────── */
.app  { max-width: 960px; margin: 0 auto; padding: 16px; }
.main { display: flex; flex-direction: column; gap: 16px; margin-top: 16px; }

.grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
@media (max-width: 600px) { .grid-2 { grid-template-columns: 1fr; } }

/* ── Header ───────────────────────────────────────────────────────────────── */
.header {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 20px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  backdrop-filter: blur(10px);
}
.header-logo {
  width: 42px; height: 42px;
  border-radius: 50%;
  background: var(--accent);
  color: #000;
  font-weight: 800;
  font-size: 1.3rem;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.header-title  { font-size: 1.25rem; font-weight: 700; }
.header-status { font-size: 0.8rem; color: var(--text-dim); }

/* ── Cards ────────────────────────────────────────────────────────────────── */
.card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
  backdrop-filter: blur(10px);
}
.card-label {
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--text-dim);
  margin-bottom: 14px;
}

/* ── Status dots ──────────────────────────────────────────────────────────── */
.stat-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; font-size: 0.95rem; }
.dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.dot.online  { background: #22c55e; box-shadow: 0 0 6px #22c55e; }
.dot.offline { background: #6b7280; }
.uptime {
  margin-top: 12px;
  font-size: 1.6rem; font-weight: 700;
  color: var(--accent);
  text-shadow: 0 0 12px rgba(6,182,212,0.5);
}

/* ── Stream ───────────────────────────────────────────────────────────────── */
.stream-game    { color: var(--accent); font-weight: 600; margin-bottom: 4px; font-size: 0.9rem; }
.stream-title   { color: var(--text); margin-bottom: 8px; font-size: 0.9rem; }
.stream-viewers { font-size: 0.8rem; color: var(--text-dim); }
.stream-offline { color: var(--text-muted); font-size: 0.9rem; }

/* ── Émotions ─────────────────────────────────────────────────────────────── */
.emotions-grid { display: flex; flex-direction: column; gap: 10px; }
.emotion-row   { display: flex; align-items: center; gap: 10px; }
.emotion-name  {
  font-size: 0.78rem; color: var(--text-dim);
  width: 72px; flex-shrink: 0; text-transform: capitalize;
}
.emotion-bar-bg {
  flex: 1; height: 6px;
  background: rgba(255,255,255,0.07);
  border-radius: 3px; overflow: hidden;
}
.emotion-bar-fill {
  height: 100%; border-radius: 3px;
  transition: width 0.6s ease;
}
.emotion-pct   { font-size: 0.75rem; color: var(--text-dim); width: 34px; text-align: right; flex-shrink: 0; }
.emotion-state { margin-top: 12px; font-size: 0.85rem; color: var(--text-dim); font-style: italic; }

/* ── Galerie ──────────────────────────────────────────────────────────────── */
.gallery-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 8px;
}
.gallery-thumb {
  aspect-ratio: 1;
  border-radius: 8px; overflow: hidden;
  cursor: pointer;
  background: rgba(255,255,255,0.05);
}
.gallery-thumb img { width: 100%; height: 100%; object-fit: cover; transition: transform 0.2s; }
.gallery-thumb:hover img { transform: scale(1.05); }

/* ── Modal ────────────────────────────────────────────────────────────────── */
.modal-bg {
  display: none;
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.85);
  z-index: 100;
  align-items: center; justify-content: center;
}
.modal-bg.open { display: flex; }
.modal-img-wrap { position: relative; max-width: 90vw; max-height: 90vh; text-align: center; }
.modal-img-wrap img { max-width: 100%; max-height: 80vh; border-radius: 8px; }
.modal-img-wrap p   { color: var(--text-dim); font-size: 0.85rem; margin-top: 8px; }
.modal-close {
  position: absolute; top: -12px; right: -12px;
  background: rgba(255,255,255,0.1); border: none;
  color: white; border-radius: 50%;
  width: 28px; height: 28px;
  cursor: pointer; font-size: 0.75rem;
}
```

- [ ] **Step 2 : Vérifier**

```bash
python3 -c "from pathlib import Path; p=Path('bot/dashboard/static/public-starter/style.css'); print(p.stat().st_size, 'bytes OK')"
```

---

## Task 6 : Starter kit — app.js

**Files:**
- Create: `bot/dashboard/static/public-starter/app.js`

- [ ] **Step 1 : Créer app.js**

Créer `bot/dashboard/static/public-starter/app.js` :
```javascript
// app.js — Wally Public UI Starter
// Appelle uniquement /api/public/* (aucune authentification requise)

var EMOTION_COLORS = {
  anger:    'var(--anger)',
  joy:      'var(--joy)',
  curiosity:'var(--curiosity)',
  sadness:  'var(--sadness)',
  boredom:  'var(--boredom)',
};
var EMOTION_LABELS = {
  anger:'Colère', joy:'Joie', curiosity:'Curiosité', sadness:'Tristesse', boredom:'Ennui',
};

// ── Utilitaires DOM (sans innerHTML sur données externes) ─────────────────────

function setText(id, val) {
  var el = document.getElementById(id);
  if (el) el.textContent = val;
}

function setClass(id, cls) {
  var el = document.getElementById(id);
  if (el) el.className = cls;
}

function el(tag, cls, text) {
  var e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

// ── Status ────────────────────────────────────────────────────────────────────

async function loadStatus() {
  try {
    var r = await fetch('/api/public/status');
    if (!r.ok) return;
    var d = await r.json();

    var online = d.discord_connected || d.twitch_connected;
    setClass('dot-discord', 'dot ' + (d.discord_connected ? 'online' : 'offline'));
    setClass('dot-twitch',  'dot ' + (d.twitch_connected  ? 'online' : 'offline'));
    setText('lbl-discord',
      d.discord_connected ? ('Discord' + (d.discord_guild ? ' — ' + d.discord_guild : '')) : 'Discord (hors ligne)');
    setText('lbl-twitch', d.twitch_connected ? 'Twitch' : 'Twitch (hors ligne)');

    if (d.uptime_seconds != null) setText('uptime', formatUptime(d.uptime_seconds));

    var hs = document.getElementById('header-status');
    if (hs) {
      hs.textContent = online ? 'En ligne' : 'Hors ligne';
      hs.style.color  = online ? 'var(--curiosity)' : 'var(--text-muted)';
    }
  } catch (_) {}
}

function formatUptime(s) {
  var h = Math.floor(s / 3600);
  var m = Math.floor((s % 3600) / 60);
  if (h > 0) return h + 'h ' + m + 'm';
  return m + 'm';
}

// ── Stream Twitch ─────────────────────────────────────────────────────────────

async function loadStream() {
  try {
    var r = await fetch('/api/public/twitch/stream');
    if (!r.ok) return;
    var d = await r.json();
    var container = document.getElementById('stream-content');
    if (!container) return;

    container.textContent = '';
    if (d.stream_live) {
      var game    = el('div', 'stream-game',    d.game_name  || '');
      var title   = el('div', 'stream-title',   d.title      || '');
      var viewers = el('div', 'stream-viewers', (d.viewer_count || 0) + ' spectateurs');
      container.appendChild(game);
      container.appendChild(title);
      container.appendChild(viewers);
    } else {
      container.appendChild(el('span', 'stream-offline', 'Hors ligne'));
    }
  } catch (_) {}
}

// ── Émotions (SSE + fallback polling) ─────────────────────────────────────────

function initEmotions() {
  var container = document.getElementById('emotions-container');
  if (!container) return;

  Object.keys(EMOTION_COLORS).forEach(function(name) {
    var row     = el('div', 'emotion-row');
    var label   = el('span', 'emotion-name', EMOTION_LABELS[name]);
    var barBg   = el('div', 'emotion-bar-bg');
    var fill    = el('div', 'emotion-bar-fill');
    var pctSpan = el('span', 'emotion-pct', '0%');

    fill.id      = 'bar-' + name;
    pctSpan.id   = 'pct-' + name;
    fill.style.width      = '0%';
    fill.style.background = EMOTION_COLORS[name];

    barBg.appendChild(fill);
    row.appendChild(label);
    row.appendChild(barBg);
    row.appendChild(pctSpan);
    container.appendChild(row);
  });

  var sse = new EventSource('/api/public/sse/emotions');
  sse.addEventListener('emotion_update', function(e) {
    try { updateBars(JSON.parse(e.data)); } catch (_) {}
  });
  sse.onerror = function() {
    sse.close();
    setTimeout(pollEmotions, 5000);
  };
}

async function pollEmotions() {
  try {
    var r = await fetch('/api/public/emotions/history');
    if (r.ok) {
      var data = await r.json();
      if (data.length) updateBars(data[data.length - 1]);
    }
  } catch (_) {}
  setTimeout(pollEmotions, 10000);
}

function updateBars(state) {
  Object.keys(EMOTION_COLORS).forEach(function(name) {
    var val  = state[name] || 0;
    var pct  = Math.round(val * 100);
    var fill = document.getElementById('bar-' + name);
    var span = document.getElementById('pct-' + name);
    if (fill) fill.style.width = pct + '%';
    if (span) span.textContent = pct + '%';
  });

  var dominant = Object.keys(EMOTION_COLORS).reduce(function(a, b) {
    return (state[a] || 0) >= (state[b] || 0) ? a : b;
  });
  var stateEl = document.getElementById('emotion-state');
  if (stateEl) {
    if ((state[dominant] || 0) > 0.3) {
      stateEl.style.display = 'block';
      stateEl.textContent   = 'Émotion dominante : ' + EMOTION_LABELS[dominant];
    } else {
      stateEl.style.display = 'none';
    }
  }
}

// ── Galerie ───────────────────────────────────────────────────────────────────

async function loadGallery() {
  try {
    var r = await fetch('/api/public/gallery?limit=6&sort=date');
    if (!r.ok) return;
    var data   = await r.json();
    var images = data.images || data;
    if (!images || !images.length) return;

    var card = document.getElementById('gallery-card');
    var grid = document.getElementById('gallery-grid');
    if (!card || !grid) return;

    card.style.display = 'block';
    grid.textContent   = '';

    images.slice(0, 6).forEach(function(img) {
      var thumb = el('div', 'gallery-thumb');
      var image = document.createElement('img');
      image.src     = '/api/public/gallery/' + img.id + '/image';
      image.alt     = img.prompt || '';
      image.loading = 'lazy';
      image.addEventListener('click', (function(src, caption) {
        return function() { openModal(src, caption); };
      })(image.src, img.prompt || ''));
      thumb.appendChild(image);
      grid.appendChild(thumb);
    });
  } catch (_) {}
}

function openModal(src, caption) {
  var bg  = document.getElementById('modal-bg');
  var img = document.getElementById('modal-img');
  var cap = document.getElementById('modal-caption');
  if (!bg || !img) return;
  img.src = src;
  if (cap) cap.textContent = caption;
  bg.classList.add('open');
}

function closeModal() {
  var bg = document.getElementById('modal-bg');
  if (bg) bg.classList.remove('open');
}

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', function() {
  loadStatus();
  initEmotions();
  loadStream();
  loadGallery();

  // Fermer modal au clic fond
  var bg = document.getElementById('modal-bg');
  var wrap = document.getElementById('modal-wrap');
  var closeBtn = document.getElementById('modal-close');
  if (closeBtn) closeBtn.addEventListener('click', closeModal);
  if (bg) bg.addEventListener('click', function(e) {
    if (e.target === bg) closeModal();
  });

  setInterval(loadStatus, 30000);
  setInterval(loadStream, 30000);
});
```

- [ ] **Step 2 : Vérifier**

```bash
python3 -c "from pathlib import Path; p=Path('bot/dashboard/static/public-starter/app.js'); print(p.stat().st_size, 'bytes OK')"
```

- [ ] **Step 3 : Commit du starter kit**

```bash
git add bot/dashboard/static/public-starter/
git commit -m "feat(dashboard): starter kit public-ui (index.html + style.css + app.js)"
```

---

## Task 7 : PUBLIC_API.md

**Files:**
- Create: `PUBLIC_API.md`

- [ ] **Step 1 : Créer PUBLIC_API.md à la racine**

Créer `PUBLIC_API.md` avec le contenu suivant :

```markdown
# Wally — Public API Reference

Tous ces endpoints sont accessibles sans authentification.
Ils constituent le contrat stable entre le bot et tout frontend custom.

Base URL : `http(s)://votre-domaine`

---

## Status

### GET /api/public/status

Reponse JSON :
- uptime_seconds (number)
- discord_connected (bool)
- twitch_connected (bool)
- discord_guild (string|null)
- message_count (number)
- version (string)

---

## Emotions

### GET /api/public/emotions/history?since=<timestamp_ms>

Historique des snapshots (un toutes les 5 minutes).
Chaque objet : { anger, joy, sadness, curiosity, boredom, timestamp }

### GET /api/public/sse/emotions

Server-Sent Events temps reel.
Event : emotion_update
Data  : { anger, joy, sadness, curiosity, boredom }

---

## Twitch

### GET /api/public/twitch/stream

Reponse JSON :
- stream_live (bool)
- title (string)
- game_name (string)
- viewer_count (number)
- started_at (string ISO8601)

---

## Galerie

### GET /api/public/gallery?limit=N&sort=date|votes&page=N

Reponse : { images: [{ id, prompt, created_at, votes }], total, page }

### GET /api/public/gallery/{id}/image

Fichier image (PNG/JPG binaire).

### POST /api/public/gallery/{id}/vote

Ajouter un vote a une image.

---

## Graphe social

### GET /api/public/social-graph/data

Reponse : { nodes: [{ id, name, summary }], edges: [{ source, target, type, fact }] }

---

## Roadmap

### GET /api/public/roadmap

Reponse : { content: "..." }

---

## Chat web

### GET /api/chat/discord-login

Lance le flux OAuth2 Discord pour obtenir un JWT de chat.

### WS /api/chat/ws/{token}

WebSocket de chat authentifie par JWT Discord.

---

## Notes

- /api/public/* : aucun token requis.
- /api/public/gallery/{id}/image retourne du binaire, pas du JSON.
- Le SSE /api/public/sse/emotions diffuse en continu — prevoir un fallback polling.
- Panel admin : /admin (token Bearer requis pour les actions d'administration).
```

- [ ] **Step 2 : Commit**

```bash
git add PUBLIC_API.md
git commit -m "docs: PUBLIC_API.md — contrat API public stable"
```

---

## Task 8 : Deploiement et verification finale

- [ ] **Step 1 : Build et demarrage**

```bash
cd /opt/stacks/wally-ai
docker compose up -d --build wally
```

- [ ] **Step 2 : Verifier que public-ui/ a ete seede**

```bash
ls /opt/stacks/wally-ai/public-ui/
```

Resultat attendu : `index.html  style.css  app.js`

- [ ] **Step 3 : Verifier les routes**

```bash
# Panel admin
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/admin
# Attendu : 200

# Public UI racine
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/
# Attendu : 200

# API publique non interceptee
curl -s http://localhost:8080/api/public/status | python3 -m json.tool | grep uptime
# Attendu : "uptime_seconds": ...

# SPA fallback
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/une-page
# Attendu : 200
```

- [ ] **Step 4 : Mise a jour TODO.md**

Cocher les 6 cases du chantier dans `TODO.md`.

```bash
git add TODO.md
git commit -m "chore: TODO.md — separation public-ui complete"
```
