# Spec — Système de theming par instance

**Date:** 2026-03-30
**Statut:** Approuvé

## Objectif

Permettre à chaque instance Wally d'avoir sa propre direction artistique (couleurs, style de navigation, disposition des onglets) sans modifier le code ni l'image Docker. L'infrastructure est posée maintenant ; les thèmes visuels réels seront créés plus tard.

---

## Approche retenue

**CSS variables dynamiques + classes de layout** — un endpoint FastAPI `GET /static/theme.css` génère les overrides CSS depuis `config.yaml`. Le layout variant est appliqué via un attribut `data-layout` sur `<body>` posé par un petit bloc JS au chargement.

Avantages : zéro changement Docker/volumes, modifiable live depuis le dashboard sans restart, extensible progressivement.

---

## 1. Modèle de données — `ThemeConfig`

Nouveau dataclass dans `bot/config.py`, intégré dans `Config` :

```python
@dataclass
class ThemeConfig:
    accent_color: str = "#06b6d4"
    bg_color: str = "#11151c"
    surface_color: str = "rgba(255,255,255,0.03)"
    sidebar_bg: str = "rgba(255,255,255,0.02)"
    layout_variant: str = "sidebar-left"   # sidebar-left | sidebar-top | sidebar-mini
    tab_style: str = "icons-only"          # icons-only | icons-labels | text-only
```

`Config.load()` lit le bloc `theme:` de `config.yaml` si présent, sinon utilise les défauts. Aucune migration requise pour les instances existantes.

`config.theme` est exposé comme attribut de `Config`. `config.save()` sérialise le bloc `theme:` dans `config.yaml`.

---

## 2. Endpoint dynamique `GET /static/theme.css`

Route FastAPI enregistrée **avant** le mount `StaticFiles` (priorité de routing FastAPI). Fichier : `bot/dashboard/routes/theme.py` (ou ajout dans `admin.py`).

Génère du CSS à partir de `config.theme` :

```css
:root {
  --accent: <accent_color>;
  --accent-soft: <accent_color à 12% alpha>;
  --bg-body: <bg_color>;
  --bg-surface: <surface_color>;
  --bg-sidebar: <sidebar_bg>;
  --layout-variant: "sidebar-left";
  --tab-style: "icons-only";
}
```

`--accent-soft` est calculé automatiquement depuis `accent_color` (parse hex → rgba avec alpha 0.12). Headers : `Content-Type: text/css`, `Cache-Control: no-store`.

---

## 3. Intégration dans `index.html`

Deux modifications :

**a) Second stylesheet** (après `style.css`) :
```html
<link rel="stylesheet" href="/static/theme.css" id="theme-link">
```

**b) Bloc JS au chargement** — lit la variable CSS et pose l'attribut sur `<body>` :
```js
const layout = getComputedStyle(document.documentElement)
  .getPropertyValue('--layout-variant').trim().replace(/"/g, '');
document.body.setAttribute('data-layout', layout || 'sidebar-left');
```

---

## 4. `style.css` — hooks pour la DA

Ajout de blocs vides à la fin de `style.css` pour chaque layout variant. Ils seront remplis lors de la DA :

```css
/* ── Layout: sidebar-top ──────────────────────────────────────── */
[data-layout="sidebar-top"] .sidebar { /* à implémenter */ }
[data-layout="sidebar-top"] .app-wrapper { /* à implémenter */ }

/* ── Layout: sidebar-mini ────────────────────────────────────── */
[data-layout="sidebar-mini"] .sidebar { /* à implémenter */ }

/* ── Tab style: icons-labels ─────────────────────────────────── */
[data-tab-style="icons-labels"] .nav-label { /* à implémenter */ }
```

Note : `tab_style` est également passé via une variable CSS `--tab-style` et posé en `data-tab-style` sur `<body>` par le même bloc JS.

---

## 5. Routes API thème

Deux routes dans `bot/dashboard/routes/admin.py` (ou `theme.py`) :

### `GET /api/admin/theme`
Retourne le thème courant depuis `config.theme` :
```json
{
  "accent_color": "#06b6d4",
  "bg_color": "#11151c",
  "surface_color": "rgba(255,255,255,0.03)",
  "sidebar_bg": "rgba(255,255,255,0.02)",
  "layout_variant": "sidebar-left",
  "tab_style": "icons-only"
}
```

### `POST /api/admin/theme`
Reçoit un body JSON partiel ou complet, valide les couleurs (regex hex ou rgba), met à jour `config.theme`, appelle `config.save()`. Retourne le thème mis à jour.

Validation : `accent_color`, `bg_color`, `surface_color`, `sidebar_bg` doivent être hex (`#rrggbb`) ou rgba valides. `layout_variant` et `tab_style` doivent être dans les valeurs connues.

---

## 6. Éditeur de thème — sous-onglet "Apparence"

Nouvel onglet **Apparence** dans la section **Paramètres** du dashboard (après Émotions · LLM · Images).

Contenu :

- **Couleurs** : 4 color pickers natifs (`<input type="color">`) + champ texte hex à côté pour `accent_color`, `bg_color`, `surface_color`, `sidebar_bg`
- **Layout** : 3 radio buttons (`sidebar-left` / `sidebar-top` / `sidebar-mini`) avec badge "à venir" sur les 2 derniers pour l'instant
- **Style onglets** : 3 radio buttons (`icons-only` / `icons-labels` / `text-only`) avec badge "à venir" sur les 2 derniers
- **Preview live** : à chaque changement de couleur, rechargement du `<link id="theme-link">` avec `?v=<timestamp>` en cache-busting — aucun rechargement de page
- **Bouton Enregistrer** : `POST /api/admin/theme` + feedback toast

---

## 7. Provisioner

`_write_config_yaml()` dans `bot/core/provisioner.py` ajoute le bloc `theme:` avec les valeurs par défaut dans le yaml généré pour chaque nouvelle instance.

Le setup wizard ne change pas — la DA se configure depuis le dashboard de l'instance après provisioning.

---

## Non-inclus dans ce spec

- Les thèmes visuels réels (palettes, gradients, styles) — travail de DA séparé
- Le step "Apparence" dans le wizard de setup
- Import/export de thème entre instances
- Thèmes prédéfinis (presets)

---

## Fichiers impactés

| Fichier | Changement |
|---|---|
| `bot/config.py` | Ajout `ThemeConfig`, intégration dans `Config` |
| `bot/core/provisioner.py` | Bloc `theme:` dans `_write_config_yaml()` |
| `bot/dashboard/routes/admin.py` | Routes `GET/POST /api/admin/theme` + endpoint `GET /static/theme.css` |
| `bot/dashboard/app.py` | Enregistrement de la route theme.css avant StaticFiles |
| `bot/dashboard/static/index.html` | Ajout `<link>` theme.css + bloc JS data-layout |
| `bot/dashboard/static/style.css` | Blocs hooks layout variants (vides) |
