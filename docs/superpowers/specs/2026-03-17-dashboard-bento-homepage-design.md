# Dashboard — Page d'accueil bento

**Date:** 2026-03-17
**Status:** Approved
**Scope:** `bot/dashboard/static/index.html`, `bot/dashboard/static/app.js`, `bot/dashboard/static/style.css`

---

## Contexte

Le dashboard public comporte actuellement 4 onglets séparés (STATUT, HUMEUR, STREAM, STATS). Le contenu de chaque onglet est peu dense — cela génère de la navigation inutile pour accéder à une information simple. L'objectif est de fusionner les 4 onglets en une seule page bento scrollable sous l'onglet STATUT, tout en ajoutant un onglet CHAT (désactivé, pour une future fonctionnalité).

---

## Décisions de design

### 1. Navigation publique

La barre d'onglets publique est réduite à 2 boutons :

| Bouton | État | Comportement |
|---|---|---|
| `📊 STATUT` | Actif | Affiche le bento |
| `💬 CHAT` | Désactivé | `pointer-events: none; opacity: 0.6` + badge `BIENTÔT` jaune |

Les boutons `😤 HUMEUR`, `🎮 STREAM`, `📈 STATS` sont **supprimés** de la nav.

Badge CHAT :
```html
<span class="badge-soon">BIENTÔT</span>
```
```css
.badge-soon {
  background: var(--card-yellow);
  border: 1.5px solid #111;
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 0.6rem;
  font-weight: 900;
}
```

### 2. Grille bento — CSS Grid 3 colonnes

```
┌──────────┬──────────────┬────────────┐
│  UPTIME  │  PLATEFORMES │  MESSAGES  │
├──────────┴──────────────┤            │
│        HUMEUR           │   STREAM   │
│  (col 1–2, large)       │  (col 3)   │
├─────────────────────────┴────────────┤
│         GRAPHE 24H (full width)      │
└──────────────────────────────────────┘
```

CSS :
```css
.bento-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 16px;
}
```

Placement des blocs :
- UPTIME : `grid-column: 1 / 2`
- PLATEFORMES : `grid-column: 2 / 3`
- MESSAGES : `grid-column: 3 / 4`
- HUMEUR : `grid-column: 1 / 3`
- STREAM : `grid-column: 3 / 4`
- GRAPHE : `grid-column: 1 / 4`

Sur mobile (`max-width: 600px`) : `grid-template-columns: 1fr` — tous les blocs passent en pleine largeur, les `grid-column` sont réinitialisés.

### 3. Contenu des blocs

| Bloc | Classe couleur | Contenu |
|---|---|---|
| UPTIME | `card-pink` | Uptime formaté (ex : "12h 34m") |
| PLATEFORMES | `card-teal` | Dot Discord + dot Twitch (online/offline) |
| MESSAGES | `card-mint` | Total messages traités + plateforme/heure dernière interaction |
| HUMEUR | `card-yellow` | 5 jauges animées (SSE) + phrase résumé dynamique |
| STREAM | `card-aqua` | Statut live/offline, titre, catégorie, viewers, lien |
| GRAPHE | `card` (blanc) | Canvas `emotionCanvas` — courbe 24h multi-émotions |

### 4. Suppression des anciens onglets publics

Les `tab-content` suivants sont **retirés du HTML** :
- `#tab-emotions`
- `#tab-stream`
- `#tab-stats`

Le JS correspondant est réorganisé :
- `loadStreamStatus()`, `loadStats()`, `startEmotionSSE()` sont appelés dans `showTab('status')` au lieu d'être liés à leurs onglets respectifs.
- `loadEmotionHistory()` (graphe 24h) est appelé dans `showTab('status')`.
- Les fonctions elles-mêmes ne changent pas — seul leur point d'appel change.

### 5. Onglet CHAT (placeholder)

```html
<button class="tab-btn disabled" data-tab="chat" title="Chat — bientôt disponible">
  💬 CHAT <span class="badge-soon">BIENTÔT</span>
</button>
```

```css
.tab-btn.disabled {
  pointer-events: none;
  opacity: 0.6;
  cursor: not-allowed;
}
```

Pas de `tab-content` associé pour l'instant.

---

## Fichiers modifiés

| Fichier | Changement |
|---|---|
| `index.html` | Réduire nav publique, remplacer les 4 tab-content par un seul `#tab-status` avec la grille bento |
| `app.js` | Déplacer les appels `loadStreamStatus`, `loadStats`, `loadEmotionHistory`, `startEmotionSSE` dans `showTab('status')` ; supprimer les branches `if (tabId === 'stream')`, `if (tabId === 'stats')`, `if (tabId === 'emotions')` |
| `style.css` | Ajouter `.bento-grid`, `.badge-soon`, responsive override mobile |

---

## Non-objectifs

- Pas de nouveau endpoint backend
- Pas de changement dans les routes SSE ou les routes de données
- Pas de modification du mode admin
- Pas de refonte du style des composants existants (cartes, jauges, canvas)

---

## Tests

- Vérifier que les 6 blocs s'affichent correctement à l'ouverture
- Vérifier que les jauges s'animent via SSE sans interaction utilisateur
- Vérifier que le graphe 24h se charge au chargement du tab STATUT
- Vérifier que le statut stream se charge au chargement
- Vérifier que l'onglet CHAT est visuellement désactivé (non cliquable)
- Vérifier le responsive mobile (grille 1 colonne)
- Vérifier que le mode admin est inchangé
