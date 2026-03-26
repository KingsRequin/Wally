# Dashboard Controls & Memory Sort — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fixed admin control bar with bot status indicators + stop/start/restart buttons, and a sort dropdown in the memory user modal.

**Architecture:** Two independent features. (1) Admin control bar: new HTML element above the main content, new admin endpoints for bot status/stop/start/restart. Restart uses docker compose restart wally via subprocess (requires Docker socket mount + group permissions). (2) Memory sort: client-side only, dropdown in the user modal that re-sorts already-loaded memories.

**Tech Stack:** FastAPI (Python), vanilla JS, CSS glassmorphism, Docker socket

---

### Task 1: Backend — Bot status and control endpoints

**Files:**
- Modify: `bot/dashboard/routes/admin.py` (add 6 new endpoints)

- [ ] **Step 1: Add bot status endpoint**

Add at the end of `admin.py`:

```python
@router.get("/bot/status")
async def get_bot_status(request: Request) -> dict:
    state = request.app.state.wally
    discord_online = (
        state.discord_bot is not None
        and state.discord_bot.is_ready()
    )
    twitch_online = (
        state.twitch_bot is not None
        and getattr(state.twitch_bot, "_eventsub_client", None) is not None
    )
    return {
        "discord": "connected" if discord_online else "disconnected",
        "twitch": "connected" if twitch_online else "disconnected",
    }
```

- [ ] **Step 2: Add Discord stop endpoint**

```python
@router.post("/bot/discord/stop")
async def stop_discord(request: Request) -> dict:
    state = request.app.state.wally
    bot = state.discord_bot
    if bot is None:
        raise HTTPException(status_code=404, detail="Discord bot not configured")
    if bot.is_closed():
        return {"ok": True, "message": "already stopped"}
    await bot.close()
    logger.info("Discord bot stopped via dashboard")
    return {"ok": True}
```

- [ ] **Step 3: Add Discord start endpoint**

```python
@router.post("/bot/discord/start")
async def start_discord(request: Request) -> dict:
    import os
    state = request.app.state.wally
    bot = state.discord_bot
    if bot is None:
        raise HTTPException(status_code=404, detail="Discord bot not configured")
    if not bot.is_closed():
        return {"ok": True, "message": "already running"}
    token = os.getenv("DISCORD_TOKEN", "")
    if not token:
        raise HTTPException(status_code=500, detail="DISCORD_TOKEN not set")
    import asyncio
    asyncio.create_task(bot.start(token))
    logger.info("Discord bot started via dashboard")
    return {"ok": True}
```

- [ ] **Step 4: Add Twitch stop endpoint**

```python
@router.post("/bot/twitch/stop")
async def stop_twitch(request: Request) -> dict:
    state = request.app.state.wally
    bot = state.twitch_bot
    if bot is None:
        raise HTTPException(status_code=404, detail="Twitch bot not configured")
    if getattr(bot, "_closed", False):
        return {"ok": True, "message": "already stopped"}
    await bot.close()
    logger.info("Twitch bot stopped via dashboard")
    return {"ok": True}
```

- [ ] **Step 5: Add Twitch start endpoint**

```python
@router.post("/bot/twitch/start")
async def start_twitch(request: Request) -> dict:
    import asyncio
    state = request.app.state.wally
    bot = state.twitch_bot
    if bot is None:
        raise HTTPException(status_code=404, detail="Twitch bot not configured")
    if not getattr(bot, "_closed", True):
        return {"ok": True, "message": "already running"}
    asyncio.create_task(bot.start())
    logger.info("Twitch bot started via dashboard")
    return {"ok": True}
```

- [ ] **Step 6: Add container restart endpoint**

```python
@router.post("/bot/restart")
async def restart_container(request: Request) -> dict:
    import asyncio
    logger.warning("Container restart requested via dashboard")
    async def _do_restart():
        await asyncio.sleep(1)
        proc = await asyncio.create_subprocess_exec(
            "docker", "compose", "restart", "wally",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error("Restart failed: {}", stderr.decode())
    asyncio.create_task(_do_restart())
    return {"ok": True, "message": "Restart initiated"}
```

- [ ] **Step 7: Commit**

```
git add bot/dashboard/routes/admin.py
git commit -m "feat(dashboard): add bot status/stop/start/restart endpoints"
```

---

### Task 2: Docker — Mount Docker socket

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add Docker socket volume and group**

In `docker-compose.yml`, in the `wally` service, add the Docker socket volume and `group_add` for the docker group:

```yaml
  wally:
    build: .
    container_name: wally-bot
    user: "1000:1000"
    group_add:
      - "999"   # docker group GID on host (run: getent group docker)
    networks:
      - wally-net
    # ... rest unchanged ...
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./config.yaml:/app/config.yaml
      - ./.env:/app/.env
      - ./ROADMAP.md:/app/ROADMAP.md:ro
      - ./bot/dashboard/static:/app/bot/dashboard/static:ro
      - /var/run/docker.sock:/var/run/docker.sock
```

- [ ] **Step 2: Install docker CLI in Dockerfile**

Add `docker-cli` (or `docker.io`) to the Dockerfile so the `docker compose restart` command is available inside the container. Check the existing Dockerfile base image and add the appropriate package install.

- [ ] **Step 3: Commit**

```
git add docker-compose.yml Dockerfile
git commit -m "feat(docker): mount Docker socket for container restart"
```

---

### Task 3: Frontend — Admin control bar HTML and CSS

**Files:**
- Modify: `bot/dashboard/static/index.html`
- Modify: `bot/dashboard/static/style.css`

- [ ] **Step 1: Add control bar HTML**

In `index.html`, inside `.app-wrapper` (line 49), right after `<div class="app-wrapper">` and before `<!-- Sidebar -->`, add:

```html
  <!-- Admin Control Bar -->
  <div class="control-bar" id="control-bar" style="display:none">
    <div class="control-bar-group">
      <div class="control-bar-indicator">
        <span class="control-bar-dot" id="discord-dot"></span>
        <span class="control-bar-label">Discord</span>
        <button class="control-bar-btn" id="discord-toggle-btn" onclick="toggleBotAdapter('discord')">Stop</button>
      </div>
      <div class="control-bar-indicator">
        <span class="control-bar-dot" id="twitch-dot"></span>
        <span class="control-bar-label">Twitch</span>
        <button class="control-bar-btn" id="twitch-toggle-btn" onclick="toggleBotAdapter('twitch')">Stop</button>
      </div>
    </div>
    <div class="control-bar-group">
      <button class="control-bar-btn restart" id="restart-btn" onclick="restartContainer()">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6M1 20v-6h6"/><path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"/></svg>
        Restart
      </button>
    </div>
  </div>
```

- [ ] **Step 2: Add control bar CSS**

In `style.css`, add after the `.sidebar` styles:

```css
/* -- Control Bar ------------------------------------------------ */
.control-bar {
  position: fixed;
  top: 0;
  left: 80px;
  right: 0;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  background: rgba(13, 17, 23, 0.85);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  z-index: 100;
  gap: 16px;
}

.control-bar-group {
  display: flex;
  align-items: center;
  gap: 20px;
}

.control-bar-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
}

.control-bar-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--c-offline);
  transition: background 0.3s ease;
}

.control-bar-dot.online {
  background: var(--c-online);
  box-shadow: 0 0 6px var(--c-online);
}

.control-bar-label {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.6);
  font-weight: 500;
}

.control-bar-btn {
  padding: 3px 10px;
  font-size: 11px;
  font-weight: 600;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.05);
  color: rgba(255, 255, 255, 0.7);
  cursor: pointer;
  transition: all 0.2s ease;
}

.control-bar-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  border-color: rgba(255, 255, 255, 0.2);
  color: #fff;
}

.control-bar-btn.restart {
  display: flex;
  align-items: center;
  gap: 5px;
  color: var(--c-anger);
  border-color: rgba(239, 68, 68, 0.2);
}

.control-bar-btn.restart:hover {
  background: rgba(239, 68, 68, 0.15);
  border-color: rgba(239, 68, 68, 0.4);
}

.control-bar-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* Shift main content down when control bar is visible */
body.admin-mode .main-content {
  padding-top: 48px;
}

/* Mobile: control bar below sidebar */
body.is-mobile .control-bar {
  left: 0;
  top: 60px;
}
```

- [ ] **Step 3: Commit**

```
git add bot/dashboard/static/index.html bot/dashboard/static/style.css
git commit -m "feat(dashboard): add admin control bar HTML + CSS"
```

---

### Task 4: Frontend — Control bar JavaScript logic

**Files:**
- Modify: `bot/dashboard/static/app.js`

- [ ] **Step 1: Add control bar state polling**

Add near the top of `app.js` (after the global variables around line 40):

```javascript
// -- Bot Control Bar ----------------------------------------------
var _controlBarInterval = null;

function showControlBar(visible) {
  var bar = document.getElementById('control-bar');
  if (bar) bar.style.display = visible ? 'flex' : 'none';
}

async function pollBotStatus() {
  var r = await apiFetch('/api/admin/bot/status');
  if (!r || !r.ok) return;
  var data = await r.json();

  var discordDot = document.getElementById('discord-dot');
  var twitchDot = document.getElementById('twitch-dot');
  var discordBtn = document.getElementById('discord-toggle-btn');
  var twitchBtn = document.getElementById('twitch-toggle-btn');

  if (discordDot) discordDot.className = 'control-bar-dot' + (data.discord === 'connected' ? ' online' : '');
  if (twitchDot) twitchDot.className = 'control-bar-dot' + (data.twitch === 'connected' ? ' online' : '');
  if (discordBtn) {
    discordBtn.textContent = data.discord === 'connected' ? 'Stop' : 'Start';
    discordBtn.disabled = false;
  }
  if (twitchBtn) {
    twitchBtn.textContent = data.twitch === 'connected' ? 'Stop' : 'Start';
    twitchBtn.disabled = false;
  }
}

function startControlBarPolling() {
  if (_controlBarInterval) return;
  pollBotStatus();
  _controlBarInterval = setInterval(pollBotStatus, 5000);
}

function stopControlBarPolling() {
  if (_controlBarInterval) {
    clearInterval(_controlBarInterval);
    _controlBarInterval = null;
  }
}
```

- [ ] **Step 2: Add toggle and restart functions**

```javascript
async function toggleBotAdapter(adapter) {
  var btn = document.getElementById(adapter + '-toggle-btn');
  if (!btn) return;
  var action = btn.textContent.trim() === 'Stop' ? 'stop' : 'start';
  btn.disabled = true;
  btn.textContent = '...';
  var r = await apiFetch('/api/admin/bot/' + adapter + '/' + action, { method: 'POST' });
  if (!r || !r.ok) {
    toast('Erreur ' + action + ' ' + adapter, 'error');
    btn.disabled = false;
    pollBotStatus();
    return;
  }
  toast(adapter + ' ' + (action === 'stop' ? 'arrêté' : 'démarré'), 'success');
  setTimeout(pollBotStatus, 2000);
}

async function restartContainer() {
  if (!confirm('Redémarrer le container Wally ? Le dashboard sera temporairement indisponible.')) return;
  var btn = document.getElementById('restart-btn');
  if (btn) btn.disabled = true;
  var r = await apiFetch('/api/admin/bot/restart', { method: 'POST' });
  if (!r || !r.ok) {
    toast('Erreur restart', 'error');
    if (btn) btn.disabled = false;
    return;
  }
  toast('Restart en cours...', 'success');
  _waitForReconnect();
}

function _waitForReconnect() {
  var attempts = 0;
  var maxAttempts = 60;
  var interval = setInterval(async function() {
    attempts++;
    if (attempts > maxAttempts) {
      clearInterval(interval);
      toast('Le bot ne répond plus', 'error');
      return;
    }
    try {
      var r = await fetch('/api/public/status', { signal: AbortSignal.timeout(3000) });
      if (r.ok) {
        clearInterval(interval);
        toast('Bot reconnecté !', 'success');
        var btn = document.getElementById('restart-btn');
        if (btn) btn.disabled = false;
        pollBotStatus();
      }
    } catch(e) { /* server still down */ }
  }, 2000);
}
```

- [ ] **Step 3: Integrate with admin mode toggle**

In the existing `switchMode()` function, after the admin nav show/hide block, add:

```javascript
showControlBar(mode === 'admin');
if (mode === 'admin') {
  startControlBarPolling();
} else {
  stopControlBarPolling();
}
```

- [ ] **Step 4: Commit**

```
git add bot/dashboard/static/app.js
git commit -m "feat(dashboard): add control bar JS logic with status polling"
```

---

### Task 5: Frontend — Memory sort dropdown

**Files:**
- Modify: `bot/dashboard/static/app.js`
- Modify: `bot/dashboard/static/style.css`

- [ ] **Step 1: Add sort dropdown in the user modal**

In `openUserModal()`, replace the standalone search input line (around line 1828):

```javascript
    + '<input type="text" class="mem-modal-search" id="modal-mem-search" placeholder="🔍 Rechercher dans les mémoires..." oninput="filterModalMemories(this.value)">'
```

With a toolbar containing both the sort dropdown and the search:

```javascript
    + '<div class="mem-modal-toolbar">'
    + '<select class="mem-sort-select" id="modal-mem-sort" onchange="sortModalMemories(this.value)">'
    + '<option value="default">Tri par défaut</option>'
    + '<option value="recent">Plus récent</option>'
    + '<option value="oldest">Plus ancien</option>'
    + '</select>'
    + '<input type="text" class="mem-modal-search" id="modal-mem-search" placeholder="🔍 Rechercher..." oninput="filterModalMemories(this.value)">'
    + '</div>'
```

- [ ] **Step 2: Store memories on the modal element for re-sorting**

After `backdrop.appendChild(modal);` (line ~1832), add:

```javascript
  modal._memories = memories;
  modal._userId = userId;
  modal._userData = userData;
```

- [ ] **Step 3: Add sortModalMemories function**

```javascript
function sortModalMemories(sortBy) {
  var modal = document.querySelector('.mem-modal');
  if (!modal || !modal._memories) return;
  var memories = modal._memories.slice();

  if (sortBy === 'recent') {
    memories.sort(function(a, b) {
      var da = new Date(a.created_at || a.date || 0);
      var db = new Date(b.created_at || b.date || 0);
      return db - da;
    });
  } else if (sortBy === 'oldest') {
    memories.sort(function(a, b) {
      var da = new Date(a.created_at || a.date || 0);
      var db = new Date(b.created_at || b.date || 0);
      return da - db;
    });
  }

  var grouped = {};
  MEM_CATEGORIES.forEach(function(cat) { grouped[cat.key] = []; });
  memories.forEach(function(m) {
    var catKey = m.category || '';
    if (!grouped[catKey]) grouped[catKey] = grouped[''];
    grouped[catKey].push(m);
  });

  if (sortBy === 'default') {
    Object.keys(grouped).forEach(function(key) {
      grouped[key].sort(function(a, b) {
        var da = new Date(b.updated_at || b.created_at || 0);
        var db = new Date(a.updated_at || a.created_at || 0);
        return da - db;
      });
    });
  }

  var userId = modal._userId;
  var platform = (modal._userData || {}).platform || userId.split(':')[0];
  var categoriesHtml = '';
  MEM_CATEGORIES.forEach(function(cat) {
    var items = grouped[cat.key] || [];
    if (items.length === 0) return;
    categoriesHtml += '<div class="mem-category" data-cat="' + escAttr(cat.key) + '">'
      + '<div class="mem-category-header" onclick="toggleMemCategory(this)">'
      + '<span class="mem-category-chevron">▼</span>'
      + '<span class="mem-category-name ' + escAttr(cat.css) + '">' + escHtml(cat.label) + '</span>'
      + '<span class="mem-category-count">(' + items.length + ')</span>'
      + '</div>'
      + '<div class="mem-category-body">'
      + items.map(function(m) {
          var isOwn = (m.source || '') === userId || (m.source_platform || '') === platform;
          var sourceIcon = isOwn ? '🤖' : '✍️';
          var dateStr = m.updated_at || m.created_at;
          var shortDate = dateStr ? new Date(dateStr).toLocaleString('fr', { day:'numeric', month:'short' }) : '';
          return '<div class="mem-entry" id="mem-entry-' + escAttr(m.id) + '" style="border-left:2px solid ' + cat.color + '4d">'
            + '<span class="mem-entry-text" id="mem-text-' + escAttr(m.id) + '">' + escHtml(m.memory) + '</span>'
            + '<span class="mem-entry-source" title="' + (isOwn ? 'Auto-extrait' : 'Ajouté manuellement') + '">' + sourceIcon + '</span>'
            + '<span class="mem-entry-date">' + escHtml(shortDate) + '</span>'
            + '<div class="mem-entry-actions">'
            + '<button class="mem-entry-action" onclick="startModalEditMemory(\'' + escAttr(userId) + '\',\'' + escAttr(m.id) + '\')" title="Modifier">✏️</button>'
            + '<button class="mem-entry-action" onclick="deleteModalMemory(\'' + escAttr(userId) + '\',\'' + escAttr(m.id) + '\')" title="Supprimer">🗑</button>'
            + '</div></div>';
        }).join('')
      + '</div></div>';
  });

  if (categoriesHtml === '') {
    categoriesHtml = '<div class="mem-empty-state">Aucun souvenir enregistré.</div>';
  }

  var container = document.getElementById('modal-categories');
  if (container) container.innerHTML = categoriesHtml;
}
```

- [ ] **Step 4: Add toolbar and select CSS**

In `style.css`:

```css
/* -- Memory Modal Toolbar --------------------------------------- */
.mem-modal-toolbar {
  display: flex;
  gap: 8px;
  padding: 0 20px 8px;
  align-items: center;
}

.mem-sort-select {
  padding: 6px 10px;
  font-size: 12px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.05);
  color: rgba(255, 255, 255, 0.8);
  cursor: pointer;
  outline: none;
  flex-shrink: 0;
}

.mem-sort-select:hover {
  border-color: rgba(255, 255, 255, 0.2);
}

.mem-sort-select:focus {
  border-color: var(--accent);
}

.mem-sort-select option {
  background: #1a1f2c;
  color: #fff;
}

.mem-modal-toolbar .mem-modal-search {
  flex: 1;
  margin: 0;
  padding: 6px 12px;
}
```

- [ ] **Step 5: Commit**

```
git add bot/dashboard/static/app.js bot/dashboard/static/style.css
git commit -m "feat(dashboard): add memory sort dropdown in user modal"
```

---

### Task 6: Update TODO and final commit

- [ ] **Step 1: Update TODO.md**

Mark the two improvements as done:

```markdown
- [x] ajouter des bouton restart, stop/start (2026-03-26) — barre de contrôle admin fixe avec statut Discord/Twitch + stop/start + restart container
- [x] ajouter un tris pas date (memoire le plus recent en premier) pour la page memoire (2026-03-26) — dropdown tri (récent/ancien/défaut) dans modal mémoire utilisateur
```

- [ ] **Step 2: Commit**

```
git add TODO.md
git commit -m "docs: mark dashboard controls + memory sort as done"
```
