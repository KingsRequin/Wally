# Dashboard — Graphique émotions : fenêtre glissante 24h, sélecteur de période, stats moyennes, fix emoji

**Date :** 2026-03-18
**Statut :** Approuvé

---

## Contexte

Le graphique d'émotions du dashboard affiche actuellement les données depuis minuit jusqu'à maintenant (jour calendaire), au lieu des 24 dernières heures glissantes. De plus, certains emojis dans les barres d'humeur en direct se placent au-dessus du texte (overflow de la largeur fixe du label), causant un espacement vertical irrégulier.

On en profite pour ajouter un sélecteur de période (24h / 7 jours / 30 jours) et des statistiques de moyenne par émotion sur la période sélectionnée.

---

## Changements

### 1. Bug — Fenêtre temporelle du graphique (backend)

**Fichier :** `bot/db/database.py`

`get_today_emotion_snapshots()` calcule `midnight` comme borne inférieure. Remplacer par une fenêtre glissante de 24h (`time.time() - 86400`).

- Renommer la méthode en `get_emotion_snapshots_since(since: float) -> list[dict]`
- `since` est un timestamp Unix ; la requête reste `WHERE snapshot_at >= ? ORDER BY snapshot_at ASC`
- Vérifier que `get_today_emotion_snapshots` n'est appelée nulle part ailleurs (journal, cron, etc.) et mettre à jour tous les call-sites en même temps

**Rétention :** `cleanup_old_emotion_history()` supprime actuellement les données de plus de 7 jours. Passer `days=30` dans l'appel existant afin que le bouton 30J puisse afficher des données réelles.

**Fichier :** `bot/dashboard/routes/emotions.py`

L'endpoint `GET /api/public/emotions/history` accepte un query param optionnel `since: float` (timestamp Unix). Valeur par défaut : `time.time() - 86400` (24h glissantes). Le paramètre est cappé côté serveur à 30 jours maximum (`max(since, time.time() - 30 * 86400)`) pour éviter de retourner la table entière si `since=0` ou une valeur très ancienne. `max` garantit qu'on ne remonte jamais au-delà de 30 jours en arrière.

```
GET /api/public/emotions/history           → 24h glissantes
GET /api/public/emotions/history?since=X   → depuis timestamp X (cap 30j)
```

### 2. Feature — Sélecteur de période (frontend)

**Fichier :** `bot/dashboard/static/app.js`

- Variable d'état `let currentGraphSince = null` (null = 24h glissantes par défaut)
- `loadEmotionHistory(since?)` passe `?since=<ts>` si fourni
- 3 boutons dans le header de la carte graphique : **24H**, **7J**, **30J**
  - Actif = classe `graph-range-btn active`
  - Inactif = classe `graph-range-btn`
- Le titre `<span id="graph-title">` se met à jour dynamiquement :
  - 24H → `📈 DERNIÈRES 24H`
  - 7J → `📈 7 DERNIERS JOURS`
  - 30J → `📈 30 DERNIERS JOURS`
- Les event listeners du tooltip (`mousemove`) restent inchangés : ils lisent `_graphMeta` qui est mis à jour à chaque appel de `drawEmotionGraph`, donc compatibles avec les changements de période sans réinitialisation.

**Fichier :** `bot/dashboard/static/index.html`

Remplacer le `<div class="card-title" style="padding:8px 8px 0">📈 DERNIÈRES 24H</div>` par :

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

**CSS à ajouter dans `style.css` :**

```css
.graph-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 8px 0;
}
.graph-range-btns { display: flex; gap: 4px; }
.graph-range-btn {
  background: transparent;
  color: var(--text-muted);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 0.7rem;
  font-weight: 700;
  cursor: pointer;
}
.graph-range-btn.active {
  background: var(--accent);
  color: #000;
  border-color: var(--accent);
}
```

### 3. Feature — Statistiques de moyenne (frontend)

**Fichier :** `bot/dashboard/static/app.js`

Après `drawEmotionGraph(history)`, calculer la moyenne de chaque émotion sur tous les snapshots de `history` et afficher une ligne compacte sous le canvas.

Format : `😤 0.23  😊 0.61  😢 0.15  🤔 0.44  😴 0.30` — chaque valeur colorée avec `EMOTION_COLORS[e]`.

Ajouter dans `index.html`, après le `<canvas id="emotionCanvas">` et dans le même `.graph-container` :

```html
<div id="emotion-averages" style="display:none"></div>
```

- `renderEmotionAverages(history)` injecte son contenu et passe `display` à `flex`
- `renderEmotionAverages(history)` calcule et injecte le contenu
- Masqué si `history.length < 2` (aligné sur le guard de `drawEmotionGraph` qui retourne early si `< 2`)
- Recalculé à chaque changement de période via `setGraphRange()`

### 4. Bug — Alignement emoji dans les barres d'humeur (CSS)

**Fichier :** `bot/dashboard/static/style.css`

`.emotion-label` a `width: 80px` sans `white-space: nowrap`. Pour CURIOSITY (le label le plus long), l'emoji déborde sur une seconde ligne, causant une hauteur variable sur les `.emotion-row`.

Fix :
```css
.emotion-label {
  width: 100px;          /* était 80px */
  white-space: nowrap;   /* ajout */
  /* autres propriétés inchangées */
}
```

---

## Architecture

Aucun nouveau fichier. Aucune nouvelle table. Les changements sont localisés dans :

| Fichier | Type |
|---|---|
| `bot/db/database.py` | Bug fix + signature méthode |
| `bot/dashboard/routes/emotions.py` | Query param optionnel |
| `bot/dashboard/static/index.html` | Structure HTML carte graphique |
| `bot/dashboard/static/app.js` | Sélecteur période + moyennes |
| `bot/dashboard/static/style.css` | Fix width + white-space |

---

## Comportement attendu

- À l'ouverture du dashboard, le graphique affiche les 24 dernières heures glissantes (ex : 14h à 14h le lendemain)
- Les boutons 24H / 7J / 30J rechargent les données et mettent à jour le titre + les moyennes
- Les barres d'humeur en direct ont toutes la même hauteur de ligne quel que soit l'emoji

---

## Hors scope

- Persistance de la période sélectionnée entre sessions (pas de localStorage pour ce choix)
- Zoom interactif sur le graphique
- Export des données
