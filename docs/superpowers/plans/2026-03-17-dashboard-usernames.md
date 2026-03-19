# Dashboard Usernames Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Afficher les pseudos Discord/Twitch dans le dashboard mémoire, et synchroniser les utilisateurs Qdrant existants vers `memory_users`.

**Architecture:** Ajout d'une colonne `username` dans `memory_users`, capturée lors des analyses de sessions via `SessionManager`. Sync boot et manuelle via scroll Qdrant. Le dashboard affiche le pseudo à la place de l'ID numérique.

**Tech Stack:** Python asyncio, aiosqlite, qdrant-client, FastAPI, vanilla JS

---

## File Map

| Fichier | Changement |
|---|---|
| `bot/db/database.py` | Migration `username`, update `upsert_memory_user`, `list_memory_users`, add `sync_memory_users_from_qdrant` |
| `bot/core/memory.py` | `add()` accepte `username: str = ""` |
| `bot/core/sessions.py` | `_analyze_session()` passe `username=display_name` |
| `bot/main.py` | Boot sync après init DB |
| `bot/dashboard/routes/memory.py` | Route `POST /memory/sync` + enrich `/memory/search` |
| `bot/dashboard/static/app.js` | Affichage username, bouton Sync, résultats de recherche |
| `tests/test_dashboard_memory_db.py` | Tests username + sync mock |

---

## Task 1 — DB: colonne `username` + `upsert_memory_user` mis à jour

**Files:**
- Modify: `bot/db/database.py`
- Test: `tests/test_dashboard_memory_db.py`

- [ ] **Étape 1 : Écrire les tests**

Ajouter dans `tests/test_dashboard_memory_db.py` :

```python
@pytest.mark.asyncio
async def test_upsert_memory_user_stores_username():
    db = await Database.create(":memory:")
    await db.upsert_memory_user("discord:alice", "discord", username="Alice")
    users = await db.list_memory_users()
    assert users[0]["username"] == "Alice"
    await db.close()


@pytest.mark.asyncio
async def test_upsert_memory_user_preserves_username_when_empty():
    db = await Database.create(":memory:")
    await db.upsert_memory_user("discord:alice", "discord", username="Alice")
    await db.upsert_memory_user("discord:alice", "discord", username="")  # pas d'écrasement
    users = await db.list_memory_users()
    assert users[0]["username"] == "Alice"
    await db.close()


@pytest.mark.asyncio
async def test_list_memory_users_filter_by_username():
    db = await Database.create(":memory:")
    await db.upsert_memory_user("discord:111", "discord", username="OlafMC")
    await db.upsert_memory_user("twitch:222", "twitch", username="StreamerXYZ")
    users = await db.list_memory_users(q="Olaf")
    assert len(users) == 1
    assert users[0]["username"] == "OlafMC"
    await db.close()


@pytest.mark.asyncio
async def test_list_memory_users_filter_by_user_id_still_works():
    db = await Database.create(":memory:")
    await db.upsert_memory_user("discord:111", "discord", username="OlafMC")
    users = await db.list_memory_users(q="discord:111")
    assert len(users) == 1
    await db.close()
```

- [ ] **Étape 2 : Vérifier que les tests échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_dashboard_memory_db.py::test_upsert_memory_user_stores_username -v
```

Attendu : `FAILED` (colonne `username` inexistante)

- [ ] **Étape 3 : Implémenter la migration et mettre à jour `upsert_memory_user` + `list_memory_users`**

Dans `bot/db/database.py`, dans `Database.create()`, après `await conn.executescript(SCHEMA)` :

```python
# Migration: ajouter username à memory_users si absent
try:
    await conn.execute("ALTER TABLE memory_users ADD COLUMN username TEXT")
    await conn.commit()
except Exception:
    pass  # colonne déjà présente
```

Modifier `upsert_memory_user` (ligne ~247) :

```python
async def upsert_memory_user(self, user_id: str, platform: str, username: str = "") -> None:
    await self.execute(
        "INSERT INTO memory_users(user_id, platform, last_updated, username) VALUES(?,?,?,?)"
        " ON CONFLICT(user_id) DO UPDATE SET"
        "   last_updated=excluded.last_updated,"
        "   username=COALESCE(NULLIF(excluded.username,''), memory_users.username)",
        (user_id, platform, time.time(), username or None),
    )
```

Modifier `list_memory_users` — ajouter `username` dans le SELECT et étendre le filtre :

```python
async def list_memory_users(self, q: str | None = None) -> list[dict]:
    sql = (
        "SELECT m.user_id, m.platform, m.last_updated, m.username, "
        "COALESCE(t.score, 0.5) AS trust_score "
        "FROM memory_users m "
        "LEFT JOIN trust_scores t "
        "  ON t.platform = m.platform "
        "  AND t.user_id = SUBSTR(m.user_id, LENGTH(m.platform) + 2)"
    )
    params: tuple = ()
    if q:
        sql += " WHERE (m.user_id LIKE ? OR m.username LIKE ?)"
        params = (f"%{q}%", f"%{q}%")
    sql += " ORDER BY m.last_updated DESC"
    async with self._conn.execute(sql, params) as cur:
        rows = await cur.fetchall()
    return [
        {
            "user_id": r["user_id"],
            "platform": r["platform"],
            "last_updated": r["last_updated"],
            "username": r["username"],
            "trust_score": round(float(r["trust_score"]), 2),
        }
        for r in rows
    ]
```

- [ ] **Étape 4 : Vérifier que les tests passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_dashboard_memory_db.py -v
```

Attendu : tous les tests PASS (y compris les anciens)

- [ ] **Étape 5 : Commit**

```bash
git add bot/db/database.py tests/test_dashboard_memory_db.py
git commit -m "feat(db): add username column to memory_users with migration"
```

---

## Task 2 — DB: `sync_memory_users_from_qdrant()`

**Files:**
- Modify: `bot/db/database.py`
- Test: `tests/test_dashboard_memory_db.py`

- [ ] **Étape 1 : Écrire le test (mock Qdrant)**

Ajouter dans `tests/test_dashboard_memory_db.py` :

```python
from unittest.mock import MagicMock, patch


@pytest.mark.asyncio
async def test_sync_memory_users_from_qdrant_imports_new_users():
    db = await Database.create(":memory:")

    # Simuler 2 points Qdrant avec user_id dans le payload
    point_a = MagicMock()
    point_a.payload = {"user_id": "discord:111"}
    point_b = MagicMock()
    point_b.payload = {"user_id": "twitch:bob"}

    # QdrantClient est importé à l'intérieur de la méthode → patcher le module source
    with patch("qdrant_client.QdrantClient") as MockClient:
        client_instance = MockClient.return_value
        # scroll retourne (points, next_offset) — None = fin
        client_instance.scroll.return_value = ([point_a, point_b], None)

        n = await db.sync_memory_users_from_qdrant("http://localhost:6333")

    assert n == 2
    users = await db.list_memory_users()
    user_ids = {u["user_id"] for u in users}
    assert "discord:111" in user_ids
    assert "twitch:bob" in user_ids
    await db.close()


@pytest.mark.asyncio
async def test_sync_memory_users_from_qdrant_skips_existing():
    db = await Database.create(":memory:")
    await db.upsert_memory_user("discord:111", "discord", username="OlafMC")

    point = MagicMock()
    point.payload = {"user_id": "discord:111"}

    with patch("qdrant_client.QdrantClient") as MockClient:
        client_instance = MockClient.return_value
        client_instance.scroll.return_value = ([point], None)
        n = await db.sync_memory_users_from_qdrant("http://localhost:6333")

    # Aucun nouveau — mais le username existant est préservé
    users = await db.list_memory_users()
    assert users[0]["username"] == "OlafMC"
    await db.close()


@pytest.mark.asyncio
async def test_sync_memory_users_from_qdrant_handles_qdrant_error():
    db = await Database.create(":memory:")

    with patch("qdrant_client.QdrantClient") as MockClient:
        MockClient.side_effect = Exception("Qdrant unavailable")
        n = await db.sync_memory_users_from_qdrant("http://localhost:6333")

    assert n == 0
    await db.close()
```

- [ ] **Étape 2 : Vérifier que les tests échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_dashboard_memory_db.py::test_sync_memory_users_from_qdrant_imports_new_users -v
```

Attendu : `FAILED` (méthode inexistante)

- [ ] **Étape 3 : Implémenter `sync_memory_users_from_qdrant()`**

En haut de `bot/db/database.py`, ajouter l'import conditionnel (dans la méthode, pas au toplevel pour éviter les erreurs si qdrant-client absent) :

Ajouter la méthode dans `Database` :

```python
async def sync_memory_users_from_qdrant(self, qdrant_url: str) -> int:
    """Importe dans memory_users les user_id trouvés dans Qdrant.

    Retourne le nombre de nouveaux utilisateurs insérés.
    Silencieux si Qdrant est indisponible.
    """
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(url=qdrant_url)
        user_ids: set[str] = set()
        offset = None
        while True:
            points, next_offset = client.scroll(
                collection_name="wally_memory",
                limit=100,
                with_payload=True,
                offset=offset,
            )
            for point in points:
                uid = (point.payload or {}).get("user_id")
                if uid and isinstance(uid, str) and ":" in uid:
                    user_ids.add(uid)
            if next_offset is None:
                break
            offset = next_offset

        inserted = 0
        before = {u["user_id"] for u in await self.list_memory_users()}
        for uid in user_ids:
            platform = uid.split(":")[0]
            await self.upsert_memory_user(uid, platform, username="")
            if uid not in before:
                inserted += 1

        if inserted:
            logger.info("sync_memory_users_from_qdrant: {n} nouveaux utilisateurs importés", n=inserted)
        return inserted

    except Exception as exc:
        logger.warning("sync_memory_users_from_qdrant échoué: {e}", e=exc)
        return 0
```

- [ ] **Étape 4 : Vérifier que les tests passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_dashboard_memory_db.py -v
```

Attendu : tous PASS

- [ ] **Étape 5 : Commit**

```bash
git add bot/db/database.py tests/test_dashboard_memory_db.py
git commit -m "feat(db): add sync_memory_users_from_qdrant()"
```

---

## Task 3 — MemoryService.add() avec username

**Files:**
- Modify: `bot/core/memory.py`
- Test: `tests/test_memory.py`

- [ ] **Étape 1 : Écrire le test**

Ajouter dans `tests/test_memory.py` :

```python
@pytest.mark.asyncio
async def test_memory_add_passes_username_to_db():
    """Vérifie que memory.add() transmet le username à db.upsert_memory_user."""
    from bot.core.memory import MemoryService

    config = make_config()
    svc = MemoryService(config)

    mock_mem0 = MagicMock()
    mock_mem0.add.return_value = {"results": []}
    svc._mem0_init_attempted = True  # doit être avant l'assignation de _mem0
    svc._mem0 = mock_mem0

    mock_db = MagicMock()
    mock_db.upsert_memory_user = AsyncMock()
    svc.set_db(mock_db)

    await svc.add("discord", "123", "some content", username="OlafMC")

    mock_db.upsert_memory_user.assert_called_once()
    call_kwargs = mock_db.upsert_memory_user.call_args
    # Vérifier que username="OlafMC" est passé
    assert "OlafMC" in call_kwargs.args or call_kwargs.kwargs.get("username") == "OlafMC"
```

- [ ] **Étape 2 : Vérifier que le test échoue**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_memory.py::test_memory_add_passes_username_to_db -v
```

Attendu : `FAILED`

- [ ] **Étape 3 : Modifier `MemoryService.add()`**

Dans `bot/core/memory.py`, ligne ~113 :

```python
async def add(self, platform: str, user_id: str, content: str,
              username: str = "", emotion_context: str = "") -> None:
    self._init_mem0()
    if self._mem0 is None:
        return
    try:
        uid = self._user_id(platform, user_id)
        full_content = f"[{emotion_context}] {content}" if emotion_context else content
        result = await asyncio.to_thread(self._mem0.add, full_content, user_id=uid)
        stored = result.get("results", []) if isinstance(result, dict) else (result if isinstance(result, list) else [])
        for entry in stored:
            event = entry.get("event", "")
            memory = entry.get("memory", "")
            if event in ("ADD", "UPDATE") and memory:
                logger.debug("mem0 {event} [{uid}]: {mem}", event=event, uid=uid, mem=memory)
        if self._db is not None:
            await self._db.upsert_memory_user(uid, platform, username)
        self._fire(self._maybe_consolidate(platform, user_id))
    except Exception as exc:
        logger.warning("mem0 add failed: {e}", e=exc)
```

- [ ] **Étape 4 : Vérifier que les tests passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_memory.py -v
```

Attendu : tous PASS

- [ ] **Étape 5 : Commit**

```bash
git add bot/core/memory.py tests/test_memory.py
git commit -m "feat(memory): add username parameter to MemoryService.add()"
```

---

## Task 4 — sessions.py : passer username à memory.add()

**Files:**
- Modify: `bot/core/sessions.py`
- Test: `tests/test_memory_tag.py` (ou nouveau fichier `tests/test_sessions_username.py`)

- [ ] **Étape 1 : Écrire le test**

Créer `tests/test_sessions_username.py` :

```python
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from bot.core.sessions import SessionManager, _Session


@pytest.mark.asyncio
async def test_analyze_session_passes_display_name_as_username():
    """_analyze_session doit passer display_name comme username à memory.add()."""
    mock_memory = MagicMock()
    mock_memory.add = AsyncMock()

    mock_openai = MagicMock()
    mock_openai.complete_secondary = AsyncMock(
        return_value="### OlafMC\n- aime le jeu de stratégie\n"
    )

    manager = SessionManager(mock_memory, mock_openai)

    session = _Session(
        channel_id="ch1",
        platform="discord",
        messages=[
            {"author": "OlafMC", "user_id": "111", "content": "salut", "timestamp": 1.0},
            {"author": "OlafMC", "user_id": "111", "content": "tu joues ?", "timestamp": 2.0},
        ],
        participants={"111": "OlafMC"},
    )

    await manager._analyze_session(session)

    mock_memory.add.assert_called_once()
    call_kwargs = mock_memory.add.call_args.kwargs
    assert call_kwargs.get("username") == "OlafMC"
```

- [ ] **Étape 2 : Vérifier que le test échoue**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_sessions_username.py -v
```

Attendu : `FAILED` (`username` non passé)

- [ ] **Étape 3 : Modifier `_analyze_session()`**

Dans `bot/core/sessions.py`, ligne ~155, modifier l'appel à `memory.add()` :

```python
for user_id, display_name in session.participants.items():
    user_facts = _extract_user_section(analysis, display_name)
    if not user_facts:
        logger.debug(
            "No durable facts for {u} in session — skipping memory",
            u=display_name,
        )
        continue
    await self._memory.add(
        session.platform,
        user_id,
        user_facts,
        username=display_name,  # ← ajout
    )
    stored += 1
```

- [ ] **Étape 4 : Vérifier que les tests passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_sessions_username.py -v
```

Attendu : `PASSED`

- [ ] **Étape 5 : Lancer la suite complète**

```bash
cd /opt/stacks/wally-ai && python -m pytest -v
```

Attendu : tous PASS (régression zéro)

- [ ] **Étape 6 : Commit**

```bash
git add bot/core/sessions.py tests/test_sessions_username.py
git commit -m "feat(sessions): pass display_name as username to memory.add()"
```

---

## Task 5 — main.py : boot sync

**Files:**
- Modify: `bot/main.py`

- [ ] **Étape 1 : Ajouter le boot sync**

Dans `bot/main.py`, après la ligne `await db.cleanup_old_emotion_history()` (ligne ~65), ajouter :

```python
qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
await db.sync_memory_users_from_qdrant(qdrant_url)
logger.info("Memory users sync from Qdrant complete")
```

- [ ] **Étape 2 : Vérifier que le bot démarre sans erreur**

```bash
cd /opt/stacks/wally-ai && python -m pytest -v
```

Attendu : tous PASS (le sync échoue silencieusement si Qdrant absent en test)

- [ ] **Étape 3 : Commit**

```bash
git add bot/main.py
git commit -m "feat(main): sync memory users from Qdrant at startup"
```

---

## Task 6 — Dashboard API : POST /memory/sync + enrich /memory/search

**Files:**
- Modify: `bot/dashboard/routes/memory.py`

- [ ] **Étape 1 : Ajouter la route POST /memory/sync**

Dans `bot/dashboard/routes/memory.py`, après les imports existants, ajouter :

```python
import os
```

Puis ajouter la route (après `delete_memory`) :

```python
# ── POST /memory/sync ─────────────────────────────────────────────────────────

@router.post("/memory/sync")
async def sync_memory_users(request: Request):
    state = request.app.state.wally
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    n = await state.db.sync_memory_users_from_qdrant(qdrant_url)
    return {"synced": n}
```

- [ ] **Étape 2 : Enrichir `/memory/search` avec username**

Dans `search_memories()`, charger la map `user_id → username` avant la boucle, puis l'injecter dans les résultats :

```python
@router.get("/memory/search")
async def search_memories(request: Request, q: str | None = None):
    if not q or not q.strip():
        raise HTTPException(400, detail="q parameter required")
    state = request.app.state.wally
    mem0 = _get_mem0(request)

    users = await state.db.list_memory_users()
    username_map = {u["user_id"]: u.get("username") for u in users}

    all_results = []
    for user in users:
        uid = user["user_id"]
        platform = user["platform"]
        try:
            raw = await asyncio.to_thread(mem0.search, q, user_id=uid, limit=3)
            for r in _unwrap(raw):
                if r.get("memory"):
                    all_results.append({
                        "user_id": uid,
                        "username": username_map.get(uid),
                        "platform": platform,
                        "memory": r["memory"],
                        "score": r.get("score", 0.0),
                    })
        except Exception as exc:
            logger.warning("mem0 search failed for {uid}: {e}", uid=uid, e=exc)

    all_results.sort(key=lambda x: x["score"], reverse=True)
    return {"results": all_results}
```

- [ ] **Étape 3 : Vérifier les tests**

```bash
cd /opt/stacks/wally-ai && python -m pytest -v
```

Attendu : tous PASS

- [ ] **Étape 4 : Commit**

```bash
git add bot/dashboard/routes/memory.py
git commit -m "feat(dashboard): add POST /memory/sync route and enrich search with username"
```

---

## Task 7 — Frontend : affichage username + bouton Sync

**Files:**
- Modify: `bot/dashboard/static/app.js`

- [ ] **Étape 1 : Mettre à jour `loadMemoryUsers` — afficher username**

Dans `app.js`, fonction `loadMemoryUsers` (ligne ~582), remplacer la ligne d'affichage du nom :

```javascript
// Avant :
<span style="font-size:0.8rem">${escHtml(u.user_id.split(':').slice(1).join(':') || u.user_id)}</span>

// Après :
<span style="font-size:0.8rem">${escHtml(u.username || u.user_id.split(':').slice(1).join(':') || u.user_id)}</span>
```

- [ ] **Étape 2 : Mettre à jour `renderMemories` — header avec username**

Dans `renderMemories` (ligne ~623), remplacer l'entête :

```javascript
// Avant :
<span style="font-size:0.7rem;color:#aaa;letter-spacing:2px">${escHtml(userId)} — ${memories.length} souvenir(s)</span>

// Après :
// Récupérer username depuis la liste (passé en paramètre)
// → modifier la signature : renderMemories(userId, memories, username = null)
<span style="font-size:0.7rem;color:#aaa;letter-spacing:2px">
  ${username ? escHtml(username) + ' (' + escHtml(userId) + ')' : escHtml(userId)} — ${memories.length} souvenir(s)
</span>
```

Mettre à jour les appelants :
- `loadUserMemories` : passer `username` depuis l'état `_selectedMemUser` (stocker username au moment de `selectMemUser`)

```javascript
// Ajouter variable d'état :
let _selectedMemUsername = null;

// Dans selectMemUser :
async function selectMemUser(userId, username) {
  _selectedMemUser = userId;
  _selectedMemUsername = username || null;
  // ... (reste inchangé)
  await loadUserMemories(userId);
}

// Dans loadUserMemories :
async function loadUserMemories(userId) {
  const r = await apiFetch('/api/admin/memory/users/' + encodeURIComponent(userId));
  if (!r || !r.ok) return;
  const { memories } = await r.json();
  renderMemories(userId, memories, _selectedMemUsername);
}
```

Mettre à jour `onclick` dans `loadMemoryUsers` :
```javascript
// Avant :
onclick="selectMemUser('${escAttr(u.user_id)}')"

// Après :
onclick="selectMemUser('${escAttr(u.user_id)}','${escAttr(u.username || '')}')"
```

- [ ] **Étape 3 : Ajouter le bouton Sync**

Dans `renderMemoryTab`, ajouter le bouton dans la barre de recherche :

```javascript
// Avant :
<span style="font-size:0.7rem;color:#aaa;letter-spacing:2px;white-space:nowrap">CHERCHER</span>

// Après :
<span style="font-size:0.7rem;color:#aaa;letter-spacing:2px;white-space:nowrap">CHERCHER</span>
<button class="btn" onclick="syncMemoryUsers()"
        style="font-size:0.72rem;padding:4px 10px;white-space:nowrap">↻ SYNC</button>
```

Ajouter la fonction `syncMemoryUsers` :

```javascript
async function syncMemoryUsers() {
  const r = await apiFetch('/api/admin/memory/sync', { method: 'POST' });
  if (!r || !r.ok) { toast('Erreur sync', 'error'); return; }
  const { synced } = await r.json();
  toast(`${synced} utilisateur(s) importé(s)`, 'success');
  const filter = document.getElementById('mem-user-filter')?.value || '';
  loadMemoryUsers(filter);
}
```

- [ ] **Étape 4 : Mettre à jour `searchMemories` — afficher username**

Dans `searchMemories` (ligne ~700), remplacer l'affichage du `user_id` :

```javascript
// Avant :
<span style="font-size:0.65rem;color:#888;display:block;margin-bottom:4px">${escHtml(res.user_id)}</span>

// Après :
<span style="font-size:0.65rem;color:#888;display:block;margin-bottom:4px">
  ${res.username ? escHtml(res.username) + ' · ' : ''}${escHtml(res.user_id)}
</span>
```

- [ ] **Étape 5 : Vérifier les tests**

```bash
cd /opt/stacks/wally-ai && python -m pytest -v
```

Attendu : tous PASS (les tests JS n'existent pas — vérification visuelle)

- [ ] **Étape 6 : Commit**

```bash
git add bot/dashboard/static/app.js
git commit -m "feat(dashboard): display username in memory tab with sync button"
```

---

## Vérification finale

- [ ] **Lancer tous les tests**

```bash
cd /opt/stacks/wally-ai && python -m pytest -v
```

Attendu : tous PASS

- [ ] **Vérification manuelle**
  1. Ouvrir le dashboard → onglet mémoire
  2. Cliquer ↻ SYNC → toast "N utilisateur(s) importés"
  3. Les utilisateurs existants apparaissent avec leur pseudo (ou ID si pas encore d'interaction)
  4. Sélectionner un utilisateur → le header affiche `pseudo (discord:ID) — N souvenir(s)`
  5. Recherche globale → sous-texte avec `pseudo · discord:ID`
  6. Envoyer un message Discord → vérifier que le username est stocké dans `memory_users`
