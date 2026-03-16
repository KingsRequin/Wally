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
`EmotionEngine.reset()` remet toutes les émotions à `0.0` — la route admin reset appellera
`set_emotion(e, 0.5)` pour chaque émotion, pas `reset()`.

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
- Arrêt coordonné : `uvicorn.Server.should_exit = True` dans le signal handler de `main.py`.

---

## Structure de fichiers

```
bot/
└── dashboard/
    ├── __init__.py
    ├── app.py          # create_dashboard_app(...) → FastAPI, lifespan, background task snapshots 5min
    ├── auth.py         # middleware Bearer + dépendance FastAPI require_auth()
    ├── state.py        # AppState dataclass (voir détail ci-dessous)
    └── routes/
        ├── __init__.py
        ├── status.py   # uptime bot, connectivité Discord/Twitch, stats messages
        ├── emotions.py # GET état, POST set/reset, GET history 24h
        ├── memory.py   # router vide Phase 2 — tout appel retourne 501
        ├── admin.py    # config GET/POST, modèles OpenAI filtrés
        ├── sse.py      # SSE émotions (depuis EmotionEngine en mémoire) + SSE logs
        └── twitch.py   # statut stream Azrael_TTV, cache TTL
    static/
        ├── index.html  # markup complet, onglets publics + admin
        ├── style.css   # dark neobrutalism strict
        └── app.js      # routing onglets, SSE, fetch API, auth modal, canvas graphe
```

---

## AppState — Champs complets

```python
import time
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class AppState:
    config: Config
    db: Database
    emotion: EmotionEngine
    memory: MemoryService
    persona: PersonaService
    openai_client: OpenAIClient
    token_manager: TwitchTokenManager      # accès tokens Twitch pour appels Helix API
    twitch_api: Optional[TwitchAPI]        # appels Helix (get_stream, etc.) — None si Twitch désactivé
    discord_bot: Optional[WallyDiscord]    # connectivité Discord via .is_ready()
    twitch_bot: Optional[WallyTwitch]      # connectivité Twitch via _eventsub_client
    start_time: float = field(default_factory=time.time)  # timestamp démarrage processus
    message_count: int = 0                 # compteur en mémoire, incrémenté par handlers
```

---

## Attribut `dashboard_state` sur les bots

`WallyDiscord` et `WallyTwitch` reçoivent chacun un attribut `dashboard_state: Optional[AppState] = None`,
déclaré dans leur `__init__()`. Wired dans `main.py` après création de l'`AppState` :

```python
discord_bot.dashboard_state = state
twitch_bot.dashboard_state = state  # si twitch_bot existe
```

Les handlers incrémentent le compteur avec un guard :
```python
if self.dashboard_state is not None:
    self.dashboard_state.message_count += 1
```

---

## Connectivité Discord/Twitch

| Champ | Source | Notes |
|-------|--------|-------|
| `discord_online` | `state.discord_bot.is_ready()` si non-None, sinon `False` | API discord.py standard |
| `twitch_online` | `getattr(state.twitch_bot, "_eventsub_client", None) is not None` si bot non-None | Safe getattr — `_eventsub_client` est None avant start et pendant restart |

---

## Uptime

`uptime_seconds = time.time() - state.start_time`

`start_time` est initialisé dans `AppState` via `field(default_factory=time.time)` — représente
le démarrage du processus (pas le Discord ready time).

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
| POST | `/api/admin/config` | Mise à jour partielle + `config.save()` — voir section merge |
| GET | `/api/admin/openai/models` | Modèles OpenAI filtrés (gpt/chatgpt/o1/o3/o4, excl. realtime/preview/audio/vision) |
| GET | `/api/admin/emotions` | État actuel (même que public) |
| POST | `/api/admin/emotions/set` | `{emotion: str, value: float}` → `emotion.set_emotion()` |
| POST | `/api/admin/emotions/reset` | Reset toutes les émotions à **0.5** — appelle `set_emotion(e, 0.5)` pour chaque émotion, **pas** `emotion.reset()` |
| GET | `/api/admin/sse/logs` | SSE flux logs loguru en temps réel |

### Racine

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| GET | `/` | Sert `index.html` |
| GET | `/static/{path}` | CSS, JS statiques |

---

## Auth — Cas limites

- `dashboard_token` absent ou vide dans `config.yaml` → les routes `/api/admin/*` retournent **503 Service Unavailable** avec body `{"detail": "dashboard_token not configured"}`.
- Token invalide → **401 Unauthorized**.
- Routes publiques → pas de vérification.

---

## `POST /api/admin/config` — Stratégie de merge et validation

Le body JSON contient un sous-ensemble des sections de `config.yaml`
(ex: `{"openai": {"primary_model": "gpt-4o"}}`). L'endpoint patch les champs dans le dataclass
`Config` en mémoire section par section, puis appelle `config.save()`. Les sections absentes du
body ne sont pas modifiées.

Validation des champs contraints :
- `openai.temperature` : doit être `0.0–2.0` → 400 si invalide
- `emotions.*.decay_lambda` : doit être > 0 → 400 si invalide
- Champs inconnus dans une section : ignorés silencieusement

Comportement des types `list` (ex : `bot.trigger_names`, `twitch.channels`, `discord.channel_whitelist`) :
les listes sont **remplacées entièrement** par la valeur fournie dans le body — pas de merge
élément par élément. Le merge section-par-section ne s'applique qu'aux sous-objets `dict`.

---

## SSE — Détails d'implémentation

### SSE Émotions (`/api/public/sse/emotions`)
- Lit `emotion.get_state()` depuis l'objet `EmotionEngine` injecté dans `AppState`.
- **Pas de lecture DB** — l'état en mémoire avec décroissance en cours est la source de vérité.
- Push toutes les 5 secondes.
- Format : `data: {"anger": 0.3, "joy": 0.7, ...}\n\n`

### SSE Logs (`/api/admin/sse/logs`) — Architecture fan-out

- Loguru `sink` custom ajouté au démarrage de la lifespan FastAPI.
- Liste globale de queues : `_log_queues: list[asyncio.Queue]` dans `sse.py`.
- Le sink loguru écrit dans **toutes** les queues de la liste (fan-out broadcast).
- Le sink est **synchrone** (loguru appelle les sinks depuis un thread) — utiliser `queue.put_nowait()`.
  Queue de taille max 100 ; si pleine, le record est silencieusement ignoré (`try/except`).
- Thread-safety : dans le sink, itérer sur une **copie** de la liste pour éviter un `RuntimeError`
  si la liste est modifiée (append/remove) depuis le thread asyncio en parallèle :
  ```python
  for q in list(_log_queues):
      try: q.put_nowait(record)
      except: pass
  ```
- À chaque connexion SSE : créer une `asyncio.Queue(maxsize=100)`, l'ajouter à `_log_queues`, la retirer à la déconnexion.
- Le sink extrait depuis le record loguru : `record["level"].name`, `record["message"]`, `record["time"].strftime("%H:%M:%S")`.
- Format push : `data: {"level": "INFO", "message": "...", "time": "HH:MM:SS"}\n\n`
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
    result = await state.twitch_api.get_stream()  # TwitchAPI.get_stream() via AppState
    _cache.update({"data": result, "fetched_at": now, "is_live": result["live"]})
    return result
```

---

## `TwitchAPI.get_stream()` — Nouvelle méthode

`bot/twitch/api.py` reçoit une nouvelle méthode :

```python
async def get_stream(self) -> dict:
    """Appelle GET /helix/streams?user_id={self._broadcaster_id}.
    Retourne {live, title, category, viewers, started_at, last_stream_at}.
    Utilise self._tm.bot_token (cohérent avec send_message()).
    """
```

- Lit `self._broadcaster_id` (déjà en attribut, cohérent avec `send_message()`).
- Token : `self._tm.bot_token` — `_tm` est le nom réel de l'attribut dans `TwitchAPI.__init__`.
- Si `data` vide → stream offline, retourne `{live: False, last_stream_at: None, ...}`.

---

## Background Task — Snapshots 5min

Dans `dashboard/app.py`, via la lifespan FastAPI :

```python
async def _snapshot_task(state: AppState):
    # Snapshot immédiat au démarrage — le graphe 24h est disponible dès l'ouverture du dashboard
    await state.db.insert_emotion_snapshot(state.emotion.get_state())
    while True:
        await asyncio.sleep(300)  # 5 minutes
        await state.db.insert_emotion_snapshot(state.emotion.get_state())
```

> Coexiste avec les snapshots horaires existants du decay loop d'`emotion.py` (toutes les 60 ticks ≈ 60 min). Les deux sources écrivent dans `emotion_history` indépendamment — pas de conflit, la table accepte plusieurs rows par période.

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
  #tab-stats      Compteur messages depuis dernier démarrage
  #tab-admin-config     Formulaire config.yaml (sliders λ, sélecteur modèle, champs)
  #tab-admin-emotions   5 jauges éditables + bouton Reset à neutre (0.5)
  #tab-admin-logs       Flux SSE logs avec filtre niveau
<div#auth-modal>  Saisie token → localStorage
```

---

## Design Dark Neobrutalism

Règles non-négociables :

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
| `bot/main.py` | Création `AppState` (avec `twitch_api`), wiring `dashboard_state` sur les bots, ajout `uvicorn.Server` dans `asyncio.gather()` |
| `bot/twitch/api.py` | Ajout méthode `get_stream()` |
| `bot/discord/bot.py` | Attribut `dashboard_state: Optional[AppState] = None` dans `__init__()` |
| `bot/twitch/bot.py` | Attribut `dashboard_state: Optional[AppState] = None` dans `__init__()` |
| `bot/discord/handlers.py` | Incrémentation `if self.dashboard_state: self.dashboard_state.message_count += 1` |
| `bot/twitch/handlers.py` | Incrémentation `if self.dashboard_state: self.dashboard_state.message_count += 1` |
| `docker-compose.yml` | Ajout `ports: ["127.0.0.1:8080:8080"]` sur le service `wally` |
| `requirements.txt` | Ajout `fastapi>=0.111.0` et `uvicorn>=0.30.0` |

> `emotion_history` table déjà présente dans `database.py`. Aucune migration DB nécessaire.

---

## Hors scope Phase 1 (prévu phases suivantes)

- Gestion mémoire mem0 (liste users, souvenirs, suppression, recherche sémantique) — Phase 2
- Dashboard coûts OpenAI (graphiques, breakdown) — Phase 2
- Éditeur Persona (SOUL/IDENTITY/VOICE/EMOTIONS + templates prompts) — Phase 3
- Gestion timeouts (liste mutes actifs, historique) — Phase 3
- Historique pics émotion (quel user a déclenché quoi) — Phase 3
- Persistance du compteur `message_count` entre redémarrages (repart à 0 — acceptable Phase 1)
