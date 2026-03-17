# Dashboard — Bento Homepage Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fusionner les 4 onglets publics (STATUT, HUMEUR, STREAM, STATS) en une seule page bento 3-colonnes, et ajouter un onglet CHAT désactivé.

**Architecture:** Changements purement frontend — 3 fichiers statiques. Aucun endpoint backend n'est modifié. Le CSS Grid gère le layout bento. Le JS réorganise les points d'appel des fonctions existantes sans les modifier.

**Tech Stack:** Vanilla JS, CSS Grid, HTML5. Fichiers : `bot/dashboard/static/index.html`, `app.js`, `style.css`.

---

## Fichiers modifiés

| Fichier | Rôle des changements |
|---|---|
| `bot/dashboard/static/style.css` | Ajout `.bento-grid` (grid 3 cols), `.badge-soon` (badge BIENTÔT), media query mobile |
| `bot/dashboard/static/index.html` | Réduire nav publique à 2 tabs, remplacer 4 tab-contents par 1 bento dans `#tab-status` |
| `bot/dashboard/static/app.js` | Déplacer `loadStreamStatus`+`loadEmotionHistory` dans `showTab('status')`, supprimer branche `loadStats()` |

---

## Task 1 : CSS — Ajouter `.bento-grid` et `.badge-soon`

**Fichier :** `bot/dashboard/static/style.css`

Ouvrir le fichier et localiser la ligne `.grid-2 { ... }` (ligne ~190). Ajouter juste après :

- [ ] **Step 1 : Ajouter `.bento-grid`, `.badge-soon`, et compléter `.tab-btn.disabled` dans style.css**

Insérer après la ligne `.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }` :

```css
.bento-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 16px;
}

.badge-soon {
  background: var(--card-yellow);
  border: 1.5px solid #111;
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 0.6rem;
  font-weight: 900;
  vertical-align: middle;
}
```

Le fichier contient déjà une règle `.tab-btn.disabled` incomplète. La localiser et s'assurer qu'elle contient **au minimum** `pointer-events: none` et `opacity: 0.6` (en plus de `cursor: not-allowed` déjà présent). Ajouter les propriétés manquantes :

```css
.tab-btn.disabled {
  pointer-events: none;
  opacity: 0.6;
  cursor: not-allowed;
}
```

- [ ] **Step 2 : Ajouter le responsive mobile pour `.bento-grid`**

Localiser le bloc `@media (max-width: 600px)` (il contient déjà `.grid-2, .grid-3 { grid-template-columns: 1fr; }`). Ajouter à l'intérieur de ce bloc :

```css
  .bento-grid {
    grid-template-columns: 1fr;
  }
  .bento-grid > * {
    grid-column: 1 / 2 !important;
  }
```

- [ ] **Step 3 : Commit**

```bash
git add bot/dashboard/static/style.css
git commit -m "style(dashboard): add bento-grid and badge-soon CSS classes"
```

---

## Task 2 : HTML — Remplacer la nav publique et le contenu des 4 onglets

**Fichier :** `bot/dashboard/static/index.html`

**Contexte :** Actuellement la nav publique a 4 boutons (STATUT, HUMEUR, STREAM, STATS) et il y a 4 `tab-content` correspondants. On remplace tout ça.

- [ ] **Step 1 : Remplacer les boutons de la nav publique**

Remplacer le bloc complet :
```html
<!-- Tab navigation — public -->
<nav class="tabs" id="tabs-public">
  <button class="tab-btn active" data-tab="status"   onclick="showTab('status')">📊 STATUT</button>
  <button class="tab-btn"        data-tab="emotions" onclick="showTab('emotions')">😤 HUMEUR</button>
  <button class="tab-btn"        data-tab="stream"   onclick="showTab('stream')">🎮 STREAM</button>
  <button class="tab-btn"        data-tab="stats"    onclick="showTab('stats')">📈 STATS</button>
</nav>
```

Par :
```html
<!-- Tab navigation — public -->
<nav class="tabs" id="tabs-public">
  <button class="tab-btn active" data-tab="status" onclick="showTab('status')">📊 STATUT</button>
  <button class="tab-btn disabled" data-tab="chat" title="Chat — bientôt disponible">💬 CHAT <span class="badge-soon">BIENTÔT</span></button>
</nav>
```

- [ ] **Step 2 : Remplacer le contenu de `#tab-status` et supprimer les 3 autres tab-contents**

⚠️ **Important :** Remplacer les 4 blocs `tab-content` (`#tab-status`, `#tab-emotions`, `#tab-stream`, `#tab-stats`) en **une seule opération atomique**. Ne pas les modifier séparément — `#stat-messages` est actuellement dans `#tab-stats` et sera déplacé dans le nouveau `#tab-status` ; avoir les deux en même temps créerait un ID dupliqué.

Remplacer le bloc de `<!-- ── STATUS ──` jusqu'à la fin de `<!-- ── STATS ──` (les 4 premiers `tab-content`) par ce bento unique :

```html
  <!-- ── BENTO HOMEPAGE ──────────────────────────────────────────────── -->
  <div class="tab-content active" id="tab-status">
    <div class="bento-grid">

      <!-- Ligne 1 : UPTIME | PLATEFORMES | MESSAGES -->
      <div class="card card-pink" style="grid-column: 1 / 2">
        <div class="card-title">UPTIME</div>
        <div class="card-value" id="uptime">—</div>
      </div>

      <div class="card card-teal" style="grid-column: 2 / 3">
        <div class="card-title">PLATEFORMES</div>
        <div style="margin-bottom:8px">
          <span class="status-dot offline" id="dot-discord"></span>
          <span id="lbl-discord">Discord</span>
        </div>
        <div>
          <span class="status-dot offline" id="dot-twitch"></span>
          <span id="lbl-twitch">Twitch</span>
        </div>
      </div>

      <div class="card card-mint" style="grid-column: 3 / 4">
        <div class="card-title">MESSAGES TRAITÉS</div>
        <div class="card-value" id="stat-messages">—</div>
        <div style="color:var(--text-muted);font-size:0.75rem;margin-top:6px">depuis le dernier démarrage</div>
      </div>

      <!-- Ligne 2 : HUMEUR (2 cols) | STREAM (1 col) -->
      <div class="card card-yellow" style="grid-column: 1 / 3">
        <div class="card-title">HUMEUR EN DIRECT</div>
        <div id="gauges-public"></div>
        <div class="emotion-summary" id="emotion-summary">—</div>
      </div>

      <div class="card card-aqua" style="grid-column: 3 / 4" id="stream-card">
        <div class="card-title">AZRAEL_TTV</div>
        <div id="stream-content">Chargement…</div>
      </div>

      <!-- Ligne 3 : GRAPHE 24H (pleine largeur) -->
      <div class="graph-container" style="grid-column: 1 / 4">
        <div class="card-title" style="padding:8px 8px 0">DERNIÈRES 24H</div>
        <canvas id="emotionCanvas" height="140"></canvas>
      </div>

    </div>
  </div>
```

- [ ] **Step 3 : Vérifier que le HTML est valide (balises bien fermées)**

Ouvrir `index.html` et confirmer que :
- La `<main>` contient maintenant : `#tab-status`, `#tab-admin-config`, `#tab-admin-emotions`, `#tab-admin-logs`, `#tab-memory`
- `#tab-emotions`, `#tab-stream`, `#tab-stats` ont bien disparu

- [ ] **Step 4 : Commit**

```bash
git add bot/dashboard/static/index.html
git commit -m "feat(dashboard): merge public tabs into bento homepage, add disabled CHAT tab"
```

---

## Task 3 : JS — Réorganiser les points d'appel dans `showTab`

**Fichier :** `bot/dashboard/static/app.js`

**Contexte :** La fonction `showTab` déclenche des chargements selon l'onglet actif. Il faut :
- Déplacer `loadStreamStatus` et `loadEmotionHistory` dans la branche `status`
- Supprimer les branches `stream`, `stats`, `emotions`
- Supprimer la fonction `loadStats()` (redondante avec `loadStatus()`)

- [ ] **Step 1 : Modifier le bloc de chargements dans `showTab`**

Localiser dans `showTab` (lignes ~70–82) le bloc :
```js
  // Chargements spécifiques par onglet
  if (tabId === 'stream')   loadStreamStatus();
  if (tabId === 'stats')    loadStats();
  if (tabId === 'emotions') loadEmotionHistory();
  if (tabId === 'memory' && !document.getElementById('mem-user-list')) renderMemoryTab();
  if (tabId === 'admin-logs') {
    requestAnimationFrame(() => {
      const el = document.getElementById('log-stream');
      if (el) el.scrollTop = el.scrollHeight;
    });
  }
```

Remplacer par :
```js
  // Chargements spécifiques par onglet
  if (tabId === 'status') {
    loadStreamStatus();
    requestAnimationFrame(() => loadEmotionHistory());
  }
  if (tabId === 'memory' && !document.getElementById('mem-user-list')) renderMemoryTab();
  if (tabId === 'admin-logs') {
    requestAnimationFrame(() => {
      const el = document.getElementById('log-stream');
      if (el) el.scrollTop = el.scrollHeight;
    });
  }
```

- [ ] **Step 2 : Supprimer la fonction `loadStats()`**

Localiser et supprimer le bloc complet (lignes ~156–162) :
```js
// ── Stats ─────────────────────────────────────────────────────────────────────

async function loadStats() {
  const r = await fetch('/api/public/status');
  if (!r.ok) return;
  const d = await r.json();
  document.getElementById('stat-messages').textContent = d.total_messages.toLocaleString();
}
```

Note : `loadStatus()` écrit déjà sur `#stat-messages` (ligne ~152) et est polled toutes les 30s — `loadStats` était un doublon.

- [ ] **Step 3 : Ajouter les appels initiaux dans `DOMContentLoaded`**

Le `DOMContentLoaded` ne calling pas `showTab('status')` directement. Sans ce correctif, `loadStreamStatus()` et `loadEmotionHistory()` ne s'exécuteraient qu'au premier clic sur STATUT — pas au chargement de la page.

Localiser dans `DOMContentLoaded` (lignes ~526–542) le bloc :
```js
  // Polling statut toutes les 30s
  setInterval(loadStatus, 30000);
```

Ajouter immédiatement après :
```js
  // Chargement initial du bento (stream + graphe)
  loadStreamStatus();
  requestAnimationFrame(() => loadEmotionHistory());
```

- [ ] **Step 4 : Commit**

```bash
git add bot/dashboard/static/app.js
git commit -m "refactor(dashboard): move stream/history loads to status tab, remove redundant loadStats"
```

---

## Task 4 : Vérification visuelle

Ces vérifications sont manuelles (frontend pur, pas de tests pytest applicables).

**Ouvrir le dashboard dans un navigateur** (`http://localhost:8080` ou l'URL configurée).

- [ ] **Step 1 : Vérifier le bento en mode public**
  - Les 6 blocs sont visibles sans scroll : UPTIME, PLATEFORMES, MESSAGES, HUMEUR, STREAM, GRAPHE
  - Les couleurs des cartes correspondent à la spec (rose, teal, mint, jaune, aqua, blanc)
  - Le graphe 24h se charge immédiatement (pas besoin de cliquer sur un onglet)

- [ ] **Step 2 : Vérifier la nav publique**
  - Seuls 2 boutons : `📊 STATUT` (actif) et `💬 CHAT` avec badge jaune `BIENTÔT`
  - Cliquer sur CHAT ne fait rien (curseur `not-allowed`)
  - Les anciens onglets HUMEUR, STREAM, STATS ont disparu

- [ ] **Step 3 : Vérifier les jauges SSE**
  - Les jauges d'émotions s'animent automatiquement via SSE sans interaction
  - La phrase résumé ("Wally est joyeux…") se met à jour avec les données SSE

- [ ] **Step 4 : Vérifier le mode admin inchangé**
  - Basculer en mode ADMIN → les 7 onglets admin sont présents et fonctionnels
  - CONFIG, HUMEUR, LOGS, MÉMOIRE fonctionnent normalement

- [ ] **Step 5 : Vérifier le responsive mobile**
  - Réduire la fenêtre à moins de 600px → les 6 blocs passent en colonne unique
  - Aucun débordement horizontal

- [ ] **Step 6 : Commit final si tout est bon**

```bash
git add .
git commit -m "chore: verify bento homepage — all checks passed"
```

---

## Résumé des commits attendus

1. `style(dashboard): add bento-grid and badge-soon CSS classes`
2. `feat(dashboard): merge public tabs into bento homepage, add disabled CHAT tab`
3. `refactor(dashboard): move stream/history loads to status tab, remove redundant loadStats`
4. `chore: verify bento homepage — all checks passed` *(si step 4 produit des corrections)*
