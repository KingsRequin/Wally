# Twitch Visit Awareness — Journal "Petit Voyage" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enregistrer les visites de Wally sur les chaînes Twitch invitées, générer un résumé narratif à la fin de chaque visite, et l'injecter dans le journal quotidien comme un "petit voyage".

**Architecture:** Nouvelle table SQLite `twitch_visits` persistée via migration. `WallyTwitch` track les visites actives en mémoire, génère un résumé LLM au départ via `llm_secondary`, puis le stocke. Le journal reçoit un bloc `twitch_visits_block` injecté dans le prompt, identique au pattern `gallery_block` existant.

**Tech Stack:** aiosqlite, Python asyncio, twitchio 2.x, `llm_secondary.complete()` (OpenAI/Claude selon config), pytest-asyncio

---

## Fichiers modifiés / créés

| Fichier | Action |
|---|---|
| `bot/db/database.py` | +table `twitch_visits` dans SCHEMA, +migration, +3 méthodes |
| `bot/persona/prompts/twitch_visit_summary.md` | Créer prompt résumé |
| `bot/twitch/bot.py` | +`_active_visits`, +`_bg_tasks`, +`_fire()`, modifier `add_guest_channel`, `remove_guest_channel`, +`_finalize_visit` |
| `bot/twitch/handlers.py` | +incrémentation `msg_count` dans `handle_message` |
| `bot/core/journal.py` | +bloc `twitch_visits_block` dans `generate_and_send` |
| `tests/test_database.py` | +tests pour les 3 nouvelles méthodes DB |
| `tests/test_twitch_bot_visits.py` | Créer — tests pour le tracking des visites |
| `tests/test_journal.py` | +test pour le bloc twitch_visits |

---

### Task 1: Table DB + 3 méthodes + tests

**Files:**
- Modify: `bot/db/database.py`
- Test: `tests/test_database.py`

- [ ] **Step 1.1 : Écrire les tests DB échouants**

Ajouter à la fin de `tests/test_database.py` :

```python
@pytest.mark.asyncio
async def test_twitch_visits_table_exists(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    tables = await db.fetch_all("SELECT name FROM sqlite_master WHERE type='table'")
    names = {row["name"] for row in tables}
    assert "twitch_visits" in names
    await db.close()


@pytest.mark.asyncio
async def test_start_twitch_visit_returns_id(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    visit_id = await db.start_twitch_visit("azrael")
    assert isinstance(visit_id, int)
    assert visit_id > 0
    await db.close()


@pytest.mark.asyncio
async def test_end_twitch_visit_fills_fields(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    visit_id = await db.start_twitch_visit("azrael")
    left_at = time.time() + 600
    await db.end_twitch_visit(visit_id, left_at, 42, "Super visite chez Azrael.")
    rows = await db.fetch_all("SELECT * FROM twitch_visits WHERE id = ?", (visit_id,))
    assert len(rows) == 1
    row = rows[0]
    assert row["channel"] == "azrael"
    assert row["left_at"] == left_at
    assert row["duration_s"] == 600
    assert row["msg_count"] == 42
    assert row["summary"] == "Super visite chez Azrael."
    await db.close()


@pytest.mark.asyncio
async def test_get_twitch_visits_for_date(tmp_path):
    from datetime import date
    db = await Database.create(str(tmp_path / "test.db"))
    today = date.today().isoformat()

    # Visite aujourd'hui
    vid = await db.start_twitch_visit("streamer1")
    await db.end_twitch_visit(vid, time.time() + 100, 10, "Bonne ambiance.")

    # Visite hier (ne doit pas apparaître)
    yesterday_ts = time.time() - 86400 - 1
    await db._conn.execute(
        "INSERT INTO twitch_visits (channel, joined_at, left_at, duration_s, msg_count, summary) VALUES (?, ?, ?, ?, ?, ?)",
        ("old_channel", yesterday_ts, yesterday_ts + 300, 300, 5, "Hier."),
    )
    await db._conn.commit()

    visits = await db.get_twitch_visits_for_date(today)
    assert len(visits) == 1
    assert visits[0]["channel"] == "streamer1"
    assert visits[0]["summary"] == "Bonne ambiance."
    await db.close()
```

- [ ] **Step 1.2 : Lancer les tests — vérifier qu'ils échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_database.py::test_twitch_visits_table_exists tests/test_database.py::test_start_twitch_visit_returns_id tests/test_database.py::test_end_twitch_visit_fills_fields tests/test_database.py::test_get_twitch_visits_for_date -v 2>&1 | tail -20
```

Attendu : 4 FAILED (table / méthode inexistante)

- [ ] **Step 1.3 : Ajouter la table dans le SCHEMA**

Dans `bot/db/database.py`, trouver la constante `SCHEMA` (la grande string SQL en haut du fichier). Ajouter juste avant la fermeture `"""` :

```sql
CREATE TABLE IF NOT EXISTS twitch_visits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    channel     TEXT    NOT NULL,
    joined_at   REAL    NOT NULL,
    left_at     REAL,
    duration_s  INTEGER,
    msg_count   INTEGER DEFAULT 0,
    summary     TEXT
);
```

- [ ] **Step 1.4 : Ajouter les 3 méthodes dans `Database`**

À la fin de la classe `Database`, avant la méthode `close()`, ajouter :

```python
# ── Twitch visits ─────────────────────────────────────────────────────────────

async def start_twitch_visit(self, channel: str) -> int:
    """Démarre une visite sur une chaîne invitée. Retourne l'id de la ligne."""
    now = time.time()
    cursor = await self._conn.execute(
        "INSERT INTO twitch_visits (channel, joined_at) VALUES (?, ?)",
        (channel, now),
    )
    await self._conn.commit()
    return cursor.lastrowid

async def end_twitch_visit(
    self,
    visit_id: int,
    left_at: float,
    msg_count: int,
    summary: str | None,
) -> None:
    """Complète une visite avec durée, comptage et résumé LLM."""
    await self.execute(
        "UPDATE twitch_visits SET left_at = ?, duration_s = ?, msg_count = ?, summary = ? WHERE id = ?",
        (left_at, int(left_at - (await self._get_visit_joined_at(visit_id))), msg_count, summary, visit_id),
    )

async def _get_visit_joined_at(self, visit_id: int) -> float:
    """Helper interne : récupère joined_at pour calculer duration_s."""
    row = await self.fetch_one(
        "SELECT joined_at FROM twitch_visits WHERE id = ?", (visit_id,)
    )
    return float(row["joined_at"]) if row else time.time()

async def get_twitch_visits_for_date(self, date_str: str) -> list[dict]:
    """Retourne les visites dont joined_at tombe dans la journée (Europe/Paris).

    date_str : format YYYY-MM-DD
    """
    from datetime import date as date_type
    target = date_type.fromisoformat(date_str)
    midnight = datetime.combine(target, datetime.min.time(), tzinfo=_TZ_DB).timestamp()
    end = midnight + 86400
    rows = await self.fetch_all(
        "SELECT * FROM twitch_visits WHERE joined_at >= ? AND joined_at < ? ORDER BY joined_at ASC",
        (midnight, end),
    )
    return [dict(row) for row in rows]
```

- [ ] **Step 1.5 : Lancer les tests — vérifier qu'ils passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_database.py::test_twitch_visits_table_exists tests/test_database.py::test_start_twitch_visit_returns_id tests/test_database.py::test_end_twitch_visit_fills_fields tests/test_database.py::test_get_twitch_visits_for_date -v 2>&1 | tail -20
```

Attendu : 4 PASSED

- [ ] **Step 1.6 : Vérifier que les tests DB existants passent encore**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_database.py -v 2>&1 | tail -20
```

Attendu : tous PASSED

- [ ] **Step 1.7 : Commit**

```bash
git add bot/db/database.py tests/test_database.py
git commit -m "feat(db): table twitch_visits + start/end/get méthodes"
```

---

### Task 2: Prompt de résumé de visite

**Files:**
- Create: `bot/persona/prompts/twitch_visit_summary.md`

- [ ] **Step 2.1 : Créer le fichier prompt**

Créer `bot/persona/prompts/twitch_visit_summary.md` avec ce contenu :

```markdown
Tu es Wally. Tu viens de rentrer d'une visite sur la chaîne Twitch d'un autre streamer.
Rédige 3 à 5 lignes à la première personne, style carnet de voyage — intime, vivant, légèrement
sardonic comme tu es.

Mentionne obligatoirement :
- le nom du streamer visité
- combien de temps tu y as passé
- l'ambiance générale (calme, chaotique, bonne vibe...)
- au moins un moment notable si les messages le permettent (sub, raid, échange marquant)

Si les messages sont vides ou insignifiants, décris juste l'ambiance générale de la chaîne.
Ne commence pas par "Je" — varie les entrées. Pas de ponctuation excessive.
```

- [ ] **Step 2.2 : Commit**

```bash
git add bot/persona/prompts/twitch_visit_summary.md
git commit -m "feat(prompts): twitch_visit_summary — résumé carnet de voyage"
```

---

### Task 3: WallyTwitch — tracking des visites + _finalize_visit

**Files:**
- Modify: `bot/twitch/bot.py`
- Create: `tests/test_twitch_bot_visits.py`

- [ ] **Step 3.1 : Écrire les tests échouants**

Créer `tests/test_twitch_bot_visits.py` :

```python
# tests/test_twitch_bot_visits.py
"""Tests pour le tracking des visites Twitch invitées dans WallyTwitch."""
import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def make_twitch_bot():
    """Retourne un WallyTwitch minimal mocké pour les tests de visite."""
    from bot.twitch.bot import WallyTwitch
    # On bypasse __init__ de twitchio
    bot = object.__new__(WallyTwitch)
    bot.config = MagicMock()
    bot.config.twitch.channel = "homechannel"
    bot.config.twitch.guest_channels = []
    bot.db = MagicMock()
    bot.db.start_twitch_visit = AsyncMock(return_value=42)
    bot.db.end_twitch_visit = AsyncMock()
    bot.memory = MagicMock()
    bot.memory.get_context = MagicMock(return_value=[
        {"author": "viewer1", "content": "poggers", "timestamp": time.time()},
        {"author": "viewer2", "content": "hype train!", "timestamp": time.time() + 1},
    ])
    bot.llm_secondary = MagicMock()
    bot.llm_secondary.complete = AsyncMock(return_value="Bonne visite chez streamer.")
    bot._cooldowns = {}
    bot._channel_ids = {}
    bot._channel_was_live = {}
    bot._active_visits = {}
    bot._bg_tasks = set()
    bot.config.save = MagicMock()
    return bot


@pytest.mark.asyncio
async def test_add_guest_channel_starts_visit(tmp_path):
    """add_guest_channel doit créer une entrée dans _active_visits."""
    bot = make_twitch_bot()
    bot.twitch_api = MagicMock()
    bot.twitch_api.get_broadcaster_id = AsyncMock(return_value="999")

    with patch.object(bot, "join_channels", AsyncMock()), \
         patch.object(bot, "_restart_eventsub", AsyncMock()):
        await bot.add_guest_channel("streamer1")

    assert "streamer1" in bot._active_visits
    info = bot._active_visits["streamer1"]
    assert info["visit_id"] == 42
    assert info["msg_count"] == 0
    assert isinstance(info["joined_at"], float)
    bot.db.start_twitch_visit.assert_awaited_once_with("streamer1")


@pytest.mark.asyncio
async def test_remove_guest_channel_finalizes_visit(tmp_path):
    """remove_guest_channel doit lancer _finalize_visit en fire-and-forget."""
    bot = make_twitch_bot()
    bot.config.twitch.guest_channels = ["streamer1"]
    bot._active_visits["streamer1"] = {
        "visit_id": 42,
        "msg_count": 5,
        "joined_at": time.time() - 300,
    }

    with patch.object(bot, "part_channels", AsyncMock()), \
         patch.object(bot, "_restart_eventsub", AsyncMock()):
        await bot.remove_guest_channel("streamer1")

    # Laisser les tâches fire-and-forget se terminer
    await asyncio.sleep(0.05)

    assert "streamer1" not in bot._active_visits
    bot.db.end_twitch_visit.assert_awaited_once()
    call_args = bot.db.end_twitch_visit.call_args
    assert call_args.args[0] == 42   # visit_id
    assert call_args.args[2] == 5    # msg_count
    assert call_args.args[3] == "Bonne visite chez streamer."  # summary


@pytest.mark.asyncio
async def test_remove_guest_channel_without_active_visit():
    """remove_guest_channel sans visite active ne doit pas lever d'erreur."""
    bot = make_twitch_bot()
    bot.config.twitch.guest_channels = []
    # Pas d'entrée dans _active_visits

    with patch.object(bot, "part_channels", AsyncMock()), \
         patch.object(bot, "_restart_eventsub", AsyncMock()):
        await bot.remove_guest_channel("unknownchannel")  # ne doit pas raise

    bot.db.end_twitch_visit.assert_not_awaited()


@pytest.mark.asyncio
async def test_finalize_visit_calls_llm_and_db():
    """_finalize_visit doit appeler llm_secondary et end_twitch_visit."""
    bot = make_twitch_bot()
    joined_at = time.time() - 600

    await bot._finalize_visit("streamer1", 42, joined_at, 10)

    bot.llm_secondary.complete.assert_awaited_once()
    bot.db.end_twitch_visit.assert_awaited_once()
    call_args = bot.db.end_twitch_visit.call_args
    assert call_args.args[0] == 42
    assert call_args.args[2] == 10  # msg_count
    assert call_args.args[3] == "Bonne visite chez streamer."


@pytest.mark.asyncio
async def test_finalize_visit_handles_llm_error():
    """_finalize_visit doit enregistrer la visite même si le LLM échoue."""
    bot = make_twitch_bot()
    bot.llm_secondary.complete = AsyncMock(side_effect=Exception("LLM timeout"))
    joined_at = time.time() - 120

    await bot._finalize_visit("streamer1", 42, joined_at, 3)

    # end_twitch_visit doit quand même être appelé avec summary=None
    bot.db.end_twitch_visit.assert_awaited_once()
    call_args = bot.db.end_twitch_visit.call_args
    assert call_args.args[3] is None
```

- [ ] **Step 3.2 : Lancer les tests — vérifier qu'ils échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_twitch_bot_visits.py -v 2>&1 | tail -20
```

Attendu : FAILED (AttributeError sur `_active_visits`, `_fire`, `_finalize_visit`)

- [ ] **Step 3.3 : Modifier `WallyTwitch.__init__`**

Dans `bot/twitch/bot.py`, dans `__init__`, après la ligne `self._channel_was_live: dict[str, bool] = {}`, ajouter :

```python
        # Visites actives sur chaînes invitées : channel_name → {visit_id, msg_count, joined_at}
        self._active_visits: dict[str, dict] = {}
        # Strong refs pour fire-and-forget tasks
        self._bg_tasks: set[asyncio.Task] = set()
```

- [ ] **Step 3.4 : Ajouter `_fire()` dans `WallyTwitch`**

Après `set_cooldown()` (vers la ligne 74), ajouter :

```python
    def _fire(self, coro) -> asyncio.Task:
        """Fire-and-forget avec strong reference pour éviter la GC."""
        t = asyncio.create_task(coro)
        self._bg_tasks.add(t)
        t.add_done_callback(self._bg_tasks.discard)
        return t
```

- [ ] **Step 3.5 : Modifier `add_guest_channel`**

Dans `add_guest_channel`, remplacer la ligne `logger.info(...)` finale par :

```python
        logger.info("Wally rejoint la chaîne invitée {name} (id={bid})", name=name, bid=broadcaster_id)
        # Démarrer le tracking de la visite
        if self.db is not None:
            visit_id = await self.db.start_twitch_visit(name)
            self._active_visits[name] = {
                "visit_id": visit_id,
                "msg_count": 0,
                "joined_at": time.time(),
            }
        return broadcaster_id
```

**Important :** supprimer le `return broadcaster_id` qui existait avant si présent juste avant ce bloc.

- [ ] **Step 3.6 : Modifier `remove_guest_channel`**

Dans `remove_guest_channel`, avant la ligne `logger.info("Wally a quitté...")`, ajouter :

```python
        # Finaliser la visite en fire-and-forget
        info = self._active_visits.pop(name, None)
        if info:
            self._fire(self._finalize_visit(
                name,
                info["visit_id"],
                info["joined_at"],
                info["msg_count"],
            ))
```

- [ ] **Step 3.7 : Ajouter `_finalize_visit`**

Après `remove_guest_channel()`, ajouter :

```python
    async def _finalize_visit(
        self,
        channel: str,
        visit_id: int,
        joined_at: float,
        msg_count: int,
    ) -> None:
        """Génère un résumé LLM de la visite et persiste la ligne twitch_visits."""
        from bot.core.prompts import load_prompt
        left_at = time.time()

        # Récupérer les messages capturés pendant la visite
        context = self.memory.get_context(f"twitch:{channel}")
        summary: str | None = None
        try:
            system_prompt = load_prompt(
                "twitch_visit_summary",
                fallback=(
                    "Tu es Wally. Résume en 3-5 lignes à la première personne "
                    "ta visite sur la chaîne Twitch de {channel}, style carnet de voyage."
                ).format(channel=channel),
            )
            if context:
                messages_text = "\n".join(
                    f"[{m['author']}]: {m['content']}" for m in context[-50:]
                )
                user_content = (
                    f"Chaîne visitée : {channel}\n"
                    f"Durée : {int(left_at - joined_at) // 60} minutes\n"
                    f"Messages vus :\n{messages_text}"
                )
            else:
                user_content = (
                    f"Chaîne visitée : {channel}\n"
                    f"Durée : {int(left_at - joined_at) // 60} minutes\n"
                    f"Pas de messages capturés."
                )
            summary = await self.llm_secondary.complete(
                system_prompt,
                [{"role": "user", "content": user_content}],
                purpose="twitch_visit_summary",
            )
        except Exception as exc:
            logger.warning("_finalize_visit: LLM failed for {ch}: {e}", ch=channel, e=exc)

        if self.db is not None:
            try:
                await self.db.end_twitch_visit(visit_id, left_at, msg_count, summary)
                logger.info(
                    "Visite {ch} finalisée : {d}min, {n} msgs",
                    ch=channel, d=int(left_at - joined_at) // 60, n=msg_count,
                )
            except Exception as exc:
                logger.warning("_finalize_visit: DB write failed: {e}", e=exc)
```

- [ ] **Step 3.8 : Lancer les tests — vérifier qu'ils passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_twitch_bot_visits.py -v 2>&1 | tail -20
```

Attendu : 5 PASSED

- [ ] **Step 3.9 : Vérifier que les tests Twitch existants passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_twitch_handlers.py tests/test_twitch_events.py -v 2>&1 | tail -20
```

Attendu : tous PASSED

- [ ] **Step 3.10 : Commit**

```bash
git add bot/twitch/bot.py tests/test_twitch_bot_visits.py
git commit -m "feat(twitch): tracking visites guest — _active_visits, _finalize_visit, résumé LLM"
```

---

### Task 4: Incrémentation msg_count dans handle_message

**Files:**
- Modify: `bot/twitch/handlers.py`
- Test: `tests/test_twitch_handlers.py`

- [ ] **Step 4.1 : Écrire le test échouant**

Ajouter dans `tests/test_twitch_handlers.py` :

```python
@pytest.mark.asyncio
async def test_handle_message_increments_visit_msg_count(monkeypatch):
    """Un message sur une chaîne invitée active doit incrémenter msg_count."""
    monkeypatch.setenv("TWITCH_BOT_NICK", "wallybot")
    bot = make_bot()
    bot.config.twitch.channel = "homechannel"
    bot._active_visits = {
        "guestchannel": {"visit_id": 1, "msg_count": 3, "joined_at": time.time() - 100}
    }
    payload = make_payload(content="salut !", author_name="viewer1",
                           author_id="200", channel="guestchannel")
    await handle_message(bot, payload)
    assert bot._active_visits["guestchannel"]["msg_count"] == 4
```

- [ ] **Step 4.2 : Lancer le test — vérifier qu'il échoue**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_twitch_handlers.py::test_handle_message_increments_visit_msg_count -v 2>&1 | tail -10
```

Attendu : FAILED

- [ ] **Step 4.3 : Ajouter l'incrémentation dans `handle_message`**

Dans `bot/twitch/handlers.py`, dans `handle_message()`, après le bloc de filtrage bot badge (première dizaine de lignes de la fonction), trouver l'endroit où `channel_name` est défini et ajouter juste après — avant le traitement principal :

```python
    # Incrémentation du compteur de messages pour les visites actives
    active_visits = getattr(bot, "_active_visits", {})
    if channel_name in active_visits:
        active_visits[channel_name]["msg_count"] += 1
```

Placer ce bloc après la ligne `channel_id = f"twitch:{channel_name}"` (ligne ~76) et avant le bloc `overlay_cfg`.

- [ ] **Step 4.4 : Lancer le test — vérifier qu'il passe**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_twitch_handlers.py::test_handle_message_increments_visit_msg_count -v 2>&1 | tail -10
```

Attendu : PASSED

- [ ] **Step 4.5 : Vérifier les tests handlers existants**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_twitch_handlers.py -v 2>&1 | tail -20
```

Attendu : tous PASSED

- [ ] **Step 4.6 : Commit**

```bash
git add bot/twitch/handlers.py tests/test_twitch_handlers.py
git commit -m "feat(twitch): incrémente msg_count dans handle_message pour les visites actives"
```

---

### Task 5: Journal — bloc twitch_visits_block + test

**Files:**
- Modify: `bot/core/journal.py`
- Test: `tests/test_journal.py`

- [ ] **Step 5.1 : Écrire le test échouant**

Ajouter dans `tests/test_journal.py` :

```python
@pytest.mark.asyncio
async def test_journal_includes_twitch_visits_block():
    """Le journal doit inclure les visites Twitch dans son prompt si elles existent."""
    config, llm, llm_secondary, emotion, memory = make_deps()
    db = MagicMock()
    db.get_today_messages = AsyncMock(return_value=[])
    db.get_emotion_peaks_since = AsyncMock(return_value=[])
    db.get_emotion_snapshots_since = AsyncMock(return_value=[])
    db.get_emotion_averages = AsyncMock(return_value={})
    db.get_yesterday_journal = AsyncMock(return_value=None)
    db.get_gallery_images_for_date = AsyncMock(return_value=[])
    db.insert_journal = AsyncMock()
    db.get_twitch_visits_for_date = AsyncMock(return_value=[
        {
            "channel": "azrael",
            "joined_at": 1000.0,
            "left_at": 1000.0 + 2700,
            "duration_s": 2700,
            "msg_count": 34,
            "summary": "Chez Azrael, ambiance chill, un sub pendant ma visite.",
        }
    ])

    journal = DailyJournal(config, llm, llm_secondary, emotion, memory, db=db)
    journal.set_send_callback(AsyncMock())

    await journal.generate_and_send()

    # Vérifier que le prompt envoyé au LLM contient le bloc visites
    call_args = llm.complete.call_args
    user_msg = call_args[0][1][0]["content"]  # messages[0]["content"]
    assert "azrael" in user_msg.lower()
    assert "45 min" in user_msg
    assert "Chez Azrael" in user_msg
```

- [ ] **Step 5.2 : Lancer le test — vérifier qu'il échoue**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_journal.py::test_journal_includes_twitch_visits_block -v 2>&1 | tail -10
```

Attendu : FAILED

- [ ] **Step 5.3 : Ajouter le bloc `twitch_visits_block` dans `generate_and_send`**

Dans `bot/core/journal.py`, dans `generate_and_send()`, après le bloc `gallery_block` (vers la ligne 510), ajouter :

```python
        # ── Twitch visits of the day ──
        twitch_visits_block = ""
        if self._db is not None:
            try:
                visits = await self._db.get_twitch_visits_for_date(effective_date.isoformat())
                if visits:
                    lines = [f"**Visites Twitch du jour** : {len(visits)} chaîne(s)"]
                    for v in visits:
                        dur = f"{v['duration_s'] // 60} min" if v.get("duration_s") else "durée inconnue"
                        lines.append(f"- {v['channel']} ({dur}) : {v.get('summary') or '...'}")
                    twitch_visits_block = "\n".join(lines)
            except Exception as exc:
                logger.warning("Failed to get twitch visits for journal: {e}", e=exc)
```

Puis dans l'assemblage des `sections` (après le bloc `gallery_block`), ajouter :

```python
        if twitch_visits_block:
            sections.append(twitch_visits_block)
```

- [ ] **Step 5.4 : Lancer le test — vérifier qu'il passe**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_journal.py::test_journal_includes_twitch_visits_block -v 2>&1 | tail -10
```

Attendu : PASSED

- [ ] **Step 5.5 : Vérifier tous les tests journal**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_journal.py tests/test_journal_improvements.py -v 2>&1 | tail -20
```

Attendu : tous PASSED

- [ ] **Step 5.6 : Commit**

```bash
git add bot/core/journal.py tests/test_journal.py
git commit -m "feat(journal): bloc twitch_visits_block — visites du jour injectées dans le prompt"
```

---

### Task 6: Vérification finale

- [ ] **Step 6.1 : Lancer la suite complète**

```bash
cd /opt/stacks/wally-ai && python -m pytest --tb=short -q 2>&1 | tail -30
```

Attendu : tous les tests passent (876+ PASSED, 0 FAILED)

- [ ] **Step 6.2 : Commit final si nécessaire**

Si des fichiers non encore commités sont présents :

```bash
git status
git add <fichiers manquants>
git commit -m "chore: finalisation twitch visit journal"
```
