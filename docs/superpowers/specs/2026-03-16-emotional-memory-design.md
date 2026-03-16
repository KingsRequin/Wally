# Wally Bot — Mémoire Émotionnelle (Design Spec)

**Date :** 2026-03-16
**Scope :** Approche A+B — Profondeur émotionnelle & Intelligence mémorielle
**Statut :** Approuvé

---

## Objectif

Donner à Wally une vie intérieure persistante et mémorielle :

1. Son état émotionnel survit aux redémarrages
2. Son humeur est tracée dans le temps (courbe journalière)
3. Ses souvenirs sont colorés par l'émotion ressentie au moment de l'échange
4. Son journal peut raconter une vraie narrative émotionnelle de la journée
5. Les émotions sont affichées en pourcentage partout (plus lisible)

---

## Composants & fichiers impactés

| Fichier | Nature du changement |
|---|---|
| `bot/db/database.py` | 2 nouvelles tables dans `SCHEMA`, 5 nouveaux helpers |
| `bot/core/emotion.py` | `load_state()`, persistence debouncée, snapshot horaire, `build_emotion_tag()` module-level |
| `bot/core/memory.py` | Paramètre `emotion_context` optionnel sur `add()` |
| `bot/discord/handlers.py` | Construit le tag AVANT `_post_process` et le passe à `memory.add()` |
| `bot/twitch/handlers.py` | Même logique que Discord |
| `bot/core/journal.py` | Reçoit `db`, arc émotionnel injecté dans le prompt, `_build_emotion_arc()` module-level |
| `bot/discord/commands/mood.py` | Affichage en % (valeur sous barre) |
| `bot/discord/commands/setup.py` | Affichage en % partout : état initial, boutons +/-, modal feedback |
| `bot/main.py` | Injecte `db` dans `EmotionEngine` et `DailyJournal`, appelle `emotion.load_state()` |

> **Note** : `status.py` n'affiche que les noms des émotions dominantes (pas de valeur numérique) — pas de changement requis.

---

## 1. Nouvelles tables SQLite

Ces deux tables sont ajoutées à la constante `SCHEMA` dans `database.py`, au même niveau que les tables existantes. `executescript()` (appelé dans `Database.create()`) les crée automatiquement au démarrage.

### `emotion_state`

Stocke l'état courant (1 ligne par émotion). Rechargé au démarrage.

```sql
CREATE TABLE IF NOT EXISTS emotion_state (
    emotion    TEXT PRIMARY KEY,
    value      REAL NOT NULL DEFAULT 0.0,
    updated_at REAL NOT NULL
);
```

### `emotion_history`

Snapshots horodatés toutes les heures. Nettoyé automatiquement après 7 jours.

```sql
CREATE TABLE IF NOT EXISTS emotion_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_at REAL NOT NULL,
    anger       REAL NOT NULL DEFAULT 0.0,
    joy         REAL NOT NULL DEFAULT 0.0,
    sadness     REAL NOT NULL DEFAULT 0.0,
    curiosity   REAL NOT NULL DEFAULT 0.0,
    boredom     REAL NOT NULL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_emotion_history_ts ON emotion_history(snapshot_at);
```

### Helpers ajoutés à `Database`

```python
async def load_emotion_state(self) -> dict[str, float]
    # SELECT emotion, value FROM emotion_state
    # Retourne {} si vide

async def save_emotion_state(self, state: dict[str, float]) -> None
    # INSERT OR REPLACE INTO emotion_state VALUES (emotion, value, time.time())
    # Une ligne par émotion

async def insert_emotion_snapshot(self, state: dict[str, float]) -> None
    # INSERT INTO emotion_history (snapshot_at, anger, joy, sadness, curiosity, boredom)
    # VALUES (time.time(), ...)

async def get_today_emotion_snapshots(self) -> list[dict]
    # SELECT * FROM emotion_history WHERE snapshot_at >= <minuit Europe/Paris>
    # Retourne [] si aucun résultat

async def cleanup_old_emotion_history(self, days: int = 7) -> None
    # DELETE FROM emotion_history WHERE snapshot_at < time.time() - days * 86400
```

**Calcul de la borne "minuit" dans `get_today_emotion_snapshots()`** : utiliser `Europe/Paris` (même fuseau que `prompts.py` — cohérent avec la cron journal à 21h00). Le conteneur Docker peut tourner en UTC, il faut donc être explicite :

```python
from datetime import datetime
from zoneinfo import ZoneInfo
_TZ = ZoneInfo("Europe/Paris")
midnight = datetime.now(_TZ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
```

---

## 2. Persistence de l'état émotionnel (`emotion.py`)

### Nouveaux imports requis dans `emotion.py`

Aucun import supplémentaire — `asyncio`, `time`, `logger` sont déjà présents.

### Chargement au démarrage

`EmotionEngine.__init__` accepte un `db: Database | None = None` optionnel.

Le chargement initial de l'état est **asynchrone** — `__init__` ne peut pas l'awaiter. Une nouvelle méthode publique `async def load_state()` est ajoutée. Elle retourne immédiatement si `self._db is None` (comportement actuel conservé). Si la table est vide, `_state` reste à 0.0.

**Séquence complète dans `main.py`** (section qui remplace les lignes concernées) :

```python
db = await Database.create(db_path)           # crée le schéma (SCHEMA) en interne
await db.cleanup_old_emotion_history()        # nettoyage des snapshots > 7 jours
emotion = EmotionEngine(config, db=db)        # construction sync, _state = {e: 0.0}
await emotion.load_state()                    # charge l'état persisté depuis emotion_state
emotion.start_decay_task()                    # APRÈS load_state — évite un tick pendant le chargement
# ... (openai_client, memory, etc. inchangés)
journal = DailyJournal(config, openai_client, emotion, memory, db=db)
```

### Initialisations dans `__init__`

```python
self._db = db
self._dirty: bool = False
self._save_task: asyncio.Task | None = None
self._ticks: int = 0
```

### `load_state()`

```python
async def load_state(self) -> None:
    if self._db is None:
        return
    try:
        loaded = await self._db.load_emotion_state()
        for emotion, value in loaded.items():
            if emotion in self._state:
                self._state[emotion] = max(0.0, min(1.0, value))
        logger.info("Emotion state loaded from DB: {s}", s=self._state)
    except Exception as exc:
        logger.warning("Failed to load emotion state: {e}", e=exc)
        # _state reste à 0.0
```

### Sauvegarde debouncée

`apply_delta()` et `set_emotion()` marquent `self._dirty = True` et appellent `_schedule_save()`.

**Contrainte** : `asyncio.create_task()` requiert une boucle asyncio active. `apply_delta()` et `set_emotion()` ne doivent pas être appelées avant le démarrage de la boucle — ce n'est pas le cas dans le code actuel (`__init__` ne les appelle pas).

`_schedule_save()` retourne immédiatement si `self._db is None` (évite de créer des tâches inutiles).

`_delayed_save()` entoure le `save` d'un `try/except` : si la sauvegarde échoue, `_dirty` reste `True` (retry au prochain delta).

```python
def _schedule_save(self) -> None:
    if self._db is None:
        return
    if self._save_task and not self._save_task.done():
        self._save_task.cancel()
    self._save_task = asyncio.create_task(self._delayed_save())

async def _delayed_save(self) -> None:
    await asyncio.sleep(5)
    if self._db and self._dirty:
        try:
            await self._db.save_emotion_state(self._state)
            self._dirty = False
        except Exception as exc:
            logger.warning("Failed to persist emotion state: {e}", e=exc)
            # _dirty reste True → retry au prochain delta
```

### Snapshot horaire

`self._ticks` est initialisé à `0` dans `__init__`. La boucle `_decay_loop()` l'incrémente à chaque itération (60s). Toutes les 60 itérations (= 60 minutes), elle insère un snapshot.

`_apply_decay()` modifie `_state` — après chaque decay, `_dirty` est mis à `True` et `_schedule_save()` est appelé pour persister l'état décru. Ainsi, même sans message utilisateur, l'état persisté reflète la décroissance naturelle des émotions.

L'insertion du snapshot est enveloppée dans un `try/except` — une erreur DB ne doit pas interrompre la boucle de decay.

```python
async def _decay_loop(self) -> None:
    while True:
        await asyncio.sleep(60)
        self._apply_decay()
        self._dirty = True
        self._schedule_save()
        self._ticks += 1
        if self._ticks % 60 == 0 and self._db:
            try:
                await self._db.insert_emotion_snapshot(self._state)
            except Exception as exc:
                logger.warning("Failed to insert emotion snapshot: {e}", e=exc)
```

### Aucun breaking change

`db=None` est la valeur par défaut — le comportement actuel est conservé. Les tests existants ne changent pas.

---

## 3. Mémoire taguée émotionnellement (`memory.py` + handlers)

### `memory.add()` — nouveau paramètre optionnel

```python
async def add(self, platform: str, user_id: str, content: str,
              emotion_context: str = "") -> None:
    full_content = f"[{emotion_context}] {content}" if emotion_context else content
    # ... reste inchangé (full_content remplace content dans l'appel mem0)
```

### `build_emotion_tag()` dans `emotion.py`

Défini comme helper **module-level** dans `bot/core/emotion.py` (hors classe), publique (sans underscore) :

```python
def build_emotion_tag(emotion_state: dict[str, float]) -> str:
    """Construit un tag textuel à partir des émotions dominantes (≥ 0.4)."""
    dominant = [e for e, v in emotion_state.items() if v >= 0.4]
    if not dominant:
        return ""
    return "Wally: " + ", ".join(dominant)
```

Import dans les deux handlers :
```python
from bot.core.emotion import build_emotion_tag
```

### Ordre d'appel dans les handlers

Le tag est construit **avant** `_fire(_post_process(...))`, pour capturer l'état émotionnel au moment de l'échange (avant que `process_message` ne le modifie).

**Discord** (`bot/discord/handlers.py`) — dans `_respond()`, remplace les deux `_fire()` existants en fin de fonction :

```python
tag = build_emotion_tag(bot.emotion.get_state())
_fire(bot.memory.add(platform, user_id, exchange, emotion_context=tag))
_fire(_post_process(bot, message.content, platform, user_id, guild_id, trust, context_messages))
```

**Twitch** (`bot/twitch/handlers.py`) — dans `handle_message()`, remplace les `_fire()` existants. Note : `_post_process` Twitch n'a pas de paramètre `guild_id` (Twitch ne gère pas de guilds) :

```python
tag = build_emotion_tag(bot.emotion.get_state())
_fire(bot.memory.add(platform, user_id, exchange, emotion_context=tag))
_fire(_post_process(bot, content, platform, user_id, trust, context_msgs))
```

### Exemples de tags

- `""` → entrée neutre, aucun tag ajouté
- `"Wally: curiosity"` → Wally était curieux
- `"Wally: anger, sadness"` → Wally était en colère et mélancolique

### Impact sur la récupération

`memory.search()` n'est pas modifié. Le LLM voit le tag dans le texte brut des souvenirs et peut interpréter le contexte émotionnel d'un échange passé.

---

## 4. Journal enrichi avec arc émotionnel (`journal.py`)

### Nouveaux imports requis dans `journal.py`

```python
from datetime import datetime   # s'ajoute à l'import existant `from datetime import date`
from zoneinfo import ZoneInfo
```

### `DailyJournal.__init__` — nouveau paramètre

`db: Database | None = None` (optionnel pour ne pas casser les tests existants). Si `None`, l'arc est omis du journal (fallback silencieux).

```python
def __init__(self, config, openai, emotion, memory, db=None):
    ...
    self._db = db
```

### `_build_emotion_arc()` — fonction module-level

Même convention que `_split_for_discord` déjà présente dans ce fichier.

```python
_TZ_JOURNAL = ZoneInfo("Europe/Paris")

def _build_emotion_arc(snapshots: list[dict]) -> str:
    """Construit l'arc émotionnel de la journée depuis les snapshots horaires."""
    if len(snapshots) < 2:
        return ""
    lines = []
    for snap in snapshots:
        ts = datetime.fromtimestamp(snap["snapshot_at"], tz=_TZ_JOURNAL)
        parts = []
        for emotion in ["anger", "joy", "sadness", "curiosity", "boredom"]:
            pct = int(snap[emotion] * 100)
            if pct < 30:
                continue
            if pct >= 70:
                label = f"pic de {emotion} ({pct}%)"
            elif pct >= 50:
                label = f"{emotion} montante ({pct}%)"
            else:
                label = f"{emotion} légère ({pct}%)"
            parts.append(label)
        if parts:
            lines.append(f"{ts.strftime('%Hh%M')} — {', '.join(parts)}")
        else:
            lines.append(f"{ts.strftime('%Hh%M')} — neutre")
    return "Arc émotionnel de la journée :\n" + "\n".join(lines)
```

### Injection dans `generate_and_send()`

L'arc est injecté par **concaténation conditionnelle** (pas via `str.format()` avec `{arc}` — évite les lignes vides parasites si arc est vide) :

`_JOURNAL_USER_TEMPLATE` (constante module-level actuelle) est **supprimée** — la construction du message passe entièrement par concaténation conditionnelle dans `generate_and_send()` :

```python
# Récupération des snapshots (try/except → fallback [] si DB indisponible ou erreur)
try:
    snapshots = await self._db.get_today_emotion_snapshots() if self._db else []
except Exception as exc:
    logger.warning("Failed to get emotion snapshots for journal: {e}", e=exc)
    snapshots = []

arc = _build_emotion_arc(snapshots)
arc_section = f"\n{arc}\n" if arc else ""

emotions_text = ", ".join(f"{k}: {int(v*100)}%" for k, v in emotions.items())

user_msg = (
    f"Voici un résumé de la journée :\n\n{context_text}"
    f"{arc_section}"
    f"\nTon état émotionnel actuel : {emotions_text}\n\n"
    f"Écris ton journal intime pour aujourd'hui."
)
```

**Fallback** : si `arc == ""` (< 2 snapshots ou DB indisponible/erreur), la section est absente — aucune régression.

---

## 5. Affichage en pourcentage

La représentation interne (float 0.0–1.0) n'est pas modifiée. Seul l'affichage change.

**`commands/mood.py`** — ligne `value=f"{bar} \`{value:.2f}\`"` → `value=f"{bar} \`{int(value*100)}%\`"`

**`journal.py`** — `emotions_text` dans `generate_and_send()` : voir construction dans la section 4.

**`commands/setup.py`** — 4 occurrences à changer :

| Classe | Ligne actuelle | Nouvelle valeur |
|---|---|---|
| `SetupTabSelect.callback` (onglet mood) | `f"**{e}** : {v:.2f}"` | `f"**{e}** : {int(v*100)}%"` |
| `EmotionMinusButton.callback` | `f"{self.emotion}: {v:.2f}"` | `f"{self.emotion}: {int(v*100)}%"` |
| `EmotionPlusButton.callback` | `f"{self.emotion}: {v:.2f}"` | `f"{self.emotion}: {int(v*100)}%"` |
| `EditEmotionModal.on_submit` | `f"{self.emotion} mis à {v:.2f}"` | `f"{self.emotion} mis à {int(v*100)}%"` |

**`journal.py`** — `emotions_text` dans `generate_and_send()` : voir section 4 ci-dessus.

---

## Flux de données complet

```
Message reçu
    │
    ├─► memory.append_message()              (contexte glissant, inchangé)
    │
    ▼
_respond() / handle_message()
    │
    ├─► emotion.get_state()                  → build_emotion_tag() → tag
    ├─► _fire(memory.add(..., tag))          → stockage enrichi dans mem0
    └─► _fire(_post_process())
            └─► emotion.process_message()
                    └─► apply_delta()
                            ├─► _dirty = True
                            └─► _schedule_save() → DB dans 5s

Chaque heure (_decay_loop, ticks % 60 == 0):
    └─► db.insert_emotion_snapshot()

À 21h00 (journal):
    ├─► db.get_today_emotion_snapshots() → _build_emotion_arc()
    └─► openai.complete_secondary()      → journal avec arc
```

---

## Gestion des erreurs

- `db=None` partout : pas de persistence, comportement actuel conservé (0 crash)
- `load_state()` échoue : log WARNING, `_state` reste à 0.0
- `save_emotion_state()` échoue : log WARNING, `_dirty` reste True (retry au prochain delta)
- `get_today_emotion_snapshots()` échoue : `try/except` dans `generate_and_send()`, `snapshots = []`, arc omis
- `insert_emotion_snapshot()` échoue : `try/except` dans `_decay_loop()`, log WARNING, boucle continue

---

## Tests à ajouter

- `test_emotion_state_persists_across_restart` — load/save round-trip via DB mock asyncio
- `test_snapshot_written_every_hour` — ticks % 60 == 0 déclenche `insert_emotion_snapshot`
- `test_load_state_no_db` — `load_state()` sans DB ne crash pas, state reste 0.0
- `test_emotion_tag_added_to_memory` — tag présent quand émotion ≥ 0.4, absent sinon
- `test_emotion_tag_before_post_process` — tag capturé avant modification par `process_message`
- `test_journal_arc_format` — arc bien construit depuis snapshots fictifs, heures en Europe/Paris
- `test_journal_arc_fallback_no_snapshots` — pas de crash si 0 ou 1 snapshot, arc omis
- `test_percentage_display` — dans `test_discord_commands.py` : les embeds de `/wally mood` et les feedbacks de `setup` (boutons +/-, modal) contiennent `"73%"` et non `"0.73"` pour une émotion à 0.73
- `test_journal_emotions_text_percentage` — `emotions_text` dans le message journal contient `"joy: 73%"` et non `"joy: 0.73"`
- Vérifier que les tests existants de `test_journal.py` passent sans modification (`DailyJournal(config, openai, emotion, memory)` reste valide car `db=None` par défaut)
