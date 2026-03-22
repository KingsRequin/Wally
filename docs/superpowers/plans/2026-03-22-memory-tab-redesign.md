# Memory Tab Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the sidebar+detail memory tab with a card grid + modal popup layout, with categorized memories and improved filtering/sorting.

**Architecture:** Backend-first approach — DB migrations and API changes first, then fact extraction schema update, then frontend rewrite. Each task is independently testable.

**Tech Stack:** Python/FastAPI (backend), vanilla JS (frontend), aiosqlite, mem0/Qdrant, CSS glassmorphism.

**Spec:** `docs/superpowers/specs/2026-03-22-memory-tab-redesign.md`

---

### Task 1: DB migrations — avatar_url and memory_count columns

**Files:**
- Modify: `bot/db/database.py:260-289` (migration block)
- Test: `tests/test_dashboard_memory_db.py`

- [ ] **Step 1: Write failing test for new columns**

```python
# In tests/test_dashboard_memory_db.py — add at end of file
@pytest.mark.asyncio
async def test_memory_users_has_avatar_and_count_columns(tmp_path):
    from bot.db.database import Database
    db = await Database.create(MagicMock(bot=MagicMock(dashboard_token="")), db_path=str(tmp_path / "test.db"))
    await db.upsert_memory_user("discord:123", "discord", username="TestUser")
    # Verify columns exist by querying them
    row = await db.fetchone("SELECT avatar_url, memory_count FROM memory_users WHERE user_id=?", ("discord:123",))
    assert row is not None
    assert row["avatar_url"] is None
    assert row["memory_count"] == 0
    await db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dashboard_memory_db.py::test_memory_users_has_avatar_and_count_columns -v`
Expected: FAIL — columns don't exist

- [ ] **Step 3: Add migrations in database.py**

Add after the `love_updated_at` migration block (~line 283):

```python
# Migration: add avatar_url to memory_users
try:
    await conn.execute("ALTER TABLE memory_users ADD COLUMN avatar_url TEXT DEFAULT NULL")
    await conn.commit()
except aiosqlite.OperationalError:
    pass
# Migration: add memory_count to memory_users
try:
    await conn.execute("ALTER TABLE memory_users ADD COLUMN memory_count INTEGER DEFAULT 0")
    await conn.commit()
except aiosqlite.OperationalError:
    pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dashboard_memory_db.py::test_memory_users_has_avatar_and_count_columns -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot/db/database.py tests/test_dashboard_memory_db.py
git commit -m "feat(db): add avatar_url and memory_count columns to memory_users"
```

---

### Task 2: memory.add() — accept category parameter

**Files:**
- Modify: `bot/core/memory.py:161-193` (add method)
- Test: `tests/test_memory.py`

- [ ] **Step 1: Write failing test**

```python
# In tests/test_memory.py — add test
@pytest.mark.asyncio
async def test_add_with_category_passes_metadata(memory_service):
    """Category should be included in mem0 metadata alongside origin."""
    memory_service._mem0 = MagicMock()
    memory_service._mem0.add = MagicMock(return_value={"results": []})
    memory_service._db = AsyncMock()
    memory_service._db.upsert_memory_user = AsyncMock()

    await memory_service.add("discord", "123", "Likes Python", category="FAIT")

    call_args = memory_service._mem0.add.call_args
    metadata = call_args.kwargs.get("metadata", {})
    assert metadata["category"] == "FAIT"
    assert metadata["origin"] == "discord:123"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_memory.py::test_add_with_category_passes_metadata -v`
Expected: FAIL — `add()` doesn't accept `category`

- [ ] **Step 3: Update memory.add() signature and metadata**

In `bot/core/memory.py`, modify the `add()` method signature (line 161):

```python
async def add(self, platform: str, user_id: str, content: str,
              username: str = "", emotion_context: str = "",
              category: str = "") -> None:
```

And modify the metadata dict (line 170-173):

```python
metadata = {"origin": origin}
if category:
    metadata["category"] = category
result = await asyncio.to_thread(
    self._mem0.add, full_content, user_id=uid,
    metadata=metadata,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_memory.py::test_add_with_category_passes_metadata -v`
Expected: PASS

- [ ] **Step 5: Run all memory tests to check no regressions**

Run: `python -m pytest tests/test_memory.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add bot/core/memory.py tests/test_memory.py
git commit -m "feat(memory): add category parameter to memory.add()"
```

---

### Task 3: Update FACT_EXTRACTION_SCHEMA for categories

**Files:**
- Modify: `bot/core/fact_extractor.py:76-124` (schema) and `bot/core/fact_extractor.py:396-440` (_extract_facts processing)
- Modify: `bot/persona/prompts/fact_extraction_system.md`
- Test: `tests/test_fact_extractor.py`

- [ ] **Step 1: Write failing test for categorized facts**

```python
# In tests/test_fact_extractor.py — add test
@pytest.mark.asyncio
async def test_extract_facts_with_categories():
    fe = _make_fact_extractor()
    fe._openai.complete_secondary_structured = AsyncMock(return_value={
        "facts": [
            {
                "target": "Alice",
                "target_user_id": "discord:111",
                "scope": "personal",
                "facts": [
                    {"text": "Works as a developer", "category": "FAIT"},
                    {"text": "Lives in Lyon", "category": "FAIT"},
                ],
            }
        ],
        "aliases": [],
    })
    fe._db.list_aliases = AsyncMock(return_value=[])
    fe._db.list_memory_users = AsyncMock(return_value=[])

    messages = [
        {"user_id": "111", "display_name": "Alice", "content": "I'm a developer living in Lyon"},
    ]
    count = await fe._extract_facts(messages, "discord", "chan1")
    assert count == 1

    # Verify category was passed to memory.add()
    call_args = fe._memory.add.call_args
    assert call_args.kwargs.get("category") == "FAIT"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fact_extractor.py::test_extract_facts_with_categories -v`
Expected: FAIL — schema expects strings, not objects

- [ ] **Step 3: Update FACT_EXTRACTION_SCHEMA**

In `bot/core/fact_extractor.py`, replace the inner `facts` field in the schema (line 94):

```python
"facts": {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "category": {
                "type": "string",
                "enum": ["FAIT", "PREF", "LANG", "REL"],
            },
        },
        "required": ["text", "category"],
        "additionalProperties": False,
    },
},
```

- [ ] **Step 4: Update _extract_facts() processing logic**

In `bot/core/fact_extractor.py`, update the facts processing loop (~line 398-440). The `facts_list` now contains objects instead of strings:

```python
facts_list = entry.get("facts", [])
if not facts_list:
    continue

scope = entry.get("scope", "personal")

# Build text from fact objects (backward-compat: handle both str and dict)
fact_items = []
for f in facts_list:
    if isinstance(f, dict):
        fact_items.append(f)
    else:
        fact_items.append({"text": str(f), "category": "FAIT"})

facts_text = "\n".join(f"- {fi['text']}" for fi in fact_items)

# Determine dominant category for the batch
categories = [fi.get("category", "FAIT") for fi in fact_items]
dominant_category = max(set(categories), key=categories.count) if categories else "FAIT"
```

Then pass `category=dominant_category` to `memory.add()` and `memory.add_global()` calls:

For community scope (~line 408) — `add_global` intentionally does NOT receive category (global facts are community knowledge, not per-user categorized):
```python
await self._memory.add_global(facts_text)
```

For personal scope with known user (~line 423):
```python
await self._memory.add(plat, raw_id, facts_text, category=dominant_category)
```

For unknown user (~line 433):
```python
await self._memory.add("unknown", nickname, facts_text, category=dominant_category)
```

- [ ] **Step 5: Update fact_extraction_system.md prompt**

Add to `bot/persona/prompts/fact_extraction_system.md` the instruction to classify facts:

```
Chaque fait doit être classé dans une catégorie :
- "FAIT" : information factuelle (métier, lieu, âge, hobbies, etc.)
- "PREF" : préférence ou goût (aime/n'aime pas, préfère, etc.)
- "LANG" : langue parlée ou préférence linguistique
- "REL" : relation avec une autre personne ou un autre utilisateur

Format de chaque fait : {"text": "le fait", "category": "FAIT|PREF|LANG|REL"}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_fact_extractor.py::test_extract_facts_with_categories -v`
Expected: PASS

- [ ] **Step 7: Run all fact extractor tests**

Run: `python -m pytest tests/test_fact_extractor.py -v`
Expected: All PASS (backward-compat handles old string format)

- [ ] **Step 8: Commit**

```bash
git add bot/core/fact_extractor.py bot/persona/prompts/fact_extraction_system.md tests/test_fact_extractor.py
git commit -m "feat(facts): add category classification to fact extraction schema"
```

---

### Task 4: Backend — update GET /memory/users with sort_by, trust, love, avatar

**Files:**
- Modify: `bot/dashboard/routes/memory.py:34-81`
- Test: `tests/test_dashboard_memory_routes.py`

- [ ] **Step 1: Write failing test for sort_by parameter**

```python
# In tests/test_dashboard_memory_routes.py — add test
# Uses existing pattern: _make_state() + async with _make_client(state)
@pytest.mark.asyncio
async def test_list_users_sort_by_trust():
    state, _, db = _make_state()
    db.list_memory_users.return_value = [
        {"user_id": "discord:1", "platform": "discord", "username": "Alice", "memory_count": 5, "avatar_url": None},
        {"user_id": "discord:2", "platform": "discord", "username": "Bob", "memory_count": 10, "avatar_url": None},
    ]
    db.list_link_proposals = AsyncMock(return_value=[])
    db.get_trust_score = AsyncMock(side_effect=lambda p, uid: 0.9 if "1" in uid else 0.3)
    db.get_love_score = AsyncMock(side_effect=lambda p, uid, **kw: 0.5 if "1" in uid else 0.8)

    async with _make_client(state) as client:
        r = await client.get("/api/admin/memory/users?sort_by=trust", headers=HEADERS)
    assert r.status_code == 200
    users = r.json()["users"]
    assert users[0]["trust_score"] >= users[1]["trust_score"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dashboard_memory_routes.py::test_list_users_sort_by_trust -v`
Expected: FAIL — endpoint doesn't accept sort_by

- [ ] **Step 3: Update list_users endpoint**

In `bot/dashboard/routes/memory.py`, update the `list_users` function:

```python
@router.get("/memory/users")
async def list_users(request: Request, q: str | None = None,
                     show_all: str | None = None,
                     sort_by: str = "memories"):
    state = request.app.state.wally
    include_no_memory = show_all == "1"
    users = await state.db.list_memory_users(q, include_no_memory=include_no_memory)

    # ... existing alias filtering code stays the same ...

    # Enrich with trust, love scores and ensure avatar_url/memory_count
    for user in merged_users:
        platform = user.get("platform", "")
        raw_id = user["user_id"].replace(f"{platform}:", "") if platform else user["user_id"]
        try:
            user["trust_score"] = await state.db.get_trust_score(platform, raw_id)
        except Exception:
            user["trust_score"] = 0.0
        try:
            user["love_score"] = await state.db.get_love_score(platform, raw_id)
        except Exception:
            user["love_score"] = 0.0
        user.setdefault("avatar_url", None)
        user.setdefault("memory_count", 0)

    # Sort
    sort_keys = {
        "memories": lambda u: u.get("memory_count", 0),
        "trust": lambda u: u.get("trust_score", 0.0),
        "love": lambda u: u.get("love_score", 0.0),
        "name": lambda u: (u.get("username") or "").lower(),
    }
    key_fn = sort_keys.get(sort_by, sort_keys["memories"])
    reverse = sort_by != "name"
    merged_users.sort(key=key_fn, reverse=reverse)

    return {"users": merged_users}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dashboard_memory_routes.py::test_list_users_sort_by_trust -v`
Expected: PASS

- [ ] **Step 5: Run all dashboard memory route tests**

Run: `python -m pytest tests/test_dashboard_memory_routes.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add bot/dashboard/routes/memory.py tests/test_dashboard_memory_routes.py
git commit -m "feat(api): add sort_by, trust/love scores to GET /memory/users"
```

---

### Task 5: Backend — update GET /memory/users/{user_id} to return category metadata

**Files:**
- Modify: `bot/dashboard/routes/memory.py:115-170`
- Test: `tests/test_dashboard_memory_routes.py`

- [ ] **Step 1: Write failing test**

```python
@pytest.mark.asyncio
async def test_get_user_memories_includes_category():
    state, mock_mem0, db = _make_state()
    mock_mem0.get_all.return_value = [
        {
            "id": "mem1",
            "memory": "Likes Python",
            "metadata": {"origin": "discord:123", "category": "PREF"},
            "created_at": "2026-03-20",
            "updated_at": "2026-03-20",
        },
        {
            "id": "mem2",
            "memory": "Lives in Lyon",
            "metadata": {"origin": "discord:123"},  # no category
            "created_at": "2026-03-19",
            "updated_at": "2026-03-19",
        },
    ]
    db.list_link_proposals = AsyncMock(return_value=[])

    async with _make_client(state) as client:
        r = await client.get("/api/admin/memory/users/discord:123", headers=HEADERS)
    assert r.status_code == 200
    memories = r.json()["memories"]
    assert memories[0]["category"] == "PREF"
    assert memories[1]["category"] == ""  # uncategorized
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dashboard_memory_routes.py::test_get_user_memories_includes_category -v`
Expected: FAIL — no `category` in response

- [ ] **Step 3: Update get_user_memories to extract category from metadata**

In `bot/dashboard/routes/memory.py`, update the memory dict construction in `get_user_memories()` (~line 129-140):

```python
memories = [
    {
        "id": r.get("id"),
        "memory": r.get("memory", ""),
        "source": user_id,
        "source_platform": _extract_origin(r, user_id),
        "category": (r.get("metadata") or {}).get("category", ""),
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
    }
    for r in _unwrap(results)
    if r.get("memory")
]
```

Apply the same change to the alias memories loop (~line 153-160):

```python
memories.append({
    "id": r.get("id"),
    "memory": r.get("memory", ""),
    "source": alias_id,
    "source_platform": _extract_origin(r, alias_id),
    "category": (r.get("metadata") or {}).get("category", ""),
    "created_at": r.get("created_at"),
    "updated_at": r.get("updated_at"),
})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dashboard_memory_routes.py::test_get_user_memories_includes_category -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot/dashboard/routes/memory.py tests/test_dashboard_memory_routes.py
git commit -m "feat(api): include category metadata in GET /memory/users/{user_id}"
```

---

### Task 6: Backend — add category to POST/PUT memory endpoints

**Files:**
- Modify: `bot/dashboard/routes/memory.py:175-233` (AddMemoryRequest, UpdateMemoryRequest, handlers)
- Test: `tests/test_dashboard_memory_routes.py`

- [ ] **Step 1: Write failing test**

```python
@pytest.mark.asyncio
async def test_add_memory_with_category():
    state, mock_mem0, db = _make_state()
    mock_mem0.add.return_value = {"results": []}
    db.upsert_memory_user = AsyncMock()

    async with _make_client(state) as client:
        r = await client.post("/api/admin/memory/users/discord:123/memories",
                              json={"content": "Likes cats", "category": "PREF"},
                              headers=HEADERS)
    assert r.status_code == 200
    # Verify category was passed in metadata
    call_args = mock_mem0.add.call_args
    metadata = call_args.kwargs.get("metadata", {})
    assert metadata.get("category") == "PREF"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dashboard_memory_routes.py::test_add_memory_with_category -v`
Expected: FAIL — AddMemoryRequest doesn't have category field

- [ ] **Step 3: Update request models and handlers**

In `bot/dashboard/routes/memory.py`:

Update `AddMemoryRequest` (~line 175):
```python
class AddMemoryRequest(BaseModel):
    content: str
    category: str = ""
```

Update `add_memory` handler (~line 192-195):
```python
metadata = {"origin": user_id}
if body.category:
    metadata["category"] = body.category
result = await asyncio.to_thread(
    mem0.add, content, user_id=user_id,
    metadata=metadata,
)
```

Update `UpdateMemoryRequest` (~line 219):
```python
class UpdateMemoryRequest(BaseModel):
    content: str
    category: str = ""
```

Update `update_memory` handler to also update category metadata if provided (~line 231).

**Important:** Do NOT instantiate a Qdrant client directly — the collection name varies by mem0 version and direct `set_payload` would overwrite the existing `origin` metadata. Instead, use Qdrant's `set_payload` with a nested key path to only update the category field, or read-merge-write via mem0. The safest approach is to read the existing point, merge the category, and write back:

```python
await asyncio.to_thread(mem0.update, memory_id, content)
# Update category in metadata if provided
if body.category:
    try:
        # Read existing memory to get current metadata
        existing = await asyncio.to_thread(mem0.get, memory_id)
        if existing:
            current_meta = (existing.get("metadata") or {}).copy()
            current_meta["category"] = body.category
            # mem0 doesn't expose metadata-only update, use Qdrant directly
            # with the correct collection from mem0's config
            import os
            from qdrant_client import QdrantClient
            qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
            qc = QdrantClient(url=qdrant_url)
            # Use overwrite=False to merge into existing payload
            qc.set_payload(
                collection_name="m0_default",
                payload={"metadata": current_meta},
                points=[memory_id],
            )
    except Exception as exc:
        logger.warning("Failed to update category metadata: {e}", e=exc)
```

**Note for implementer:** Verify the actual collection name by checking `mem0`'s configuration or running `qc.get_collections()` before hardcoding. The collection name may be `m0_default`, `mem0`, or another value depending on the mem0 version.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dashboard_memory_routes.py::test_add_memory_with_category -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot/dashboard/routes/memory.py tests/test_dashboard_memory_routes.py
git commit -m "feat(api): add category support to POST/PUT memory endpoints"
```

---

### Task 7: Backend — merge resolve-usernames into sync + update memory_count

**Files:**
- Modify: `bot/dashboard/routes/memory.py:399-463`
- Test: `tests/test_dashboard_memory_routes.py`

- [ ] **Step 1: Write failing test**

```python
@pytest.mark.asyncio
async def test_sync_also_resolves_usernames():
    state, mock_mem0, db = _make_state()
    db.sync_memory_users_from_qdrant = AsyncMock(return_value=3)
    db.list_memory_users = AsyncMock(return_value=[
        {"user_id": "discord:999", "platform": "discord", "username": ""},
    ])
    db.upsert_memory_user = AsyncMock()
    db.execute = AsyncMock()
    mock_mem0.get_all.return_value = []
    mock_discord = MagicMock()
    mock_user = MagicMock()
    mock_user.display_name = "ResolvedName"
    mock_user.name = "ResolvedName"
    mock_discord.fetch_user = AsyncMock(return_value=mock_user)
    state.discord_bot = mock_discord
    state.twitch_bot = None

    async with _make_client(state) as client:
        r = await client.post("/api/admin/memory/sync", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["synced"] == 3
    assert data["resolved"] >= 0  # New field
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dashboard_memory_routes.py::test_sync_also_resolves_usernames -v`
Expected: FAIL — sync doesn't return `resolved`

- [ ] **Step 3: Update sync endpoint to also resolve usernames**

In `bot/dashboard/routes/memory.py`, replace the `sync_memory_users` function (~line 399-404):

```python
@router.post("/memory/sync")
async def sync_memory_users(request: Request):
    state = request.app.state.wally
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    n = await state.db.sync_memory_users_from_qdrant(qdrant_url)

    # Also resolve usernames (merge of former resolve-usernames endpoint)
    resolved = 0
    users = await state.db.list_memory_users(include_no_memory=True)

    if state.discord_bot is not None:
        for user in users:
            if user["platform"] != "discord" or user.get("username"):
                continue
            raw_id = user["user_id"].replace("discord:", "")
            if not raw_id.isdigit():
                continue
            try:
                discord_user = await state.discord_bot.fetch_user(int(raw_id))
                name = discord_user.display_name or discord_user.name
                if name:
                    await state.db.upsert_memory_user(user["user_id"], "discord", username=name)
                    resolved += 1
            except Exception as e:
                logger.warning("Impossible de résoudre discord:{id}: {e}", id=raw_id, e=e)

    if state.twitch_bot is not None:
        twitch_to_resolve = []
        for user in users:
            if user["platform"] != "twitch" or user.get("username"):
                continue
            raw_id = user["user_id"].replace("twitch:", "")
            if raw_id.isdigit():
                twitch_to_resolve.append((user["user_id"], int(raw_id)))
        for i in range(0, len(twitch_to_resolve), 100):
            batch = twitch_to_resolve[i:i + 100]
            ids = [uid for _, uid in batch]
            try:
                twitch_users = await state.twitch_bot.fetch_users(ids=ids)
                id_to_name = {str(tu.id): tu.display_name or tu.name for tu in twitch_users}
                for full_id, numeric_id in batch:
                    name = id_to_name.get(str(numeric_id))
                    if name:
                        await state.db.upsert_memory_user(full_id, "twitch", username=name)
                        resolved += 1
            except Exception as e:
                logger.warning("Impossible de résoudre batch Twitch: {e}", e=e)

    # Update memory_count for all users
    mem0 = _get_mem0(request)
    for user in users:
        try:
            results = await asyncio.to_thread(mem0.get_all, user_id=user["user_id"])
            count = len(_unwrap(results))
            await state.db.execute(
                "UPDATE memory_users SET memory_count=? WHERE user_id=?",
                (count, user["user_id"]),
            )
        except Exception:
            pass

    return {"synced": n, "resolved": resolved}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dashboard_memory_routes.py::test_sync_also_resolves_usernames -v`
Expected: PASS

- [ ] **Step 5: Run all route tests**

Run: `python -m pytest tests/test_dashboard_memory_routes.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add bot/dashboard/routes/memory.py tests/test_dashboard_memory_routes.py
git commit -m "feat(api): merge resolve-usernames into sync, add memory_count update"
```

---

### Task 8: Frontend CSS — grid layout, cards, modal, link mode

**Files:**
- Modify: `bot/dashboard/static/style.css:881-1260` (replace mem-sidebar/mem-detail/mem-layout)

- [ ] **Step 1: Replace sidebar+detail CSS with grid+modal+card styles**

Remove/replace the old `.mem-layout`, `.mem-sidebar`, `.mem-detail`, `.mem-user-item`, `.mem-user-list`, `.mem-sidebar-filter`, `.mem-sidebar-actions` classes (lines 881-1020).

Add new CSS classes:

```css
/* ── Memory Grid Layout ──────────────────────────────────────────── */
.mem-toolbar {
  padding: 12px 16px;
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 12px;
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.mem-search {
  flex: 1;
  min-width: 180px;
  max-width: 300px;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 8px;
  padding: 7px 10px;
  font-size: 12px;
  color: #e2e8f0;
}
.mem-search::placeholder { color: #64748b; }
.mem-platform-pills {
  display: flex;
  gap: 2px;
  background: rgba(255,255,255,0.05);
  border-radius: 8px;
  padding: 2px;
}
.mem-platform-pill {
  font-size: 11px;
  padding: 5px 10px;
  border-radius: 6px;
  cursor: pointer;
  color: #64748b;
  border: none;
  background: transparent;
  transition: all 0.2s;
}
.mem-platform-pill.active {
  background: rgba(6,182,212,0.2);
  color: #06b6d4;
}
.mem-sort-select {
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 8px;
  padding: 5px 10px;
  font-size: 11px;
  color: #94a3b8;
  cursor: pointer;
}
.mem-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: #64748b;
  cursor: pointer;
}
.mem-toggle-track {
  width: 32px;
  height: 18px;
  border-radius: 9px;
  background: rgba(255,255,255,0.1);
  position: relative;
  transition: background 0.2s;
}
.mem-toggle-track.active {
  background: rgba(6,182,212,0.3);
}
.mem-toggle-thumb {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #64748b;
  position: absolute;
  top: 2px;
  left: 2px;
  transition: all 0.2s;
}
.mem-toggle-track.active .mem-toggle-thumb {
  background: #06b6d4;
  left: 16px;
}
.mem-action-btn {
  font-size: 11px;
  padding: 5px 10px;
  border-radius: 8px;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.08);
  color: #94a3b8;
  cursor: pointer;
  transition: all 0.2s;
}
.mem-action-btn:hover {
  background: rgba(255,255,255,0.08);
  color: #e2e8f0;
}

/* ── User Card Grid ──────────────────────────────────────────────── */
.mem-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
@media (max-width: 1200px) { .mem-grid { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 768px) { .mem-grid { grid-template-columns: repeat(2, 1fr); } }

.mem-card {
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 12px;
  padding: 14px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
  position: relative;
}
.mem-card:hover {
  border-color: rgba(6,182,212,0.3);
  background: rgba(255,255,255,0.07);
}
.mem-card.no-memory {
  opacity: 0.6;
  border-style: dashed;
}
.mem-card-avatar {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  margin: 0 auto 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  color: #fff;
  background-size: cover;
  background-position: center;
}
.mem-card-avatar.discord {
  background: linear-gradient(135deg, #5865F2, #3b82f6);
  box-shadow: 0 0 0 2px rgba(88,101,242,0.3);
}
.mem-card-avatar.twitch {
  background: linear-gradient(135deg, #9146FF, #a855f7);
  box-shadow: 0 0 0 2px rgba(145,70,255,0.3);
}
.mem-card-name {
  font-size: 13px;
  font-weight: 600;
  color: #e2e8f0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.mem-card-sub {
  font-size: 10px;
  color: #64748b;
  margin-bottom: 8px;
}
.mem-card-bars {
  display: flex;
  gap: 4px;
}
.mem-card-bar {
  flex: 1;
  height: 4px;
  border-radius: 2px;
  background: rgba(255,255,255,0.1);
  overflow: hidden;
}
.mem-card-bar-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s;
}
.mem-card-bar-fill.trust { background: #06b6d4; }
.mem-card-bar-fill.love { background: #ec4899; }
.mem-card-stats {
  display: flex;
  gap: 12px;
  justify-content: center;
  margin-top: 4px;
  font-size: 9px;
  color: #475569;
}
.mem-card-link-badge {
  position: absolute;
  top: 8px;
  right: 8px;
  font-size: 9px;
  padding: 2px 6px;
  border-radius: 6px;
  background: rgba(6,182,212,0.15);
  color: #06b6d4;
}

/* ── Link Mode ───────────────────────────────────────────────────── */
.mem-link-banner {
  background: rgba(6,182,212,0.1);
  border: 1px solid rgba(6,182,212,0.2);
  border-radius: 10px;
  padding: 10px 14px;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.mem-link-banner-info {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #06b6d4;
}
.mem-card.link-mode { cursor: crosshair; }
.mem-card.link-source { opacity: 0.4; pointer-events: none; }
.mem-card.link-mode:hover {
  box-shadow: 0 0 12px rgba(6,182,212,0.2);
}

/* ── Modal ───────────────────────────────────────────────────────── */
.mem-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.6);
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  animation: fadeIn 0.15s ease;
}
.mem-modal {
  background: rgba(30,30,40,0.95);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 14px;
  padding: 20px;
  width: 90%;
  max-width: 650px;
  max-height: 80vh;
  overflow-y: auto;
  backdrop-filter: blur(10px);
  animation: scaleIn 0.15s ease;
}
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
@keyframes scaleIn { from { opacity: 0; transform: scale(0.95); } to { opacity: 1; transform: scale(1); } }

.mem-modal-header {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 16px;
  padding-bottom: 14px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}
.mem-modal-avatar {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  color: #fff;
  flex-shrink: 0;
  background-size: cover;
  background-position: center;
}
.mem-modal-info { flex: 1; }
.mem-modal-name { font-size: 17px; font-weight: 600; color: #e2e8f0; }
.mem-modal-sub { font-size: 11px; color: #64748b; margin-top: 2px; }
.mem-modal-stats {
  display: flex;
  gap: 12px;
  align-items: center;
}
.mem-modal-stat {
  text-align: center;
}
.mem-modal-stat-value { font-size: 16px; font-weight: 600; }
.mem-modal-stat-value.trust { color: #06b6d4; }
.mem-modal-stat-value.love { color: #ec4899; }
.mem-modal-stat-value.count { color: #e2e8f0; }
.mem-modal-stat-label { font-size: 9px; color: #475569; }
.mem-modal-close {
  font-size: 18px;
  color: #475569;
  cursor: pointer;
  margin-left: 8px;
  background: none;
  border: none;
}
.mem-modal-close:hover { color: #e2e8f0; }

/* Modal actions */
.mem-modal-actions {
  display: flex;
  gap: 6px;
  margin-bottom: 14px;
}
.mem-modal-action {
  font-size: 10px;
  padding: 4px 10px;
  border-radius: 8px;
  cursor: pointer;
  border: 1px solid;
  transition: all 0.2s;
}
.mem-modal-action.add {
  background: rgba(6,182,212,0.1);
  border-color: rgba(6,182,212,0.2);
  color: #06b6d4;
}
.mem-modal-action.link {
  background: rgba(255,255,255,0.05);
  border-color: rgba(255,255,255,0.08);
  color: #94a3b8;
}
.mem-modal-action.danger {
  background: rgba(239,68,68,0.1);
  border-color: rgba(239,68,68,0.15);
  color: #ef4444;
  margin-left: auto;
}

/* Modal search */
.mem-modal-search {
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 8px;
  padding: 7px 10px;
  font-size: 11px;
  color: #e2e8f0;
  width: 100%;
  margin-bottom: 14px;
}
.mem-modal-search::placeholder { color: #64748b; }

/* ── Memory Categories ───────────────────────────────────────────── */
.mem-category {
  margin-bottom: 14px;
}
.mem-category-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  cursor: pointer;
  user-select: none;
}
.mem-category-chevron {
  font-size: 10px;
  color: #475569;
  transition: transform 0.2s;
}
.mem-category-chevron.collapsed { transform: rotate(-90deg); }
.mem-category-name {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.mem-category-name.fait { color: #22c55e; }
.mem-category-name.pref { color: #3b82f6; }
.mem-category-name.lang { color: #eab308; }
.mem-category-name.rel { color: #a855f7; }
.mem-category-name.other { color: #64748b; }
.mem-category-count {
  font-size: 10px;
  color: #475569;
}
.mem-category-body {
  padding-left: 4px;
}
.mem-category-body.collapsed { display: none; }

/* ── Memory Entry ────────────────────────────────────────────────── */
.mem-entry {
  padding: 8px 10px;
  margin-bottom: 4px;
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.05);
  border-radius: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: #cbd5e1;
}
.mem-entry:hover { border-color: rgba(255,255,255,0.12); }
.mem-entry-text { flex: 1; line-height: 1.4; }
.mem-entry-source {
  font-size: 9px;
  color: #475569;
  flex-shrink: 0;
}
.mem-entry-actions {
  opacity: 0;
  transition: opacity 0.15s;
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}
.mem-entry:hover .mem-entry-actions { opacity: 1; }
.mem-entry-action {
  font-size: 9px;
  cursor: pointer;
  color: #64748b;
  background: none;
  border: none;
  padding: 2px;
}
.mem-entry-action:hover { color: #e2e8f0; }

/* ── Linked Accounts Section ─────────────────────────────────────── */
.mem-linked-section {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid rgba(255,255,255,0.06);
}
.mem-linked-title {
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 8px;
}
.mem-linked-pills { display: flex; gap: 8px; flex-wrap: wrap; }
.mem-linked-pill {
  padding: 6px 10px;
  border-radius: 8px;
  font-size: 11px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.mem-linked-pill.discord {
  background: rgba(88,101,242,0.1);
  border: 1px solid rgba(88,101,242,0.2);
  color: #5865F2;
}
.mem-linked-pill.twitch {
  background: rgba(145,70,255,0.1);
  border: 1px solid rgba(145,70,255,0.2);
  color: #a855f7;
}
.mem-linked-pill-unlink {
  font-size: 9px;
  color: #64748b;
  cursor: pointer;
  background: none;
  border: none;
}
.mem-linked-pill-unlink:hover { color: #ef4444; }
```

- [ ] **Step 2: Verify CSS loads without errors**

Open dashboard in browser, check no console errors. The old memory tab will look broken — this is expected since the JS hasn't been updated yet.

- [ ] **Step 3: Commit**

```bash
git add bot/dashboard/static/style.css
git commit -m "feat(css): replace sidebar layout with grid+modal+card styles for memory tab"
```

---

### Task 9: Frontend JS — rewrite renderMemoryTab() with grid, toolbar, cards

**Files:**
- Modify: `bot/dashboard/static/app.js:1315-1566` (renderMemoryTab, loadMemoryUsers, related functions)

- [ ] **Step 1: Rewrite renderMemoryTab()**

Replace `renderMemoryTab()` (line 1315-1356) with the new toolbar + grid layout. This function creates the HTML structure; `loadMemoryUsers()` populates the grid.

The toolbar includes: search input, platform pills (Tous/Discord/Twitch), sort dropdown, "sans mémoire" toggle, Sync button, Analyser button.

Below the toolbar: a `<div class="mem-grid" id="mem-grid"></div>` container.

- [ ] **Step 2: Rewrite loadMemoryUsers()**

Replace `loadMemoryUsers()` (line 1500-1566). Fetch from `/api/admin/memory/users` with query params (`q`, `show_all`, `sort_by`). Render each user as a `.mem-card` with:
- Avatar (use `avatar_url` if present, fallback to initial letter with platform gradient)
- Username, platform + memory count subtitle
- Trust and love bars with numeric values
- Link badge if `linked_accounts` present
- Click handler: `openUserModal(userId)`

- [ ] **Step 3: Add filter/sort event handlers**

Wire up the toolbar controls:
- Search input: debounced (300ms), calls `loadMemoryUsers()` with query
- Platform pills: active state toggle, filter param
- Sort dropdown: change event, reloads grid
- Toggle: show/hide no-memory users

- [ ] **Step 4: Remove old sidebar functions**

Remove/replace: `selectMemUser()`, `refreshUserList()`, `toggleShowAll()`, `showAddUserForm()`, `submitAddUser()`, `syncMemoryUsers()`, `resolveUsernames()`. The sync and analyze functions stay but call updated endpoints.

- [ ] **Step 5: Test in browser**

Open dashboard, verify:
- Grid renders with user cards
- Search filters in real-time
- Platform pills filter correctly
- Sort dropdown works
- Toggle hides/shows no-memory users

- [ ] **Step 6: Commit**

```bash
git add bot/dashboard/static/app.js
git commit -m "feat(js): rewrite memory tab with card grid layout and toolbar"
```

---

### Task 10: Frontend JS — user detail modal with categorized memories

**Files:**
- Modify: `bot/dashboard/static/app.js:1593-1900` (loadUserDetail, memory CRUD, search)

- [ ] **Step 1: Create openUserModal() function**

New function that:
1. Fetches user detail from `GET /memory/users/{userId}`
2. Creates modal backdrop + modal DOM
3. Renders header (avatar, name, platform, stats)
4. Renders action bar (add memory, link account, delete all)
5. Renders search input
6. Groups memories by `category` field (FAIT/PREF/LANG/REL/empty→"other")
7. Within each category, sorts by `updated_at` descending
8. Renders collapsible category sections with memory entries
9. Renders linked accounts section at bottom
10. Appends modal to document.body
11. Click on backdrop or ✕ closes modal

- [ ] **Step 2: Implement category grouping and collapsing**

```javascript
const CATEGORIES = [
  { key: 'FAIT', label: 'Faits', css: 'fait' },
  { key: 'PREF', label: 'Préférences', css: 'pref' },
  { key: 'LANG', label: 'Langue', css: 'lang' },
  { key: 'REL', label: 'Relations', css: 'rel' },
  { key: '', label: 'Non classé', css: 'other' },
];
```

Group `memories` array by `category`. For each non-empty category, render a `.mem-category` section. Chevron toggles `.collapsed` class on body.

- [ ] **Step 3: Implement memory CRUD in modal context**

- Add memory: inline form with text input + category dropdown, POST then refresh modal
- Edit memory: inline input replacing text, PUT then refresh modal
- Delete memory: confirm, DELETE then refresh modal
- Delete all: confirm, DELETE then close modal and refresh grid
- Search: filter visible entries across all categories (client-side filter on `.mem-entry-text`)

- [ ] **Step 4: Test in browser**

Verify:
- Modal opens on card click
- Categories display correctly (grouped, colored, collapsible)
- Memories sorted by date within categories
- Source icons (🤖/✍️) display correctly
- Edit/delete buttons appear on hover
- Add memory form works with category selector
- Search filters across categories
- Modal closes on backdrop click or ✕

- [ ] **Step 5: Commit**

```bash
git add bot/dashboard/static/app.js
git commit -m "feat(js): add user detail modal with categorized memories"
```

---

### Task 11: Frontend JS — account linking flow (grid selection mode)

**Files:**
- Modify: `bot/dashboard/static/app.js` (link mode functions ~1358-1443)

- [ ] **Step 1: Implement link mode from modal**

When "🔗 Lier un compte" is clicked in the modal:
1. Store `linkSourceUserId` and `linkSourceUsername`
2. Close modal
3. Show `.mem-link-banner` above grid with source user info + cancel button
4. Add `.link-mode` class to all cards except source (which gets `.link-source`)
5. On card click in link mode: show `confirm("Lier {source} avec {target} ?")`
6. On confirm: `POST /api/admin/links/manual` with canonical + alias IDs
7. On success: exit link mode, reopen modal on source user via `openUserModal(sourceUserId)`
8. Cancel button: remove link mode classes, hide banner

- [ ] **Step 2: Test in browser**

Verify:
- "Lier un compte" closes modal, shows banner
- Cards get crosshair cursor except source (grayed out)
- Clicking a card shows confirmation
- On confirm: link created, modal reopens with linked account visible
- Cancel exits link mode cleanly

- [ ] **Step 3: Commit**

```bash
git add bot/dashboard/static/app.js
git commit -m "feat(js): add grid-based account linking flow with modal reopen"
```

---

### Task 12: Cleanup — remove old sidebar code and unused CSS

**Files:**
- Modify: `bot/dashboard/static/app.js` (remove dead functions)
- Modify: `bot/dashboard/static/style.css` (remove old .mem-sidebar, .mem-detail, etc.)

- [ ] **Step 1: Remove old functions from app.js**

Remove functions that are fully replaced and no longer called:
- `selectMemUser()`
- `refreshUserList()`
- `toggleShowAll()`
- `showAddUserForm()` / `submitAddUser()`
- `showInlineLink()` / `submitInlineLink()`
- Old `loadUserDetail()` (replaced by `openUserModal()`)
- `toggleLinkMode()` / `updateLinkModeBar()` / `handleLinkModeClick()` / `confirmLinkSelection()` (replaced by new link mode)

Keep: `syncMemoryUsers()`, `resolveUsernames()` (now internal), `analyzeLinks()`, `acceptLink()`, `rejectLink()`, `unlinkAccounts()`, all global memory functions, all dashboard functions.

- [ ] **Step 2: Remove old CSS classes**

Remove from style.css the old classes that are no longer referenced:
- `.mem-sidebar`, `.mem-sidebar-filter`, `.mem-sidebar-actions`
- `.mem-user-list`, `.mem-user-item` (and variants)
- `.mem-user-header`, `.mem-user-name`, `.mem-user-meta`
- `.mem-detail`, `.mem-empty-state`, `.mem-detail-header`, `.mem-detail-user`, `.mem-detail-platform`, `.mem-detail-name`, `.mem-detail-id`, `.mem-detail-actions`, `.mem-detail-section`, `.mem-detail-section-title`
- `.mem-link-card` (and variants), `.mem-link-status`, `.mem-link-confidence`, `.mem-link-actions`
- `.mem-detail-memories` (replaced by `.mem-category`)
- Old `.mem-entry-edit`, `.mem-entry-delete` (replaced by `.mem-entry-action`)

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All existing tests pass (frontend changes don't affect Python tests)

- [ ] **Step 4: Test full flow in browser**

End-to-end verification:
1. Open Memory tab → grid of user cards loads
2. Search filters grid
3. Platform pills work
4. Sort dropdown works
5. Toggle hides no-memory users
6. Click card → modal opens with categorized memories
7. Add/edit/delete memory works
8. Link account flow: modal → grid selection → confirm → modal reopens
9. Global and Dashboard sub-tabs still work
10. Sync button works

- [ ] **Step 5: Commit**

```bash
git add bot/dashboard/static/app.js bot/dashboard/static/style.css
git commit -m "refactor: remove old sidebar memory tab code, clean up CSS"
```

---

### Task 13: Final integration test and commit

- [ ] **Step 1: Run full Python test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All tests pass

- [ ] **Step 2: Visual QA pass**

Verify glassmorphism consistency:
- Backgrounds use `rgba(255,255,255, 0.03-0.05)`
- Borders are `1px solid rgba(255,255,255, 0.08)`
- Border-radius `12px`-`14px`
- No hard shadows, no neobrutalism
- Emotion colors match spec
- Responsive at 768px and 1200px breakpoints

- [ ] **Step 3: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: final polish for memory tab redesign"
```
