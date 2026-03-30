# Instance Theming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre à chaque instance Wally d'avoir sa propre DA (couleurs, layout, style onglets) via CSS variables dynamiques pilotées par config.yaml.

**Architecture:** Un endpoint FastAPI `GET /static/theme.css` génère les overrides CSS depuis `config.theme`. Le layout variant est appliqué via `data-layout` sur `<body>` posé par un bloc JS au chargement. Un sous-onglet "Apparence" dans le dashboard admin permet l'édition live avec preview instantanée.

**Tech Stack:** Python dataclasses, FastAPI, CSS custom properties, vanilla JS

---

### Task 1: ThemeConfig dataclass + intégration Config

**Files:**
- Modify: `bot/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Écrire le test qui échoue**

Dans `tests/test_config.py`, ajouter en bas du fichier :

```python
def test_theme_config_defaults():
    """ThemeConfig a des valeurs par défaut sensées."""
    from bot.config import ThemeConfig
    t = ThemeConfig()
    assert t.accent_color == "#06b6d4"
    assert t.bg_color == "#11151c"
    assert t.layout_variant == "sidebar-left"
    assert t.tab_style == "icons-only"


def test_load_config_theme_defaults(tmp_path):
    """Config.load() crée un ThemeConfig par défaut si absent du YAML."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(MINIMAL_CONFIG))
    config = Config.load(str(cfg_file))
    assert config.theme.accent_color == "#06b6d4"
    assert config.theme.layout_variant == "sidebar-left"


def test_load_config_theme_from_yaml(tmp_path):
    """Config.load() lit le bloc theme: du YAML."""
    data = dict(MINIMAL_CONFIG)
    data["theme"] = {"accent_color": "#ff6b6b", "layout_variant": "sidebar-top"}
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(data))
    config = Config.load(str(cfg_file))
    assert config.theme.accent_color == "#ff6b6b"
    assert config.theme.layout_variant == "sidebar-top"
    assert config.theme.bg_color == "#11151c"  # défaut conservé


def test_save_config_includes_theme(tmp_path):
    """Config.save() sérialise le bloc theme: dans le YAML."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(MINIMAL_CONFIG))
    config = Config.load(str(cfg_file))
    config.theme.accent_color = "#abc123"
    config.save()
    saved = yaml.safe_load(cfg_file.read_text())
    assert saved["theme"]["accent_color"] == "#abc123"
```

- [ ] **Step 2: Vérifier que les tests échouent**

```bash
pytest tests/test_config.py::test_theme_config_defaults tests/test_config.py::test_load_config_theme_defaults -v
```
Attendu : `ImportError: cannot import name 'ThemeConfig'`

- [ ] **Step 3: Ajouter ThemeConfig dans `bot/config.py`**

Après le bloc `@dataclass class OverlayImageConfig:` (vers ligne 224), ajouter :

```python
VALID_LAYOUT_VARIANTS = ("sidebar-left", "sidebar-top", "sidebar-mini")
VALID_TAB_STYLES = ("icons-only", "icons-labels", "text-only")


@dataclass
class ThemeConfig:
    accent_color: str = "#06b6d4"
    bg_color: str = "#11151c"
    surface_color: str = "rgba(255,255,255,0.03)"
    sidebar_bg: str = "rgba(255,255,255,0.02)"
    layout_variant: str = "sidebar-left"
    tab_style: str = "icons-only"
```

- [ ] **Step 4: Ajouter le champ `theme` dans le dataclass `Config`**

Dans la classe `Config`, après `overlay_image: OverlayImageConfig = field(default_factory=OverlayImageConfig)`, ajouter :

```python
    theme: ThemeConfig = field(default_factory=ThemeConfig)
```

- [ ] **Step 5: Mettre à jour `Config.load()`**

Dans la méthode `load()`, dans le bloc `instance = cls(...)`, ajouter `theme=ThemeConfig(**raw.get("theme", {}))` :

```python
            instance = cls(
                bot=BotConfig(**raw["bot"]),
                openai=openai_config,
                llm=llm_config,
                discord=DiscordConfig(**discord_raw, spam_detection=SpamDetectionConfig(**spam_raw)),
                twitch=TwitchConfig(**twitch_raw),
                emotions=emotions,
                # ... tous les champs existants ...
                theme=ThemeConfig(**raw.get("theme", {})),
            )
```

- [ ] **Step 6: Mettre à jour `Config.save()`**

Dans la méthode `save()`, dans le dict `data`, ajouter après `"overlay_image"` :

```python
            "theme": asdict(self.theme),
```

- [ ] **Step 7: Vérifier que les tests passent**

```bash
pytest tests/test_config.py -v
```
Attendu : tous les tests verts, dont les 4 nouveaux.

- [ ] **Step 8: Commit**

```bash
git add bot/config.py tests/test_config.py
git commit -m "feat(theme): ThemeConfig dataclass + intégration Config"
```

---

### Task 2: Endpoint `/static/theme.css` dynamique

**Files:**
- Create: `bot/dashboard/routes/theme.py`
- Modify: `bot/dashboard/app.py`
- Test: `tests/test_dashboard_theme.py` (nouveau)

- [ ] **Step 1: Créer le fichier de test**

Créer `tests/test_dashboard_theme.py` :

```python
"""Tests des routes de theming dashboard."""
import pytest
from unittest.mock import MagicMock
from httpx import AsyncClient, ASGITransport

from bot.dashboard.app import create_dashboard_app
from bot.dashboard.state import AppState
from bot.config import ThemeConfig


def _make_state_with_theme(accent="#06b6d4", layout="sidebar-left"):
    """AppState minimal avec ThemeConfig réel."""
    from tests.test_dashboard_routes import _make_state
    state = _make_state()
    state.config.theme = ThemeConfig(accent_color=accent, layout_variant=layout)
    return state


@pytest.fixture
def app():
    return create_dashboard_app(_make_state_with_theme())


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_theme_css_returns_200(client):
    r = await client.get("/static/theme.css")
    assert r.status_code == 200


async def test_theme_css_content_type(client):
    r = await client.get("/static/theme.css")
    assert "text/css" in r.headers["content-type"]


async def test_theme_css_contains_accent(client):
    r = await client.get("/static/theme.css")
    assert "--accent: #06b6d4" in r.text


async def test_theme_css_contains_layout_variant(client):
    r = await client.get("/static/theme.css")
    assert '--layout-variant: "sidebar-left"' in r.text


async def test_theme_css_contains_accent_soft(client):
    r = await client.get("/static/theme.css")
    assert "--accent-soft: rgba(6, 182, 212, 0.12)" in r.text


async def test_theme_css_no_cache(client):
    r = await client.get("/static/theme.css")
    assert "no-store" in r.headers.get("cache-control", "")


async def test_theme_css_custom_accent():
    """Accent personnalisé génère la bonne couleur."""
    app = create_dashboard_app(_make_state_with_theme(accent="#ff6b6b"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/static/theme.css")
    assert "--accent: #ff6b6b" in r.text
    assert "--accent-soft: rgba(255, 107, 107, 0.12)" in r.text
```

- [ ] **Step 2: Vérifier que les tests échouent**

```bash
pytest tests/test_dashboard_theme.py -v
```
Attendu : `ImportError` ou `404` — le fichier route n'existe pas encore.

- [ ] **Step 3: Créer `bot/dashboard/routes/theme.py`**

```python
# bot/dashboard/routes/theme.py
"""Routes de theming : CSS dynamique + API admin."""
from __future__ import annotations

import re
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from bot.config import ThemeConfig, VALID_LAYOUT_VARIANTS, VALID_TAB_STYLES

# Router pour l'API admin /api/admin/theme
router = APIRouter()

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_RGBA_RE = re.compile(r"^rgba?\([\d\s,./]+\)$")


def _hex_to_rgba_soft(hex_color: str, alpha: float = 0.12) -> str:
    """Convertit #rrggbb → rgba(r, g, b, alpha). Retourne le défaut cyan si invalide."""
    try:
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r}, {g}, {b}, {alpha})"
    except Exception:
        return f"rgba(6, 182, 212, {alpha})"


def _is_valid_color(value: str) -> bool:
    return bool(_HEX_RE.match(value) or _RGBA_RE.match(value))


def generate_theme_css(theme: ThemeConfig) -> str:
    """Génère le contenu CSS des variables de thème."""
    accent_soft = _hex_to_rgba_soft(theme.accent_color)
    return f""":root {{
  --accent: {theme.accent_color};
  --accent-soft: {accent_soft};
  --bg-body: {theme.bg_color};
  --bg-surface: {theme.surface_color};
  --bg-sidebar: {theme.sidebar_bg};
  --layout-variant: "{theme.layout_variant}";
  --tab-style: "{theme.tab_style}";
}}
"""


async def serve_theme_css(request: Request) -> Response:
    """Endpoint GET /static/theme.css — CSS dynamique depuis config.theme."""
    theme = request.app.state.wally.config.theme
    css = generate_theme_css(theme)
    return Response(
        content=css,
        media_type="text/css",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "CDN-Cache-Control": "no-store",
        },
    )


@router.get("/theme")
async def get_theme(request: Request) -> dict:
    """Retourne la config de thème courante."""
    return asdict(request.app.state.wally.config.theme)


@router.post("/theme")
async def update_theme(request: Request, body: dict) -> dict:
    """Met à jour la config de thème et sauvegarde."""
    cfg = request.app.state.wally.config
    theme = cfg.theme
    color_fields = {"accent_color", "bg_color", "surface_color", "sidebar_bg"}
    for field, value in body.items():
        if field in color_fields:
            if not _is_valid_color(str(value)):
                raise HTTPException(status_code=400, detail=f"{field}: couleur invalide (hex #rrggbb ou rgba(...))")
            setattr(theme, field, value)
        elif field == "layout_variant":
            if value not in VALID_LAYOUT_VARIANTS:
                raise HTTPException(status_code=400, detail=f"layout_variant invalide: {value}")
            theme.layout_variant = value
        elif field == "tab_style":
            if value not in VALID_TAB_STYLES:
                raise HTTPException(status_code=400, detail=f"tab_style invalide: {value}")
            theme.tab_style = value
    cfg.save()
    return asdict(theme)
```

- [ ] **Step 4: Enregistrer les routes dans `bot/dashboard/app.py`**

Dans `create_dashboard_app()`, ajouter l'import et les enregistrements. Localiser la ligne :
```python
from bot.dashboard.routes import status, emotions, admin, sse, twitch, memory, links, costs, roadmap, chat_auth, chat, gallery, actions, setup, twitch_auth
```
Et la remplacer par :
```python
from bot.dashboard.routes import status, emotions, admin, sse, twitch, memory, links, costs, roadmap, chat_auth, chat, gallery, actions, setup, twitch_auth, theme
```

Ensuite, **avant** la ligne `app.mount("/static", NoCacheStaticFiles(...))`, ajouter :
```python
    # Theme CSS dynamique — enregistré AVANT le mount static pour priorité de routing
    app.add_api_route("/static/theme.css", theme.serve_theme_css, methods=["GET"], include_in_schema=False)
    app.include_router(theme.router, prefix="/api/admin")
```

- [ ] **Step 5: Vérifier que les tests passent**

```bash
pytest tests/test_dashboard_theme.py -v
```
Attendu : 7 tests verts.

- [ ] **Step 6: Commit**

```bash
git add bot/dashboard/routes/theme.py bot/dashboard/app.py tests/test_dashboard_theme.py
git commit -m "feat(theme): endpoint /static/theme.css dynamique + routes GET/POST /api/admin/theme"
```

---

### Task 3: Tests des routes API theme

**Files:**
- Modify: `tests/test_dashboard_theme.py`

- [ ] **Step 1: Ajouter les tests API dans `tests/test_dashboard_theme.py`**

Ajouter à la fin du fichier :

```python
async def test_get_theme_returns_all_fields(client):
    r = await client.get("/api/admin/theme", headers={"Authorization": "Bearer testtoken"})
    assert r.status_code == 200
    data = r.json()
    assert "accent_color" in data
    assert "bg_color" in data
    assert "layout_variant" in data
    assert "tab_style" in data
    assert "surface_color" in data
    assert "sidebar_bg" in data


async def test_post_theme_updates_accent(client):
    r = await client.post(
        "/api/admin/theme",
        json={"accent_color": "#ff6b6b"},
        headers={"Authorization": "Bearer testtoken"},
    )
    assert r.status_code == 200
    assert r.json()["accent_color"] == "#ff6b6b"


async def test_post_theme_rejects_invalid_color(client):
    r = await client.post(
        "/api/admin/theme",
        json={"accent_color": "notacolor"},
        headers={"Authorization": "Bearer testtoken"},
    )
    assert r.status_code == 400


async def test_post_theme_rejects_invalid_layout(client):
    r = await client.post(
        "/api/admin/theme",
        json={"layout_variant": "top-bar"},
        headers={"Authorization": "Bearer testtoken"},
    )
    assert r.status_code == 400


async def test_post_theme_calls_config_save(client):
    state = _make_state_with_theme()
    state.config.save = MagicMock()
    app = create_dashboard_app(state)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post(
            "/api/admin/theme",
            json={"accent_color": "#aabbcc"},
            headers={"Authorization": "Bearer testtoken"},
        )
    state.config.save.assert_called_once()
```

- [ ] **Step 2: Vérifier que les tests passent**

```bash
pytest tests/test_dashboard_theme.py -v
```
Attendu : 12 tests verts (7 existants + 5 nouveaux).

- [ ] **Step 3: Commit**

```bash
git add tests/test_dashboard_theme.py
git commit -m "test(theme): tests routes API GET/POST /api/admin/theme"
```

---

### Task 4: `index.html` — chargement theme.css + JS data-layout

**Files:**
- Modify: `bot/dashboard/static/index.html`
- Modify: `bot/dashboard/app.py`

- [ ] **Step 1: Ajouter le `<link>` theme.css dans `index.html`**

Dans `bot/dashboard/static/index.html`, localiser la ligne qui charge `style.css` :
```html
<link rel="stylesheet" href="/static/style.css?v=4">
```
Ajouter **immédiatement après** :
```html
<link rel="stylesheet" href="/static/theme.css" id="theme-link">
```

- [ ] **Step 2: Ajouter le bloc JS de layout dans `index.html`**

Dans `index.html`, juste avant la fermeture `</head>` (ou après les autres `<link>`), ajouter :
```html
<script>
  // Applique les variants de layout et tab-style depuis les CSS vars du thème
  (function() {
    var style = getComputedStyle(document.documentElement);
    var layout = style.getPropertyValue('--layout-variant').trim().replace(/"/g, '') || 'sidebar-left';
    var tabStyle = style.getPropertyValue('--tab-style').trim().replace(/"/g, '') || 'icons-only';
    document.body.setAttribute('data-layout', layout);
    document.body.setAttribute('data-tab-style', tabStyle);
  })();
</script>
```

Ce script doit être exécuté **après** le chargement des stylesheets. Le placer juste avant `</body>` si `</head>` est trop tôt pour que le DOM soit prêt, ou dans le bloc `DOMContentLoaded` existant.

- [ ] **Step 3: Mettre à jour le cache-busting dans `app.py`**

Dans la fonction `root()` de `app.py`, localiser :
```python
html = html.replace("style.css?v=4", f"style.css?v={_asset_version}")
html = html.replace("app.js?v=4", f"app.js?v={_asset_version}")
```
Ajouter après ces deux lignes :
```python
html = html.replace('href="/static/theme.css"', f'href="/static/theme.css?v={_asset_version}"')
```

- [ ] **Step 4: Vérifier manuellement**

Ouvrir le dashboard dans un navigateur. Dans DevTools (Réseau), vérifier que `/static/theme.css` se charge avec statut 200 et contient les variables CSS. Dans la console JS, vérifier que `document.body.getAttribute('data-layout')` retourne `"sidebar-left"`.

- [ ] **Step 5: Commit**

```bash
git add bot/dashboard/static/index.html bot/dashboard/app.py
git commit -m "feat(theme): index.html charge theme.css + JS applique data-layout"
```

---

### Task 5: `style.css` — variables CSS overridables + hooks layout

**Files:**
- Modify: `bot/dashboard/static/style.css`

- [ ] **Step 1: Ajouter les variables de thème dans `:root`**

Dans `style.css`, dans le bloc `:root` existant (ligne 3), ajouter après les variables d'émotion existantes :

```css
  /* Thème — overridés par /static/theme.css */
  --accent: #06b6d4;
  --accent-soft: rgba(6, 182, 212, 0.12);
  --bg-body: #11151c;
  --bg-surface: rgba(255, 255, 255, 0.03);
  --bg-sidebar: rgba(255, 255, 255, 0.02);
  --layout-variant: "sidebar-left";
  --tab-style: "icons-only";
```

Note: ces valeurs dans `:root` servent de fallback si `theme.css` ne se charge pas. `theme.css` override ces mêmes variables.

- [ ] **Step 2: Remplacer les couleurs hardcodées dans `body`**

Localiser dans `style.css` :
```css
body {
  background: #11151c;
```
Remplacer par :
```css
body {
  background: var(--bg-body);
```

- [ ] **Step 3: Remplacer la couleur de fond du sidebar**

Localiser la règle `.sidebar { ... }` et remplacer la valeur de background hardcodée par `var(--bg-sidebar)`.

- [ ] **Step 4: Remplacer les surfaces de cards/panels**

Chercher toutes les occurrences de `rgba(255, 255, 255, 0.03)` utilisées comme background de cards, panels, et les remplacer par `var(--bg-surface)`. Faire de même pour `rgba(255, 255, 255, 0.02)` utilisés dans le sidebar.

```bash
grep -n "rgba(255, 255, 255, 0.0[23])" bot/dashboard/static/style.css
```
Remplacer les occurrences pertinentes (background/background-color) par `var(--bg-surface)` ou `var(--bg-sidebar)` selon le contexte.

- [ ] **Step 5: Ajouter les hooks de layout (blocs vides) en fin de fichier**

Ajouter à la toute fin de `style.css` :

```css
/* ═══════════════════════════════════════════════════════════════
   Layout Variants — remplis lors de la DA par instance
   ════════════════════════════════════════════════════════════════ */

/* ── sidebar-top : navigation horizontale en haut ────────────── */
[data-layout="sidebar-top"] .app-wrapper { /* TODO: DA */ }
[data-layout="sidebar-top"] .sidebar { /* TODO: DA */ }
[data-layout="sidebar-top"] .main-content { /* TODO: DA */ }

/* ── sidebar-mini : sidebar icônes uniquement, plus étroite ──── */
[data-layout="sidebar-mini"] .sidebar { /* TODO: DA */ }
[data-layout="sidebar-mini"] .sidebar .nav-label { /* TODO: DA */ }

/* ═══════════════════════════════════════════════════════════════
   Tab Style Variants
   ════════════════════════════════════════════════════════════════ */

/* ── icons-labels : icône + texte ────────────────────────────── */
[data-tab-style="icons-labels"] .nav-label { /* TODO: DA */ }

/* ── text-only : texte sans icône ────────────────────────────── */
[data-tab-style="text-only"] .nav-icon { /* TODO: DA */ }
[data-tab-style="text-only"] .nav-label { /* TODO: DA */ }
```

- [ ] **Step 6: Vérifier que le dashboard s'affiche correctement**

Ouvrir le dashboard. L'apparence doit être identique à avant (les variables de fallback dans `:root` sont les mêmes valeurs). Aucune régression visuelle.

- [ ] **Step 7: Commit**

```bash
git add bot/dashboard/static/style.css
git commit -m "feat(theme): style.css utilise CSS variables pour couleurs + hooks layout variants"
```

---

### Task 6: Dashboard — sous-onglet "Apparence" dans Paramètres

**Files:**
- Modify: `bot/dashboard/static/index.html`

- [ ] **Step 1: Ajouter l'onglet "Apparence" dans la navigation Paramètres**

Dans `index.html`, localiser la nav des sous-onglets de la section Paramètres (qui contient Émotions, LLM, Images). Ajouter un bouton :

```html
<button class="sub-tab-btn" data-sub-tab="admin-apparence" onclick="showSubTab('admin-apparence', this)">Apparence</button>
```

- [ ] **Step 2: Ajouter le panneau HTML du sous-onglet Apparence**

Dans `index.html`, après le dernier panneau des sous-onglets Paramètres (Images), ajouter :

```html
<!-- Sous-onglet Apparence -->
<div id="admin-apparence" class="sub-tab-panel" style="display:none">
  <div class="section-card">
    <h3 class="section-title">Couleurs</h3>
    <div class="config-grid">
      <div class="config-row">
        <label>Couleur d'accent</label>
        <div style="display:flex;gap:8px;align-items:center">
          <input type="color" id="theme-accent-picker" oninput="onThemeColorInput('accent_color', this.value)">
          <input type="text" id="theme-accent-hex" class="config-input" style="width:100px" placeholder="#06b6d4"
                 oninput="onThemeHexInput('accent_color', 'theme-accent-picker', this.value)">
        </div>
      </div>
      <div class="config-row">
        <label>Fond général</label>
        <div style="display:flex;gap:8px;align-items:center">
          <input type="color" id="theme-bg-picker" oninput="onThemeColorInput('bg_color', this.value)">
          <input type="text" id="theme-bg-hex" class="config-input" style="width:100px" placeholder="#11151c"
                 oninput="onThemeHexInput('bg_color', 'theme-bg-picker', this.value)">
        </div>
      </div>
    </div>
  </div>

  <div class="section-card" style="margin-top:16px">
    <h3 class="section-title">Layout</h3>
    <div class="config-grid">
      <div class="config-row">
        <label>Disposition</label>
        <div style="display:flex;gap:12px;flex-wrap:wrap">
          <label class="radio-option">
            <input type="radio" name="layout-variant" value="sidebar-left" onchange="onThemeRadio('layout_variant', this.value)">
            Sidebar gauche
          </label>
          <label class="radio-option" style="opacity:0.5">
            <input type="radio" name="layout-variant" value="sidebar-top" disabled>
            Navigation top <span class="badge-soon">à venir</span>
          </label>
          <label class="radio-option" style="opacity:0.5">
            <input type="radio" name="layout-variant" value="sidebar-mini" disabled>
            Sidebar mini <span class="badge-soon">à venir</span>
          </label>
        </div>
      </div>
      <div class="config-row">
        <label>Style onglets</label>
        <div style="display:flex;gap:12px;flex-wrap:wrap">
          <label class="radio-option">
            <input type="radio" name="tab-style" value="icons-only" onchange="onThemeRadio('tab_style', this.value)">
            Icônes seules
          </label>
          <label class="radio-option" style="opacity:0.5">
            <input type="radio" name="tab-style" value="icons-labels" disabled>
            Icônes + labels <span class="badge-soon">à venir</span>
          </label>
          <label class="radio-option" style="opacity:0.5">
            <input type="radio" name="tab-style" value="text-only" disabled>
            Texte seul <span class="badge-soon">à venir</span>
          </label>
        </div>
      </div>
    </div>
  </div>

  <div style="margin-top:16px;display:flex;gap:12px;align-items:center">
    <button class="btn-primary" onclick="saveTheme()">Enregistrer</button>
    <span id="theme-save-status" style="font-size:13px;color:#94a3b8"></span>
  </div>
</div>
```

Ajouter aussi dans `<style>` ou `style.css` :
```css
.badge-soon {
  font-size: 10px;
  background: rgba(255,255,255,0.1);
  border-radius: 4px;
  padding: 1px 5px;
  color: #94a3b8;
  vertical-align: middle;
}
.radio-option {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  font-size: 14px;
}
```

- [ ] **Step 3: Ajouter les fonctions JS de theming**

Dans le bloc JS de `index.html` (ou `app.js`), ajouter :

```javascript
// ── Theming ──────────────────────────────────────────────────

let _themeChanges = {};  // accumule les changements avant save

async function loadTheme() {
  try {
    const r = await fetch('/api/admin/theme', { headers: { Authorization: `Bearer ${TOKEN}` } });
    if (!r.ok) return;
    const t = await r.json();
    // Remplir les color pickers
    const accentPicker = document.getElementById('theme-accent-picker');
    const accentHex = document.getElementById('theme-accent-hex');
    const bgPicker = document.getElementById('theme-bg-picker');
    const bgHex = document.getElementById('theme-bg-hex');
    if (accentPicker) { accentPicker.value = t.accent_color; accentHex.value = t.accent_color; }
    if (bgPicker) { bgPicker.value = t.bg_color; bgHex.value = t.bg_color; }
    // Sélectionner les radio buttons
    const layoutRadio = document.querySelector(`input[name="layout-variant"][value="${t.layout_variant}"]`);
    if (layoutRadio) layoutRadio.checked = true;
    const tabRadio = document.querySelector(`input[name="tab-style"][value="${t.tab_style}"]`);
    if (tabRadio) tabRadio.checked = true;
  } catch (e) { console.warn('loadTheme failed', e); }
}

function onThemeColorInput(field, hexValue) {
  // Sync le champ texte
  const hexId = field === 'accent_color' ? 'theme-accent-hex' : 'theme-bg-hex';
  const hexInput = document.getElementById(hexId);
  if (hexInput) hexInput.value = hexValue;
  _themeChanges[field] = hexValue;
  // Preview live : recharger theme.css avec cache-bust
  _reloadThemeCss();
}

function onThemeHexInput(field, pickerId, hexValue) {
  if (/^#[0-9a-fA-F]{6}$/.test(hexValue)) {
    const picker = document.getElementById(pickerId);
    if (picker) picker.value = hexValue;
    _themeChanges[field] = hexValue;
    _reloadThemeCss();
  }
}

function onThemeRadio(field, value) {
  _themeChanges[field] = value;
}

function _reloadThemeCss() {
  // Preview live sans rechargement de page
  const link = document.getElementById('theme-link');
  if (!link) return;
  const base = '/static/theme.css';
  link.href = `${base}?v=${Date.now()}`;
}

async function saveTheme() {
  const status = document.getElementById('theme-save-status');
  if (Object.keys(_themeChanges).length === 0) {
    if (status) status.textContent = 'Aucune modification.';
    return;
  }
  try {
    const r = await fetch('/api/admin/theme', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${TOKEN}` },
      body: JSON.stringify(_themeChanges),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      if (status) status.textContent = `Erreur: ${err.detail || r.status}`;
      return;
    }
    _themeChanges = {};
    if (status) { status.textContent = 'Sauvegardé ✓'; setTimeout(() => { status.textContent = ''; }, 3000); }
    _reloadThemeCss();
  } catch (e) {
    if (status) status.textContent = `Erreur réseau`;
  }
}
```

- [ ] **Step 4: Appeler `loadTheme()` quand l'onglet Apparence est affiché**

Localiser la fonction `showSubTab()` (ou équivalent) dans `index.html`. Ajouter un appel à `loadTheme()` quand `admin-apparence` est activé :

```javascript
function showSubTab(id, btn) {
  // ... logique existante ...
  if (id === 'admin-apparence') loadTheme();
}
```

- [ ] **Step 5: Vérifier manuellement**

Ouvrir le dashboard > Paramètres > Apparence. Les color pickers doivent afficher les couleurs actuelles. Changer l'accent color : le dashboard doit se mettre à jour en live. Cliquer Enregistrer : vérifier que le changement persiste après rechargement.

- [ ] **Step 6: Commit**

```bash
git add bot/dashboard/static/index.html
git commit -m "feat(theme): sous-onglet Apparence dans Paramètres — color pickers + preview live"
```

---

### Task 7: Provisioner — bloc `theme:` par défaut

**Files:**
- Modify: `bot/core/provisioner.py`
- Test: `tests/test_setup_provisioner.py`

- [ ] **Step 1: Lire les tests existants du provisioner**

```bash
head -60 tests/test_setup_provisioner.py
```

- [ ] **Step 2: Ajouter le test du bloc theme**

Dans `tests/test_setup_provisioner.py`, ajouter :

```python
def test_provisioner_config_includes_theme_defaults(tmp_path, monkeypatch):
    """Le config.yaml généré contient un bloc theme: avec les valeurs par défaut."""
    import yaml
    from bot.core.provisioner import _write_config_yaml

    data = {"bot_name": "TestBot", "language_default": "fr"}
    _write_config_yaml(tmp_path, "testslug", data)

    cfg = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert "theme" in cfg
    assert cfg["theme"]["accent_color"] == "#06b6d4"
    assert cfg["theme"]["layout_variant"] == "sidebar-left"
    assert cfg["theme"]["tab_style"] == "icons-only"
```

- [ ] **Step 3: Vérifier que le test échoue**

```bash
pytest tests/test_setup_provisioner.py::test_provisioner_config_includes_theme_defaults -v
```
Attendu : `AssertionError: assert "theme" in cfg`

- [ ] **Step 4: Ajouter le bloc `theme:` dans `_write_config_yaml()`**

Dans `bot/core/provisioner.py`, dans la fonction `_write_config_yaml()`, dans le dictionnaire `cfg`, ajouter après `"overlay_image"` :

```python
        "theme": {
            "accent_color": "#06b6d4",
            "bg_color": "#11151c",
            "surface_color": "rgba(255,255,255,0.03)",
            "sidebar_bg": "rgba(255,255,255,0.02)",
            "layout_variant": "sidebar-left",
            "tab_style": "icons-only",
        },
```

- [ ] **Step 5: Vérifier que le test passe**

```bash
pytest tests/test_setup_provisioner.py -v
```
Attendu : tous les tests verts.

- [ ] **Step 6: Run la suite complète**

```bash
pytest tests/ -x -q
```
Attendu : tous les tests passent (876+).

- [ ] **Step 7: Commit final**

```bash
git add bot/core/provisioner.py tests/test_setup_provisioner.py
git commit -m "feat(theme): provisioner inclut bloc theme: par défaut dans config.yaml des instances"
```

---

## Récapitulatif des fichiers impactés

| Fichier | Changement |
|---|---|
| `bot/config.py` | `ThemeConfig` dataclass + champ dans `Config` + `load()` + `save()` |
| `bot/dashboard/routes/theme.py` | **Nouveau** — endpoint theme.css + routes API admin |
| `bot/dashboard/app.py` | Import theme + `add_api_route` theme.css + `include_router` + cache-bust |
| `bot/dashboard/static/index.html` | `<link>` theme.css + JS data-layout + onglet Apparence |
| `bot/dashboard/static/style.css` | CSS vars dans `:root` + remplacement hardcoded + hooks layout |
| `bot/core/provisioner.py` | Bloc `theme:` dans `_write_config_yaml()` |
| `tests/test_config.py` | 4 nouveaux tests ThemeConfig |
| `tests/test_dashboard_theme.py` | **Nouveau** — 12 tests routes theme |
| `tests/test_setup_provisioner.py` | 1 nouveau test provisioner |
