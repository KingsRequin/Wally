# Admin Panel Redesign — Spec

## Objectif

Refonte complète du panel admin Wally : supprimer la partie publique intégrée, adopter un design dark mode sobre de style GitHub/Discord Dark, conserver l'intégralité des fonctionnalités admin.

## Contexte

Le panel actuel (`/admin` → `index.html`) mélange dashboard public (Status, Chat, Galerie, Info, Roadmap, Réseau) et admin (Params, Mémoire, Couts, Actions, Prompts, Système) dans un seul SPA avec un toggle mode. Le vrai dashboard public est déjà servi indépendamment par `public-ui/` sur `/`. Le code public dans `index.html` est donc du code mort côté admin.

Le style actuel utilise du glassmorphism (backdrop-filter, rgba transparences), un fond animé naker.io (particules + canvas blur), et des couleurs néon/cyan. La refonte passe à un design plat, sobre et standard.

## Fichiers impactés

| Fichier | Action |
|---------|--------|
| `bot/dashboard/static/index.html` | Nettoyer : supprimer nav publique, naker.io, mode toggle, tabs publiques |
| `bot/dashboard/static/style.css` | Refonte complète : palette GitHub Dark, layout admin-only |
| `bot/dashboard/static/app.js` | Supprimer fonctions publiques, mode toggle, graphes publics |
| `bot/dashboard/app.py` | Pas de changement fonctionnel (la route `/admin` sert toujours `index.html`) |

## Ce qui est supprimé

### Dans `index.html`
- `<div id="naker-bg">` + `<canvas id="naker-blurred">` + script naker.io
- Script de détection mobile (`is-mobile` body class)
- `<nav id="nav-public">` (Status, Chat, Galerie, Info, Roadmap, Réseau)
- `<div id="sidebar-divider">` 
- Bouton `sidebar-mode-toggle` (toggle public/admin)
- Lien "Retour" (mobile-back-btn) dans nav-admin
- Script `data-layout` / `data-tab-style` en bas de page
- Tabs publiques : `tab-status`, `tab-chat`, `tab-gallery`, `tab-journal-detail`, `tab-roadmap`, `tab-graph`
- Tabs orphelines/legacy : `tab-admin-config`, `tab-admin-logs`, `tab-memory`, `tab-global-memory`, `tab-admin-memory-dash`, `tab-admin-instances`, `tab-admin-twitch`, `tab-admin-overlay`

### Dans `app.js`
- Fonction `switchMode()` et variable `currentMode`
- Fonction `toggleMode()` + logique d'authentification liée au toggle
- Fonctions de rendu des tabs publiques : `renderStatusTab()`, `renderChatTab()`, `renderGalleryTab()`, `renderJournalTab()`, `renderRoadmapTab()`, `renderGraphTab()` (et similaires)
- Polling/SSE des données publiques (emotions graph public, stream info, uptime, messages count)
- Code de détection mobile/responsive lié au mode public
- Toute référence à `nav-public`, `sidebar-divider`, `sidebar-mode-toggle`

### Dans `style.css`
- Styles glassmorphism (`backdrop-filter`, `rgba(255,255,255,0.03)`)
- Styles naker-bg, naker-blurred
- Styles des tabs publiques
- Styles du mode toggle, sidebar-divider
- Couleurs néon/cyan de l'ancien thème

## Ce qui est conservé

### Fonctionnalité (inchangée)
- 6 onglets admin : Paramètres, Mémoire, Coûts, Actions, Prompts, Système
- Control bar : statut Discord/Twitch (dots + toggle), bouton Update, version badge, bouton Restart
- Modal d'authentification admin (Bearer token)
- Toast container
- Tailwind CSS via CDN
- Toute la logique JS de rendu des onglets admin
- Routes API `/api/admin/*`, `/api/actions/*`, `/api/setup/*`
- `public-ui/` servi sur `/` — aucune modification

### Restylé
- Sidebar : mêmes 6 items (icônes + texte), nouvelle palette
- Control bar : même contenu, nouveau style
- Cards admin : même structure, nouvelles couleurs/bordures
- Modal auth : même flow, nouveau style
- Inputs, selects, boutons : restylés dans la palette

## Design System — GitHub/Discord Dark

### Palette

```css
:root {
  --bg-canvas:    #0d1117;
  --bg-surface:   #161b22;
  --bg-overlay:   #1c2128;
  --border:       #30363d;
  --border-accent:#3d444d;
  --text-primary: #e6edf3;
  --text-secondary:#7d8590;
  --text-muted:   #484f58;
  --accent:       #58a6ff;
  --accent-hover: #79c0ff;
  --success:      #3fb950;
  --danger:       #f85149;
  --warning:      #d29e0b;
}
```

### Émotions (inchangées)
- anger: `#f85149`
- joy: `#d29e0b`
- curiosity: `#3fb950`
- sadness: `#58a6ff`
- boredom: `#a371f7`

### Layout
- Sidebar : 200px fixe à gauche, `background: var(--bg-surface)`, `border-right: 1px solid var(--border)`
- Zone principale : `background: var(--bg-canvas)`, padding 20-24px
- Cards : `background: var(--bg-surface)`, `border: 1px solid var(--border)`, `border-radius: 8px`
- Control bar : `background: var(--bg-surface)`, `border: 1px solid var(--border)`, `border-radius: 8px`

### Typographie
- Font : Inter (déjà chargée via Google Fonts)
- Tailles : labels 10-11px uppercase, body 13px, titres 15px
- Couleurs : labels `var(--text-secondary)`, body `var(--text-primary)`, muted `var(--text-muted)`

### Composants
- **Sidebar item actif** : `background: #1f2937`, `border-radius: 6px`, texte `var(--text-primary)`
- **Sidebar item inactif** : texte `var(--text-secondary)`, hover → `var(--bg-overlay)`
- **Boutons primaires** : `background: var(--accent)`, texte blanc, hover → `var(--accent-hover)`
- **Boutons danger** : `background: var(--danger)`, texte blanc
- **Inputs** : `background: var(--bg-canvas)`, `border: 1px solid var(--border)`, `color: var(--text-primary)`
- **Badges/pills** : `background: rgba(couleur, 0.15)`, `border: 1px solid rgba(couleur, 0.3)`, `border-radius: 12px`
- **Dot status** : `width: 8px`, `height: 8px`, `border-radius: 50%`, success/danger color

### Pas de
- `backdrop-filter` / `blur()`
- Ombres portées (sauf très subtiles `0 1px 3px rgba(0,0,0,0.3)` si besoin)
- Animations décoratives
- Gradients
- Néon / glow / text-shadow

## Route `/admin`

Aucun changement dans `app.py`. La route `/admin` continue de servir `index.html` avec cache-bust sur les assets. Le fichier `index.html` ne contient plus que du code admin.

## Hors périmètre

- Dashboard public (`public-ui/`) — aucune modification
- Overlay (`overlay.html`, `overlay_image.html`) — inchangé
- Setup wizard (`setup.html`) — inchangé
- Routes API backend — inchangées
- `theme.css` dynamique — conservé (le panel admin peut toujours charger un thème custom si configuré)
