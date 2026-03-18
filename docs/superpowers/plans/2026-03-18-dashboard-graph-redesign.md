# Dashboard Graph Redesign — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corriger le graphique pour afficher 24h glissantes, ajouter un sélecteur 24H/7J/30J avec statistiques de moyennes, et fixer le bug d'alignement des emojis dans les barres d'humeur.

**Architecture:** 2 tâches backend (renommage méthode DB + endpoint query param), 3 tâches frontend (CSS fix emoji, HTML+CSS sélecteur, JS logique). Aucun nouveau fichier, aucune nouvelle table. Les tâches backend et CSS sont indépendantes et peuvent être faites en parallèle.

**Tech Stack:** Python/FastAPI, aiosqlite, pytest-asyncio, vanilla JS, CSS

---

## Fichiers touchés

| Fichier | Changement |
|---|---|
| `bot/db/database.py` | Renommer `get_today_emotion_snapshots` → `get_emotion_snapshots_since(since)`, rétention 30j |
| `bot/core/journal.py` | Mettre à jour le call-site (passer `time.time() - 86400`) |
| `bot/main.py` | `cleanup_old_emotion_history(days=30)` |
| `bot/dashboard/routes/emotions.py` | Ajouter `since: float` query param avec cap 30j |
| `bot/dashboard/static/style.css` | Fix `.emotion-label` + CSS boutons période |
| `bot/dashboard/static/index.html` | Remplacer `card-title` par `graph-header` + `emotion-averages` div |
| `bot/dashboard/static/app.js` | `setGraphRange()`, `renderEmotionAverages()`, `loadEmotionHistory(since?)` |
| `tests/test_database.py` | Renommer les appels + ajouter test `since` param |
| `tests/test_dashboard_routes.py` | Renommer mock + ajouter test `since` param |
| `tests/test_emotion.py` | Renommer l'appel réel |
| `tests/test_journal.py` | Renommer le mock |

---

## Task 1 : Backend — Renommer `get_today_emotion_snapshots` + rétention 30j

**Fichiers :**
- Modify: `bot/db/database.py:255-263`
- Modify: `bot/core/journal.py:189`
- Modify: `bot/main.py:64`
- Modify: `tests/test_database.py:130-146`
- Modify: `tests/test_emotion.py:374`
- Modify: `tests/test_journal.py:301`
- Modify: `tests/test_dashboard_routes.py:66,245`

- [ ] **Étape 1 : Mettre à jour les tests `test_database.py`**

Dans `tests/test_database.py`, renommer les deux appels `get_today_emotion_snapshots()` en `get_emotion_snapshots_since(time.time() - 86400)`. Renommer aussi les fonctions de test pour refléter la nouvelle sémantique :

```python
# test_database.py ligne 130 — changer :
async def test_insert_and_get_today_snapshots(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    state = {"anger": 0.2, "joy": 0.5, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.0}
    await db.insert_emotion_snapshot(state)
    await db.insert_emotion_snapshot(state)
    import time
    snapshots = await db.get_emotion_snapshots_since(time.time() - 86400)
    assert len(snapshots) == 2
    assert abs(snapshots[0]["joy"] - 0.5) < 0.001
    await db.close()


async def test_get_snapshots_since_returns_empty_list_when_none(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    import time
    snapshots = await db.get_emotion_snapshots_since(time.time() - 86400)
    assert snapshots == []
    await db.close()


# Ajouter ce nouveau test à la suite :
async def test_get_snapshots_since_excludes_old_data(tmp_path):
    """Les snapshots antérieurs au cutoff ne sont pas retournés."""
    import time
    db = await Database.create(str(tmp_path / "test.db"))
    old_ts = time.time() - 25 * 3600  # 25h avant = hors fenêtre 24h
    await db.execute(
        "INSERT INTO emotion_history (snapshot_at, anger, joy, sadness, curiosity, boredom) "
        "VALUES (?, 0.1, 0.9, 0.0, 0.0, 0.0)",
        (old_ts,),
    )
    await db.insert_emotion_snapshot(
        {"anger": 0.2, "joy": 0.5, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.0}
    )
    snapshots = await db.get_emotion_snapshots_since(time.time() - 86400)
    assert len(snapshots) == 1
    assert abs(snapshots[0]["anger"] - 0.2) < 0.001
    await db.close()
```

- [ ] **Étape 2 : Mettre à jour le mock dans `test_emotion.py`**

Ligne 374 de `tests/test_emotion.py` — remplacer :
```python
snapshots = await db.get_today_emotion_snapshots()
```
par :
```python
import time as _time
snapshots = await db.get_emotion_snapshots_since(_time.time() - 86400)
```

- [ ] **Étape 3 : Mettre à jour les mocks dans `test_journal.py` et `test_dashboard_routes.py`**

Dans `tests/test_journal.py:301`, renommer le mock :
```python
db.get_emotion_snapshots_since = AsyncMock(return_value=[])
```

Dans `tests/test_dashboard_routes.py:66` et `:245`, renommer le mock (deux occurrences dans `_make_state`) :
```python
db.get_emotion_snapshots_since = AsyncMock(return_value=[])
```

- [ ] **Étape 4 : Lancer les tests pour confirmer qu'ils échouent**

```bash
cd /opt/stacks/wally-ai
python -m pytest tests/test_database.py tests/test_emotion.py tests/test_journal.py tests/test_dashboard_routes.py -v 2>&1 | tail -30
```

Attendu : des erreurs `AttributeError: get_emotion_snapshots_since` (méthode pas encore renommée dans `database.py`).

- [ ] **Étape 5 : Renommer la méthode dans `bot/db/database.py`**

Remplacer `get_today_emotion_snapshots` (ligne 255) par :

```python
async def get_emotion_snapshots_since(self, since: float) -> list[dict]:
    rows = await self.fetch_all(
        "SELECT * FROM emotion_history WHERE snapshot_at >= ? ORDER BY snapshot_at ASC",
        (since,),
    )
    return [dict(row) for row in rows]
```

Supprimer les imports `datetime` et `_TZ_DB` si devenus inutilisés — vérifier d'abord s'ils sont utilisés ailleurs dans le fichier avant de supprimer.

- [ ] **Étape 6 : Mettre à jour `bot/core/journal.py:189`**

```python
# Avant :
snapshots = await self._db.get_today_emotion_snapshots() if self._db else []
# Après :
snapshots = await self._db.get_emotion_snapshots_since(time.time() - 86400) if self._db else []
```

Vérifier que `import time` est présent en tête de fichier.

- [ ] **Étape 7 : Mettre à jour `bot/main.py:64` — rétention 30j**

```python
# Avant :
await db.cleanup_old_emotion_history()
# Après :
await db.cleanup_old_emotion_history(days=30)
```

- [ ] **Étape 8 : Lancer les tests pour confirmer qu'ils passent**

```bash
python -m pytest tests/test_database.py tests/test_emotion.py tests/test_journal.py tests/test_dashboard_routes.py -v 2>&1 | tail -30
```

Attendu : tous les tests PASS.

- [ ] **Étape 9 : Commit**

```bash
git add bot/db/database.py bot/core/journal.py bot/main.py \
        tests/test_database.py tests/test_emotion.py tests/test_journal.py tests/test_dashboard_routes.py
git commit -m "fix(db): renommer get_today_emotion_snapshots → get_emotion_snapshots_since, rétention 30j"
```

---

## Task 2 : Backend — Endpoint `/emotions/history` avec `since` query param

**Fichiers :**
- Modify: `bot/dashboard/routes/emotions.py:18-22`
- Modify: `tests/test_dashboard_routes.py`

- [ ] **Étape 1 : Écrire le test pour le query param `since`**

Ajouter dans `tests/test_dashboard_routes.py`, après `test_get_emotions_history` :

```python
async def test_get_emotions_history_with_since_param(app):
    """Le param since est transmis à la DB ; la réponse contient toujours 'history'."""
    import time
    state = _make_state()
    # Remplacer le mock pour capturer l'argument reçu
    captured = {}
    async def fake_since(since):
        captured["since"] = since
        return []
    state.db.get_emotion_snapshots_since = fake_since

    app2 = create_dashboard_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app2), base_url="http://test"
    ) as c:
        since_val = time.time() - 7 * 86400
        r = await c.get(f"/api/public/emotions/history?since={since_val}")
    assert r.status_code == 200
    assert "history" in r.json()
    assert abs(captured["since"] - since_val) < 1.0


async def test_get_emotions_history_since_capped_at_30d(app):
    """Un since trop ancien est cappé à 30 jours."""
    import time
    state = _make_state()
    captured = {}
    async def fake_since(since):
        captured["since"] = since
        return []
    state.db.get_emotion_snapshots_since = fake_since

    app2 = create_dashboard_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app2), base_url="http://test"
    ) as c:
        r = await c.get("/api/public/emotions/history?since=0")
    assert r.status_code == 200
    # Le since reçu par la DB doit être >= now - 30j - quelques secondes de marge
    assert captured["since"] >= time.time() - 30 * 86400 - 5
```

- [ ] **Étape 2 : Lancer les tests pour confirmer qu'ils échouent**

```bash
python -m pytest tests/test_dashboard_routes.py::test_get_emotions_history_with_since_param \
                 tests/test_dashboard_routes.py::test_get_emotions_history_since_capped_at_30d -v
```

Attendu : FAIL (signature de l'endpoint ne prend pas encore `since`).

- [ ] **Étape 3 : Mettre à jour `bot/dashboard/routes/emotions.py`**

```python
import time as _time
from fastapi import APIRouter, HTTPException, Query, Request

@public_router.get("/emotions/history")
async def get_emotions_history(
    request: Request,
    since: float = Query(default=None),
) -> dict:
    state = request.app.state.wally
    if since is None:
        since = _time.time() - 86400
    # Cap à 30 jours maximum
    since = max(since, _time.time() - 30 * 86400)
    snapshots = await state.db.get_emotion_snapshots_since(since)
    return {"history": snapshots}
```

- [ ] **Étape 4 : Lancer tous les tests dashboard**

```bash
python -m pytest tests/test_dashboard_routes.py -v 2>&1 | tail -30
```

Attendu : tous PASS.

- [ ] **Étape 5 : Lancer la suite complète**

```bash
python -m pytest --tb=short 2>&1 | tail -20
```

Attendu : tous les tests passent (110+).

- [ ] **Étape 6 : Commit**

```bash
git add bot/dashboard/routes/emotions.py tests/test_dashboard_routes.py
git commit -m "feat(api): /emotions/history accepte query param since avec cap 30j"
```

---

## Task 3 : Fix CSS — Alignement emoji dans les barres d'humeur

**Fichiers :**
- Modify: `bot/dashboard/static/style.css:271-276`

- [ ] **Étape 1 : Modifier `.emotion-label` dans `style.css`**

Localiser le bloc `.emotion-label` (ligne ~271) et modifier :

```css
.emotion-label {
  width: 100px;          /* était 80px */
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 1px;
  flex-shrink: 0;
  white-space: nowrap;   /* ajout */
}
```

- [ ] **Étape 2 : Vérifier visuellement**

Ouvrir le dashboard dans un navigateur et vérifier que toutes les barres d'humeur (ANGER, JOY, SADNESS, CURIOSITY, BOREDOM) ont l'emoji et le texte sur la même ligne, et que l'espacement vertical est uniforme.

- [ ] **Étape 3 : Commit**

```bash
git add bot/dashboard/static/style.css
git commit -m "fix(css): emotion-label width 100px + white-space nowrap pour fixer alignement emoji"
```

---

## Task 4 : Frontend HTML+CSS — Sélecteur de période + zone moyennes

**Fichiers :**
- Modify: `bot/dashboard/static/index.html:83-86`
- Modify: `bot/dashboard/static/style.css` (append)

- [ ] **Étape 1 : Remplacer le `card-title` dans `index.html`**

Localiser dans `index.html` (ligne ~83) :
```html
<div class="card-title" style="padding:8px 8px 0">📈 DERNIÈRES 24H</div>
```

Remplacer par :
```html
<div class="graph-header">
  <span id="graph-title">📈 DERNIÈRES 24H</span>
  <div class="graph-range-btns">
    <button class="graph-range-btn active" onclick="setGraphRange('24h')">24H</button>
    <button class="graph-range-btn" onclick="setGraphRange('7d')">7J</button>
    <button class="graph-range-btn" onclick="setGraphRange('30d')">30J</button>
  </div>
</div>
```

- [ ] **Étape 2 : Ajouter `emotion-averages` après le canvas dans `index.html`**

Localiser `<canvas id="emotionCanvas" height="140"></canvas>` et ajouter après :
```html
<div id="emotion-averages" style="display:none"></div>
```

- [ ] **Étape 3 : Ajouter le CSS des boutons dans `style.css`**

Ajouter à la fin de `style.css` :

```css
/* ── Graph range selector ────────────────────────────────────────────────── */

.graph-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 8px 0;
}

.graph-range-btns {
  display: flex;
  gap: 4px;
}

.graph-range-btn {
  background: transparent;
  color: var(--text-muted);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 0.7rem;
  font-weight: 700;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}

.graph-range-btn.active {
  background: var(--accent);
  color: #000;
  border-color: var(--accent);
}

/* ── Emotion averages bar ────────────────────────────────────────────────── */

#emotion-averages {
  justify-content: center;
  gap: 16px;
  padding: 6px 8px;
  font-size: 0.75rem;
  font-weight: 700;
  opacity: 0.8;
}
```

- [ ] **Étape 4 : Commit**

```bash
git add bot/dashboard/static/index.html bot/dashboard/static/style.css
git commit -m "feat(dashboard): graph-header avec sélecteur période, zone emotion-averages"
```

---

## Task 5 : Frontend JS — Logique sélecteur de période + moyennes

**Fichiers :**
- Modify: `bot/dashboard/static/app.js`

- [ ] **Étape 1 : Ajouter la variable d'état `currentGraphSince`**

Après la ligne `let currentEmotions = {};` (ligne ~32), ajouter :
```javascript
let currentGraphSince = null;  // null = 24h glissantes par défaut
```

- [ ] **Étape 2 : Modifier `loadEmotionHistory()` pour accepter un param `since`**

Remplacer la fonction existante `loadEmotionHistory` (ligne ~227) :

```javascript
async function loadEmotionHistory(since) {
  const url = since != null
    ? `/api/public/emotions/history?since=${since}`
    : '/api/public/emotions/history';
  const r = await fetch(url);
  if (!r.ok) return;
  const { history } = await r.json();
  drawEmotionGraph(history);
  renderEmotionAverages(history);
}
```

- [ ] **Étape 3 : Ajouter `setGraphRange()`**

Ajouter après `loadEmotionHistory` :

```javascript
function setGraphRange(range) {
  const now = Date.now() / 1000;
  const titles = {
    '24h': '📈 DERNIÈRES 24H',
    '7d':  '📈 7 DERNIERS JOURS',
    '30d': '📈 30 DERNIERS JOURS',
  };
  const offsets = {
    '24h': 86400,
    '7d':  7 * 86400,
    '30d': 30 * 86400,
  };
  currentGraphSince = now - offsets[range];

  // Mettre à jour le titre
  const titleEl = document.getElementById('graph-title');
  if (titleEl) titleEl.textContent = titles[range];

  // Mettre à jour l'état actif des boutons
  document.querySelectorAll('.graph-range-btn').forEach(btn => {
    btn.classList.toggle('active', btn.textContent === { '24h': '24H', '7d': '7J', '30d': '30J' }[range]);
  });

  loadEmotionHistory(currentGraphSince);
}
```

- [ ] **Étape 4 : Ajouter `renderEmotionAverages()`**

Ajouter après `setGraphRange` :

```javascript
function renderEmotionAverages(history) {
  const el = document.getElementById('emotion-averages');
  if (!el) return;
  if (!history || history.length < 2) {
    el.style.display = 'none';
    return;
  }
  const avgs = {};
  for (const e of EMOTIONS) {
    const sum = history.reduce((acc, snap) => acc + (snap[e] ?? 0), 0);
    avgs[e] = sum / history.length;
  }
  el.innerHTML = EMOTIONS.map(e =>
    `<span style="color:${EMOTION_COLORS[e]}">${EMOTION_EMOJIS[e]} ${avgs[e].toFixed(2)}</span>`
  ).join('');
  el.style.display = 'flex';
}
```

- [ ] **Étape 5 : Mettre à jour l'appel initial dans `showTab('status')`**

Localiser la ligne `requestAnimationFrame(() => loadEmotionHistory())` (ligne ~77) et la laisser telle quelle — `loadEmotionHistory()` sans argument utilise le défaut 24h côté serveur.

- [ ] **Étape 6 : Vérifier visuellement dans le navigateur**

1. Ouvrir le dashboard
2. Vérifier que le graphique affiche "DERNIÈRES 24H" par défaut
3. Cliquer "7J" → titre change, graphique recharge, moyennes se mettent à jour
4. Cliquer "30J" → idem
5. Revenir sur "24H" → retour à l'état initial
6. Vérifier que les moyennes apparaissent sous le canvas (si ≥2 snapshots disponibles)

- [ ] **Étape 7 : Commit**

```bash
git add bot/dashboard/static/app.js
git commit -m "feat(dashboard): sélecteur période 24H/7J/30J + moyennes émotions sous le graphe"
```

---

## Vérification finale

- [ ] **Lancer la suite de tests complète**

```bash
cd /opt/stacks/wally-ai
python -m pytest --tb=short 2>&1 | tail -20
```

Attendu : tous les tests passent.

- [ ] **Test manuel du dashboard**

Démarrer le bot (ou la partie dashboard en isolation) et vérifier :
1. Graphique : fenêtre de 24h glissantes, pas depuis minuit
2. Boutons 24H / 7J / 30J fonctionnels
3. Moyennes affichées sous le canvas
4. Barres d'humeur : emojis sur la même ligne que le texte, espacement uniforme
