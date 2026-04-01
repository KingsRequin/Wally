# Coûts détaillés + Mémoire de relation + Alias — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter une vue détaillée des coûts LLM (par fonctionnalité, camembert, journal brut, prix token) et un système de gestion d'alias + détection de mentions tierces dans les conversations.

**Architecture:** Trois nouveaux endpoints dans `costs.py` + une méthode DB paginée pour les logs. Trois routes CRUD alias dans `admin.py` avec rechargement du cache mémoire. Helper `_third_party_mention_context()` dans Discord et Twitch handlers, injecté en priorité 6 dans les memory_parts.

**Tech Stack:** Python (aiosqlite, FastAPI, difflib stdlib), Vanilla JS (canvas 2D pour le camembert, même pattern que drawCostGraph existant)

---

## Files

| Action | Fichier | Responsabilité |
|--------|---------|----------------|
| Modify | `bot/db/database.py` | Ajouter `get_cost_logs_paginated()` |
| Modify | `bot/dashboard/routes/costs.py` | 3 nouveaux endpoints + `PURPOSE_FEATURE_MAP` |
| Modify | `bot/dashboard/routes/admin.py` | 3 routes CRUD alias |
| Modify | `bot/dashboard/static/app.js` | Camembert, section features, prix, log table, alias modal |
| Modify | `bot/discord/handlers.py` | `_third_party_mention_context()` + intégration priority 6 |
| Modify | `bot/twitch/handlers.py` | Même helper + intégration priority 6 |
| Modify | `tests/test_dashboard_costs.py` | Tests pour by-feature, prices, logs |
| Modify | `tests/test_dashboard_routes.py` | Tests pour alias CRUD |
| Create | `tests/test_third_party_mentions.py` | Tests pour la détection de mentions |

---

## Task 1: DB — get_cost_logs_paginated

**Files:**
- Modify: `bot/db/database.py` (après `get_cost_stats`, vers ligne 598)
- Test: `tests/test_database.py`

- [ ] **Écrire le test en premier** dans `tests/test_database.py`, ajouter à la fin :

```python
@pytest.mark.asyncio
async def test_get_cost_logs_paginated_basic(tmp_path):
    from bot.db.database import Database
    import time
    db = await Database.create_test(tmp_path / "test.db")
    ts = time.time()
    await db.log_cost("gpt-5", 100, 50, 0.001, purpose="discord_response", user_id="discord:123")
    await db.log_cost("gpt-5-mini", 80, 30, 0.0005, purpose="emotion_analysis", user_id=None)
    await db.upsert_memory_user("discord:123", "discord", username="Azrael")

    result = await db.get_cost_logs_paginated(ts - 1, page=1, limit=10)
    assert result["total"] == 2
    assert result["page"] == 1
    assert len(result["logs"]) == 2
    second = result["logs"][1]
    assert second["username"] == "Azrael"
    await db.close()


@pytest.mark.asyncio
async def test_get_cost_logs_paginated_pagination(tmp_path):
    from bot.db.database import Database
    import time
    db = await Database.create_test(tmp_path / "test2.db")
    ts = time.time()
    for i in range(5):
        await db.log_cost("gpt-5", 10, 5, 0.0001, purpose="discord_response", user_id=None)
    result = await db.get_cost_logs_paginated(ts - 1, page=2, limit=2)
    assert result["total"] == 5
    assert len(result["logs"]) == 2
    await db.close()
```

- [ ] **Vérifier que le test échoue**

```bash
python -m pytest tests/test_database.py::test_get_cost_logs_paginated_basic -x 2>&1 | tail -5
```
Attendu : `AttributeError: 'Database' object has no attribute 'get_cost_logs_paginated'`

- [ ] **Implémenter** dans `bot/db/database.py`, après `get_cost_stats` (ligne ~598) :

```python
async def get_cost_logs_paginated(
    self,
    since_ts: float,
    page: int = 1,
    limit: int = 50,
) -> dict:
    """Journal paginé des appels LLM avec résolution username."""
    offset = (page - 1) * limit
    rows = await self.fetch_all(
        "SELECT cl.timestamp, cl.model, cl.input_tokens, cl.output_tokens, "
        "cl.cost_usd, cl.purpose, cl.user_id, mu.username "
        "FROM cost_log cl "
        "LEFT JOIN memory_users mu ON mu.user_id = cl.user_id "
        "WHERE cl.timestamp >= ? "
        "ORDER BY cl.timestamp DESC "
        "LIMIT ? OFFSET ?",
        (since_ts, limit, offset),
    )
    count_row = await self.fetch_one(
        "SELECT COUNT(*) AS n FROM cost_log WHERE timestamp >= ?",
        (since_ts,),
    )
    total = count_row["n"] if count_row else 0
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "logs": [
            {
                "datetime": datetime.fromtimestamp(r["timestamp"], tz=_TZ_DB).strftime("%Y-%m-%d %H:%M:%S"),
                "model": r["model"] or "",
                "input_tokens": r["input_tokens"] or 0,
                "output_tokens": r["output_tokens"] or 0,
                "cost_usd": round(float(r["cost_usd"]), 6),
                "purpose": r["purpose"] or "",
                "user_id": r["user_id"] or "",
                "username": r["username"] or "",
            }
            for r in rows
        ],
    }
```

- [ ] **Vérifier que les tests passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_database.py::test_get_cost_logs_paginated_basic tests/test_database.py::test_get_cost_logs_paginated_pagination -v
```
Attendu : 2 PASSED

- [ ] **Commit**

```bash
git add bot/db/database.py tests/test_database.py
git commit -m "feat(db): ajouter get_cost_logs_paginated() avec résolution username"
```

---

## Task 2: Backend — nouveaux endpoints coûts

**Files:**
- Modify: `bot/dashboard/routes/costs.py`
- Test: `tests/test_dashboard_costs.py`

- [ ] **Écrire les tests** dans `tests/test_dashboard_costs.py`, ajouter à la fin :

```python
async def test_costs_by_feature_grouping(client):
    db = client._transport.app.state.wally.db
    db.get_cost_breakdown = AsyncMock(return_value=[
        {"key": "discord_response", "total": 5.0, "count": 40},
        {"key": "discord_spontaneous", "total": 1.0, "count": 10},
        {"key": "daily_journal", "total": 2.0, "count": 2},
        {"key": "emotion_analysis", "total": 0.5, "count": 50},
        {"key": "image_generation", "total": 3.0, "count": 5},
        {"key": "embedding", "total": 0.2, "count": 100},
        {"key": "reminder", "total": 0.1, "count": 3},
        {"key": "unknown_thing", "total": 0.05, "count": 1},
    ])
    r = await client.get("/api/admin/costs/by-feature?days=30", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    features = {d["feature"]: d for d in data}
    assert features["Reponses"]["cost"] == pytest.approx(6.0)  # 5.0 + 1.0
    assert "Journal" in features
    assert "Images" in features
    assert "Emotions" in features or "Émotions" in features
    assert "Memoire" in features or "Mémoire" in features
    assert "Systeme" in features or "Système" in features
    assert "Autre" in features
    total_pct = sum(d["pct"] for d in data)
    assert total_pct == pytest.approx(100.0, abs=0.5)


async def test_costs_prices(client):
    r = await client.get("/api/admin/costs/prices", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert len(data) > 0
    for model, prices in data.items():
        assert "input_per_1k" in prices
        assert "output_per_1k" in prices
        assert prices["input_per_1k"] > 0


async def test_costs_logs_paginated(client):
    db = client._transport.app.state.wally.db
    db.get_cost_logs_paginated = AsyncMock(return_value={
        "total": 150, "page": 1, "limit": 50,
        "logs": [{"datetime": "2026-03-29 14:00:00", "model": "gpt-5",
                  "input_tokens": 200, "output_tokens": 80, "cost_usd": 0.00124,
                  "purpose": "discord_response", "user_id": "discord:123", "username": "Azrael"}],
    })
    r = await client.get("/api/admin/costs/logs?days=7&page=1&limit=50", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 150
    assert data["logs"][0]["username"] == "Azrael"


async def test_costs_logs_auth_required(client):
    r = await client.get("/api/admin/costs/logs")
    assert r.status_code == 401
```

- [ ] **Vérifier que les tests échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_dashboard_costs.py::test_costs_by_feature_grouping tests/test_dashboard_costs.py::test_costs_prices tests/test_dashboard_costs.py::test_costs_logs_paginated -x 2>&1 | tail -5
```
Attendu : 404 (routes inexistantes)

- [ ] **Implémenter dans `bot/dashboard/routes/costs.py`**

Ajouter le dict `PURPOSE_FEATURE_MAP` après les imports existants (avant `router = APIRouter()`) :

```python
PURPOSE_FEATURE_MAP: dict[str, str] = {
    "discord_response": "Réponses",
    "discord_spontaneous": "Réponses",
    "discord_ask": "Réponses",
    "twitch_response": "Réponses",
    "twitch_spontaneous": "Réponses",
    "twitch_event": "Réponses",
    "web_response": "Réponses",
    "daily_journal": "Journal",
    "journal_chunk_summary": "Journal",
    "journal_final_summary": "Journal",
    "opinion_formation": "Journal",
    "image_generation": "Images",
    "image_title": "Images",
    "image_description": "Images",
    "emotion_analysis": "Émotions",
    "fact_extraction": "Mémoire",
    "memory_consolidation": "Mémoire",
    "memory_evaluate": "Mémoire",
    "context_summary": "Mémoire",
    "context_summary_final": "Mémoire",
    "memory_cleanup": "Mémoire",
    "embedding": "Mémoire",
    "spam_warning": "Système",
    "reminder": "Système",
    "twitch_visit_summary": "Système",
    "twitch_overlay_announce": "Système",
}
```

Ajouter les trois endpoints à la fin du fichier :

```python
@router.get("/costs/by-feature")
async def costs_by_feature(request: Request, days: int = 30) -> list:
    days = _clamp_days(days)
    db = request.app.state.wally.db
    rows = await db.get_cost_breakdown(_since_ts(days), "purpose")
    features: dict[str, dict] = {}
    grand_total = sum(r["total"] for r in rows)
    for r in rows:
        feat = PURPOSE_FEATURE_MAP.get(r["key"] or "", "Autre")
        if feat not in features:
            features[feat] = {"feature": feat, "cost": 0.0, "count": 0}
        features[feat]["cost"] = round(features[feat]["cost"] + r["total"], 6)
        features[feat]["count"] += r["count"]
    result = sorted(features.values(), key=lambda x: x["cost"], reverse=True)
    for item in result:
        item["pct"] = round(item["cost"] / grand_total * 100, 1) if grand_total > 0 else 0.0
    return result


@router.get("/costs/prices")
async def costs_prices(request: Request) -> dict:
    from bot.core.llm.openai_client import MODEL_COSTS
    from bot.core.llm.claude_client import CLAUDE_MODEL_COSTS
    result: dict[str, dict] = {}
    for model, (inp, out) in MODEL_COSTS.items():
        result[model] = {"input_per_1k": round(inp / 1000, 8), "output_per_1k": round(out / 1000, 8)}
    for model, (inp, out) in CLAUDE_MODEL_COSTS.items():
        result[model] = {"input_per_1k": round(inp / 1000, 8), "output_per_1k": round(out / 1000, 8)}
    return result


@router.get("/costs/logs")
async def costs_logs(request: Request, days: int = 30, page: int = 1, limit: int = 50) -> dict:
    days = _clamp_days(days)
    limit = max(1, min(limit, 200))
    page = max(1, page)
    db = request.app.state.wally.db
    return await db.get_cost_logs_paginated(_since_ts(days), page=page, limit=limit)
```

- [ ] **Vérifier que les tests passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_dashboard_costs.py -v 2>&1 | tail -20
```
Attendu : tous PASSED

- [ ] **Commit**

```bash
git add bot/dashboard/routes/costs.py tests/test_dashboard_costs.py
git commit -m "feat(costs): by-feature, prices et logs paginés"
```

---

## Task 3: Frontend — camembert + fonctionnalités + prix tokens + journal des appels

**Files:**
- Modify: `bot/dashboard/static/app.js`

Note : tout le code JS suit le pattern existant de `app.js` : `escHtml()`/`escAttr()` pour la sanitisation XSS, `apiFetch()` pour les appels API authentifiés, canvas 2D pour les graphiques (même pattern que `drawCostGraph`).

### 3a — Couleurs et camembert

- [ ] **Ajouter les couleurs des features et `drawFeaturePie()`** juste après `drawCostGraph()` (vers ligne 2992) :

```javascript
// Couleurs par feature (palette cohérente avec le reste du dashboard)
var FEATURE_COLORS = {
  'Réponses': '#06b6d4',
  'Images': '#a855f7',
  'Journal': '#eab308',
  'Émotions': '#ef4444',
  'Mémoire': '#22c55e',
  'Système': '#3b82f6',
  'Autre': '#6b7280',
};

function drawFeaturePie(canvas, data) {
  if (!canvas || !data || data.length === 0) return;
  var W = canvas.offsetWidth || 300;
  var H = 220;
  canvas.width = W;
  canvas.height = H;
  var ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, W, H);

  var cx = W / 2 - 40, cy = H / 2;
  var r = Math.min(cx, cy) - 10;
  var total = data.reduce(function(s, d) { return s + d.cost; }, 0);
  if (total === 0) return;

  var angle = -Math.PI / 2;
  data.forEach(function(d) {
    var slice = (d.cost / total) * Math.PI * 2;
    var color = FEATURE_COLORS[d.feature] || '#6b7280';
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, r, angle, angle + slice);
    ctx.closePath();
    ctx.fillStyle = color;
    ctx.fill();
    ctx.strokeStyle = 'rgba(0,0,0,0.3)';
    ctx.lineWidth = 1;
    ctx.stroke();
    angle += slice;
  });

  // Legende droite
  var legendX = cx + r + 20, legendY = 20;
  ctx.font = '11px system-ui';
  data.forEach(function(d) {
    var color = FEATURE_COLORS[d.feature] || '#6b7280';
    ctx.fillStyle = color;
    ctx.fillRect(legendX, legendY, 10, 10);
    ctx.fillStyle = 'rgba(255,255,255,0.8)';
    ctx.fillText(escHtml(d.feature) + ' ' + d.pct + '%', legendX + 14, legendY + 9);
    legendY += 18;
  });
}
```

### 3b — Fonctions de chargement

- [ ] **Ajouter `loadCostsByFeature`, `loadCostPrices`, `loadCostLogs`** après `renderCostUsers` (vers ligne 3034) :

```javascript
async function loadCostsByFeature(days) {
  var r = await apiFetch('/api/admin/costs/by-feature?days=' + days);
  if (!r || !r.ok) return;
  var data = await r.json();
  var canvas = document.getElementById('featurePieCanvas');
  if (canvas) drawFeaturePie(canvas, data);
  var el = document.getElementById('cost-by-feature-bars');
  if (!el) return;
  var bars = data.map(function(d) {
    var color = FEATURE_COLORS[d.feature] || '#6b7280';
    var bar = document.createElement('div');
    bar.style.cssText = 'margin-bottom:8px';
    var header = document.createElement('div');
    header.style.cssText = 'display:flex;justify-content:space-between;margin-bottom:3px';
    var label = document.createElement('span');
    label.style.cssText = 'color:rgba(255,255,255,0.8);font-size:0.8rem';
    label.textContent = d.feature;
    var amount = document.createElement('span');
    amount.style.cssText = 'color:rgba(255,255,255,0.5);font-size:0.75rem';
    amount.textContent = '$' + d.cost.toFixed(4) + ' \u00b7 ' + d.pct + '%';
    header.appendChild(label);
    header.appendChild(amount);
    bar.appendChild(header);
    var track = document.createElement('div');
    track.style.cssText = 'background:rgba(255,255,255,0.06);border-radius:4px;height:6px';
    var fill = document.createElement('div');
    fill.style.cssText = 'background:' + color + ';width:' + d.pct + '%;height:100%;border-radius:4px';
    track.appendChild(fill);
    bar.appendChild(track);
    return bar;
  });
  el.textContent = '';
  bars.forEach(function(b) { el.appendChild(b); });
}

async function loadCostPrices() {
  var r = await apiFetch('/api/admin/costs/prices');
  if (!r || !r.ok) return;
  var data = await r.json();
  var el = document.getElementById('cost-prices-table');
  if (!el) return;
  var table = document.createElement('table');
  table.style.cssText = 'width:100%;border-collapse:collapse';
  var head = document.createElement('tr');
  ['Modele', 'Input/1M', 'Output/1M'].forEach(function(h, i) {
    var th = document.createElement('th');
    th.style.cssText = 'text-align:' + (i > 0 ? 'right' : 'left') + ';padding:4px 8px;font-size:0.7rem;color:rgba(255,255,255,0.4)';
    th.textContent = h;
    head.appendChild(th);
  });
  table.appendChild(head);
  Object.entries(data).forEach(function(entry) {
    var model = entry[0], p = entry[1];
    var tr = document.createElement('tr');
    var td1 = document.createElement('td');
    td1.style.cssText = 'padding:4px 8px;color:rgba(255,255,255,0.8);font-size:0.75rem';
    td1.textContent = model;
    var td2 = document.createElement('td');
    td2.style.cssText = 'padding:4px 8px;color:#06b6d4;font-size:0.75rem;text-align:right';
    td2.textContent = '$' + (p.input_per_1k * 1000).toFixed(3);
    var td3 = document.createElement('td');
    td3.style.cssText = 'padding:4px 8px;color:#a855f7;font-size:0.75rem;text-align:right';
    td3.textContent = '$' + (p.output_per_1k * 1000).toFixed(3);
    tr.appendChild(td1); tr.appendChild(td2); tr.appendChild(td3);
    table.appendChild(tr);
  });
  el.textContent = '';
  el.appendChild(table);
}

var _costLogsPage = 1;
async function loadCostLogs(days, page) {
  page = page || 1;
  _costLogsPage = page;
  var r = await apiFetch('/api/admin/costs/logs?days=' + days + '&page=' + page + '&limit=50');
  if (!r || !r.ok) return;
  var data = await r.json();
  var el = document.getElementById('cost-logs-table');
  if (!el) return;
  el.textContent = '';
  if (data.logs.length === 0) {
    var empty = document.createElement('div');
    empty.style.cssText = 'color:rgba(255,255,255,0.3);text-align:center;padding:20px';
    empty.textContent = 'Aucun appel sur cette période';
    el.appendChild(empty);
    return;
  }
  var cols = ['Date', 'Modele', 'In', 'Out', 'Cout', 'Purpose', 'User'];
  var table = document.createElement('table');
  table.style.cssText = 'width:100%;border-collapse:collapse;font-size:0.72rem';
  var thead = document.createElement('tr');
  cols.forEach(function(c, i) {
    var th = document.createElement('th');
    th.style.cssText = 'padding:4px 6px;color:rgba(255,255,255,0.4);text-align:' + (i >= 2 && i <= 4 ? 'right' : 'left');
    th.textContent = c;
    thead.appendChild(th);
  });
  table.appendChild(thead);
  data.logs.forEach(function(l) {
    var tr = document.createElement('tr');
    tr.style.cssText = 'border-top:1px solid rgba(255,255,255,0.04)';
    var cells = [
      {text: l.datetime, style: 'color:rgba(255,255,255,0.5)', align: 'left'},
      {text: l.model, style: 'color:rgba(255,255,255,0.8)', align: 'left'},
      {text: String(l.input_tokens), style: 'color:rgba(255,255,255,0.5)', align: 'right'},
      {text: String(l.output_tokens), style: 'color:rgba(255,255,255,0.5)', align: 'right'},
      {text: '$' + l.cost_usd.toFixed(5), style: 'color:#06b6d4', align: 'right'},
      {text: l.purpose, style: 'color:rgba(255,255,255,0.6)', align: 'left'},
      {text: l.username || l.user_id || '\u2014', style: 'color:rgba(255,255,255,0.6)', align: 'left'},
    ];
    cells.forEach(function(c) {
      var td = document.createElement('td');
      td.style.cssText = 'padding:4px 6px;text-align:' + c.align + ';' + c.style;
      td.textContent = c.text;
      tr.appendChild(td);
    });
    table.appendChild(tr);
  });
  el.appendChild(table);
  // Pagination
  var totalPages = Math.ceil(data.total / data.limit);
  var pag = document.getElementById('cost-logs-pagination');
  if (pag) {
    pag.textContent = '';
    if (page > 1) {
      var prev = document.createElement('button');
      prev.className = 'btn-sm';
      prev.textContent = '\u2190 Prec';
      prev.onclick = function() { loadCostLogs(days, page - 1); };
      pag.appendChild(prev);
    }
    var info = document.createElement('span');
    info.style.cssText = 'color:rgba(255,255,255,0.4);font-size:0.75rem';
    info.textContent = ((page - 1) * 50 + 1) + '\u2013' + Math.min(page * 50, data.total) + ' / ' + data.total;
    pag.appendChild(info);
    if (page < totalPages) {
      var next = document.createElement('button');
      next.className = 'btn-sm';
      next.textContent = 'Suiv \u2192';
      next.onclick = function() { loadCostLogs(days, page + 1); };
      pag.appendChild(next);
    }
  }
}
```

### 3c — Mise à jour de loadCosts() et renderCostsTab()

- [ ] **Mettre à jour `loadCosts()`** : à la fin du bloc try/catch existant, après les appels `renderCost*` existants, ajouter :

```javascript
    // Nouvelles sections détail
    var detailDays = { '7d': 7, '30d': 30, '90d': 90 }[currentCostRange] || 7;
    await Promise.all([
      loadCostsByFeature(detailDays),
      loadCostPrices(),
      loadCostLogs(detailDays, _costLogsPage),
    ]);
```

- [ ] **Mettre à jour `renderCostsTab()`** : remplacer le contenu du sous-onglet `costs-sub-detail` (les lignes entre `<div class="mem-subnav-content" id="costs-sub-detail">` et son `</div>`) par la structure suivante (utiliser `el.querySelector` ou reconstruire via `insertAdjacentHTML` après le subnav).

  La nouvelle structure doit contenir dans l'ordre :
  1. Card "PAR FONCTIONNALITE" avec un `<canvas id="featurePieCanvas">` (300x220) et un `<div id="cost-by-feature-bars">`
  2. Grid 3 colonnes avec les cards existantes : `cost-by-model`, `cost-by-purpose`, `cost-top-users`
  3. Card "PRIX DES TOKENS" avec `<div id="cost-prices-table">`
  4. Card "JOURNAL DES APPELS" avec `<div id="cost-logs-table">` et `<div id="cost-logs-pagination">`
  5. Card `cost-alert-bar` (déjà existante)

  Construire ces éléments via `document.createElement` et `appendChild` pour éviter tout risque XSS, en suivant strictement le pattern de `renderMemoireTab()`.

- [ ] **Mettre à jour `setCostRange()`** pour reset `_costLogsPage = 1` au changement de plage :

```javascript
function setCostRange(range) {
  currentCostRange = range;
  _costLogsPage = 1;
  // ... reste inchangé
}
```

- [ ] **Tester manuellement** : charger le dashboard, aller sur Coûts > Détail. Vérifier camembert visible, barres features, tableau prix, journal paginé.

- [ ] **Commit**

```bash
git add bot/dashboard/static/app.js
git commit -m "feat(dashboard): camembert features, prix tokens, journal appels LLM"
```

---

## Task 4: Backend — routes CRUD alias

**Files:**
- Modify: `bot/dashboard/routes/admin.py`
- Test: `tests/test_dashboard_routes.py`

- [ ] **Écrire les tests** dans `tests/test_dashboard_routes.py`, ajouter à la fin :

```python
class TestAliasCRUD:
    @pytest.fixture
    def alias_app(self):
        from bot.dashboard.app import create_dashboard_app
        state = _make_state()
        state.db.list_aliases = AsyncMock(return_value=[
            {"nickname": "melio", "canonical_uid": "discord:123", "display_name": "Meliodas",
             "source": "manual", "confidence": 1.0, "created_at": 1000.0},
        ])
        state.db.upsert_alias = AsyncMock()
        state.db.delete_alias = AsyncMock()
        state.memory = MagicMock()
        state.memory.load_aliases = AsyncMock()
        return create_dashboard_app(state)

    async def test_list_aliases(self, alias_app):
        async with AsyncClient(transport=ASGITransport(app=alias_app), base_url="http://test") as c:
            r = await c.get("/api/admin/aliases", headers={"Authorization": "Bearer testtoken"})
        assert r.status_code == 200
        assert r.json()[0]["nickname"] == "melio"

    async def test_create_alias(self, alias_app):
        async with AsyncClient(transport=ASGITransport(app=alias_app), base_url="http://test") as c:
            r = await c.post("/api/admin/aliases",
                json={"nickname": "melio", "canonical_uid": "discord:123", "display_name": "Meliodas"},
                headers={"Authorization": "Bearer testtoken"})
        assert r.status_code == 200
        assert r.json()["ok"] is True
        alias_app.state.wally.db.upsert_alias.assert_awaited_once_with(
            "melio", "discord:123", "Meliodas", source="manual", confidence=1.0
        )
        alias_app.state.wally.memory.load_aliases.assert_awaited_once()

    async def test_create_alias_missing_fields(self, alias_app):
        async with AsyncClient(transport=ASGITransport(app=alias_app), base_url="http://test") as c:
            r = await c.post("/api/admin/aliases",
                json={"nickname": "melio"},
                headers={"Authorization": "Bearer testtoken"})
        assert r.status_code == 400

    async def test_delete_alias(self, alias_app):
        async with AsyncClient(transport=ASGITransport(app=alias_app), base_url="http://test") as c:
            r = await c.delete("/api/admin/aliases/melio",
                headers={"Authorization": "Bearer testtoken"})
        assert r.status_code == 200
        alias_app.state.wally.db.delete_alias.assert_awaited_once_with("melio")
        alias_app.state.wally.memory.load_aliases.assert_awaited_once()

    async def test_alias_auth_required(self, alias_app):
        async with AsyncClient(transport=ASGITransport(app=alias_app), base_url="http://test") as c:
            for method, path in [("GET", "/api/admin/aliases"), ("DELETE", "/api/admin/aliases/x")]:
                r = await c.request(method, path)
                assert r.status_code == 401
```

- [ ] **Vérifier que les tests échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_dashboard_routes.py::TestAliasCRUD -x 2>&1 | tail -5
```
Attendu : 404

- [ ] **Implémenter dans `bot/dashboard/routes/admin.py`**, ajouter à la fin du fichier :

```python
# ── Alias management ──────────────────────────────────────────────────────────

@router.get("/aliases")
async def list_aliases(request: Request, canonical_uid: str | None = None) -> list:
    db = request.app.state.wally.db
    return await db.list_aliases(canonical_uid=canonical_uid)


@router.post("/aliases")
async def create_alias(request: Request) -> dict:
    body = await request.json()
    nickname = (body.get("nickname") or "").strip()
    canonical_uid = (body.get("canonical_uid") or "").strip()
    display_name = (body.get("display_name") or nickname).strip()
    if not nickname or not canonical_uid:
        raise HTTPException(status_code=400, detail="nickname et canonical_uid requis")
    db = request.app.state.wally.db
    await db.upsert_alias(nickname, canonical_uid, display_name, source="manual", confidence=1.0)
    memory = getattr(request.app.state.wally, "memory", None)
    if memory:
        await memory.load_aliases(db)
    return {"ok": True}


@router.delete("/aliases/{nickname}")
async def delete_alias(nickname: str, request: Request) -> dict:
    db = request.app.state.wally.db
    await db.delete_alias(nickname)
    memory = getattr(request.app.state.wally, "memory", None)
    if memory:
        await memory.load_aliases(db)
    return {"ok": True}
```

- [ ] **Vérifier que les tests passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_dashboard_routes.py::TestAliasCRUD -v
```
Attendu : tous PASSED

- [ ] **Commit**

```bash
git add bot/dashboard/routes/admin.py tests/test_dashboard_routes.py
git commit -m "feat(admin): routes CRUD alias avec rechargement cache memoire"
```

---

## Task 5: Frontend — section alias dans la modal utilisateur

**Files:**
- Modify: `bot/dashboard/static/app.js`

Note : construire les éléments DOM via `document.createElement`/`appendChild`/`textContent` uniquement. Ne pas utiliser de template strings avec données utilisateur non contrôlées. Utiliser `escAttr()` pour les attributs onclick.

- [ ] **Modifier `openUserModal()`** : après la ligne `var aliasR = ...` (juste après le fetch mémoires), ajouter la récupération des alias :

```javascript
  var aliasR = await apiFetch('/api/admin/aliases?canonical_uid=' + encodeURIComponent(userId));
  var aliases = aliasR && aliasR.ok ? await aliasR.json() : [];
```

- [ ] **Construire la section alias** via DOM, dans `openUserModal()`, juste avant `backdrop.appendChild(modal)` :

```javascript
  // Alias section
  var aliasSection = document.createElement('div');
  aliasSection.className = 'mem-linked-section';
  aliasSection.id = 'modal-aliases-section';
  var aliasTitle = document.createElement('div');
  aliasTitle.className = 'mem-linked-title';
  aliasTitle.textContent = 'Alias (pseudos reconnus)';
  aliasSection.appendChild(aliasTitle);
  var aliasPills = document.createElement('div');
  aliasPills.className = 'mem-linked-pills';
  aliasPills.id = 'modal-aliases-pills';
  _renderAliasPills(aliasPills, aliases, userId);
  aliasSection.appendChild(aliasPills);
  // Add form
  var addRow = document.createElement('div');
  addRow.style.cssText = 'margin-top:8px;display:flex;gap:6px';
  var aliasInput = document.createElement('input');
  aliasInput.type = 'text';
  aliasInput.id = 'modal-alias-input';
  aliasInput.placeholder = 'Nouveau alias...';
  aliasInput.style.cssText = 'background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);border-radius:6px;padding:4px 8px;color:#fff;font-size:0.8rem;flex:1';
  var addBtn = document.createElement('button');
  addBtn.className = 'mem-modal-action add';
  addBtn.style.cssText = 'padding:4px 10px;font-size:0.8rem';
  addBtn.textContent = '+ Ajouter';
  addBtn.addEventListener('click', function() { addModalAlias(userId); });
  addRow.appendChild(aliasInput);
  addRow.appendChild(addBtn);
  aliasSection.appendChild(addRow);
  modal.appendChild(aliasSection);
```

- [ ] **Ajouter les helpers** après `openUserModal` :

```javascript
function _renderAliasPills(container, aliases, userId) {
  container.textContent = '';
  aliases.forEach(function(a) {
    var pill = document.createElement('div');
    pill.className = 'mem-linked-pill';
    pill.style.cssText = 'display:flex;align-items:center;gap:4px';
    var name = document.createElement('span');
    name.textContent = a.nickname;
    var badge = document.createElement('span');
    badge.textContent = a.source === 'manual' ? 'Manuel' : 'Auto';
    badge.style.cssText = 'font-size:0.6rem;padding:1px 4px;border-radius:3px;'
      + (a.source === 'manual' ? 'background:rgba(6,182,212,0.2);color:#06b6d4' : 'background:rgba(255,255,255,0.1);color:rgba(255,255,255,0.4)');
    var del = document.createElement('button');
    del.textContent = '\u2715';
    del.style.cssText = 'background:none;border:none;color:rgba(255,255,255,0.4);cursor:pointer;padding:0 2px';
    del.title = 'Supprimer';
    del.addEventListener('click', function() { deleteModalAlias(a.nickname, userId); });
    pill.appendChild(name);
    pill.appendChild(badge);
    pill.appendChild(del);
    container.appendChild(pill);
  });
}

async function addModalAlias(userId) {
  var input = document.getElementById('modal-alias-input');
  if (!input || !input.value.trim()) return;
  var nickname = input.value.trim();
  var modal = document.querySelector('.mem-modal');
  var userData = modal ? (modal._userData || {}) : {};
  var displayName = userData.username || userId.split(':').slice(1).join(':');
  var r = await apiFetch('/api/admin/aliases', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({nickname: nickname, canonical_uid: userId, display_name: displayName}),
  });
  if (r && r.ok) {
    input.value = '';
    var aliasR = await apiFetch('/api/admin/aliases?canonical_uid=' + encodeURIComponent(userId));
    var aliases = aliasR && aliasR.ok ? await aliasR.json() : [];
    var pills = document.getElementById('modal-aliases-pills');
    if (pills) _renderAliasPills(pills, aliases, userId);
  }
}

async function deleteModalAlias(nickname, userId) {
  var r = await apiFetch('/api/admin/aliases/' + encodeURIComponent(nickname), {method: 'DELETE'});
  if (r && r.ok) {
    var aliasR = await apiFetch('/api/admin/aliases?canonical_uid=' + encodeURIComponent(userId));
    var aliases = aliasR && aliasR.ok ? await aliasR.json() : [];
    var pills = document.getElementById('modal-aliases-pills');
    if (pills) _renderAliasPills(pills, aliases, userId);
  }
}
```

- [ ] **Tester manuellement** : ouvrir modal d'un utilisateur → section "Alias" visible en bas, ajouter/supprimer fonctionne.

- [ ] **Commit**

```bash
git add bot/dashboard/static/app.js
git commit -m "feat(dashboard): section alias dans la modal utilisateur"
```

---

## Task 6: Détection de mentions tierces (Discord + Twitch)

**Files:**
- Modify: `bot/discord/handlers.py`
- Modify: `bot/twitch/handlers.py`
- Create: `tests/test_third_party_mentions.py`

- [ ] **Écrire les tests** dans `tests/test_third_party_mentions.py` :

```python
# tests/test_third_party_mentions.py
"""Tests pour la détection de mentions tierces dans les conversations."""
import pytest
from unittest.mock import AsyncMock, MagicMock, ANY


def make_bot(alias_map=None, memory_results="", all_users=None):
    bot = MagicMock()
    bot.db.get_nickname_alias_map = AsyncMock(return_value=alias_map or {})
    bot.db.list_memory_users = AsyncMock(return_value=all_users or [])
    bot.memory.search = AsyncMock(return_value=memory_results)
    return bot


@pytest.mark.asyncio
async def test_exact_alias_match_injects_memories():
    from bot.discord.handlers import _third_party_mention_context
    bot = make_bot(alias_map={"melio": "discord:999"}, memory_results="Meliodas aime les pizzas")
    messages = [{"content": "tu te souviens de melio ?", "author": "alice"}]
    result = await _third_party_mention_context(bot, "discord", "123", messages)
    assert result is not None
    assert "aime les pizzas" in result


@pytest.mark.asyncio
async def test_alias_of_current_author_ignored():
    from bot.discord.handlers import _third_party_mention_context
    bot = make_bot(alias_map={"melio": "discord:123"})
    messages = [{"content": "salut melio c'est moi", "author": "melio"}]
    result = await _third_party_mention_context(bot, "discord", "123", messages)
    assert result is None


@pytest.mark.asyncio
async def test_fuzzy_high_ratio_returns_hint():
    from bot.discord.handlers import _third_party_mention_context
    bot = make_bot(alias_map={}, all_users=[{"username": "azrael", "user_id": "discord:789"}])
    messages = [{"content": "azrae etait la hier ?", "author": "alice"}]
    result = await _third_party_mention_context(bot, "discord", "123", messages)
    # azrae vs azrael -> ratio ~0.91 -> note interne
    assert result is not None
    assert "azrael" in result.lower()
    assert "confiance" in result


@pytest.mark.asyncio
async def test_empty_messages_returns_none():
    from bot.discord.handlers import _third_party_mention_context
    bot = make_bot()
    result = await _third_party_mention_context(bot, "discord", "123", [])
    assert result is None


@pytest.mark.asyncio
async def test_no_match_returns_none():
    from bot.discord.handlers import _third_party_mention_context
    bot = make_bot(alias_map={}, all_users=[])
    messages = [{"content": "salut comment tu vas", "author": "alice"}]
    result = await _third_party_mention_context(bot, "discord", "123", messages)
    assert result is None


@pytest.mark.asyncio
async def test_max_two_third_party_users():
    from bot.discord.handlers import _third_party_mention_context
    bot = make_bot(
        alias_map={"alice": "discord:1", "bob": "discord:2", "charlie": "discord:3"},
        memory_results="quelque chose",
    )
    messages = [{"content": "alice bob charlie etaient la", "author": "other"}]
    result = await _third_party_mention_context(bot, "discord", "999", messages)
    if result:
        assert result.count("--- Souvenirs sur") <= 2
```

- [ ] **Vérifier que les tests échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_third_party_mentions.py -x 2>&1 | tail -5
```
Attendu : `ImportError: cannot import name '_third_party_mention_context'`

- [ ] **Ajouter `import difflib`** dans `bot/discord/handlers.py` (après les imports existants ligne ~10)

- [ ] **Implémenter `_third_party_mention_context()`** dans `bot/discord/handlers.py`, après la définition de `_NOTE_TOOLS` :

```python
async def _third_party_mention_context(
    bot: "WallyDiscord",
    platform: str,
    author_user_id: str,
    messages: list[dict],
) -> str | None:
    """Cherche les pseudos mentionnes dans les messages recents.

    - Alias exact connu -> injecte les souvenirs du tiers (max 2 users).
    - Pseudo proche d'un username connu (ratio >= 0.75) -> note interne.
    - Retourne None si rien de pertinent.
    """
    try:
        if not messages:
            return None
        corpus = " ".join(m.get("content", "") for m in messages[-15:])
        words = set(re.findall(r"\b\w{3,}\b", corpus.lower()))
        if not words:
            return None
        author_uid = f"{platform}:{author_user_id}"
        alias_map: dict[str, str] = await bot.db.get_nickname_alias_map()
        # Exact alias matches (excluding current author)
        matched: list[tuple[str, str]] = [
            (uid, word)
            for word in words
            for uid in [alias_map.get(word)]
            if uid and uid != author_uid
        ]
        if matched:
            results = []
            for uid, word in matched[:2]:
                parts = uid.split(":", 1)
                if len(parts) != 2:
                    continue
                uid_platform, uid_raw = parts
                try:
                    mems = await bot.memory.search(uid_platform, uid_raw, corpus)
                    if mems:
                        results.append(f"--- Souvenirs sur {word} ---\n{mems}")
                except Exception:
                    pass
            return "\n".join(results) if results else None
        # Fuzzy match against known usernames
        try:
            all_users = await bot.db.list_memory_users(limit=500)
        except Exception:
            return None
        known = [
            (u["username"].lower(), u["username"], u["user_id"])
            for u in all_users
            if u.get("username") and u["user_id"] != author_uid
        ]
        if not known:
            return None
        best_ratio, best_word, best_name = 0.0, "", ""
        for word in words:
            for lname, display_name, _ in known:
                ratio = difflib.SequenceMatcher(None, word, lname).ratio()
                if ratio > best_ratio:
                    best_ratio, best_word, best_name = ratio, word, display_name
        if best_ratio >= 0.75 and best_name:
            pct = int(best_ratio * 100)
            return (
                f"Note interne : '{best_word}' ressemble a {best_name} "
                f"(confiance {pct}%) -- si c'est bien lui, mentionne-le naturellement."
            )
        return None
    except Exception as exc:
        logger.debug("_third_party_mention_context failed: {e}", e=exc)
        return None
```

- [ ] **Vérifier que les tests passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_third_party_mentions.py -v
```
Attendu : tous PASSED

- [ ] **Intégrer en Priority 6 dans `_respond()` Discord** (`bot/discord/handlers.py`), après le bloc Priority 5 et avant `mem_context = assemble_memory_context(...)` :

```python
        # Priority 6: Third-party mentions
        try:
            third_party = await _third_party_mention_context(
                bot, platform, user_id, prelude
            )
            if third_party:
                memory_parts.append((6, third_party))
        except Exception:
            pass
```

- [ ] **Intégrer dans Twitch** (`bot/twitch/handlers.py`) :
  1. Ajouter `import difflib` après les imports existants
  2. Copier la fonction `_third_party_mention_context` complète (identique) au début du fichier après les imports, en changeant le type hint de `"WallyDiscord"` en `Any` ou en supprimant le type hint
  3. Ajouter le même bloc Priority 6 dans `handle_message()` après le bloc Priority 5

- [ ] **Vérifier les tests globaux**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_third_party_mentions.py tests/test_discord_handlers.py tests/test_twitch_handlers.py -v 2>&1 | tail -20
```
Attendu : tous PASSED

- [ ] **Commit**

```bash
git add bot/discord/handlers.py bot/twitch/handlers.py tests/test_third_party_mentions.py
git commit -m "feat(handlers): detection mentions tierces, injection souvenirs, fuzzy match"
```

---

## Task 7: Régression globale + TODO

- [ ] **Lancer la suite complète**

```bash
cd /opt/stacks/wally-ai && python -m pytest --tb=short -q 2>&1 | tail -20
```
Attendu : tous PASSED, aucune régression

- [ ] **Cocher dans `TODO.md`**

```markdown
- [x] ajouter plus de details dans les couts (2026-03-29) — camembert par fonctionnalite, prix tokens, journal pages des appels
- [x] **Memoire de relation** — alias CRUD dashboard + detection mentions tierces + injection souvenirs + fuzzy match (2026-03-29)
```

- [ ] **Commit final**

```bash
git add TODO.md
git commit -m "docs(todo): cocher couts detailles et memoire de relation"
```
