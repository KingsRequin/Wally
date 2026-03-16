# Web Dashboard Wally — Phase 1 — Design Spec

**Date:** 2026-03-16
**Scope:** Phase 1 uniquement — infrastructure FastAPI + page publique + admin Config/Humeur/Logs
**Phases futures:** Phase 2 (Mémoire, Coûts) · Phase 3 (Persona, Timeouts)

---

## Contexte

Wally est un bot Discord+Twitch Python asyncio tournant en conteneur Docker. Le dashboard web
est intégré directement dans le processus existant via `asyncio.gather()`. Aucun nouveau service
Docker n'est requis.

Le `dashboard_token` existe déjà dans `BotConfig`. La table `emotion_history` existe déjà dans
`database.py` avec `insert_emotion_snapshot()` et `get_today_emotion_snapshots()`.

---

## Décisions d'architecture

### Frontend
- **Vanilla JS SPA** : FastAPI sert un seul `index.html` + fichiers statiques CSS/JS.
- Pas de framework JS. Pas de build step. Pas de Jinja2.
- SSE via l'API native `EventSource`.
- Mini-graphe humeur 24h via `<canvas>` vanilla.
- Auth : token saisi dans un modal → stocké en `localStorage['wally_token']`.
  > ⚠️ Note dans `app.js` : un cookie HttpOnly serait plus sécurisé pour une exposition publique future.

### Backend
- **FastAPI** intégré via `uvicorn.Server` dans `asyncio.gather()`.
- Services injectés via `AppState` (dataclass, pas de globals).
- Routes publiques : `/api/public/*` — pas d'auth.
- Routes admin : `/api/admin/*` — middleware Bearer token.
- Port : `8080`, exposé dans `docker-compose.yml` comme `127.0.0.1:8080:8080`.

---

## Structure de fichiers

```
bot/
└── dashboard/
    ├── __init__.py
    ├── app.py          # create_dashboard_app(...) → FastAPI, background task snapshots 5min
    ├── auth.py         # middleware Bearer + dépendance FastAPI require_auth()
    ├── state.py        # AppState dataclass (config, db, emotion, memory, persona, openai_client)
    └── routes/
        ├── __init__.py
        ├── status.py   # uptime bot, connectivité Discord/Twitch, stats messages
        ├── emotions.py # GET état, POST set/reset, GET history 24h
        ├── memory.py   # stub Phase 3 (fichier créé, endpoints à compléter plus tard)
        ├── admin.py    # config GET/POST, modèles OpenAI filtrés
        ├── sse.py      # SSE émotions (depuis EmotionEngine en mémoire) + SSE logs
        └── twitch.py   # statut stream Azrael_TTV, cache TTL
    static/
        ├── index.html  # markup complet, onglets publics + admin
        ├── style.css   # dark neobrutalism strict
        └── app.js      # routing onglets, SSE, fetch API, auth modal, canvas graphe
```

---

## API Endpoints — Phase 1

### Public `/api/public/*`

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| GET | `/api/public/status` | `{uptime_seconds, discord_online, twitch_online, total_messages}` |
| GET | `/api/public/emotions` | `{anger, joy, sadness, curiosity, boredom}` (floats 0–1) |
| GET | `/api/public/emotions/history` | Snapshots 24h depuis `emotion_history` |
| GET | `/api/public/twitch/stream` | Statut stream avec cache TTL |
| GET | `/api/public/sse/emotions` | SSE stream, push toutes les 5s depuis `EmotionEngine` |

### Admin `/api/admin/*` (Bearer token requis)

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| GET | `/api/admin/config` | Config complète sérialisée |
| POST | `/api/admin/config` | Mise à jour partielle + `config.save()` |
| GET | `/api/admin/openai/models` | Modèles OpenAI filtrés (gpt/chatgpt/o1/o3/o4, excl. realtime/preview/audio/vision) |
| GET | `/api/admin/emotions` | État actuel (même que public) |
| POST | `/api/admin/emotions/set` | `{emotion: str, value: float}` → `emotion.set_emotion()` |
| POST | `/api/admin/emotions/reset` | Reset toutes les émotions à **0.5** (neutre) |
| GET | `/api/admin/sse/logs` | SSE flux logs loguru en temps réel |

### Racine

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| GET | `/` | Sert `index.html` |
| GET | `/static/{path}` | CSS, JS statiques |

---

## SSE — Détails d'implémentation

### SSE Émotions (`/api/public/sse/emotions`)
- Lit `emotion.get_state()` depuis l'objet `EmotionEngine` injecté dans `AppState`.
- **Pas de lecture DB** — l'état en mémoire avec décroissance en cours est la source de vérité.
- Push toutes les 5 secondes.
- Format : `data: {"anger": 0.3, "joy": 0.7, ...}\n\n`

### SSE Logs (`/api/admin/sse/logs`)
- Loguru `sink` custom ajouté au démarrage : écrit dans un `asyncio.Queue`.
- Le handler SSE consomme la queue et pousse vers le client.
- Format : `data: {"level": "INFO", "message": "...", "time": "14:32:01"}\n\n`
- Filtrable côté client par niveau (INFO / WARNING / ERROR).

---

## Cache Twitch (`routes/twitch.py`)

```python
_cache: dict = {"data": None, "fetched_at": 0.0, "is_live": False}

TTL_LIVE    = 60     # secondes — statut live
TTL_OFFLINE = 300    # secondes — statut offline

async def get_stream_status(state: AppState) -> dict:
    now = time.time()
    ttl = TTL_LIVE if _cache["is_live"] else TTL_OFFLINE
    if _cache["data"] and (now - _cache["fetched_at"]) < ttl:
        return _cache["data"]
    # ... appel TwitchAPI via httpx, mise à jour cache
```

---

## Background Task — Snapshots 5min

Dans `dashboard/app.py`, au démarrage de la lifespan FastAPI :

```python
async def _snapshot_task(state: AppState):
    while True:
        await asyncio.sleep(300)  # 5 minutes
        await state.db.insert_emotion_snapshot(state.emotion.get_state())
```

> Complète les snapshots horaires existants de `emotion.py` (decay loop, toutes les 60 ticks).

---

## Frontend — Structure `index.html`

```
<header>          WALLY · [PUBLIC] [ADMIN 🔒]
<nav.tabs>        Statut | Humeur | Stream | Stats  (public)
                  Config | Humeur | Logs | [grisés: Mémoire Coûts Persona Timeouts]  (admin)
<main>
  #tab-status     Uptime, dots Discord/Twitch
  #tab-emotions   5 jauges + phrase résumée + canvas graphe 24h
  #tab-stream     Carte live/offline Azrael_TTV
  #tab-stats      Compteurs messages
  #tab-admin-config     Formulaire config.yaml (sliders λ, sélecteur modèle, champs)
  #tab-admin-emotions   5 jauges éditables + bouton Reset à neutre (0.5)
  #tab-admin-logs       Flux SSE logs avec filtre niveau
<div#auth-modal>  Saisie token → localStorage
```

---

## Design Dark Neobrutalism

Règles non-négociables (du cahier des charges) :

| Règle | Valeur |
|-------|--------|
| Bordures | `3px solid #ffffff` |
| Ombres | `4px 4px 0px #ffffff` (pas de flou) |
| Border-radius | 0px (max 4px) |
| Font-weight | 700–900 pour les titres |
| Fond principal | `#0f0f0f` |
| Fond cartes | `#1a1a1a` |
| Texte principal | `#ffffff` / secondaire `#aaaaaa` |

Couleurs émotions : Anger `#ff3333` · Joy `#ffdd00` · Curiosity `#00ccff` · Sadness `#7777ff` · Boredom `#888888`

Boutons : ombre `4px 4px 0px #fff` au repos → `0px 0px` au hover (effet "appui physique").

Favicon : SVG inline, couleur mise à jour via SSE selon l'émotion dominante.

---

## Modifications fichiers existants

| Fichier | Changement |
|---------|-----------|
| `bot/main.py` | Import `create_dashboard_app`, ajout `uvicorn.Server` dans `asyncio.gather()` |
| `docker-compose.yml` | Ajout `ports: ["127.0.0.1:8080:8080"]` sur le service `wally` |
| `requirements.txt` | Ajout `fastapi>=0.111.0` et `uvicorn>=0.30.0` |

> `emotion_history` table déjà présente dans `database.py`. Aucune migration DB nécessaire.

---

## Hors scope Phase 1 (prévu phases 2-3)

- Gestion mémoire mem0 (liste users, souvenirs, suppression, recherche sémantique)
- Dashboard coûts OpenAI (graphiques, breakdown)
- Éditeur Persona (SOUL/IDENTITY/VOICE/EMOTIONS + templates prompts)
- Gestion timeouts (liste mutes actifs, historique)
- Historique pics émotion (quel user a déclenché quoi)
