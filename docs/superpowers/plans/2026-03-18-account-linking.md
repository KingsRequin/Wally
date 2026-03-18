# Account Linking (Twitch ↔ Discord) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre de lier manuellement un compte Twitch et un compte Discord (même personne réelle) afin que leurs mémoires mem0 fusionnent en un profil unique, avec analyse de similarité de pseudo et approbation manuelle dans le dashboard.

**Architecture:** Nouvelle table `user_links` en DB. `MemoryService` maintient un cache d'alias `{alias_id → canonical_id}` pour résoudre les IDs au runtime de façon transparente. `account_linker.py` calcule les scores Jaro-Winkler et génère les propositions. Le dashboard expose 4 routes admin + une section UI dédiée. L'identité Discord est toujours canonique (ID numérique stable) ; l'identité Twitch est l'alias.

**Tech Stack:** Python, aiosqlite, jellyfish (Jaro-Winkler), FastAPI, pytest, httpx (tests).

---

## File Map

| Fichier | Action | Description |
|---|---|---|
| `requirements.txt` | Modifier | Ajouter `jellyfish>=0.11.2` |
| `bot/config.py` | Modifier | Ajouter `link_min_confidence: float = 0.75` dans `BotConfig` |
| `config.yaml` | Modifier | Ajouter `link_min_confidence: 0.75` sous `bot:` |
| `bot/db/database.py` | Modifier | Table `user_links`, 5 nouvelles méthodes |
| `bot/core/account_linker.py` | Créer | `_normalize()`, `score()`, `analyze_all()`, `analyze_new_user()` |
| `bot/core/memory.py` | Modifier | `_alias_cache`, `load_aliases()`, `_user_id()` avec résolution |
| `bot/main.py` | Modifier | Appel `await memory.load_aliases(db)` après `memory.set_db(db)` |
| `bot/dashboard/routes/sse.py` | Modifier | Ajouter `broadcast_event(data: dict)` (sync, put_nowait) |
| `bot/dashboard/routes/links.py` | Créer | 4 routes admin : GET list, POST analyze, POST accept, POST reject |
| `bot/dashboard/app.py` | Modifier | Importer et inclure le router links |
| `bot/dashboard/static/index.html` | Modifier | Onglet "🔗 LIAISONS" dans tabs-admin + section HTML |
| `bot/dashboard/static/app.js` | Modifier | Logique JS : fetch, render cards, accept/reject, SSE discriminateur |
| `tests/test_account_linker.py` | Créer | Tests normalisation + scoring + seuil |
| `tests/test_memory_alias.py` | Créer | Tests résolution d'alias dans `_user_id()` |
| `tests/test_dashboard_links.py` | Créer | Tests routes GET/POST via httpx AsyncClient |

---

### Task 1 : Dépendance jellyfish + BotConfig.link_min_confidence

**Files:**
- Modify: `requirements.txt`
- Modify: `bot/config.py`
- Modify: `config.yaml`

- [ ] **Step 1 : Ajouter jellyfish à requirements.txt**

Ajouter après `langdetect` :

```
jellyfish>=0.11.2
```

- [ ] **Step 2 : Installer jellyfish**

```bash
cd /opt/stacks/wally-ai
pip install jellyfish>=0.11.2
```

Attendu : `Successfully installed jellyfish-...`

- [ ] **Step 3 : Ajouter link_min_confidence dans BotConfig**

Dans `bot/config.py`, dans le dataclass `BotConfig` :

```python
@dataclass
class BotConfig:
    trigger_names: list[str]
    language_default: str
    context_window_size: int
    context_token_threshold: int
    journal_time: str
    journal_channel_id: Optional[int] = None
    dashboard_token: Optional[str] = None
    prelude_window_size: int = 15
    link_min_confidence: float = 0.75  # ← ajout
```

- [ ] **Step 4 : Ajouter link_min_confidence dans config.yaml**

Sous la section `bot:`, ajouter :

```yaml
bot:
  # ... champs existants ...
  link_min_confidence: 0.75
```

- [ ] **Step 5 : Vérifier que Config.load() fonctionne**

```bash
python -c "from bot.config import Config; c = Config.load('config.yaml'); print(c.bot.link_min_confidence)"
```

Attendu : `0.75`

- [ ] **Step 6 : Vérifier que les tests existants passent toujours**

```bash
pytest --tb=short -q
```

Attendu : 0 erreurs.

- [ ] **Step 7 : Commit**

```bash
git add requirements.txt bot/config.py config.yaml
git commit -m "feat(links): ajouter jellyfish et link_min_confidence dans BotConfig"
```

---

### Task 2 : Schéma DB + méthodes user_links

**Files:**
- Modify: `bot/db/database.py`
- Create: `tests/test_db_links.py`

- [ ] **Step 1 : Écrire les tests DB (failing)**

```python
# tests/test_db_links.py
import asyncio
import time
import pytest
from bot.db.database import Database


@pytest.fixture
async def db(tmp_path):
    d = await Database.create(str(tmp_path / "test.db"))
    yield d
    await d.close()


@pytest.mark.asyncio
async def test_upsert_link_proposal_insert(db):
    await db.upsert_link_proposal("discord:123", "twitch:abc", 0.9)
    rows = await db.list_link_proposals()
    assert len(rows["proposals"]) == 1
    p = rows["proposals"][0]
    assert p["canonical_id"] == "discord:123"
    assert p["alias_id"] == "twitch:abc"
    assert p["confidence"] == pytest.approx(0.9)
    assert p["status"] == "pending"


@pytest.mark.asyncio
async def test_upsert_link_proposal_updates_confidence(db):
    await db.upsert_link_proposal("discord:123", "twitch:abc", 0.8)
    await db.upsert_link_proposal("discord:123", "twitch:abc", 0.92)
    rows = await db.list_link_proposals()
    assert len(rows["proposals"]) == 1
    assert rows["proposals"][0]["confidence"] == pytest.approx(0.92)


@pytest.mark.asyncio
async def test_upsert_link_proposal_ignores_accepted(db):
    await db.upsert_link_proposal("discord:123", "twitch:abc", 0.8)
    proposal_id = (await db.list_link_proposals())["proposals"][0]["id"]
    await db.accept_link(proposal_id)
    await db.upsert_link_proposal("discord:123", "twitch:abc", 0.5)  # score baisse
    rows = await db.list_link_proposals(status="accepted")
    assert rows["proposals"][0]["confidence"] == pytest.approx(0.8)  # inchangé


@pytest.mark.asyncio
async def test_accept_link(db):
    await db.upsert_link_proposal("discord:123", "twitch:abc", 0.9)
    proposal_id = (await db.list_link_proposals())["proposals"][0]["id"]
    await db.accept_link(proposal_id)
    rows = await db.list_link_proposals(status="accepted")
    assert len(rows["proposals"]) == 1
    assert rows["proposals"][0]["resolved_at"] is not None


@pytest.mark.asyncio
async def test_reject_link(db):
    await db.upsert_link_proposal("discord:123", "twitch:abc", 0.9)
    proposal_id = (await db.list_link_proposals())["proposals"][0]["id"]
    await db.reject_link(proposal_id)
    rows = await db.list_link_proposals(status="rejected")
    assert len(rows["proposals"]) == 1


@pytest.mark.asyncio
async def test_list_link_proposals_filter_by_status(db):
    await db.upsert_link_proposal("discord:1", "twitch:a", 0.9)
    await db.upsert_link_proposal("discord:2", "twitch:b", 0.8)
    id1 = (await db.list_link_proposals())["proposals"][0]["id"]
    await db.accept_link(id1)
    pending = await db.list_link_proposals(status="pending")
    assert len(pending["proposals"]) == 1
    assert pending["proposals"][0]["alias_id"] == "twitch:b"


@pytest.mark.asyncio
async def test_list_link_proposals_counts(db):
    await db.upsert_link_proposal("discord:1", "twitch:a", 0.9)
    await db.upsert_link_proposal("discord:2", "twitch:b", 0.8)
    id1 = (await db.list_link_proposals())["proposals"][0]["id"]
    await db.accept_link(id1)
    result = await db.list_link_proposals()
    assert result["counts"]["pending"] == 1
    assert result["counts"]["accepted"] == 1
    assert result["counts"]["rejected"] == 0


@pytest.mark.asyncio
async def test_get_alias_map(db):
    await db.upsert_link_proposal("discord:123", "twitch:abc", 0.9)
    proposal_id = (await db.list_link_proposals())["proposals"][0]["id"]
    await db.accept_link(proposal_id)
    alias_map = await db.get_alias_map()
    assert alias_map == {"twitch:abc": "discord:123"}


@pytest.mark.asyncio
async def test_get_alias_map_excludes_pending_and_rejected(db):
    await db.upsert_link_proposal("discord:1", "twitch:a", 0.9)  # pending
    await db.upsert_link_proposal("discord:2", "twitch:b", 0.8)
    id2 = (await db.list_link_proposals(status="pending"))["proposals"][1]["id"]
    await db.reject_link(id2)
    alias_map = await db.get_alias_map()
    assert alias_map == {}  # rien d'accepté
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```bash
pytest tests/test_db_links.py -v 2>&1 | head -30
```

Attendu : AttributeError / FAILED — méthodes inexistantes.

- [ ] **Step 3 : Ajouter la table user_links dans SCHEMA**

Dans `bot/db/database.py`, ajouter à la fin de la variable `SCHEMA` (avant le `"""`) :

```sql
CREATE TABLE IF NOT EXISTS user_links (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_id  TEXT NOT NULL,
    alias_id      TEXT NOT NULL,
    confidence    REAL NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    created_at    REAL NOT NULL,
    resolved_at   REAL,
    UNIQUE(canonical_id, alias_id)
);

CREATE INDEX IF NOT EXISTS idx_user_links_status ON user_links(status);
```

- [ ] **Step 4 : Ajouter les méthodes DB**

Ajouter à la fin de la classe `Database` dans `bot/db/database.py` :

```python
# ── Account linking ───────────────────────────────────────────────────────────

async def upsert_link_proposal(
    self, canonical_id: str, alias_id: str, confidence: float
) -> None:
    """Insert la proposition si absente. Met à jour confidence si status=pending.
    No-op si le lien est déjà accepted ou rejected."""
    await self.execute(
        """
        INSERT INTO user_links (canonical_id, alias_id, confidence, status, created_at)
        VALUES (?, ?, ?, 'pending', ?)
        ON CONFLICT(canonical_id, alias_id) DO UPDATE SET
            confidence = CASE WHEN excluded.confidence > user_links.confidence
                              AND user_links.status = 'pending'
                         THEN excluded.confidence
                         ELSE user_links.confidence END
        """,
        (canonical_id, alias_id, confidence, time.time()),
    )

async def list_link_proposals(self, status: str | None = None) -> dict:
    """Retourne {proposals: [...], counts: {pending, accepted, rejected}}.

    Chaque proposal inclut les usernames depuis memory_users (LEFT JOIN).
    """
    params: list = []
    where = ""
    if status:
        where = "WHERE ul.status = ?"
        params.append(status)

    sql = f"""
        SELECT ul.id, ul.canonical_id, ul.alias_id, ul.confidence,
               ul.status, ul.created_at, ul.resolved_at,
               mc.username AS canonical_username,
               ma.username AS alias_username
        FROM user_links ul
        LEFT JOIN memory_users mc ON mc.user_id = ul.canonical_id
        LEFT JOIN memory_users ma ON ma.user_id = ul.alias_id
        {where}
        ORDER BY ul.confidence DESC, ul.created_at DESC
    """
    rows = await self.fetch_all(sql, tuple(params))
    proposals = [
        {
            "id": r["id"],
            "canonical_id": r["canonical_id"],
            "alias_id": r["alias_id"],
            "confidence": round(float(r["confidence"]), 4),
            "status": r["status"],
            "created_at": r["created_at"],
            "resolved_at": r["resolved_at"],
            "canonical_username": r["canonical_username"],
            "alias_username": r["alias_username"],
        }
        for r in rows
    ]
    count_rows = await self.fetch_all(
        "SELECT status, COUNT(*) AS n FROM user_links GROUP BY status"
    )
    counts: dict[str, int] = {"pending": 0, "accepted": 0, "rejected": 0}
    for row in count_rows:
        if row["status"] in counts:
            counts[row["status"]] = int(row["n"])
    return {"proposals": proposals, "counts": counts}

async def accept_link(self, link_id: int) -> None:
    await self.execute(
        "UPDATE user_links SET status='accepted', resolved_at=? WHERE id=?",
        (time.time(), link_id),
    )

async def reject_link(self, link_id: int) -> None:
    await self.execute(
        "UPDATE user_links SET status='rejected', resolved_at=? WHERE id=?",
        (time.time(), link_id),
    )

async def get_alias_map(self) -> dict[str, str]:
    """Retourne {alias_id: canonical_id} pour tous les liens acceptés."""
    rows = await self.fetch_all(
        "SELECT alias_id, canonical_id FROM user_links WHERE status='accepted'"
    )
    return {r["alias_id"]: r["canonical_id"] for r in rows}
```

- [ ] **Step 5 : Vérifier que les tests passent**

```bash
pytest tests/test_db_links.py -v
```

Attendu : tous verts.

- [ ] **Step 6 : Vérifier la suite complète**

```bash
pytest --tb=short -q
```

- [ ] **Step 7 : Commit**

```bash
git add bot/db/database.py tests/test_db_links.py
git commit -m "feat(links): table user_links + méthodes DB (upsert, list, accept, reject, alias_map)"
```

---

### Task 3 : Moteur de similarité account_linker.py

**Files:**
- Create: `bot/core/account_linker.py`
- Create: `tests/test_account_linker.py`

- [ ] **Step 1 : Écrire les tests (failing)**

```python
# tests/test_account_linker.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.core.account_linker import _normalize, score, analyze_all


def test_normalize_lowercase():
    assert _normalize("KingsRequin") == "kingsrequin"


def test_normalize_strips_ttv():
    assert _normalize("KingsRequin_TTV") == "kingsrequin"
    assert _normalize("azraelttv") == "azrael"


def test_normalize_strips_separators():
    assert _normalize("kings-requinn") == "kingsrequinn"
    assert _normalize("kings.requinn") == "kingsrequinn"


def test_normalize_strips_trailing_digits():
    assert _normalize("bariballix123") == "bariballix"
    assert _normalize("user42") == "user"


def test_score_identical():
    assert score("kingsrequin", "kingsrequin") == pytest.approx(1.0, abs=0.01)


def test_score_similar():
    s = score("kingsrequin", "kingsrequin")  # après normalisation identique
    assert s > 0.9


def test_score_very_different():
    s = score("bariballix", "kingsrequin")
    assert s < 0.7


def test_score_normalized_ttv():
    """Jaro-Winkler sur pseudos normalisés : KingsRequin_TTV ↔ KingsRequin."""
    s = score("KingsRequin_TTV", "KingsRequin")
    assert s > 0.95


@pytest.mark.asyncio
async def test_analyze_all_inserts_proposals_above_threshold():
    db = AsyncMock()
    db.list_memory_users.return_value = [
        {"user_id": "discord:123", "platform": "discord", "username": "KingsRequin"},
        {"user_id": "twitch:kingsrequin_ttv", "platform": "twitch", "username": "KingsRequin_TTV"},
    ]
    db.upsert_link_proposal = AsyncMock()

    count = await analyze_all(db, threshold=0.75)

    assert count == 1
    db.upsert_link_proposal.assert_awaited_once()
    call_args = db.upsert_link_proposal.call_args
    assert call_args[0][0] == "discord:123"     # canonical
    assert call_args[0][1] == "twitch:kingsrequin_ttv"  # alias
    assert call_args[0][2] > 0.75               # confidence


@pytest.mark.asyncio
async def test_analyze_all_skips_below_threshold():
    db = AsyncMock()
    db.list_memory_users.return_value = [
        {"user_id": "discord:123", "platform": "discord", "username": "Alice"},
        {"user_id": "twitch:zzz", "platform": "twitch", "username": "zzz"},
    ]
    db.upsert_link_proposal = AsyncMock()

    count = await analyze_all(db, threshold=0.75)

    assert count == 0
    db.upsert_link_proposal.assert_not_awaited()


@pytest.mark.asyncio
async def test_analyze_all_skips_missing_usernames():
    """Un utilisateur sans username ne génère pas de proposition."""
    db = AsyncMock()
    db.list_memory_users.return_value = [
        {"user_id": "discord:123", "platform": "discord", "username": None},
        {"user_id": "twitch:abc", "platform": "twitch", "username": "abc"},
    ]
    db.upsert_link_proposal = AsyncMock()
    count = await analyze_all(db, threshold=0.75)
    assert count == 0
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```bash
pytest tests/test_account_linker.py -v 2>&1 | head -20
```

Attendu : ImportError / FAILED.

- [ ] **Step 3 : Créer bot/core/account_linker.py**

```python
# bot/core/account_linker.py
"""Analyse de similarité de pseudos pour la liaison Twitch ↔ Discord.

Fonctions pures exportées :
    _normalize(name) → str          — normalise un pseudo pour la comparaison
    score(a, b) → float             — score Jaro-Winkler 0.0–1.0 entre deux pseudos bruts
    analyze_all(db, threshold) → int — compare tous Discord vs tous Twitch, insère propositions
    analyze_new_user(db, user_id, threshold) — compare un arrivant vs l'autre plateforme
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

import jellyfish
from loguru import logger

if TYPE_CHECKING:
    from bot.db.database import Database


def _normalize(name: str) -> str:
    """Normalise un pseudo pour la comparaison Jaro-Winkler.

    - Lowercase
    - Strip suffixe _TTV / TTV (insensible à la casse)
    - Strip séparateurs _ - .
    - Strip chiffres finaux
    """
    name = name.lower().strip()
    name = re.sub(r'_?ttv$', '', name)
    name = re.sub(r'[_\-\.]', '', name)
    name = re.sub(r'\d+$', '', name)
    return name.strip()


def score(a: str, b: str) -> float:
    """Score Jaro-Winkler entre deux pseudos bruts (normalisation incluse)."""
    return jellyfish.jaro_winkler_similarity(_normalize(a), _normalize(b))


async def analyze_all(db: "Database", threshold: float = 0.75) -> int:
    """Compare tous les comptes Discord vs tous les comptes Twitch dans memory_users.

    Pour chaque paire (discord, twitch) dont le score >= threshold, insère une
    proposition via upsert_link_proposal (Discord = canonical, Twitch = alias).

    Retourne le nombre de propositions créées ou mises à jour.
    """
    users = await db.list_memory_users()
    discord_users = [u for u in users if u["platform"] == "discord" and u.get("username")]
    twitch_users  = [u for u in users if u["platform"] == "twitch"  and u.get("username")]

    count = 0
    for discord_user in discord_users:
        for twitch_user in twitch_users:
            s = score(discord_user["username"], twitch_user["username"])
            if s >= threshold:
                await db.upsert_link_proposal(
                    discord_user["user_id"],  # canonical
                    twitch_user["user_id"],   # alias
                    s,
                )
                count += 1
                logger.debug(
                    "Link proposal: {d} ↔ {t} ({s:.2%})",
                    d=discord_user["user_id"],
                    t=twitch_user["user_id"],
                    s=s,
                )
    logger.info("analyze_all: {n} proposition(s) générée(s)", n=count)
    return count


async def analyze_new_user(
    db: "Database", new_user_id: str, threshold: float = 0.75
) -> None:
    """Compare un nouvel arrivant contre tous les comptes de l'autre plateforme.

    Appelé en fire-and-forget depuis MemoryService.add() après upsert_memory_user.
    Ne fait rien si le compte n'a pas de username ou si la plateforme est inconnue.
    """
    try:
        users = await db.list_memory_users()
        new_user = next((u for u in users if u["user_id"] == new_user_id), None)
        if not new_user or not new_user.get("username"):
            return

        new_platform = new_user["platform"]
        other_platform = "twitch" if new_platform == "discord" else "discord"
        candidates = [u for u in users if u["platform"] == other_platform and u.get("username")]

        for candidate in candidates:
            s = score(new_user["username"], candidate["username"])
            if s < threshold:
                continue
            # Discord toujours canonical
            if new_platform == "discord":
                canonical_id, alias_id = new_user_id, candidate["user_id"]
            else:
                canonical_id, alias_id = candidate["user_id"], new_user_id
            await db.upsert_link_proposal(canonical_id, alias_id, s)
            logger.info(
                "Nouveau lien proposé: {c} ↔ {a} ({s:.2%})",
                c=canonical_id, a=alias_id, s=s,
            )
    except Exception as exc:
        logger.warning("analyze_new_user failed for {uid}: {e}", uid=new_user_id, e=exc)
```

- [ ] **Step 4 : Vérifier que les tests passent**

```bash
pytest tests/test_account_linker.py -v
```

Attendu : tous verts.

- [ ] **Step 5 : Vérifier la suite complète**

```bash
pytest --tb=short -q
```

- [ ] **Step 6 : Commit**

```bash
git add bot/core/account_linker.py tests/test_account_linker.py
git commit -m "feat(links): account_linker — normalisation + Jaro-Winkler + analyze_all/new_user"
```

---

### Task 4 : MemoryService — cache d'alias + résolution runtime

**Files:**
- Modify: `bot/core/memory.py`
- Modify: `bot/main.py`
- Create: `tests/test_memory_alias.py`

- [ ] **Step 1 : Écrire les tests (failing)**

```python
# tests/test_memory_alias.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.core.memory import MemoryService


def make_config():
    config = MagicMock()
    config.bot.context_window_size = 10
    config.bot.context_token_threshold = 2000
    config.bot.prelude_window_size = 3
    config.bot.link_min_confidence = 0.75
    config.openai.secondary_model = "gpt-4o-mini"
    return config


def test_user_id_no_alias():
    """Sans alias, _user_id retourne platform:user_id."""
    svc = MemoryService(make_config())
    assert svc._user_id("discord", "123") == "discord:123"


def test_user_id_resolves_alias():
    """Avec alias chargé, _user_id retourne le canonical_id."""
    svc = MemoryService(make_config())
    svc._alias_cache = {"twitch:abc": "discord:123"}
    assert svc._user_id("twitch", "abc") == "discord:123"


def test_user_id_unknown_alias_passthrough():
    """Un ID non aliasé passe tel quel."""
    svc = MemoryService(make_config())
    svc._alias_cache = {"twitch:abc": "discord:123"}
    assert svc._user_id("twitch", "xyz") == "twitch:xyz"


@pytest.mark.asyncio
async def test_load_aliases_populates_cache():
    svc = MemoryService(make_config())
    db = AsyncMock()
    db.get_alias_map.return_value = {"twitch:abc": "discord:123"}
    await svc.load_aliases(db)
    assert svc._alias_cache == {"twitch:abc": "discord:123"}


@pytest.mark.asyncio
async def test_load_aliases_empty():
    svc = MemoryService(make_config())
    db = AsyncMock()
    db.get_alias_map.return_value = {}
    await svc.load_aliases(db)
    assert svc._alias_cache == {}
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```bash
pytest tests/test_memory_alias.py -v 2>&1 | head -20
```

Attendu : AttributeError `_alias_cache` / FAILED.

- [ ] **Step 3 : Modifier MemoryService dans memory.py**

Dans `__init__`, ajouter après `self._bg_tasks`:

```python
self._alias_cache: dict[str, str] = {}  # alias_id → canonical_id
```

Remplacer la méthode `_user_id` (ligne 111) :

```python
def _user_id(self, platform: str, user_id: str) -> str:
    raw = f"{platform}:{user_id}"
    return self._alias_cache.get(raw, raw)
```

Ajouter après `set_db` :

```python
async def load_aliases(self, db) -> None:
    """Charge le cache d'alias depuis la DB. Appelé au démarrage depuis main.py."""
    try:
        self._alias_cache = await db.get_alias_map()
        logger.info("Alias cache loaded: {n} alias(es)", n=len(self._alias_cache))
    except Exception as exc:
        logger.warning("Failed to load alias cache: {e}", e=exc)
```

- [ ] **Step 4 : Ajouter le hook analyze_new_user dans MemoryService.add()**

Dans `MemoryService.add()`, après `await self._db.upsert_memory_user(uid, platform, username)` :

```python
# Fire-and-forget : analyse de similarité pour le nouvel arrivant.
# Uniquement si uid n'est pas déjà un alias résolu (pas dans _alias_cache).
raw_uid = f"{platform}:{user_id}"
if uid == raw_uid and self._db is not None:
    from bot.core import account_linker
    threshold = self._config.bot.link_min_confidence
    self._fire(account_linker.analyze_new_user(self._db, uid, threshold))
```

- [ ] **Step 5 : Modifier main.py — appel load_aliases**

Dans `bot/main.py`, après `memory.set_db(db)` (ligne ~81) :

```python
await memory.load_aliases(db)
logger.info("Memory alias cache loaded")
```

- [ ] **Step 6 : Vérifier que les tests passent**

```bash
pytest tests/test_memory_alias.py -v
```

- [ ] **Step 7 : Vérifier la suite complète**

```bash
pytest --tb=short -q
```

- [ ] **Step 8 : Commit**

```bash
git add bot/core/memory.py bot/main.py tests/test_memory_alias.py
git commit -m "feat(links): MemoryService alias cache — _user_id résolution + load_aliases + hook analyze_new_user"
```

---

### Task 5 : SSE broadcast_event + routes links.py

**Files:**
- Modify: `bot/dashboard/routes/sse.py`
- Create: `bot/dashboard/routes/links.py`
- Modify: `bot/dashboard/app.py`
- Create: `tests/test_dashboard_links.py`

- [ ] **Step 1 : Écrire les tests (failing)**

```python
# tests/test_dashboard_links.py
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from bot.dashboard.app import create_dashboard_app
from bot.dashboard.state import AppState
from bot.config import (
    BotConfig, OpenAIConfig, EmotionDecayConfig,
    TwitchEventConfig, TwitchConfig, DiscordConfig,
)


def _make_config():
    cfg = MagicMock()
    cfg.bot = BotConfig(
        trigger_names=["wally"], language_default="fr",
        context_window_size=10, context_token_threshold=2000,
        prelude_window_size=3, journal_time="08:00",
        dashboard_token="test-token", link_min_confidence=0.75,
    )
    cfg.openai = OpenAIConfig(primary_model="gpt-4o-mini", secondary_model="gpt-4o-mini", temperature=0.7, max_tokens=1000)
    cfg.discord = DiscordConfig(anger_trigger_threshold=3, timeout_minutes=10)
    cfg.twitch = TwitchConfig(guest_channels=[], cooldown_seconds=10)
    cfg.emotions = {e: EmotionDecayConfig(decay_lambda=0.1) for e in ["anger","joy","sadness","curiosity","boredom"]}
    cfg.twitch_events = {"follow": TwitchEventConfig(active=True, message="Hey!")}
    cfg.save = MagicMock()
    return cfg


def _make_state():
    memory = MagicMock()
    memory._alias_cache = {}
    db = AsyncMock()
    state = AppState(
        config=_make_config(), db=db, emotion=MagicMock(),
        memory=memory, persona=MagicMock(), openai_client=MagicMock(),
        token_manager=MagicMock(), twitch_api=None, discord_bot=None, twitch_bot=None,
    )
    return state, db


HEADERS = {"Authorization": "Bearer test-token"}


@pytest.mark.asyncio
async def test_get_links_returns_proposals():
    state, db = _make_state()
    db.list_link_proposals.return_value = {
        "proposals": [
            {"id": 1, "canonical_id": "discord:123", "alias_id": "twitch:abc",
             "confidence": 0.92, "status": "pending", "created_at": 1700000000.0,
             "resolved_at": None, "canonical_username": "Alice", "alias_username": "alice_ttv"},
        ],
        "counts": {"pending": 1, "accepted": 0, "rejected": 0},
    }
    async with AsyncClient(transport=ASGITransport(create_dashboard_app(state)), base_url="http://test") as client:
        resp = await client.get("/api/admin/links", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["proposals"]) == 1
    assert data["counts"]["pending"] == 1


@pytest.mark.asyncio
async def test_get_links_requires_auth():
    state, db = _make_state()
    db.list_link_proposals.return_value = {"proposals": [], "counts": {"pending":0,"accepted":0,"rejected":0}}
    async with AsyncClient(transport=ASGITransport(create_dashboard_app(state)), base_url="http://test") as client:
        resp = await client.get("/api/admin/links")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_post_analyze_starts_background():
    state, db = _make_state()
    with patch("bot.dashboard.routes.links.account_linker") as mock_linker:
        mock_linker.analyze_all = AsyncMock(return_value=3)
        async with AsyncClient(transport=ASGITransport(create_dashboard_app(state)), base_url="http://test") as client:
            resp = await client.post("/api/admin/links/analyze", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["status"] == "started"


@pytest.mark.asyncio
async def test_post_reject_link():
    state, db = _make_state()
    db.reject_link = AsyncMock()
    async with AsyncClient(transport=ASGITransport(create_dashboard_app(state)), base_url="http://test") as client:
        resp = await client.post("/api/admin/links/1/reject", headers=HEADERS)
    assert resp.status_code == 200
    db.reject_link.assert_awaited_once_with(1)
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```bash
pytest tests/test_dashboard_links.py -v 2>&1 | head -30
```

Attendu : ImportError / 404 — route inexistante.

- [ ] **Step 3 : Ajouter broadcast_event dans sse.py**

Dans `bot/dashboard/routes/sse.py`, ajouter après `_log_queues` :

```python
def broadcast_event(data: dict) -> None:
    """Push un événement structuré dans tous les canaux SSE admin.

    Fonction synchrone (même pattern que _log_sink).
    Le frontend discrimine par la présence du champ 'type'.
    """
    for q in list(_log_queues):
        try:
            q.put_nowait(data)
        except Exception:
            pass
```

- [ ] **Step 4 : Créer bot/dashboard/routes/links.py**

```python
# bot/dashboard/routes/links.py
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from bot.core import account_linker

router = APIRouter()


@router.get("/links")
async def list_links(request: Request, status: str | None = None) -> dict:
    state = request.app.state.wally
    return await state.db.list_link_proposals(status=status)


@router.post("/links/analyze")
async def analyze_links(request: Request) -> dict:
    """Déclenche analyze_all en tâche background. Réponse immédiate."""
    state = request.app.state.wally
    threshold = state.config.bot.link_min_confidence

    async def _run():
        try:
            count = await account_linker.analyze_all(state.db, threshold)
            from bot.dashboard.routes.sse import broadcast_event
            broadcast_event({"type": "links_analyzed", "count": count})
        except Exception as exc:
            logger.warning("analyze_links background task failed: {e}", e=exc)

    asyncio.create_task(_run())
    return {"status": "started"}


@router.post("/links/{link_id}/accept")
async def accept_link(link_id: int, request: Request) -> dict:
    """Fusionne les mémoires mem0 + met à jour le cache d'alias + accepte le lien."""
    state = request.app.state.wally

    # Récupérer les IDs de la proposition
    result = await state.db.list_link_proposals()
    proposal = next((p for p in result["proposals"] if p["id"] == link_id), None)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposition introuvable")
    if proposal["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Statut actuel : {proposal['status']}")

    alias_id     = proposal["alias_id"]      # ex. "twitch:kingsrequin_ttv"
    canonical_id = proposal["canonical_id"]  # ex. "discord:123456789"

    # Copier les mémoires de l'alias vers le canonical
    alias_parts = alias_id.split(":", 1)
    canonical_parts = canonical_id.split(":", 1)
    if len(alias_parts) == 2 and len(canonical_parts) == 2:
        alias_platform, alias_raw = alias_parts
        canonical_platform, canonical_raw = canonical_parts
        try:
            memories_text = await state.memory.get_all(alias_platform, alias_raw)
            if memories_text:
                for line in memories_text.splitlines():
                    line = line.strip()
                    if line:
                        await state.memory.add(canonical_platform, canonical_raw, line)
            logger.info("Mémoires copiées de {a} vers {c}", a=alias_id, c=canonical_id)
        except Exception as exc:
            logger.warning("Erreur copie mémoires lors du merge {a}→{c}: {e}",
                           a=alias_id, c=canonical_id, e=exc)

    # Supprimer les mémoires mem0 de l'alias
    try:
        state.memory._init_mem0()
        if state.memory._mem0 is not None:
            import asyncio as _asyncio
            await _asyncio.to_thread(state.memory._mem0.delete_all, user_id=alias_id)
    except Exception as exc:
        logger.warning("delete_all mem0 pour {a} échoué: {e}", a=alias_id, e=exc)

    # Supprimer de memory_users
    await state.db.execute("DELETE FROM memory_users WHERE user_id = ?", (alias_id,))

    # Accepter le lien en DB
    await state.db.accept_link(link_id)

    # Mettre à jour le cache d'alias en mémoire
    state.memory._alias_cache[alias_id] = canonical_id

    logger.info("Lien accepté : {a} → {c}", a=alias_id, c=canonical_id)
    return {"accepted": True, "alias_id": alias_id, "canonical_id": canonical_id}


@router.post("/links/{link_id}/reject")
async def reject_link(link_id: int, request: Request) -> dict:
    state = request.app.state.wally
    await state.db.reject_link(link_id)
    return {"rejected": True}
```

- [ ] **Step 5 : Inclure le router dans app.py**

Dans `bot/dashboard/app.py`, dans la fonction `create_dashboard_app`, dans la section des imports de routes :

```python
from bot.dashboard.routes import status, emotions, admin, sse, twitch, memory, links
```

Et après `app.include_router(memory.router, prefix="/api/admin")` :

```python
app.include_router(links.router, prefix="/api/admin")
```

- [ ] **Step 6 : Vérifier que les tests passent**

```bash
pytest tests/test_dashboard_links.py -v
```

Attendu : tous verts.

- [ ] **Step 7 : Vérifier la suite complète**

```bash
pytest --tb=short -q
```

- [ ] **Step 8 : Commit**

```bash
git add bot/dashboard/routes/sse.py bot/dashboard/routes/links.py bot/dashboard/app.py tests/test_dashboard_links.py
git commit -m "feat(links): routes admin GET/POST + broadcast_event SSE + accept avec merge mem0"
```

---

### Task 6 : Frontend — HTML + JS liaisons de comptes

**Files:**
- Modify: `bot/dashboard/static/index.html`
- Modify: `bot/dashboard/static/app.js`

Cette tâche n'a pas de tests unitaires — vérification manuelle dans le browser.

- [ ] **Step 1 : Ajouter l'onglet dans index.html**

Dans `bot/dashboard/static/index.html`, dans `<nav class="tabs" id="tabs-admin">`, ajouter après le bouton mémoire :

```html
<button class="tab-btn" data-tab="admin-links" onclick="showTab('admin-links')">🔗 LIAISONS</button>
```

- [ ] **Step 2 : Ajouter la section HTML dans index.html**

Dans `<main>`, ajouter la section admin-links (juste avant `</main>`) :

```html
<!-- ── ADMIN LIAISONS ──────────────────────────────────────────────────── -->
<div class="tab-content" id="tab-admin-links" style="display:none">

  <div class="card" style="margin-bottom:20px">
    <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px">
      <div>
        <div class="card-title">🔗 LIAISONS DE COMPTES</div>
        <div style="color:var(--text-secondary);font-size:0.8rem;margin-top:4px">
          Fusion mémoire Twitch ↔ Discord — approbation manuelle requise
        </div>
      </div>
      <button class="btn" id="btn-analyze-links" onclick="analyzeLinks()">⟳ ANALYSER</button>
    </div>
  </div>

  <!-- Onglets statut -->
  <div class="links-tabs" id="links-tabs">
    <button class="links-tab active" data-status="pending"   onclick="setLinksTab('pending')">
      EN ATTENTE <span class="badge" id="badge-pending">0</span>
    </button>
    <button class="links-tab" data-status="accepted" onclick="setLinksTab('accepted')">
      ACCEPTÉS <span class="badge" id="badge-accepted">0</span>
    </button>
    <button class="links-tab" data-status="rejected" onclick="setLinksTab('rejected')">
      REJETÉS <span class="badge" id="badge-rejected">0</span>
    </button>
  </div>

  <div id="links-list"></div>

</div>
```

- [ ] **Step 3 : Ajouter les styles CSS dans index.html (balise <style> existante ou inline)**

Dans `<head>`, dans le bloc `<style>` existant (ou créer un bloc) :

```css
.links-tabs {
  display: flex;
  border: 3px solid var(--border);
  box-shadow: 4px 4px 0 var(--border);
  margin-bottom: 16px;
}
.links-tab {
  flex: 1;
  padding: 10px;
  font-weight: 700;
  font-size: 0.78rem;
  letter-spacing: 1px;
  cursor: pointer;
  text-transform: uppercase;
  border: none;
  border-right: 3px solid var(--border);
  background: var(--card-bg);
  color: var(--text-secondary);
  font-family: inherit;
}
.links-tab:last-child { border-right: none; }
.links-tab.active { background: var(--border); color: var(--bg); }
.links-tab .badge {
  display: inline-block;
  padding: 1px 6px;
  font-size: 0.65rem;
  font-weight: 900;
  border: 2px solid currentColor;
  margin-left: 5px;
}
.link-card {
  border: 3px solid var(--border);
  box-shadow: 4px 4px 0 var(--border);
  background: var(--card-bg);
  padding: 16px 20px;
  margin-bottom: 12px;
  display: grid;
  grid-template-columns: 1fr auto 1fr auto auto;
  align-items: center;
  gap: 14px;
}
@media (max-width: 700px) {
  .link-card { grid-template-columns: 1fr; }
}
.link-platform {
  font-size: 0.65rem;
  font-weight: 900;
  letter-spacing: 2px;
  text-transform: uppercase;
  margin-bottom: 3px;
}
.link-platform.discord { color: #7289da; }
.link-platform.twitch  { color: #9146ff; }
.link-username { font-size: 1rem; font-weight: 700; }
.link-user-id  { color: var(--text-secondary); font-size: 0.72rem; }
.link-twitch-url {
  display: inline-flex; align-items: center; gap: 4px;
  color: #9146ff; font-size: 0.72rem; font-weight: 700;
  border-bottom: 2px solid #9146ff; text-decoration: none; margin-top: 3px;
}
.link-twitch-url:hover { color: #bf94ff; border-color: #bf94ff; }
.link-arrow { font-size: 1.3rem; color: var(--text-secondary); text-align: center; }
.link-confidence { display: flex; flex-direction: column; align-items: center; gap: 3px; }
.link-confidence-label { font-size: 0.62rem; font-weight: 900; letter-spacing: 1px; text-transform: uppercase; color: var(--text-secondary); }
.link-confidence-score { font-size: 1.4rem; font-weight: 900; }
.link-conf-bar { width: 56px; height: 5px; background: #333; border: 2px solid #555; }
.link-conf-fill { height: 100%; }
.link-actions { display: flex; flex-direction: column; gap: 7px; }
.btn-accept-link { border-color: #ffdd00 !important; color: #ffdd00 !important; font-size: 0.75rem; padding: 6px 12px; }
.btn-reject-link { border-color: #ff3333 !important; color: #ff3333 !important; font-size: 0.75rem; padding: 6px 12px; }
```

- [ ] **Step 4 : Ajouter la logique JS dans app.js**

À la fin de `bot/dashboard/static/app.js`, ajouter :

```javascript
// ── Liaisons de comptes ───────────────────────────────────────────────────────

let _linksStatus = 'pending';
let _linksData   = { proposals: [], counts: { pending: 0, accepted: 0, rejected: 0 } };

async function loadLinks(status = _linksStatus) {
  if (!getToken()) return;
  try {
    const res = await apiFetch(`/api/admin/links?status=${status}`);
    _linksData = res;
    _linksStatus = status;
    renderLinks();
    updateLinksBadges(res.counts);
  } catch (e) {
    console.warn('loadLinks error', e);
  }
}

function updateLinksBadges(counts) {
  ['pending', 'accepted', 'rejected'].forEach(s => {
    const el = document.getElementById(`badge-${s}`);
    if (el) el.textContent = counts[s] ?? 0;
  });
}

function setLinksTab(status) {
  _linksStatus = status;
  document.querySelectorAll('.links-tab').forEach(t => {
    t.classList.toggle('active', t.dataset.status === status);
  });
  loadLinks(status);
}

function _confColor(score) {
  if (score >= 0.90) return '#00ff88';
  if (score >= 0.75) return '#ffdd00';
  return '#ff8800';
}

function renderLinks() {
  const container = document.getElementById('links-list');
  if (!container) return;
  const proposals = _linksData.proposals || [];
  if (!proposals.length) {
    container.innerHTML = `<div style="border:3px dashed #444;padding:40px;text-align:center;color:#555;font-weight:700;letter-spacing:1px">AUCUNE PROPOSITION</div>`;
    return;
  }
  container.innerHTML = proposals.map(p => {
    const pct = Math.round(p.confidence * 100);
    const color = _confColor(p.confidence);
    const twitchLogin = p.alias_id.split(':')[1] || '';
    const twitchUrl = `https://twitch.tv/${twitchLogin}`;
    const isPending = p.status === 'pending';
    return `
      <div class="link-card">
        <div>
          <div class="link-platform discord">● DISCORD</div>
          <div class="link-username">${p.canonical_username || '—'}</div>
          <div class="link-user-id">${p.canonical_id}</div>
        </div>
        <div class="link-arrow">⟷</div>
        <div>
          <div class="link-platform twitch">● TWITCH</div>
          <div class="link-username">${p.alias_username || '—'}</div>
          <div class="link-user-id">${p.alias_id}</div>
          <a class="link-twitch-url" href="${twitchUrl}" target="_blank" rel="noopener">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><path d="M11.571 4.714h1.715v5.143H11.57zm4.715 0H18v5.143h-1.714zM6 0L1.714 4.286v15.428h5.143V24l4.286-4.286h3.428L22.286 12V0zm14.571 11.143l-3.428 3.428h-3.429l-3 3v-3H6.857V1.714h13.714z"/></svg>
            ${twitchLogin}
          </a>
        </div>
        <div class="link-confidence">
          <div class="link-confidence-label">CONFIANCE</div>
          <div class="link-confidence-score" style="color:${color}">${pct}%</div>
          <div class="link-conf-bar"><div class="link-conf-fill" style="width:${pct}%;background:${color}"></div></div>
        </div>
        <div class="link-actions">
          ${isPending ? `
            <button class="btn btn-accept-link" onclick="acceptLink(${p.id})">✓ FUSIONNER</button>
            <button class="btn btn-reject-link" onclick="rejectLink(${p.id})">✕ REJETER</button>
          ` : `<span style="color:#aaa;font-size:0.75rem;font-weight:700;letter-spacing:1px">${p.status.toUpperCase()}</span>`}
        </div>
      </div>`;
  }).join('');
}

async function analyzeLinks() {
  const btn = document.getElementById('btn-analyze-links');
  if (btn) { btn.disabled = true; btn.textContent = '⟳ ANALYSE...'; }
  try {
    await apiFetch('/api/admin/links/analyze', { method: 'POST' });
    showToast('Analyse lancée en arrière-plan…', 'info');
  } catch (e) {
    showToast('Erreur lors du lancement de l\'analyse', 'error');
    if (btn) { btn.disabled = false; btn.textContent = '⟳ ANALYSER'; }
  }
}

async function acceptLink(id) {
  try {
    await apiFetch(`/api/admin/links/${id}/accept`, { method: 'POST' });
    showToast('Comptes fusionnés avec succès', 'success');
    await loadLinks(_linksStatus);
  } catch (e) {
    showToast('Erreur lors de la fusion', 'error');
  }
}

async function rejectLink(id) {
  try {
    await apiFetch(`/api/admin/links/${id}/reject`, { method: 'POST' });
    showToast('Proposition rejetée', 'info');
    await loadLinks(_linksStatus);
  } catch (e) {
    showToast('Erreur lors du rejet', 'error');
  }
}
```

- [ ] **Step 5 : Ajouter le discriminateur SSE dans le handler logSSE existant**

Dans `app.js`, trouver le handler `logSSE.onmessage` et modifier pour discriminer les événements structurés :

```javascript
// Chercher dans app.js le gestionnaire onmessage du logSSE et ajouter :
// Avant appendLog(data), vérifier si c'est un événement structuré :
logSSE.onmessage = e => {
  const data = JSON.parse(e.data);
  // Événements structurés (type présent) — routage spécifique
  if (data.type === 'links_analyzed') {
    const btn = document.getElementById('btn-analyze-links');
    if (btn) { btn.disabled = false; btn.textContent = '⟳ ANALYSER'; }
    showToast(`${data.count} proposition(s) trouvée(s)`, 'success');
    if (_linksStatus === 'pending') loadLinks('pending');
    return;
  }
  // Log standard
  appendLog(data);
};
```

- [ ] **Step 6 : Ajouter l'appel loadLinks dans showTab**

Dans `app.js`, dans la fonction `showTab`, ajouter le chargement des liens quand l'onglet est activé :

```javascript
// Dans showTab(tab), ajouter :
if (tab === 'admin-links') loadLinks('pending');
```

- [ ] **Step 7 : Vérifier visuellement dans le browser**

```bash
# Démarrer le dashboard (ou utiliser docker compose up)
# Naviguer sur http://localhost:8080 → Admin → 🔗 LIAISONS
# Vérifier :
# - Section visible avec onglets pending/accepted/rejected
# - Bouton ANALYSER fonctionnel
# - Cards s'affichent si des propositions existent en DB
```

- [ ] **Step 8 : Lancer la suite de tests complète**

```bash
pytest --tb=short -q
```

Attendu : 0 erreurs.

- [ ] **Step 9 : Commit**

```bash
git add bot/dashboard/static/index.html bot/dashboard/static/app.js
git commit -m "feat(links): dashboard UI — onglet liaisons + cards + accept/reject + SSE discriminateur"
```

---

### Task 7 : Validation finale

- [ ] **Step 1 : Lancer tous les tests**

```bash
pytest -v --tb=short
```

Attendu : tous verts, 0 erreurs.

- [ ] **Step 2 : Vérifier que le style CSS CSS est cohérent avec le neobrutalism**

Contrôle visuel dans le browser : bordures épaisses, ombres dures, couleurs de confiance (vert/jaune/orange).

- [ ] **Step 3 : Commit final**

```bash
git add -A
git commit -m "feat(links): implémentation complète liaison comptes Twitch/Discord"
```
