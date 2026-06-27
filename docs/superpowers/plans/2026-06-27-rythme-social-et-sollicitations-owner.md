# Rythme social appris + discipline des sollicitations owner — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Donner à Wally une conscience apprise du rythme social (réceptivité de l'audience) pour réguler sa parole publique spontanée, et discipliner ses sollicitations vers l'owner (plus d'auto-refus du self-fix, un seul fil de sollicitation à la fois) — le tout sans jamais coder de seuil horaire en dur.

**Architecture :** Un service `SocialRhythm` apprend par EMA, dans des créneaux *heure × semaine/weekend*, deux signaux (volume de messages reçus = `ambient` ; taux de réponse à ses messages spontanés = `engagement`) et restitue une réceptivité ∈ [0,1]. La boucle cognitive la consomme (cadence, conscience injectée, amortisseur probabiliste du SPEAK). En parallèle, un `OwnerOutreachGate` partagé empêche l'empilement de MP vers l'owner, et le self-fix perd son auto-refus sur silence.

**Tech Stack :** Python 3 asyncio, aiosqlite (SQLite), loguru (jamais `print`), `zoneinfo.ZoneInfo`, pytest (+ `pytest.mark.asyncio` pour l'async). Pas de nouvelle dépendance externe.

## Global Constraints

- **Logging :** `from loguru import logger` exclusivement — jamais `print` ni `import logging`.
- **Async :** tout I/O est async ; le travail CPU léger reste synchrone et rapide. Best-effort : aucun signal d'apprentissage ne doit jamais casser un tick (try/except → log, continue).
- **Fuseau :** lire le fuseau via `config.circadian.timezone` (`"Europe/Paris"`, attribut RACINE de `Config`, PAS `config.emotions.*`). Aucun seuil « nuit » codé en dur.
- **DB :** schéma ajouté de façon **idempotente** dans `bot/db/schema_v2.py` (`CREATE TABLE IF NOT EXISTS`). La fonction `create_v2_tables(db_path)` y est le point d'entrée.
- **Construction des services cognitifs :** dans `bot/discord/bot.py` `setup_hook` (≈ l.169-226), PAS dans `bootstrap.py`. Accès depuis les handlers via attributs `bot.*` (`bot.cognitive_loop`, `bot.self_fix`, `bot.conv_log`, `bot.config`, `bot.db`).
- **Émotions :** `emotion_engine.get_state()` renvoie `dict[str,float]` clés `anger, joy, sadness, curiosity, boredom`.
- **Tests baseline préexistants à ignorer** (ne PAS compter comme régressions) : `tests/test_web_search.py::test_complete_with_tools_logs_cost` et `tests/test_dashboard_costs.py`.
- **Commandes de vérif :** `python3 -m pytest -q` (suite complète) ; cible : `python3 -m pytest tests/test_xxx.py -q`.
- **Déploiement :** backend non bind-mount → activation = rebuild image (hors périmètre de ce plan, ne pas le faire ici).

---

## File Structure

**Phase 1 — modèle (isolé, sans câblage) :**
- Create `bot/intelligence/social_rhythm.py` — le service `SocialRhythm` (modèle EMA + réceptivité + describe + persistance + backfill).
- Modify `bot/db/schema_v2.py` — table `social_rhythm_bins`.
- Create `tests/test_social_rhythm.py`.

**Phase 2 — branchement cognitif (parole publique) :**
- Modify `bot/intelligence/attention_agent.py` — champ `social_receptivity`, fix `time_of_day` UTC→Paris.
- Modify `bot/intelligence/reasoning_agent.py` — rendu de `social_receptivity` dans le prompt.
- Modify `bot/intelligence/cognitive_loop.py` — alimentation des signaux + cadence somnolente + amortisseur SPEAK.
- Modify `bot/discord/bot.py` — DI : construire `SocialRhythm`, le charger, l'injecter, le backfill.
- Modify `tests/` (nouveaux tests d'intégration cognitive).

**Phase 3 — sollicitations owner :**
- Create `bot/intelligence/owner_outreach.py` — `OwnerOutreachGate`.
- Modify `bot/intelligence/self_fix.py` — retrait auto-refus/blacklist + gate.
- Modify `bot/intelligence/action_dispatcher.py` — `_dm` consulte le gate.
- Modify `bot/discord/handlers.py` — DM owner entrant → `gate.clear()`.
- Modify `bot/discord/bot.py` — DI gate.
- Create `tests/test_owner_outreach.py`.

---

# PHASE 1 — Le modèle `SocialRhythm`

## Task 1 : Table `social_rhythm_bins` (schéma DB)

**Files:**
- Modify: `bot/db/schema_v2.py`
- Test: `tests/test_social_rhythm_schema.py` *(create)*

**Interfaces:**
- Consumes: `create_v2_tables(db_path: str)` existant.
- Produces: table `social_rhythm_bins(bin_key TEXT PRIMARY KEY, avg REAL, eng REAL, days INTEGER, eng_obs INTEGER, updated_at TEXT)`.

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/test_social_rhythm_schema.py
import aiosqlite
import pytest
from bot.db.schema_v2 import create_v2_tables


@pytest.mark.asyncio
async def test_social_rhythm_bins_table_created(tmp_path):
    db_path = str(tmp_path / "t.db")
    await create_v2_tables(db_path)
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='social_rhythm_bins'"
        )
        assert await cur.fetchone() is not None
        cur = await db.execute("PRAGMA table_info(social_rhythm_bins)")
        cols = {row[1] for row in await cur.fetchall()}
        assert cols == {"bin_key", "avg", "eng", "days", "eng_obs", "updated_at"}


@pytest.mark.asyncio
async def test_create_v2_tables_idempotent(tmp_path):
    db_path = str(tmp_path / "t.db")
    await create_v2_tables(db_path)
    await create_v2_tables(db_path)  # ne doit pas lever
```

- [ ] **Step 2 : Lancer le test pour vérifier l'échec**

Run: `python3 -m pytest tests/test_social_rhythm_schema.py -q`
Expected: FAIL (`social_rhythm_bins` absente).

- [ ] **Step 3 : Ajouter la DDL dans `_SCHEMA_SQL`**

Dans `bot/db/schema_v2.py`, ajouter à la fin de la chaîne `_SCHEMA_SQL` (avant la `"""` fermante, après le bloc des triggers FTS) :

```sql
CREATE TABLE IF NOT EXISTS social_rhythm_bins (
    bin_key    TEXT    PRIMARY KEY,
    avg        REAL    NOT NULL DEFAULT 0.0,
    eng        REAL    NOT NULL DEFAULT 0.5,
    days       INTEGER NOT NULL DEFAULT 0,
    eng_obs    INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT    NOT NULL
);
```

- [ ] **Step 4 : Lancer le test pour vérifier le succès**

Run: `python3 -m pytest tests/test_social_rhythm_schema.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5 : Commit**

```bash
git add bot/db/schema_v2.py tests/test_social_rhythm_schema.py
git commit -m "feat(cognition): table social_rhythm_bins (rythme social appris)"
```

---

## Task 2 : Cœur `SocialRhythm` — apprentissage EMA et réceptivité

**Files:**
- Create: `bot/intelligence/social_rhythm.py`
- Test: `tests/test_social_rhythm.py` *(create)*

**Interfaces:**
- Produces :
  - `SocialRhythm(tz: str = "Europe/Paris", alpha: float = 0.1, n_conf: int = 20)`
  - `record_incoming(self, when: datetime) -> None`
  - `record_spontaneous_outcome(self, answered: bool, when: datetime) -> None`
  - `receptivity(self, when: datetime) -> float`  (∈ [0,1])
  - constantes module : `PRIOR = 0.5`, `W_AMBIENT = 0.5`, `W_ENGAGEMENT = 0.5`, `R_REF = 0.4`

**Note de conception (à respecter) :** `ambient` est appris via une EMA **au passage d'un jour** : on accumule un compteur de messages par créneau pendant la journée, puis au changement de date on replie ce compteur dans la moyenne EMA (`avg`) des 24 créneaux du type-de-jour écoulé — y compris les créneaux à 0 (la nuit décroît donc vers 0 d'elle-même). `engagement` est une EMA directe de `answered ∈ {0,1}` mise à jour à chaque issue. Aucun seuil horaire codé.

- [ ] **Step 1 : Écrire les tests qui échouent**

```python
# tests/test_social_rhythm.py
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from bot.intelligence.social_rhythm import SocialRhythm, PRIOR

PARIS = ZoneInfo("Europe/Paris")


def _dt(day, hour):
    # 2026-06-01 = lundi (semaine)
    return datetime(2026, 6, day, hour, 0, tzinfo=PARIS)


def test_cold_start_is_neutral():
    sr = SocialRhythm()
    assert sr.receptivity(_dt(1, 3)) == pytest.approx(PRIOR, abs=1e-9)


def test_learns_night_dip():
    sr = SocialRhythm(alpha=0.5, n_conf=3)
    # 6 jours : beaucoup de messages à 14h, zéro la nuit (3h).
    for day in range(1, 7):
        for _ in range(20):
            sr.record_incoming(_dt(day, 14))
        # parole spontanée nocturne toujours ignorée, diurne toujours répondue
        sr.record_spontaneous_outcome(False, _dt(day, 3))
        sr.record_spontaneous_outcome(True, _dt(day, 14))
    night = sr.receptivity(_dt(8, 3))   # 2026-06-08 = lundi
    day = sr.receptivity(_dt(8, 14))
    assert day > 0.6
    assert night < 0.2
    assert night < day


def test_weekend_distinct_from_weekday():
    sr = SocialRhythm(alpha=0.5, n_conf=2)
    # weekday 20h vide, weekend 20h chargé → réceptivités différentes au même créneau horaire
    for day in (6, 7, 13, 14):      # samedis/dimanches de juin 2026
        for _ in range(20):
            sr.record_incoming(_dt(day, 20))
    wknd = sr.receptivity(_dt(20, 20))   # samedi
    week = sr.receptivity(_dt(22, 20))   # lundi
    assert wknd > week


def test_engagement_pushes_receptivity_over_time():
    sr = SocialRhythm(alpha=0.5, n_conf=2)
    for day in range(1, 5):
        sr.record_incoming(_dt(day, 10))
        sr.record_spontaneous_outcome(True, _dt(day, 10))
    high = sr.receptivity(_dt(8, 10))
    for day in range(1, 5):
        sr.record_incoming(_dt(day, 10))
        sr.record_spontaneous_outcome(False, _dt(day, 10))
    low = sr.receptivity(_dt(8, 10))
    assert low < high
```

- [ ] **Step 2 : Lancer pour vérifier l'échec**

Run: `python3 -m pytest tests/test_social_rhythm.py -q`
Expected: FAIL (`ModuleNotFoundError: bot.intelligence.social_rhythm`).

- [ ] **Step 3 : Écrire l'implémentation minimale**

```python
# bot/intelligence/social_rhythm.py
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from loguru import logger

# Prior doux au démarrage : tant qu'un créneau n'a pas assez d'observations,
# la réceptivité reste « modérée » (ni muet ni bavard).
PRIOR = 0.5
# Pondération ambient (vivacité) vs engagement (taux de réponse à ses messages).
W_AMBIENT = 0.5
W_ENGAGEMENT = 0.5
# Réceptivité de référence : au-dessus, la parole spontanée passe toujours ;
# en-dessous, la proba chute linéairement (cf. cognitive_loop). 0.4 ≈ « journée normale ».
R_REF = 0.4


def _daytype(when: datetime) -> str:
    return "we" if when.weekday() >= 5 else "wk"


def _key(when: datetime) -> str:
    return f"{_daytype(when)}:{when.hour:02d}"


class SocialRhythm:
    """Apprend, par créneau heure×semaine/weekend, à quel point l'audience est
    réceptive (0→1). Aucun seuil horaire codé : la nuit émerge comme un creux."""

    def __init__(self, tz: str = "Europe/Paris", alpha: float = 0.1,
                 n_conf: int = 20) -> None:
        self._tz = ZoneInfo(tz)
        self._alpha = alpha
        self._n_conf = max(1, n_conf)
        # bin_key -> {"avg": float, "eng": float, "days": int, "eng_obs": int,
        #             "count": float (intra-jour, non persisté)}
        self._bins: dict[str, dict] = {}
        self._cur_day: str | None = None
        self._cur_daytype: str = "wk"

    def _bin(self, key: str) -> dict:
        return self._bins.setdefault(
            key, {"avg": 0.0, "eng": 0.5, "days": 0, "eng_obs": 0, "count": 0.0}
        )

    # --- Apprentissage ----------------------------------------------------
    def record_incoming(self, when: datetime) -> None:
        """Un message reçu → vivacité du créneau courant (signal ambient)."""
        w = when.astimezone(self._tz)
        day = w.strftime("%Y-%m-%d")
        if self._cur_day is None:
            self._cur_day, self._cur_daytype = day, _daytype(w)
        elif day != self._cur_day:
            self._roll_day()
            self._cur_day, self._cur_daytype = day, _daytype(w)
        self._bin(_key(w))["count"] += 1.0

    def _roll_day(self) -> None:
        """Replie les compteurs intra-jour dans la moyenne EMA des 24 créneaux du
        type-de-jour écoulé (les créneaux à 0 décroissent → la nuit s'éteint seule)."""
        dt = self._cur_daytype
        a = self._alpha
        for h in range(24):
            b = self._bin(f"{dt}:{h:02d}")
            b["avg"] = b["avg"] * (1 - a) + b["count"] * a
            b["count"] = 0.0
            b["days"] += 1

    def record_spontaneous_outcome(self, answered: bool, when: datetime) -> None:
        """Issue d'un message spontané : répondu (+) ou ignoré ( ). EMA d'engagement."""
        w = when.astimezone(self._tz)
        b = self._bin(_key(w))
        a = self._alpha
        b["eng"] = b["eng"] * (1 - a) + (1.0 if answered else 0.0) * a
        b["eng_obs"] += 1

    # --- Restitution ------------------------------------------------------
    def receptivity(self, when: datetime) -> float:
        w = when.astimezone(self._tz)
        b = self._bins.get(_key(w))
        max_avg = max((x["avg"] for x in self._bins.values()), default=0.0)
        ambient = (b["avg"] / max_avg) if (b and max_avg > 0) else PRIOR
        eng = b["eng"] if b else PRIOR
        observed = W_AMBIENT * ambient + W_ENGAGEMENT * eng
        obs = (b["days"] + b["eng_obs"]) if b else 0
        conf = min(1.0, obs / self._n_conf)
        return PRIOR * (1 - conf) + observed * conf
```

- [ ] **Step 4 : Lancer pour vérifier le succès**

Run: `python3 -m pytest tests/test_social_rhythm.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5 : Commit**

```bash
git add bot/intelligence/social_rhythm.py tests/test_social_rhythm.py
git commit -m "feat(cognition): SocialRhythm — apprentissage EMA de la réceptivité"
```

---

## Task 3 : Persistance (`load` / `persist`)

**Files:**
- Modify: `bot/intelligence/social_rhythm.py`
- Test: `tests/test_social_rhythm_persist.py` *(create)*

**Interfaces:**
- Consumes: table `social_rhythm_bins` (Task 1), `aiosqlite`.
- Produces:
  - `async def load(self, db_path: str) -> None`
  - `async def persist(self, db_path: str) -> None`

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/test_social_rhythm_persist.py
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from bot.db.schema_v2 import create_v2_tables
from bot.intelligence.social_rhythm import SocialRhythm

PARIS = ZoneInfo("Europe/Paris")


@pytest.mark.asyncio
async def test_persist_then_load_roundtrip(tmp_path):
    db_path = str(tmp_path / "t.db")
    await create_v2_tables(db_path)
    sr = SocialRhythm(alpha=0.5, n_conf=2)
    for day in range(1, 5):
        for _ in range(10):
            sr.record_incoming(datetime(2026, 6, day, 14, tzinfo=PARIS))
        sr.record_spontaneous_outcome(True, datetime(2026, 6, day, 14, tzinfo=PARIS))
    # force un rollover final pour replier le dernier jour
    sr.record_incoming(datetime(2026, 6, 6, 14, tzinfo=PARIS))
    await sr.persist(db_path)

    sr2 = SocialRhythm(alpha=0.5, n_conf=2)
    await sr2.load(db_path)
    probe = datetime(2026, 6, 8, 14, tzinfo=PARIS)
    assert sr2.receptivity(probe) == pytest.approx(sr.receptivity(probe), abs=1e-9)
```

- [ ] **Step 2 : Lancer pour vérifier l'échec**

Run: `python3 -m pytest tests/test_social_rhythm_persist.py -q`
Expected: FAIL (`AttributeError: 'SocialRhythm' object has no attribute 'persist'`).

- [ ] **Step 3 : Ajouter `load`/`persist`**

Ajouter `import aiosqlite` en tête de `bot/intelligence/social_rhythm.py`, puis ces méthodes à la classe :

```python
    async def load(self, db_path: str) -> None:
        try:
            async with aiosqlite.connect(db_path) as db:
                cur = await db.execute(
                    "SELECT bin_key, avg, eng, days, eng_obs FROM social_rhythm_bins"
                )
                for key, avg, eng, days, eng_obs in await cur.fetchall():
                    self._bins[key] = {
                        "avg": avg, "eng": eng, "days": days,
                        "eng_obs": eng_obs, "count": 0.0,
                    }
            logger.info("SocialRhythm: {} créneaux chargés", len(self._bins))
        except Exception as e:  # noqa: BLE001 — best-effort, jamais bloquant
            logger.warning("SocialRhythm.load a échoué: {}", e)

    async def persist(self, db_path: str) -> None:
        try:
            from datetime import datetime as _dt, timezone as _tz
            now_iso = _dt.now(_tz.utc).isoformat()
            async with aiosqlite.connect(db_path) as db:
                for key, b in self._bins.items():
                    await db.execute(
                        "INSERT INTO social_rhythm_bins(bin_key, avg, eng, days, eng_obs, updated_at) "
                        "VALUES (?,?,?,?,?,?) ON CONFLICT(bin_key) DO UPDATE SET "
                        "avg=excluded.avg, eng=excluded.eng, days=excluded.days, "
                        "eng_obs=excluded.eng_obs, updated_at=excluded.updated_at",
                        (key, b["avg"], b["eng"], b["days"], b["eng_obs"], now_iso),
                    )
                await db.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning("SocialRhythm.persist a échoué: {}", e)
```

- [ ] **Step 4 : Lancer pour vérifier le succès**

Run: `python3 -m pytest tests/test_social_rhythm_persist.py -q`
Expected: PASS.

- [ ] **Step 5 : Commit**

```bash
git add bot/intelligence/social_rhythm.py tests/test_social_rhythm_persist.py
git commit -m "feat(cognition): persistance SocialRhythm (load/persist sqlite)"
```

---

## Task 4 : `describe()` — phrase de conscience FR

**Files:**
- Modify: `bot/intelligence/social_rhythm.py`
- Test: `tests/test_social_rhythm.py` *(ajouter)*

**Interfaces:**
- Produces: `def describe(self, when: datetime) -> str` — phrase courte en français, jamais vide.

- [ ] **Step 1 : Écrire le test qui échoue (ajouter à `tests/test_social_rhythm.py`)**

```python
def test_describe_reflects_low_and_high():
    sr = SocialRhythm(alpha=0.5, n_conf=3)
    for day in range(1, 7):
        for _ in range(20):
            sr.record_incoming(_dt(day, 14))
        sr.record_spontaneous_outcome(False, _dt(day, 3))
        sr.record_spontaneous_outcome(True, _dt(day, 14))
    low = sr.describe(_dt(8, 3))
    high = sr.describe(_dt(8, 14))
    assert isinstance(low, str) and low
    assert isinstance(high, str) and high
    assert low != high
```

- [ ] **Step 2 : Lancer pour vérifier l'échec**

Run: `python3 -m pytest tests/test_social_rhythm.py::test_describe_reflects_low_and_high -q`
Expected: FAIL (`AttributeError: ... 'describe'`).

- [ ] **Step 3 : Ajouter `describe`**

```python
    def describe(self, when: datetime) -> str:
        """Phrase FR injectée dans le contexte cognitif (conscience, pas contrainte)."""
        r = self.receptivity(when)
        w = when.astimezone(self._tz)
        jour = "ce week-end" if _daytype(w) == "we" else "en semaine"
        if r < 0.2:
            etat = ("le serveur est historiquement très calme à cette heure ; "
                    "tes derniers messages à ce moment sont souvent restés sans réponse")
        elif r < 0.5:
            etat = "l'activité est plutôt faible à cette heure"
        else:
            etat = "c'est une heure où l'audience est généralement présente et réactive"
        return f"Il est {w.hour}h {jour} : {etat} (réceptivité apprise {r:.2f})."
```

- [ ] **Step 4 : Lancer pour vérifier le succès**

Run: `python3 -m pytest tests/test_social_rhythm.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5 : Commit**

```bash
git add bot/intelligence/social_rhythm.py tests/test_social_rhythm.py
git commit -m "feat(cognition): SocialRhythm.describe (conscience FR injectable)"
```

---

## Task 5 : Backfill depuis les logs de conversation

**Files:**
- Modify: `bot/intelligence/social_rhythm.py`
- Test: `tests/test_social_rhythm_backfill.py` *(create)*

**Interfaces:**
- Consumes: arborescence `logs/conversations/discord/<channel>/<YYYY-MM-DD>.jsonl`, lignes `{"ts": <epoch float>, "type": "message_in", ...}`.
- Produces: `def backfill_from_logs(self, logs_dir: str) -> int` — renvoie le nb de messages rejoués ; alimente `ambient` (replays `record_incoming` puis force un rollover final). Best-effort (logs absents → 0).

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/test_social_rhythm_backfill.py
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from bot.intelligence.social_rhythm import SocialRhythm

PARIS = ZoneInfo("Europe/Paris")


def _write_log(root, channel, day, hours):
    d = root / "discord" / channel
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{day}.jsonl"
    with f.open("w") as fh:
        for h in hours:
            ts = datetime(2026, 6, int(day[-2:]), h, tzinfo=PARIS).timestamp()
            fh.write(json.dumps({"ts": ts, "type": "message_in", "content": "x"}) + "\n")


def test_backfill_warms_ambient(tmp_path):
    logs = tmp_path / "logs" / "conversations"
    # 14h très actif sur plusieurs jours, 3h jamais
    for day in ("2026-06-01", "2026-06-02", "2026-06-03"):
        _write_log(logs, "123", day, [14] * 10)
    sr = SocialRhythm(alpha=0.5, n_conf=2)
    n = sr.backfill_from_logs(str(logs))
    assert n == 30
    assert sr.receptivity(datetime(2026, 6, 8, 14, tzinfo=PARIS)) > \
           sr.receptivity(datetime(2026, 6, 8, 3, tzinfo=PARIS))


def test_backfill_missing_dir_is_safe(tmp_path):
    sr = SocialRhythm()
    assert sr.backfill_from_logs(str(tmp_path / "nope")) == 0
```

- [ ] **Step 2 : Lancer pour vérifier l'échec**

Run: `python3 -m pytest tests/test_social_rhythm_backfill.py -q`
Expected: FAIL (`AttributeError: ... 'backfill_from_logs'`).

- [ ] **Step 3 : Ajouter `backfill_from_logs`**

Ajouter `import json`, `import os`, `from datetime import timezone` en tête, puis :

```python
    def backfill_from_logs(self, logs_dir: str) -> int:
        """Pré-chauffe `ambient` en rejouant les 'message_in' horodatés des logs
        Discord. Best-effort : un fichier illisible est ignoré ligne à ligne."""
        base = os.path.join(logs_dir, "discord")
        if not os.path.isdir(base):
            return 0
        events: list[datetime] = []
        for channel in os.listdir(base):
            cdir = os.path.join(base, channel)
            if not os.path.isdir(cdir):
                continue
            for fname in os.listdir(cdir):
                if not fname.endswith(".jsonl"):
                    continue
                try:
                    with open(os.path.join(cdir, fname)) as fh:
                        for line in fh:
                            try:
                                rec = json.loads(line)
                            except Exception:  # noqa: BLE001 — ligne corrompue
                                continue
                            if rec.get("type") != "message_in":
                                continue
                            ts = rec.get("ts")
                            if isinstance(ts, (int, float)):
                                events.append(
                                    datetime.fromtimestamp(ts, tz=timezone.utc)
                                )
                except Exception as e:  # noqa: BLE001
                    logger.warning("SocialRhythm backfill: {} illisible: {}", fname, e)
        events.sort()
        for when in events:
            self.record_incoming(when)
        if events:
            self._roll_day()  # replie le dernier jour rejoué
        logger.info("SocialRhythm: backfill de {} messages depuis les logs", len(events))
        return len(events)
```

- [ ] **Step 4 : Lancer pour vérifier le succès**

Run: `python3 -m pytest tests/test_social_rhythm_backfill.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5 : Lancer toute la suite Phase 1 + commit**

Run: `python3 -m pytest tests/test_social_rhythm.py tests/test_social_rhythm_persist.py tests/test_social_rhythm_backfill.py tests/test_social_rhythm_schema.py -q`
Expected: PASS (tous).

```bash
git add bot/intelligence/social_rhythm.py tests/test_social_rhythm_backfill.py
git commit -m "feat(cognition): backfill SocialRhythm depuis logs de conversation"
```

**⛔ CHECKPOINT PHASE 1 — valider avec l'utilisateur avant la Phase 2.**

---

# PHASE 2 — Branchement cognitif (parole publique)

## Task 6 : `AttentionContext.social_receptivity` + fix `time_of_day` UTC→Paris

**Files:**
- Modify: `bot/intelligence/attention_agent.py`
- Test: `tests/test_attention_social_receptivity.py` *(create)*

**Interfaces:**
- Consumes: `SocialRhythm.describe(when)`, `SocialRhythm.receptivity(when)` (Tasks 2/4).
- Produces:
  - `AttentionContext` gagne deux champs : `social_receptivity: str | None = None` et `receptivity_score: float = 0.5`.
  - `AttentionAgent.__init__` gagne le paramètre `social_rhythm=None`.
  - `build_context` calcule `time_of_day` en `Europe/Paris` et remplit les deux champs si `social_rhythm` présent.

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/test_attention_social_receptivity.py
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from bot.intelligence.attention_agent import AttentionAgent
from bot.intelligence.social_rhythm import SocialRhythm


class _FakeFacts:
    async def search_by_category(self, *a, **k): return []
    async def get_latest_by_source(self, *a, **k): return None
    async def get_by_user(self, *a, **k): return []
    async def sample_random(self, *a, **k): return []


@pytest.mark.asyncio
async def test_build_context_fills_receptivity(monkeypatch):
    sr = SocialRhythm(alpha=0.5, n_conf=3)
    PARIS = ZoneInfo("Europe/Paris")
    for day in range(1, 7):
        for _ in range(20):
            sr.record_incoming(datetime(2026, 6, day, 14, tzinfo=PARIS))
        sr.record_spontaneous_outcome(True, datetime(2026, 6, day, 14, tzinfo=PARIS))
    # neutralise les I/O réseau de build_context
    import bot.intelligence.attention_agent as mod
    monkeypatch.setattr(mod, "read_host_metrics", lambda: None, raising=False)

    agent = AttentionAgent(_FakeFacts(), social_rhythm=sr)
    ctx = await agent.build_context({"boredom": 0.1}, [], idle=True)
    assert isinstance(ctx.social_receptivity, str) and ctx.social_receptivity
    assert 0.0 <= ctx.receptivity_score <= 1.0
```

> Note : si `build_context` appelle d'autres I/O (météo `fetch_weather_france`, etc.), les neutraliser de la même façon dans le test (monkeypatch → coroutine renvoyant `None`). Adapter au code réel observé.

- [ ] **Step 2 : Lancer pour vérifier l'échec**

Run: `python3 -m pytest tests/test_attention_social_receptivity.py -q`
Expected: FAIL (`TypeError: __init__() got an unexpected keyword 'social_rhythm'` ou attribut absent).

- [ ] **Step 3 : Modifier `attention_agent.py`**

3a. Ajouter les deux champs au dataclass `AttentionContext` (après `recent_speaks`/`upgrade_requests`) :

```python
    # Conscience du rythme social appris (SocialRhythm) — phrase FR injectée dans
    # le prompt cognitif, et score brut [0,1] consommé par la boucle (amortisseur/cadence).
    social_receptivity: str | None = None
    receptivity_score: float = 0.5
```

3b. Ajouter le paramètre au constructeur :

```python
    def __init__(self, fact_store, emotion_engine=None, emote_provider=None,
                 upgrade_registry=None, social_rhythm=None) -> None:
        ...
        self._social_rhythm = social_rhythm
```

3c. Remplacer le calcul `time_of_day` (UTC) par `Europe/Paris`. Remplacer :

```python
        hour = datetime.now(timezone.utc).hour
```
par :
```python
        from zoneinfo import ZoneInfo
        hour = datetime.now(ZoneInfo("Europe/Paris")).hour
```

3d. Juste avant le `return AttentionContext(...)`, calculer la réceptivité :

```python
        social_receptivity = None
        receptivity_score = 0.5
        if self._social_rhythm is not None:
            try:
                from zoneinfo import ZoneInfo
                _now = datetime.now(ZoneInfo("Europe/Paris"))
                receptivity_score = self._social_rhythm.receptivity(_now)
                social_receptivity = self._social_rhythm.describe(_now)
            except Exception as e:  # noqa: BLE001 — jamais bloquant
                from loguru import logger
                logger.warning("AttentionAgent: réceptivité indisponible: {}", e)
```

3e. Passer les deux champs au `return AttentionContext(...)` :

```python
            social_receptivity=social_receptivity,
            receptivity_score=receptivity_score,
```

- [ ] **Step 4 : Lancer pour vérifier le succès**

Run: `python3 -m pytest tests/test_attention_social_receptivity.py -q`
Expected: PASS.

- [ ] **Step 5 : Commit**

```bash
git add bot/intelligence/attention_agent.py tests/test_attention_social_receptivity.py
git commit -m "feat(cognition): réceptivité sociale dans AttentionContext + fix time_of_day Paris"
```

---

## Task 7 : Rendu de `social_receptivity` dans le prompt

**Files:**
- Modify: `bot/intelligence/reasoning_agent.py` (méthode `_format_context`, ≈ l.131-299)
- Test: `tests/test_reasoning_renders_receptivity.py` *(create)*

**Interfaces:**
- Consumes: `AttentionContext.social_receptivity` (Task 6).
- Produces: le texte de `social_receptivity` apparaît dans la sortie de `_format_context`.

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/test_reasoning_renders_receptivity.py
from bot.intelligence.attention_agent import AttentionContext
from bot.intelligence.reasoning_agent import ReasoningAgent


def _ctx(**kw):
    base = dict(
        emotion_state={"boredom": 0.1}, active_desires=[], active_goals=[],
        recent_thoughts=[], recent_interactions=[], time_of_day="night",
    )
    base.update(kw)
    return AttentionContext(**base)


def test_format_context_includes_receptivity():
    agent = ReasoningAgent.__new__(ReasoningAgent)   # pas d'I/O constructeur
    agent._channels_text = ""
    agent._capabilities_text = ""
    agent._channel_names = {}
    text = agent._format_context(_ctx(
        social_receptivity="Il est 3h en semaine : le serveur est très calme.",
    ))
    assert "le serveur est très calme" in text
```

> Note : si `_format_context` lit d'autres attributs d'instance non initialisés par `__new__`, les fixer dans le test (mêmes valeurs neutres) d'après le code réel.

- [ ] **Step 2 : Lancer pour vérifier l'échec**

Run: `python3 -m pytest tests/test_reasoning_renders_receptivity.py -q`
Expected: FAIL (la phrase n'apparaît pas).

- [ ] **Step 3 : Modifier `_format_context`**

Dans `reasoning_agent.py`, près du rendu de `time_of_day` (≈ l.210), ajouter (avant la ligne `**Heure :**`) :

```python
        if getattr(ctx, "social_receptivity", None):
            lines.append(f"**Rythme social (conscience, pas une consigne)** : {ctx.social_receptivity}")
```

> Respecter le nom réel de l'accumulateur de lignes observé dans la méthode (le rapport indique `lines: list[str]`). S'il diffère, utiliser le nom réel.

- [ ] **Step 4 : Lancer pour vérifier le succès**

Run: `python3 -m pytest tests/test_reasoning_renders_receptivity.py -q`
Expected: PASS.

- [ ] **Step 5 : Commit**

```bash
git add bot/intelligence/reasoning_agent.py tests/test_reasoning_renders_receptivity.py
git commit -m "feat(cognition): injecter la conscience du rythme social dans le prompt"
```

---

## Task 8 : Boucle cognitive — signaux + cadence somnolente + amortisseur SPEAK

**Files:**
- Modify: `bot/intelligence/cognitive_loop.py`
- Test: `tests/test_cognitive_loop_rhythm.py` *(create)*

**Interfaces:**
- Consumes: `SocialRhythm.record_incoming`, `record_spontaneous_outcome`, `receptivity` ; `R_REF`.
- Produces:
  - `CognitiveLoop.__init__` gagne `social_rhythm=None`.
  - `notify_activity` appelle `record_incoming(now_paris)`.
  - Quand un message spontané est répondu / abandonné, `record_spontaneous_outcome` est appelé.
  - `_tick_interval` allonge le plafond idle quand la réceptivité est basse.
  - `_tick` applique un tirage probabiliste `random() < min(1, receptivity/R_REF)` avant un SPEAK spontané (suppression journalisée).

- [ ] **Step 1 : Écrire les tests qui échouent**

```python
# tests/test_cognitive_loop_rhythm.py
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from bot.intelligence.cognitive_loop import CognitiveLoop, _speak_pass_probability

PARIS = ZoneInfo("Europe/Paris")


def test_speak_pass_probability_curve():
    # haute réceptivité → toujours passer ; basse → rare
    assert _speak_pass_probability(0.5) == pytest.approx(1.0)
    assert _speak_pass_probability(0.4) == pytest.approx(1.0)
    assert _speak_pass_probability(0.05) < 0.2
    assert _speak_pass_probability(0.0) == pytest.approx(0.0)


class _SR:
    def __init__(self, r): self._r = r; self.incoming = 0; self.outcomes = []
    def record_incoming(self, when): self.incoming += 1
    def record_spontaneous_outcome(self, answered, when): self.outcomes.append(answered)
    def receptivity(self, when): return self._r


def test_notify_activity_feeds_rhythm():
    sr = _SR(0.5)
    loop = CognitiveLoop(None, None, None, social_rhythm=sr)
    loop.notify_activity(1, "bob", "hello")
    assert sr.incoming == 1


def test_idle_ceiling_grows_when_receptivity_low():
    import bot.intelligence.cognitive_loop as mod
    low = CognitiveLoop(None, None, None, emotion_engine=None, social_rhythm=_SR(0.02))
    high = CognitiveLoop(None, None, None, emotion_engine=None, social_rhythm=_SR(0.9))
    # forcer l'état idle (pas d'activité récente)
    low._last_relevant_activity_ts = 0.0
    high._last_relevant_activity_ts = 0.0
    # max sur plusieurs tirages (intervalle aléatoire) : la borne basse doit être plus haute
    lows = max(low._tick_interval() for _ in range(50))
    highs = max(high._tick_interval() for _ in range(50))
    assert lows >= highs
```

- [ ] **Step 2 : Lancer pour vérifier l'échec**

Run: `python3 -m pytest tests/test_cognitive_loop_rhythm.py -q`
Expected: FAIL (`ImportError: _speak_pass_probability` / `TypeError: social_rhythm`).

- [ ] **Step 3 : Modifier `cognitive_loop.py`**

3a. En tête du module, après les constantes `TICK_*`, ajouter le helper + l'import :

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from bot.intelligence.social_rhythm import R_REF


def _speak_pass_probability(receptivity: float) -> float:
    """Proba de laisser passer un SPEAK spontané. ≥ R_REF → 1.0 (journée normale,
    aucun frein) ; en-dessous, décroît linéairement → nuits quasi silencieuses.
    Aucun seuil horaire : `receptivity` sort des stats apprises."""
    if receptivity >= R_REF:
        return 1.0
    return max(0.0, receptivity / R_REF)


def _now_paris() -> datetime:
    return datetime.now(ZoneInfo("Europe/Paris"))
```

3b. Ajouter `social_rhythm=None` au constructeur et le stocker :

```python
        progress_judge=None,
        social_rhythm=None,
    ) -> None:
        ...
        self._social_rhythm = social_rhythm
```

3c. Dans `notify_activity`, après `self._last_activity_ts = time.monotonic()`, alimenter le signal ambient (best-effort) :

```python
        if self._social_rhythm is not None:
            try:
                self._social_rhythm.record_incoming(_now_paris())
            except Exception as e:  # noqa: BLE001
                logger.warning("SocialRhythm.record_incoming: {}", e)
```

3d. Dans `_tick_interval`, après le calcul de `hi` (issu de l'ennui), allonger le plafond quand la réceptivité est basse :

```python
        if self._social_rhythm is not None:
            try:
                r = self._social_rhythm.receptivity(_now_paris())
                hi = int(hi * (1.0 + 2.0 * (1.0 - max(0.0, min(1.0, r)))))
            except Exception:  # noqa: BLE001
                pass
        return random.randint(TICK_IDLE, max(TICK_IDLE, hi))
```

3e. Dans `_tick`, à l'intérieur du `if decision.action == "SPEAK":`, APRÈS les suppressions existantes (canal silencieux, redirection, cooldown, anti-récap) et juste AVANT `await self._dispatcher.dispatch(decision)`, insérer l'amortisseur appris :

```python
                    if self._social_rhythm is not None:
                        try:
                            r = self._social_rhythm.receptivity(_now_paris())
                        except Exception:  # noqa: BLE001
                            r = 1.0
                        if random.random() >= _speak_pass_probability(r):
                            logger.info("CognitiveLoop: SPEAK amorti (réceptivité {:.2f})", r)
                            self._log_cog(
                                "speak_suppressed", channel=str(decision.channel_id),
                                reason=f"réceptivité apprise {r:.2f}",
                                message=(decision.message or "")[:200],
                            )
                            continue
```

3f. Alimenter le signal `engagement`. Dans `notify_activity`, le bloc existant remet `st["unanswered"] = 0` quand quelqu'un répond dans un canal où Wally avait parlé : c'est une **réponse** → issue positive. Remplacer ce bloc :

```python
        st = self._spontaneous.get(str(channel_id))
        if st is not None:
            st["unanswered"] = 0
```
par :
```python
        st = self._spontaneous.get(str(channel_id))
        if st is not None and st.get("unanswered", 0) > 0:
            if self._social_rhythm is not None:
                try:
                    self._social_rhythm.record_spontaneous_outcome(True, _now_paris())
                except Exception as e:  # noqa: BLE001
                    logger.warning("SocialRhythm outcome(+): {}", e)
            st["unanswered"] = 0
```

Et dans `_tick`, là où un SPEAK est bloqué pour `unanswered >= 3` (canal ignoré), enregistrer une issue négative juste avant le `continue` de ce cas :

```python
                    if unanswered >= 3:
                        if self._social_rhythm is not None:
                            try:
                                self._social_rhythm.record_spontaneous_outcome(False, _now_paris())
                            except Exception:  # noqa: BLE001
                                pass
                        logger.info("CognitiveLoop: SPEAK bloqué ({} sans réponse)", unanswered)
                        ...  # (reste inchangé)
```

- [ ] **Step 4 : Lancer pour vérifier le succès**

Run: `python3 -m pytest tests/test_cognitive_loop_rhythm.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5 : Commit**

```bash
git add bot/intelligence/cognitive_loop.py tests/test_cognitive_loop_rhythm.py
git commit -m "feat(cognition): boucle — signaux rythme, cadence somnolente, amortisseur SPEAK"
```

---

## Task 9 : Câblage DI dans `bot/discord/bot.py`

**Files:**
- Modify: `bot/discord/bot.py` (`setup_hook`, ≈ l.169-226)
- Test: vérification manuelle d'import + suite complète (pas de test unitaire dédié — câblage I/O).

**Interfaces:**
- Consumes: `SocialRhythm`, `_db_path`, `bot.conv_log`/logs dir, `config.circadian.timezone`.
- Produces: `bot.social_rhythm` construit, chargé (`load`), backfillé une fois, injecté dans `AttentionAgent(...)` et `CognitiveLoop(...)`.

- [ ] **Step 1 : Construire et charger `SocialRhythm` avant la construction de `AttentionAgent`**

Dans `setup_hook`, juste avant la construction de `_attention` (≈ l.169), ajouter :

```python
        from bot.intelligence.social_rhythm import SocialRhythm
        _tz = getattr(getattr(self.config, "circadian", None), "timezone", "Europe/Paris")
        self.social_rhythm = SocialRhythm(tz=_tz)
        await self.social_rhythm.load(_db_path)
        try:
            self.social_rhythm.backfill_from_logs("logs/conversations")
        except Exception as e:  # noqa: BLE001 — le backfill ne doit jamais bloquer le boot
            logger.warning("SocialRhythm: backfill ignoré: {}", e)
```

- [ ] **Step 2 : Injecter dans `AttentionAgent`**

Modifier l'appel `_attention = AttentionAgent(...)` pour ajouter `social_rhythm=self.social_rhythm` :

```python
        _attention = AttentionAgent(
            _fact_store, self.emotion,
            emote_provider=lambda: [(e.name, str(e)) for e in self.emojis],
            upgrade_registry=self.upgrade_registry,
            social_rhythm=self.social_rhythm,
        )
```

- [ ] **Step 3 : Injecter dans `CognitiveLoop`**

Modifier l'appel `self.cognitive_loop = CognitiveLoop(...)` pour ajouter `social_rhythm=self.social_rhythm` :

```python
        self.cognitive_loop = CognitiveLoop(
            _attention, _reasoning, _dispatcher, self.emotion, self.cognitive_feed,
            speakable_channels=_chan_dir.speakable_ids(),
            conv_log=_conv_log,
            fact_store=_fact_store,
            progress_judge=_progress_judge,
            social_rhythm=self.social_rhythm,
        )
```

- [ ] **Step 4 : Persistance périodique — sauvegarder dans `close`/`stop`**

Repérer la fermeture propre du bot (méthode `close` de `WallyDiscord` ou l'arrêt de `cognitive_loop`). Y ajouter, best-effort :

```python
        if getattr(self, "social_rhythm", None) is not None:
            await self.social_rhythm.persist(_db_path)  # _db_path accessible via self
```

> Si `_db_path` n'est pas un attribut d'instance, le mémoriser au boot : `self._db_path = _db_path`. Adapter au code réel.

- [ ] **Step 5 : Vérifier l'import et la suite complète, puis commit**

Run: `python3 -c "import bot.discord.bot"`
Expected: aucun import error.

Run: `python3 -m pytest -q`
Expected: pas de NOUVEL échec (seuls les 2 préexistants tolérés).

```bash
git add bot/discord/bot.py
git commit -m "feat(cognition): câblage DI SocialRhythm (load + backfill + persist)"
```

**⛔ CHECKPOINT PHASE 2 — valider avec l'utilisateur avant la Phase 3.**

---

# PHASE 3 — Discipline des sollicitations owner

## Task 10 : `OwnerOutreachGate`

**Files:**
- Create: `bot/intelligence/owner_outreach.py`
- Test: `tests/test_owner_outreach.py` *(create)*

**Interfaces:**
- Produces:
  - `OwnerOutreachGate()`
  - `is_blocked(self) -> bool`
  - `mark_sent(self) -> None`
  - `clear(self) -> None`

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/test_owner_outreach.py
from bot.intelligence.owner_outreach import OwnerOutreachGate


def test_gate_blocks_after_sent_until_cleared():
    g = OwnerOutreachGate()
    assert g.is_blocked() is False
    g.mark_sent()
    assert g.is_blocked() is True
    g.clear()
    assert g.is_blocked() is False


def test_clear_when_not_blocked_is_safe():
    g = OwnerOutreachGate()
    g.clear()
    assert g.is_blocked() is False
```

- [ ] **Step 2 : Lancer pour vérifier l'échec**

Run: `python3 -m pytest tests/test_owner_outreach.py -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3 : Écrire l'implémentation**

```python
# bot/intelligence/owner_outreach.py
from __future__ import annotations

from loguru import logger


class OwnerOutreachGate:
    """Un seul fil de sollicitation vers l'owner à la fois (tout type confondu :
    self-fix, questions DM). Tant qu'un MP est sans réponse, on n'en envoie plus ;
    quand l'owner répond, la cognition re-soulève d'elle-même ce qui compte encore.

    État volontairement minimal et en mémoire : au redémarrage, repartir « non
    bloqué » est sûr (au pire un message de plus, jamais un empilement)."""

    def __init__(self) -> None:
        self._blocked = False

    def is_blocked(self) -> bool:
        return self._blocked

    def mark_sent(self) -> None:
        self._blocked = True
        logger.info("OwnerOutreachGate: sollicitation owner en attente de réponse")

    def clear(self) -> None:
        if self._blocked:
            logger.info("OwnerOutreachGate: owner a répondu → fil libéré")
        self._blocked = False
```

- [ ] **Step 4 : Lancer pour vérifier le succès**

Run: `python3 -m pytest tests/test_owner_outreach.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5 : Commit**

```bash
git add bot/intelligence/owner_outreach.py tests/test_owner_outreach.py
git commit -m "feat(cognition): OwnerOutreachGate (un fil de sollicitation owner à la fois)"
```

---

## Task 11 : Self-fix — retrait de l'auto-refus + branchement gate

**Files:**
- Modify: `bot/intelligence/self_fix.py`
- Test: `tests/test_self_fix_no_autorefuse.py` *(create)*

**Interfaces:**
- Consumes: `OwnerOutreachGate` (Task 10).
- Produces:
  - `SelfFix.__init__` gagne `gate=None`.
  - Sur non-réponse, **plus de blacklist** (`_declined` non modifié), plus de message « j'abandonne », statut `deferred` (pas `declined`).
  - Si `gate.is_blocked()` → la demande est différée sans DM.
  - Sur envoi du DM de demande → `gate.mark_sent()`.

> Comportement « pas de timeout » : on remplace le timeout d'1 h par une attente longue bornée (72 h) afin de ne pas parker une coroutine éternellement ; sur cette expiration on met `deferred` SANS blacklist ni « j'abandonne » (re-proposable plus tard). C'est l'écart minimal qui satisfait la décision « retirer l'auto-refus ».

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/test_self_fix_no_autorefuse.py
import asyncio
import pytest
from bot.intelligence.self_fix import SelfFix, UpgradeRequest
from bot.intelligence.owner_outreach import OwnerOutreachGate


class _DM:
    def __init__(self): self.sent = []
    async def send(self, content): self.sent.append(content); return _Msg()
class _Msg:
    id = 1
    async def add_reaction(self, e): pass
class _Owner:
    async def create_dm(self): return _DM()
class _Bot:
    class config:
        class bot:
            owner_discord_id = "42"
            name = "wally"
    async def fetch_user(self, uid): return _Owner()
    memory = None


@pytest.mark.asyncio
async def test_blocked_gate_defers_without_dm():
    gate = OwnerOutreachGate(); gate.mark_sent()  # déjà un fil en attente
    sf = SelfFix(bridge=None, bot=_Bot(), gate=gate)
    # request_upgrade doit court-circuiter sans DM ni blacklist
    await sf.request_upgrade(UpgradeRequest(goal="ajouter X"))
    assert "ajouter x" not in sf._declined


@pytest.mark.asyncio
async def test_no_response_does_not_blacklist():
    # _await_reaction expire immédiatement → on vérifie : pas de blacklist, statut deferred
    gate = OwnerOutreachGate()
    sf = SelfFix(bridge=None, bot=_Bot(), gate=gate)

    async def _expire(msg, timeout): raise asyncio.TimeoutError
    sf._await_reaction = _expire  # type: ignore

    await sf.request_upgrade(UpgradeRequest(goal="ajouter Y"))
    assert "ajouter y" not in sf._declined
```

- [ ] **Step 2 : Lancer pour vérifier l'échec**

Run: `python3 -m pytest tests/test_self_fix_no_autorefuse.py -q`
Expected: FAIL (`gate` inconnu / blacklist encore appliquée).

- [ ] **Step 3 : Modifier `self_fix.py`**

3a. Constructeur — ajouter `gate=None` et le stocker ; passer le timeout par défaut à 72 h :

```python
    def __init__(self, bridge, bot, *, poll_interval: float = 10.0,
                 approval_timeout: float = 72 * 3600.0,
                 registry: UpgradeRegistry | None = None, gate=None) -> None:
        ...
        self._gate = gate
```

3b. Dans `request_upgrade`, après les gardes existantes (`_pending`, `_declined`, anti-redemande) et avant `self._pending = True`, ajouter le court-circuit gate :

```python
        if not force and self._gate is not None and self._gate.is_blocked():
            logger.info("self-fix différé : une sollicitation owner est déjà en attente")
            await self._record_outcome(
                goal, "Différé — une autre sollicitation vers le créateur attend déjà sa "
                "réponse ; à re-soulever plus tard."
            )
            return
```

3c. Dans `_run_upgrade`, après l'envoi réussi du DM de demande (`msg = await dm.send(...)` + réactions) et le `_remember_in_dm`, marquer le gate :

```python
        if self._gate is not None:
            self._gate.mark_sent()
```

3d. Dans `_run_upgrade`, branche `except asyncio.TimeoutError` : **retirer** le blacklist et le « j'abandonne », passer en `deferred` :

```python
        except asyncio.TimeoutError:
            # Plus d'auto-refus : la demande n'est ni refusée ni blacklistée. Elle
            # est simplement mise de côté (re-proposable). Pas de message « j'abandonne ».
            await self._set_status(upgrade_id, ABANDONED)
            self._remember_in_dm(dm, f"[self-fix en attente — pas encore de réponse] {goal}")
            await self._record_outcome(
                goal, f"Pas encore de réponse de {creator_name()} — demande mise de côté, "
                "ni refusée ni abandonnée définitivement ; à re-soulever plus tard."
            )
            return
```

> Note : `ABANDONED` reste le statut registre « non livré » disponible ; la sémantique « deferred » est portée par le texte d'outcome. Ne PAS ajouter `self._declined.add(norm)`.

- [ ] **Step 4 : Lancer pour vérifier le succès**

Run: `python3 -m pytest tests/test_self_fix_no_autorefuse.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5 : Commit**

```bash
git add bot/intelligence/self_fix.py tests/test_self_fix_no_autorefuse.py
git commit -m "feat(cognition): self-fix — retrait auto-refus/blacklist + gate owner"
```

---

## Task 12 : `action_dispatcher._dm` consulte le gate

**Files:**
- Modify: `bot/intelligence/action_dispatcher.py`
- Test: `tests/test_dispatcher_dm_gate.py` *(create)*

**Interfaces:**
- Consumes: `OwnerOutreachGate` (Task 10).
- Produces: `ActionDispatcher.__init__` gagne `gate=None` ; `_dm` n'envoie pas si `gate.is_blocked()`, et appelle `gate.mark_sent()` après un envoi réussi.

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/test_dispatcher_dm_gate.py
import pytest
from bot.intelligence.action_dispatcher import ActionDispatcher
from bot.intelligence.owner_outreach import OwnerOutreachGate


class _User:
    def __init__(self): self.sent = []
    async def send(self, msg):
        self.sent.append(msg)
        class _S:
            channel = type("C", (), {"id": 1})()
        return _S()
class _Bot:
    def __init__(self, u): self._u = u
    class config:
        class bot:
            owner_discord_id = "42"
    async def fetch_user(self, uid): return self._u


@pytest.mark.asyncio
async def test_dm_suppressed_when_gate_blocked():
    user = _User()
    gate = OwnerOutreachGate(); gate.mark_sent()
    d = ActionDispatcher(bot=_Bot(user), gate=gate)
    await d._dm("42", "coucou")
    assert user.sent == []   # rien envoyé


@pytest.mark.asyncio
async def test_dm_sent_marks_gate():
    user = _User()
    gate = OwnerOutreachGate()
    d = ActionDispatcher(bot=_Bot(user), gate=gate)
    d._last_dm_ts = 0.0   # neutralise le cooldown temporel
    await d._dm("42", "coucou")
    assert user.sent == ["coucou"]
    assert gate.is_blocked() is True
```

- [ ] **Step 2 : Lancer pour vérifier l'échec**

Run: `python3 -m pytest tests/test_dispatcher_dm_gate.py -q`
Expected: FAIL (`gate` inconnu).

- [ ] **Step 3 : Modifier `action_dispatcher.py`**

3a. Constructeur — ajouter `gate=None` et le stocker :

```python
    def __init__(
        self, bot=None, persona_manager=None, fact_store=None,
        feed=None, twitch_bot=None, gate=None,
    ) -> None:
        ...
        self._gate = gate
```

3b. Dans `_dm`, après la validation `user_id == owner_id` et AVANT le cooldown temporel, ajouter :

```python
        if self._gate is not None and self._gate.is_blocked():
            logger.info("Cognitive DM supprimé (sollicitation owner déjà en attente)")
            if self._feed:
                self._feed.publish({
                    "type": "DM_SUPPRESSED",
                    "reason": "sollicitation owner déjà en attente de réponse",
                    "message": message[:300],
                })
            return
```

3c. Après l'envoi réussi (`self._last_dm_ts = now`), marquer le gate :

```python
            if self._gate is not None:
                self._gate.mark_sent()
```

- [ ] **Step 4 : Lancer pour vérifier le succès**

Run: `python3 -m pytest tests/test_dispatcher_dm_gate.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5 : Commit**

```bash
git add bot/intelligence/action_dispatcher.py tests/test_dispatcher_dm_gate.py
git commit -m "feat(cognition): action DM owner soumise au OwnerOutreachGate"
```

---

## Task 13 : DM owner entrant → `gate.clear()` + câblage DI

**Files:**
- Modify: `bot/discord/handlers.py` (`on_message`, détection DM owner ≈ l.805/1399)
- Modify: `bot/discord/bot.py` (`setup_hook`)
- Test: `tests/test_handlers_owner_dm_clears_gate.py` *(create)*

**Interfaces:**
- Consumes: `OwnerOutreachGate`.
- Produces: un message reçu en DM de la part de l'owner appelle `bot.owner_gate.clear()` ; `bot.owner_gate` construit au boot et passé à `SelfFix` et `ActionDispatcher`.

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/test_handlers_owner_dm_clears_gate.py
from bot.intelligence.owner_outreach import OwnerOutreachGate
from bot.discord.handlers import maybe_clear_owner_gate


class _Cfg:
    class bot:
        owner_discord_id = "42"


def test_owner_dm_clears_gate():
    gate = OwnerOutreachGate(); gate.mark_sent()
    maybe_clear_owner_gate(gate, _Cfg, author_id="42", is_dm=True)
    assert gate.is_blocked() is False


def test_non_owner_dm_does_not_clear():
    gate = OwnerOutreachGate(); gate.mark_sent()
    maybe_clear_owner_gate(gate, _Cfg, author_id="99", is_dm=True)
    assert gate.is_blocked() is True


def test_owner_guild_message_does_not_clear():
    gate = OwnerOutreachGate(); gate.mark_sent()
    maybe_clear_owner_gate(gate, _Cfg, author_id="42", is_dm=False)
    assert gate.is_blocked() is True
```

- [ ] **Step 2 : Lancer pour vérifier l'échec**

Run: `python3 -m pytest tests/test_handlers_owner_dm_clears_gate.py -q`
Expected: FAIL (`ImportError: maybe_clear_owner_gate`).

- [ ] **Step 3 : Ajouter le helper dans `handlers.py` et l'appeler**

3a. Ajouter (près des autres helpers en tête de `handlers.py`) une fonction pure testable :

```python
def maybe_clear_owner_gate(gate, config, author_id: str, is_dm: bool) -> None:
    """Libère le fil de sollicitation owner quand l'owner répond en DM."""
    if gate is None or not is_dm:
        return
    if str(author_id) == str(getattr(getattr(config, "bot", None), "owner_discord_id", "")):
        gate.clear()
```

3b. Dans `on_message` (tôt, après calcul de `_is_dm = message.guild is None`, ≈ l.805), appeler :

```python
    maybe_clear_owner_gate(
        getattr(bot, "owner_gate", None), bot.config,
        author_id=str(message.author.id), is_dm=message.guild is None,
    )
```

- [ ] **Step 4 : Câbler le gate dans `bot/discord/bot.py` `setup_hook`**

Avant la construction de `_dispatcher` et de `self.self_fix`, créer le gate partagé :

```python
        from bot.intelligence.owner_outreach import OwnerOutreachGate
        self.owner_gate = OwnerOutreachGate()
```

Puis le passer aux deux :

```python
        _dispatcher = ActionDispatcher(
            bot=self, persona_manager=_persona_mgr, fact_store=_fact_store,
            feed=self.cognitive_feed, twitch_bot=getattr(self, "_twitch_bot", None),
            gate=self.owner_gate,
        )
        ...
        self.self_fix = SelfFix(_bridge, self, registry=self.upgrade_registry, gate=self.owner_gate)
```

- [ ] **Step 5 : Lancer les tests + suite complète, puis commit**

Run: `python3 -m pytest tests/test_handlers_owner_dm_clears_gate.py -q`
Expected: PASS (3 tests).

Run: `python3 -c "import bot.discord.bot; import bot.discord.handlers"`
Expected: aucun import error.

Run: `python3 -m pytest -q`
Expected: pas de NOUVEL échec (seuls les 2 préexistants tolérés).

```bash
git add bot/discord/handlers.py bot/discord/bot.py tests/test_handlers_owner_dm_clears_gate.py
git commit -m "feat(cognition): DM owner entrant libère le gate + câblage DI partagé"
```

**⛔ CHECKPOINT PHASE 3 — valider avec l'utilisateur. Activation = rebuild image (hors plan).**

---

## Self-Review (rempli)

**1. Couverture du spec :**
- A1 modèle (48 créneaux, EMA ambient+engagement, prior conf, fuseau) → Tasks 1-2. ✅
- A1 persistance → Task 3. ✅ ; backfill logs → Task 5. ✅ ; describe → Task 4. ✅
- A2 consommateurs : cadence → Task 8 (3d) ; conscience injectée + fix UTC→Paris → Tasks 6-7 ; amortisseur SPEAK → Task 8 (3e) ; alimentation signaux → Task 8 (3c/3f). ✅
- A3 DI → Task 9. ✅
- B1 self-fix retrait auto-refus/blacklist → Task 11. ✅
- B2 gate (interface + branchements `_dm`, self-fix, `on_message`) → Tasks 10/11/12/13. ✅
- B3 DI gate partagé → Task 13. ✅
- Tests spec → répartis sur chaque task. ✅

**2. Placeholders :** aucun « TBD/TODO ». Les rares « adapter au code réel » pointent un nom d'attribut à confirmer à la lecture, avec la valeur attendue indiquée — pas un trou de conception.

**3. Cohérence des types :** `SocialRhythm` (record_incoming/record_spontaneous_outcome/receptivity/describe/load/persist/backfill_from_logs) ; constantes `PRIOR/W_AMBIENT/W_ENGAGEMENT/R_REF` ; `_speak_pass_probability` ; `OwnerOutreachGate` (is_blocked/mark_sent/clear) ; `maybe_clear_owner_gate` — noms identiques entre définition et consommation.

## Notes d'exécution
- Respecter `CONTEXT DECAY` du projet : re-lire chaque fichier juste avant de l'éditer (les n° de ligne cités sont indicatifs).
- Les tests async exigent `pytest.mark.asyncio` (déjà utilisé dans le projet — vérifier `pytest.ini`/`conftest`). Si le mode auto est actif, le décorateur reste sûr.
- Une seule branche : `feat/site-redesign-arcade` (courante). Commits fréquents comme ci-dessus.
