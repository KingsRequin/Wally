# Twitch Channels Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter un onglet admin dédié "Twitch" qui liste les chaînes invitées avec leur statut IRC/live et un bouton Déconnecter par chaîne.

**Architecture:** Nouveau endpoint `GET /api/admin/twitch/channels` + nouvel onglet `admin-twitch` dans la sidebar admin. La carte "CHAÎNES TWITCH INVITÉES" existante dans admin-config est supprimée (dupliquée). Le formulaire d'ajout est déplacé dans le nouvel onglet.

**Tech Stack:** FastAPI (Python), Vanilla JS, CSS glassmorphism existant

**Note sécurité:** Les noms de chaînes Twitch sont des logins validés côté serveur (regex `^[a-z0-9_]{1,25}$`). Leur injection dans `innerHTML` est safe — même pratique que le code existant dans `buildAdminConfig()` et `addGuestChannel()`.

---

## File Structure

| File | Change |
|---|---|
| `bot/dashboard/routes/admin.py` | Ajouter `GET /api/admin/twitch/channels` |
| `bot/dashboard/static/index.html` | Ajouter sidebar item + div tab `admin-twitch` |
| `bot/dashboard/static/app.js` | Ajouter `loadTwitchChannelsTab()`, brancher dans `showTab()`, supprimer carte guest de `buildAdminConfig()`, adapter `addGuestChannel()` / `removeGuestChannel()` |
| `bot/dashboard/static/style.css` | Ajouter styles `.twitch-channel-card` |
| `tests/test_dashboard_twitch_channels.py` | Tests du nouveau endpoint GET |

---

## Task 1 : Endpoint GET /api/admin/twitch/channels

**Files:**
- Modify: `bot/dashboard/routes/admin.py` (apres `@router.delete("/twitch/channels/{name}")`, ligne ~404)
- Test: `tests/test_dashboard_twitch_channels.py` (nouveau)

### Context

`bot._channel_ids` est un `dict[str, str]` (name -> broadcaster_id).
`bot.get_channel(name)` retourne un objet twitchio ou `None` si IRC pas connecte.
`bot._channel_was_live` est un `dict[str, bool]` (name -> vu live au moins une fois depuis demarrage).

- [ ] **Step 1 : Ecrire le test qui echoue**

```python
# tests/test_dashboard_twitch_channels.py
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from bot.dashboard.routes.admin import router

@pytest.fixture
def app_with_twitch():
    app = FastAPI()
    app.include_router(router, prefix="/api/admin")

    mock_bot = MagicMock()
    mock_bot._channel_ids = {"keychka": "169154332", "streamer2": "999000111"}
    mock_bot._channel_was_live = {"keychka": True, "streamer2": False}
    mock_bot.get_channel.side_effect = lambda name: MagicMock() if name == "keychka" else None

    state = MagicMock()
    state.twitch_bot = mock_bot
    app.state.wally = state
    return TestClient(app)

def test_get_twitch_channels_returns_list(app_with_twitch):
    r = app_with_twitch.get("/api/admin/twitch/channels", headers={"Authorization": "Bearer test"})
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 2

def test_get_twitch_channels_irc_status(app_with_twitch):
    r = app_with_twitch.get("/api/admin/twitch/channels", headers={"Authorization": "Bearer test"})
    channels = {c["name"]: c for c in r.json()}
    assert channels["keychka"]["irc_connected"] is True
    assert channels["streamer2"]["irc_connected"] is False

def test_get_twitch_channels_live_status(app_with_twitch):
    r = app_with_twitch.get("/api/admin/twitch/channels", headers={"Authorization": "Bearer test"})
    channels = {c["name"]: c for c in r.json()}
    assert channels["keychka"]["live"] is True
    assert channels["streamer2"]["live"] is False

def test_get_twitch_channels_no_bot_returns_503(app_with_twitch):
    app_with_twitch.app.state.wally.twitch_bot = None
    r = app_with_twitch.get("/api/admin/twitch/channels", headers={"Authorization": "Bearer test"})
    assert r.status_code == 503
```

- [ ] **Step 2 : Lancer les tests pour verifier l'echec**

```bash
cd /opt/stacks/wally-ai
python3 -m pytest tests/test_dashboard_twitch_channels.py -v
```
Expected: 4 FAIL (route inexistante -> 404)

- [ ] **Step 3 : Ajouter le endpoint dans `admin.py`**

Dans `bot/dashboard/routes/admin.py`, ajouter apres `@router.delete("/twitch/channels/{name}")` (ligne ~404) :

```python
@router.get("/twitch/channels")
async def list_twitch_channels(request: Request) -> list[dict]:
    """Liste les chaines Twitch invitees avec statut IRC et live."""
    state = request.app.state.wally
    if state.twitch_bot is None:
        raise HTTPException(status_code=503, detail="Twitch non disponible")
    bot = state.twitch_bot
    return [
        {
            "name": name,
            "broadcaster_id": bid,
            "irc_connected": bot.get_channel(name) is not None,
            "live": bot._channel_was_live.get(name, False),
        }
        for name, bid in bot._channel_ids.items()
    ]
```

- [ ] **Step 4 : Relancer les tests**

```bash
python3 -m pytest tests/test_dashboard_twitch_channels.py -v
```
Expected: 4 PASS

- [ ] **Step 5 : Commit**

```bash
git add tests/test_dashboard_twitch_channels.py bot/dashboard/routes/admin.py
git commit -m "feat(dashboard): GET /api/admin/twitch/channels with IRC + live status"
```

---

## Task 2 : HTML — nouvel onglet dans la sidebar

**Files:**
- Modify: `bot/dashboard/static/index.html`

### Context

La sidebar admin est dans `<nav class="sidebar-nav" id="nav-admin">` (ligne ~106).
Le dernier item admin est `data-tab="admin-actions"` (ligne ~133).
La div `<div class="tab-content" id="tab-admin-actions"></div>` est ligne ~320.
La carte guest-channels N'EST PAS dans le HTML — elle est injectee dynamiquement par `buildAdminConfig()` en JS. Seule la div vide du tab est a creer ici.

- [ ] **Step 1 : Ajouter le sidebar item admin-twitch apres admin-actions**

Dans `bot/dashboard/static/index.html`, trouver le bloc :
```html
      <a class="sidebar-item" data-tab="admin-actions" onclick="showTab('admin-actions')" href="javascript:void(0)" aria-label="Actions">
```
Ajouter immediatement apres la fermeture de ce bloc `</a>` :

```html
      <a class="sidebar-item" data-tab="admin-twitch" onclick="showTab('admin-twitch')" href="javascript:void(0)" aria-label="Twitch">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M11.571 4.714h1.715v5.143H11.57zm4.715 0H18v5.143h-1.714zM6 0L1.714 4.286v15.428h5.143V24l4.286-4.286h3.428L22.286 12V0zm14.571 11.143l-3.428 3.428h-3.429l-3 3v-3H6.857V1.714h13.714z"/></svg>
        <span>Twitch</span>
      </a>
```

- [ ] **Step 2 : Ajouter la div tab admin-twitch apres tab-admin-actions**

Trouver `<div class="tab-content" id="tab-admin-actions"></div>` et ajouter juste apres :

```html
    <div class="tab-content" id="tab-admin-twitch"></div>
```

- [ ] **Step 3 : Verifier que le HTML parse sans erreur**

```bash
python3 -c "from html.parser import HTMLParser; p = HTMLParser(); p.feed(open('bot/dashboard/static/index.html').read()); print('HTML OK')"
```
Expected: `HTML OK`

- [ ] **Step 4 : Commit**

```bash
git add bot/dashboard/static/index.html
git commit -m "feat(dashboard): add admin-twitch tab HTML + sidebar item"
```

---

## Task 3 : CSS — styles glassmorphism pour les cartes chaine

**Files:**
- Modify: `bot/dashboard/static/style.css` (append at end)

### Context

Design system : `rgba(255,255,255,0.04)` background, `1px solid rgba(255,255,255,0.08)` border, `border-radius:12px`, accent `#06b6d4`. Statut : vert `#22c55e`, orange `#f59e0b`, rouge `#ef4444`.

- [ ] **Step 1 : Ajouter les styles en fin de `style.css`**

```css
/* ── Twitch Channels Tab ──────────────────────────────────────────── */

.twitch-channel-card {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 12px 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.twitch-channel-card .tc-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex-shrink: 0;
}

.twitch-channel-card .tc-dot.connected {
  background: #22c55e;
  box-shadow: 0 0 6px #22c55e;
}

.twitch-channel-card .tc-dot.pending {
  background: #f59e0b;
}

.twitch-channel-card .tc-name {
  flex: 1;
  font-family: var(--font-mono);
  font-size: 0.88rem;
  color: rgba(255, 255, 255, 0.9);
}

.twitch-channel-card .tc-badge {
  font-size: 0.72rem;
  padding: 2px 7px;
  border-radius: 4px;
  letter-spacing: 0.3px;
}

.twitch-channel-card .tc-badge.live {
  background: rgba(239, 68, 68, 0.2);
  color: #ef4444;
}

.twitch-channel-card .tc-badge.offline {
  background: rgba(255, 255, 255, 0.06);
  color: rgba(255, 255, 255, 0.35);
}

.twitch-channel-card .tc-kick {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.25);
  color: #ef4444;
  border-radius: 7px;
  padding: 4px 12px;
  font-size: 0.82em;
  cursor: pointer;
  transition: background 0.15s;
}

.twitch-channel-card .tc-kick:hover {
  background: rgba(239, 68, 68, 0.2);
}

#twitch-channels-add {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}
```

- [ ] **Step 2 : Verifier l'equilibre des accolades CSS**

```bash
python3 -c "
import sys
css = open('bot/dashboard/static/style.css').read()
o, c = css.count('{'), css.count('}')
if o != c: print(f'MISMATCH: {o} open vs {c} close'); sys.exit(1)
print('CSS OK')
"
```
Expected: `CSS OK`

- [ ] **Step 3 : Commit**

```bash
git add bot/dashboard/static/style.css
git commit -m "feat(dashboard): CSS for twitch-channel-card"
```

---

## Task 4 : JS — loadTwitchChannelsTab(), showTab(), suppression carte config

**Files:**
- Modify: `bot/dashboard/static/app.js`

### Context

`showTab()` est a la ligne ~268. Il dispatche les loaders selon `tabId`.
`buildAdminConfig()` est la fonction qui genere le HTML de l'onglet config. La carte `id="guest-channels-card"` (lignes ~1143–1165) est a supprimer.
`addGuestChannel()` et `removeGuestChannel()` manipulent `#guest-channels-list` et `#guest-channel-input` — ces IDs seront dans le nouvel onglet. Ces fonctions ont besoin d'adaptations mineures (classe CSS et check vide).

- [ ] **Step 1 : Ajouter `loadTwitchChannelsTab()` apres `removeGuestChannel()`** (ligne ~1408)

```js
// ── Twitch Channels Tab ──────────────────────────────────────────────────────

async function loadTwitchChannelsTab() {
  const el = document.getElementById('tab-admin-twitch');
  if (!el) return;

  el.innerHTML = '<p style="color:var(--text-muted);padding:16px">Chargement\u2026</p>';

  const r = await apiFetch('/api/admin/twitch/channels');
  if (!r || !r.ok) {
    el.innerHTML = '<p style="color:var(--c-offline);padding:16px">Erreur de chargement.</p>';
    return;
  }
  const channels = await r.json();

  const cardsHtml = channels.length === 0
    ? '<p style="color:var(--text-muted);margin-bottom:12px">Aucune cha\u00eene invit\u00e9e.</p>'
    : channels.map(ch => {
        // ch.name is a validated Twitch login (^[a-z0-9_]{1,25}$) — safe for innerHTML
        const dotClass = ch.irc_connected ? 'connected' : 'pending';
        const badgeClass = ch.live ? 'live' : 'offline';
        const badgeText = ch.live ? '\uD83D\uDD34 LIVE' : 'hors ligne';
        return '<div class="twitch-channel-card" id="guest-ch-' + ch.name + '">'
          + '<div class="tc-dot ' + dotClass + '"></div>'
          + '<span class="tc-name">' + ch.name + '</span>'
          + '<span class="tc-badge ' + badgeClass + '">' + badgeText + '</span>'
          + '<button class="tc-kick" onclick="removeGuestChannel(\'' + ch.name + '\')">D\u00e9connecter</button>'
          + '</div>';
      }).join('');

  el.innerHTML = '<div style="padding:0 2px">'
    + '<div id="guest-channels-list">' + cardsHtml + '</div>'
    + '<div id="twitch-channels-add">'
    + '<input type="text" id="guest-channel-input" placeholder="nom de cha\u00eene twitch\u2026"'
    + ' style="flex:1" onkeydown="if(event.key===\'Enter\') addGuestChannel()">'
    + '<button class="btn btn-success" onclick="addGuestChannel()">+ Ajouter</button>'
    + '</div>'
    + '<div id="guest-channel-error" style="color:var(--c-offline);font-size:0.85em;margin-top:6px;display:none"></div>'
    + '<p style="color:var(--text-muted);font-size:0.8em;margin-top:10px">'
    + 'Le broadcaster doit avoir autoris\u00e9 le bot (scope <code>channel:bot</code>) pour que Wally puisse parler.'
    + '</p>'
    + '</div>';
}
```

- [ ] **Step 2 : Adapter `removeGuestChannel()` — check liste vide**

Dans `removeGuestChannel()` (ligne ~1395), remplacer :

```js
    const list = document.getElementById('guest-channels-list');
    if (list && !list.querySelector('.guest-channel-item')) {
      list.innerHTML = '<p style="color:var(--text-muted);margin:0 0 12px">Aucune cha\u00eene invit\u00e9e.</p>';
    }
```

Par :

```js
    const list = document.getElementById('guest-channels-list');
    if (list && !list.querySelector('.twitch-channel-card, .guest-channel-item')) {
      list.innerHTML = '<p style="color:var(--text-muted);margin:0 0 12px">Aucune cha\u00eene invit\u00e9e.</p>';
    }
```

- [ ] **Step 3 : Adapter `addGuestChannel()` — injecter une `twitch-channel-card`**

Dans `addGuestChannel()` (ligne ~1383), remplacer le bloc qui cree `item` :

```js
  const item = document.createElement('div');
  item.id = `guest-ch-${name}`;
  item.className = 'guest-channel-item';
  item.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:6px';
  item.innerHTML = `<span style="flex:1;font-family:var(--font-mono);font-size:0.85rem">${name}</span>
    <button class="btn btn-danger" style="padding:2px 8px;font-size:0.8em"
      onclick="removeGuestChannel('${name}')">✕</button>`;
```

Par :

```js
  const item = document.createElement('div');
  item.id = 'guest-ch-' + name;
  item.className = 'twitch-channel-card';
  // name is validated ^[a-z0-9_]{1,25}$ before reaching here — safe for innerHTML
  item.innerHTML = '<div class="tc-dot pending"></div>'
    + '<span class="tc-name">' + name + '</span>'
    + '<span class="tc-badge offline">hors ligne</span>'
    + '<button class="tc-kick" onclick="removeGuestChannel(\'' + name + '\')">D\u00e9connecter</button>';
```

- [ ] **Step 4 : Brancher `loadTwitchChannelsTab()` dans `showTab()`**

Dans `showTab()` (ligne ~296), apres :
```js
  if (tabId === 'admin-actions') { renderActionsTab(); startActionSSE(); } else { stopActionSSE(); }
```
Ajouter :
```js
  if (tabId === 'admin-twitch') loadTwitchChannelsTab();
```

- [ ] **Step 5 : Supprimer la carte guest de `buildAdminConfig()`**

Dans `buildAdminConfig()` (lignes ~1143–1165), supprimer le bloc complet :

```js
    <!-- Chaines Twitch invitees -->
    <div class="card config-section" id="guest-channels-card">
      <div class="config-section-title">CHAINES TWITCH INVITEES</div>
      <div id="guest-channels-list">
        ${(cfg.twitch.guest_channels || []).length === 0
          ? '<p style="color:var(--text-muted);margin:0 0 12px">Aucune cha\u00eene invit\u00e9e.</p>'
          : (cfg.twitch.guest_channels || []).map(ch => `
            <div class="guest-channel-item" id="guest-ch-${ch}" style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
              <span style="flex:1;font-family:var(--font-mono);font-size:0.85rem">${ch}</span>
              <button class="btn btn-danger" style="padding:2px 8px;font-size:0.8em"
                onclick="removeGuestChannel('${ch}')">✕</button>
            </div>`).join('')
        }
      </div>
      <div style="display:flex;gap:8px;margin-top:8px">
        <input type="text" id="guest-channel-input" placeholder="nom de cha\u00eene twitch\u2026"
               style="flex:1" onkeydown="if(event.key==='Enter') addGuestChannel()">
        <button class="btn btn-success" onclick="addGuestChannel()">+ Ajouter</button>
      </div>
      <div id="guest-channel-error" style="color:var(--c-offline);font-size:0.85em;margin-top:6px;display:none"></div>
      <p style="color:var(--text-muted);font-size:0.8em;margin-top:10px">
        Le broadcaster doit avoir autoris\u00e9 le bot (scope <code>channel:bot</code>) pour que Wally puisse parler.
      </p>
    </div>
```

- [ ] **Step 6 : Verifier la syntaxe JS**

```bash
node --check bot/dashboard/static/app.js && echo "JS OK"
```
Expected: `JS OK`

- [ ] **Step 7 : Lancer tous les tests**

```bash
python3 -m pytest --tb=short -q
```
Expected: tous les tests passent (847+)

- [ ] **Step 8 : Commit**

```bash
git add bot/dashboard/static/app.js
git commit -m "feat(dashboard): twitch channels tab — loadTwitchChannelsTab, remove config card"
```
