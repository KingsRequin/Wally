# Web Dashboard Wally — Phase 2 Mémoire — Design Spec

**Date:** 2026-03-17
**Scope:** Onglet Mémoire admin du dashboard — liste users, souvenirs, suppression, recherche
**Prérequis:** Phase 1 dashboard (FastAPI + auth + SPA) complétée

---

## Contexte

Le dashboard Phase 1 inclut un stub 501 pour `GET/POST/DELETE /api/admin/memory/*`.
Cette phase remplace ce stub par une implémentation complète permettant à l'admin de visualiser
et gérer les souvenirs mem0 stockés dans Qdrant.

Le problème principal : mem0 n'a pas d'API "liste tous les users". Solution retenue : table
SQLite `memory_users` alimentée lors de chaque `memory.add()`.

---

## Architecture

### Nouvelle table SQLite

Dans `bot/db/database.py`, ajouter le bloc DDL suivant à la constante `SCHEMA` (module-level string) :

```sql
CREATE TABLE IF NOT EXISTS memory_users (
    user_id   TEXT PRIMARY KEY,  -- format mem0 : "discord:123456789" ou "twitch:username"
    platform  TEXT NOT NULL,     -- "discord" ou "twitch"
    last_updated REAL NOT NULL   -- timestamp unix
);
```

> ⚠️ Ce DDL doit être **ajouté à la constante `SCHEMA`** existante dans `database.py`, pas
> exécuté séparément. C'est ce string qui est exécuté au démarrage dans `Database.create()`.

Deux nouvelles méthodes asynchrones dans la classe `Database` :

```python
async def upsert_memory_user(self, user_id: str, platform: str) -> None:
    # Utiliser self._conn (nom réel de l'attribut connexion dans Database)
    await self._conn.execute(
        "INSERT INTO memory_users(user_id, platform, last_updated) VALUES(?,?,?)"
        " ON CONFLICT(user_id) DO UPDATE SET last_updated=excluded.last_updated",
        (user_id, platform, time.time()),
    )
    await self._conn.commit()

async def list_memory_users(self, q: str | None = None) -> list[dict]:
    sql = "SELECT user_id, platform, last_updated FROM memory_users"
    params: tuple = ()
    if q:
        sql += " WHERE user_id LIKE ?"
        params = (f"%{q}%",)
    sql += " ORDER BY last_updated DESC"
    async with self._conn.execute(sql, params) as cur:
        rows = await cur.fetchall()
    return [{"user_id": r[0], "platform": r[1], "last_updated": r[2]} for r in rows]
```

### Injection DB dans MemoryService

`MemoryService` reçoit une méthode `set_db(db: "Database") -> None` (pattern identique à `set_openai_client`) :

```python
def set_db(self, db: "Database") -> None:
    self._db = db
```

Attribut initialisé à `None` dans `__init__` : `self._db: Optional["Database"] = None`.

Dans `add()`, après `await asyncio.to_thread(self._mem0.add, ...)`, ajouter :

```python
if self._db is not None:
    await self._db.upsert_memory_user(uid, platform)
```

Wiring dans `main.py` : `memory.set_db(db)` immédiatement après la création de `MemoryService`.

---

## API Endpoints

Tous sous `/api/admin/memory/*` — Bearer token requis (middleware existant).

| Méthode | Route | Description |
|---------|-------|-------------|
| GET | `/api/admin/memory/users` | Liste users depuis SQLite. Query param `?q=` pour filtrer. Retourne `{users: [{user_id, platform, last_updated}]}` |
| GET | `/api/admin/memory/users/{user_id}` | Souvenirs d'un user. Retourne `{user_id, memories: [{id, memory}]}` |
| DELETE | `/api/admin/memory/users/{user_id}` | Supprime tous les souvenirs + ligne SQLite. Retourne `{deleted: true}` |
| DELETE | `/api/admin/memory/users/{user_id}/memories/{memory_id}` | Supprime un souvenir. Retourne `{deleted: true}` |
| GET | `/api/admin/memory/search` | Query param `?q=` requis. Recherche globale. Retourne `{results: [{user_id, platform, memory, score}]}` |

**URL encoding :** `user_id` contient `:` (ex: `discord:123`) — `encodeURIComponent()` côté client.
FastAPI décode automatiquement les path params URL-encodés (`discord%3A123` → `discord:123`).
Le path param doit être déclaré `user_id: str` sans restriction supplémentaire.

**Erreurs :**
- `mem0` non disponible → 503 `{"detail": "mem0 not available"}`
- `q` absent sur `/search` → 400 `{"detail": "q parameter required"}`

---

## Routes memory.py — Détail

### Router

Le fichier `bot/dashboard/routes/memory.py` est réécrit entièrement.
Le router s'appelle **`router`** (nom inchangé — `app.py` l'importe déjà sous ce nom via `memory.router`).

```python
from fastapi import APIRouter, HTTPException, Request
import asyncio

router = APIRouter()
```

### Initialisation lazy de mem0

Les routes accèdent à `state.memory._mem0` directement (les méthodes publiques de `MemoryService`
retournent des strings et perdent les IDs individuels nécessaires à la suppression).

**Avant toute opération mem0**, appeler `state.memory._init_mem0()` puis vérifier :

```python
state.memory._init_mem0()
if state.memory._mem0 is None:
    raise HTTPException(503, detail="mem0 not available")
```

> ℹ️ `_init_mem0()` est idempotente (guard `_mem0_init_attempted`). L'appeler à chaque requête
> est sûr — elle ne refait l'initialisation qu'une seule fois.

### Unwrapping des résultats mem0

mem0 ≥ 0.1.40 retourne `{"results": [...]}` au lieu d'une liste directe.
**Toujours** appliquer ce pattern après `get_all` et `search` :

```python
results = await asyncio.to_thread(state.memory._mem0.get_all, user_id=uid)
if isinstance(results, dict):
    results = results.get("results", [])
```

### GET /users

```python
@router.get("/memory/users")
async def list_users(request: Request, q: str | None = None):
    state = request.app.state.wally
    users = await state.db.list_memory_users(q)
    return {"users": users}
```

### GET /users/{user_id}

```python
@router.get("/memory/users/{user_id}")
async def get_user_memories(user_id: str, request: Request):
    state = request.app.state.wally
    state.memory._init_mem0()
    if state.memory._mem0 is None:
        raise HTTPException(503, detail="mem0 not available")
    uid = user_id  # déjà décodé par FastAPI
    results = await asyncio.to_thread(state.memory._mem0.get_all, user_id=uid)
    if isinstance(results, dict):
        results = results.get("results", [])
    memories = [{"id": r.get("id"), "memory": r.get("memory", "")} for r in results if r.get("memory")]
    return {"user_id": user_id, "memories": memories}
```

### DELETE /users/{user_id}

```python
@router.delete("/memory/users/{user_id}")
async def delete_user(user_id: str, request: Request):
    state = request.app.state.wally
    state.memory._init_mem0()
    if state.memory._mem0 is None:
        raise HTTPException(503, detail="mem0 not available")
    await asyncio.to_thread(state.memory._mem0.delete_all, user_id=user_id)
    # Utiliser la méthode publique execute() de Database (gère commit en interne)
    await state.db.execute("DELETE FROM memory_users WHERE user_id = ?", (user_id,))
    return {"deleted": True}
```

> ℹ️ Atomicité mem0/SQLite : si `delete_all` réussit mais que la suppression SQLite échoue
> (ou vice versa), l'état peut être incohérent. Accepté comme limitation Phase 2 — usage personnel.

### DELETE /users/{user_id}/memories/{memory_id}

```python
@router.delete("/memory/users/{user_id}/memories/{memory_id}")
async def delete_memory(user_id: str, memory_id: str, request: Request):
    state = request.app.state.wally
    state.memory._init_mem0()
    if state.memory._mem0 is None:
        raise HTTPException(503, detail="mem0 not available")
    await asyncio.to_thread(state.memory._mem0.delete, memory_id)
    return {"deleted": True}
```

### GET /search

```python
@router.get("/memory/search")
async def search_memories(request: Request, q: str | None = None):
    if not q or not q.strip():
        raise HTTPException(400, detail="q parameter required")
    state = request.app.state.wally
    state.memory._init_mem0()
    if state.memory._mem0 is None:
        raise HTTPException(503, detail="mem0 not available")

    users = await state.db.list_memory_users()
    all_results = []
    for user in users:
        uid = user["user_id"]
        platform = user["platform"]
        try:
            raw = await asyncio.to_thread(
                state.memory._mem0.search, q, user_id=uid, limit=3
            )
            if isinstance(raw, dict):
                raw = raw.get("results", [])
            for r in raw:
                if r.get("memory"):
                    all_results.append({
                        "user_id": uid,
                        "platform": platform,
                        "memory": r["memory"],
                        "score": r.get("score", 0.0),
                    })
        except Exception:
            pass  # Qdrant timeout pour cet user — on continue

    all_results.sort(key=lambda x: x["score"], reverse=True)
    return {"results": all_results}
```

> ⚠️ La recherche globale itère tous les users séquentiellement. Chaque appel `_mem0.search()`
> est exécuté dans `asyncio.to_thread()` (non-bloquant pour l'event loop). Pour usage personnel
> (< 100 users), la latence totale est acceptable. Pas de timeout global implémenté en Phase 2.

---

## Frontend

### index.html

1. Bouton MÉMOIRE — retirer `disabled`, ajouter `data-tab="memory"` et `onclick="showTab('memory')"` :
```html
<button class="tab-btn" data-tab="memory" onclick="showTab('memory')">🧠 MÉMOIRE</button>
```

2. Ajouter dans `<main>` :
```html
<div class="tab-content" id="tab-memory"></div>
```

### app.js

**Init tab mémoire** — appelé une fois lors du premier affichage (dans `showTab` si `tabId === 'memory'`) :

```js
function renderMemoryTab() {
  document.getElementById('tab-memory').innerHTML = `
    <div style="padding:12px 16px;border-bottom:2px solid #333;display:flex;gap:10px;align-items:center">
      <span style="font-size:0.7rem;color:#aaa;letter-spacing:2px">CHERCHER</span>
      <input type="text" id="mem-search" placeholder="Recherche dans tous les souvenirs…"
             oninput="onMemSearch(this.value)" style="flex:1;max-width:320px">
    </div>
    <div style="display:flex;min-height:400px">
      <div style="width:220px;border-right:2px solid #333;display:flex;flex-direction:column">
        <div style="padding:10px 12px;border-bottom:1px solid #333">
          <input type="text" id="mem-user-filter" placeholder="Filtrer users…"
                 oninput="onUserFilter(this.value)" style="width:100%">
        </div>
        <div id="mem-user-list" style="flex:1;overflow-y:auto;padding:8px"></div>
      </div>
      <div id="mem-detail" style="flex:1;overflow-y:auto"></div>
    </div>
  `;
  loadMemoryUsers();
}
```

**`loadMemoryUsers(filter="")`**

```js
async function loadMemoryUsers(filter = '') {
  const r = await apiFetch('/api/admin/memory/users' + (filter ? `?q=${encodeURIComponent(filter)}` : ''));
  if (!r || !r.ok) return;
  const { users } = await r.json();
  const el = document.getElementById('mem-user-list');
  if (!el) return;
  el.innerHTML = users.length === 0
    ? '<div style="color:#555;font-size:0.75rem;padding:8px">Aucun utilisateur</div>'
    : users.map(u => `
        <div class="mem-user-item" data-uid="${escAttr(u.user_id)}"
             onclick="selectUser('${escAttr(u.user_id)}')"
             style="padding:7px 10px;background:#1a1a1a;border:2px solid #555;margin-bottom:4px;cursor:pointer">
          <span style="color:#888;font-size:0.65rem;display:block">${escHtml(u.platform)}</span>
          <span style="font-size:0.8rem">${escHtml(u.user_id.split(':')[1] || u.user_id)}</span>
        </div>`).join('');
}
```

**`selectUser(userId)`**

```js
let _selectedUser = null;
async function selectUser(userId) {
  _selectedUser = userId;
  document.querySelectorAll('.mem-user-item').forEach(el => {
    el.style.borderColor = el.dataset.uid === userId ? '#00ccff' : '#555';
    el.style.color = el.dataset.uid === userId ? '#00ccff' : '';
  });
  await loadUserMemories(userId);
}
```

**`loadUserMemories(userId)`**

```js
async function loadUserMemories(userId) {
  const r = await apiFetch('/api/admin/memory/users/' + encodeURIComponent(userId));
  if (!r || !r.ok) return;
  const { memories } = await r.json();
  renderMemories(userId, memories);
}

function renderMemories(userId, memories) {
  const el = document.getElementById('mem-detail');
  if (!el) return;
  el.innerHTML = `
    <div style="padding:10px 16px;border-bottom:1px solid #333;display:flex;justify-content:space-between;align-items:center">
      <span style="font-size:0.7rem;color:#aaa;letter-spacing:2px">${escHtml(userId)} — ${memories.length} souvenir(s)</span>
      <button class="btn btn-danger" onclick="deleteAllMemories('${escAttr(userId)}')" style="font-size:0.72rem;padding:4px 10px">🗑 TOUT SUPPRIMER</button>
    </div>
    <div style="padding:12px">
      ${memories.length === 0
        ? '<div style="color:#555">Aucun souvenir.</div>'
        : memories.map(m => `
            <div style="background:#1a1a1a;border:2px solid #333;padding:10px 12px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:flex-start" id="mem-${escAttr(m.id)}">
              <span style="font-size:0.82rem;flex:1">${escHtml(m.memory)}</span>
              <button onclick="deleteMemory('${escAttr(userId)}','${escAttr(m.id)}')"
                      style="background:none;border:none;color:#ff3333;cursor:pointer;font-size:1rem;margin-left:10px">✕</button>
            </div>`).join('')
      }
    </div>
  `;
}
```

**`deleteMemory(userId, memoryId)`**

```js
async function deleteMemory(userId, memoryId) {
  const r = await apiFetch(
    `/api/admin/memory/users/${encodeURIComponent(userId)}/memories/${encodeURIComponent(memoryId)}`,
    { method: 'DELETE' }
  );
  if (r && r.ok) {
    document.getElementById('mem-' + memoryId)?.remove();
    toast('Souvenir supprimé', 'success');
  } else toast('Erreur suppression', 'error');
}
```

**`deleteAllMemories(userId)`**

```js
async function deleteAllMemories(userId) {
  const r = await apiFetch('/api/admin/memory/users/' + encodeURIComponent(userId), { method: 'DELETE' });
  if (r && r.ok) {
    document.getElementById('mem-detail').innerHTML = '<div style="padding:16px;color:#555">Aucun souvenir.</div>';
    loadMemoryUsers(document.getElementById('mem-user-filter')?.value || '');
    toast('Mémoire supprimée', 'success');
  } else toast('Erreur suppression', 'error');
}
```

**`onMemSearch(value)` — debounce 400ms**

```js
let _memSearchTimer = null;
function onMemSearch(value) {
  clearTimeout(_memSearchTimer);
  _memSearchTimer = setTimeout(async () => {
    if (value.length >= 2) {
      await searchMemories(value);
    } else if (_selectedUser) {
      await loadUserMemories(_selectedUser);
    }
  }, 400);
}

async function searchMemories(q) {
  const r = await apiFetch('/api/admin/memory/search?q=' + encodeURIComponent(q));
  if (!r || !r.ok) return;
  const { results } = await r.json();
  const el = document.getElementById('mem-detail');
  if (!el) return;
  el.innerHTML = `
    <div style="padding:10px 16px;border-bottom:1px solid #333">
      <span style="font-size:0.7rem;color:#aaa;letter-spacing:2px">${results.length} résultat(s) pour "${escHtml(q)}"</span>
    </div>
    <div style="padding:12px">
      ${results.length === 0
        ? '<div style="color:#555">Aucun résultat.</div>'
        : results.map(r => `
            <div style="background:#1a1a1a;border:2px solid #333;padding:10px 12px;margin-bottom:8px">
              <span style="font-size:0.65rem;color:#888;display:block;margin-bottom:4px">${escHtml(r.user_id)}</span>
              <span style="font-size:0.82rem">${escHtml(r.memory)}</span>
            </div>`).join('')
      }
    </div>
  `;
}
```

**`onUserFilter(value)` — debounce 300ms**

```js
let _userFilterTimer = null;
function onUserFilter(value) {
  clearTimeout(_userFilterTimer);
  _userFilterTimer = setTimeout(() => loadMemoryUsers(value), 300);
}
```

**Intégration dans `showTab`** — ajouter dans la fonction existante :

```js
if (tabId === 'memory' && !document.getElementById('mem-user-list')) renderMemoryTab();
```

**Helper `escAttr`** (pour les attributs HTML inline) :

```js
function escAttr(str) {
  return String(str).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
```

---

## Modifications fichiers existants

| Fichier | Changement |
|---------|------------|
| `bot/db/database.py` | DDL `memory_users` dans `SCHEMA` + méthodes `upsert_memory_user` + `list_memory_users` |
| `bot/core/memory.py` | `self._db = None` dans `__init__` + `set_db()` + appel `upsert_memory_user` dans `add()` |
| `bot/main.py` | `memory.set_db(db)` après création MemoryService |
| `bot/dashboard/routes/memory.py` | Réécriture complète — supprime stub 501, garde nom `router` |
| `bot/dashboard/static/index.html` | Active bouton MÉMOIRE + ajoute `#tab-memory` |
| `bot/dashboard/static/app.js` | Fonctions mémoire + init tab dans `showTab` + `escAttr` helper |

> `app.py` n'a pas besoin d'être modifié — il importe déjà `memory.router` et le monte sous `/api/admin`.

---

## Hors scope Phase 2

- Ajout manuel de souvenir depuis le dashboard
- Édition d'un souvenir existant
- Export des souvenirs (CSV, JSON)
- Pagination (acceptable pour usage personnel < 100 users)
- Atomicité totale mem0/SQLite (si l'une des deux opérations échoue lors d'une suppression, l'état peut être légèrement incohérent — acceptable usage personnel)
