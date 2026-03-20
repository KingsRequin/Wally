# Web Chat Wally — Design Spec

> Date: 2026-03-20
> Status: Approved

---

## Objectif

Ajouter un chat en temps réel sur le dashboard web, permettant aux utilisateurs de discuter avec Wally via le navigateur. Le circuit de traitement est identique à Discord/Twitch (mêmes services core), avec en plus un avatar animé reflétant l'état émotionnel.

---

## Décisions de design

| Aspect | Décision | Raison |
|---|---|---|
| Auth | Discord OAuth2 obligatoire | Identifie l'utilisateur, lie la mémoire à `discord:{user_id}` |
| Mémoire | Partagée avec Discord (`discord:{user_id}`) | Un seul profil par personne, peu importe la plateforme |
| Type de chat | Salon unique partagé | Communauté visible, ambiance salon Discord |
| Trigger | Wally répond à chaque message | C'est son chat dédié |
| Cooldown | Par utilisateur, configurable | Prévenir le spam et les coûts OpenAI |
| Historique | Persisté en SQLite, N derniers chargés | Contexte à l'arrivée |
| Transport | WebSocket | Temps réel bidirectionnel, typing indicator |
| Avatar | GIF/PNG par émotion + tier | Personnification visuelle de Wally |

---

## 1. Auth — Discord OAuth2

### Flow

1. Utilisateur clique "Se connecter avec Discord"
2. `GET /api/chat/auth/login` → redirect vers Discord authorize URL
   - Scope: `identify` uniquement
   - Redirect URI: `{BASE_URL}/api/chat/auth/callback`
3. `GET /api/chat/auth/callback` → échange le `code` contre un access token via Discord API
4. Fetch `GET https://discord.com/api/users/@me` avec le token → récupère `id`, `username`, `avatar`
5. Génère un **JWT** signé avec `dashboard_token` (de `config.yaml`):
   ```json
   {
     "discord_id": "123456789",
     "username": "KingsRequin",
     "avatar_url": "https://cdn.discordapp.com/avatars/...",
     "exp": 1711000000
   }
   ```
   Expiration: **1 heure**
6. Génère un **refresh token** (UUID opaque), stocké en SQLite (`chat_refresh_tokens`), expiration **30 jours**
7. Retourne JWT + refresh token au client (stockés en `localStorage`)

### Refresh silencieux

- `GET /api/chat/auth/refresh` avec le refresh token en header
- Si valide et non expiré → nouveau JWT (1h) + nouveau refresh token (30j, rotation)
- Si expiré → 401, l'utilisateur doit se reconnecter via Discord
- Le client appelle automatiquement le refresh quand le JWT expire (ou au chargement de la page)

### Endpoint profil

- `GET /api/chat/auth/me` avec JWT en header → retourne le profil Discord (id, username, avatar)
- Utilisé au chargement pour vérifier si l'utilisateur est toujours connecté

### Variables d'environnement

```
DISCORD_CLIENT_ID=...        # Application ID dans Discord Developer Portal
DISCORD_CLIENT_SECRET=...   # OAuth2 secret (jamais exposé au client)
```

Le JWT est signé avec `dashboard_token` déjà présent dans `config.yaml` — pas de secret supplémentaire.

---

## 2. WebSocket & message flow

### Connexion

```
Client → WS /ws/chat?token={JWT}
Serveur → valide JWT
        → si invalide: close(4001, "Invalid token")
        → si valide: ajoute le client au pool, envoie les N derniers messages
```

### Format des messages

**Client → Serveur:**
```json
{
  "type": "message",
  "content": "Salut Wally !"
}
```

**Serveur → Client (message utilisateur):**
```json
{
  "type": "message",
  "id": 42,
  "discord_id": "discord:123456789",
  "username": "KingsRequin",
  "avatar_url": "https://cdn.discordapp.com/...",
  "content": "Salut Wally !",
  "is_wally": false,
  "created_at": 1711000000.0
}
```

**Serveur → Client (réponse Wally):**
```json
{
  "type": "message",
  "id": 43,
  "discord_id": "wally",
  "username": "Wally",
  "avatar_url": null,
  "content": "Hey ! Comment ça va ?",
  "is_wally": true,
  "created_at": 1711000001.0
}
```

**Serveur → Client (typing indicator):**
```json
{
  "type": "typing",
  "username": "Wally"
}
```

**Serveur → Client (historique initial):**
```json
{
  "type": "history",
  "messages": [...]
}
```

### Pipeline de traitement

À la réception d'un message utilisateur:

1. **Valider** le cooldown (rejet silencieux si en cooldown)
2. **Persister** en SQLite (`chat_messages`)
3. **Broadcast** le message à tous les clients WS connectés
4. **Append** dans `memory.append_message("web:chat", username, content, platform="web")`
5. **Broadcast** typing indicator
6. **Pipeline Wally** (identique à Discord):
   - Trust score lookup (`discord:{user_id}`)
   - Memory search (`discord:{user_id}`, query=content, context=prelude)
   - PromptBuilder: situation `{"platform": "Web", "channel": "Chat public"}`
   - `openai_client.complete()` avec purpose `"web_response"`
7. **Broadcast** réponse Wally à tous les clients
8. **Persister** réponse Wally en SQLite
9. **Append** Wally dans context_window
10. **Post-process** (émotion, trust, love) — même `_post_process` que Discord

### Gestion des connexions

- Pool de clients: `dict[WebSocket, UserInfo]`
- À la déconnexion: retrait du pool, pas de cleanup spécial
- Pas de heartbeat custom — le protocole WS gère les pings/pongs

---

## 3. Avatar animé

### Structure de dossiers

```
bot/dashboard/static/avatar/
├── emotions/
│   ├── neutral/
│   │   └── idle.gif|.png
│   ├── joy/
│   │   ├── low.gif|.png
│   │   ├── mid.gif|.png
│   │   └── high.gif|.png
│   ├── anger/
│   │   ├── low.gif|.png
│   │   ├── mid.gif|.png
│   │   └── high.gif|.png
│   ├── sadness/
│   │   ├── low.gif|.png
│   │   ├── mid.gif|.png
│   │   └── high.gif|.png
│   ├── curiosity/
│   │   ├── low.gif|.png
│   │   ├── mid.gif|.png
│   │   └── high.gif|.png
│   └── boredom/
│       ├── low.gif|.png
│       ├── mid.gif|.png
│       └── high.gif|.png
└── random/
    └── (animations aléatoires: gaming.gif, sleeping.gif, etc.)
```

### Logique de sélection (côté client JS)

1. Réception SSE émotions (toutes les 5s, existant)
2. Trouver l'émotion dominante (score le plus élevé)
3. Déterminer le tier:
   - `>= 0.7` → `high`
   - `>= 0.4` → `mid`
   - `>= 0.2` → `low`
   - `< 0.2` pour toutes → `neutral/idle`
4. Tirage random (probabilité `random_avatar_chance`):
   - Si tirage positif et dossier `random/` non vide → GIF/PNG aléatoire
   - Sinon → `emotions/{emotion}/{tier}.gif` (fallback `.png` si pas de GIF)
5. Mettre à jour le `<img>` de l'avatar (avec transition CSS)

### Format accepté

- `.gif` (prioritaire — animations)
- `.png` (fallback — images statiques)
- Le JS cherche d'abord `{tier}.gif`, puis `{tier}.png`

---

## 4. Base de données

### Table `chat_messages`

```sql
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_id TEXT NOT NULL,
    username TEXT NOT NULL,
    avatar_url TEXT,
    content TEXT NOT NULL,
    is_wally BOOLEAN DEFAULT 0,
    created_at REAL NOT NULL
);
```

### Table `chat_refresh_tokens`

```sql
CREATE TABLE IF NOT EXISTS chat_refresh_tokens (
    token TEXT PRIMARY KEY,
    discord_id TEXT NOT NULL,
    username TEXT NOT NULL,
    avatar_url TEXT,
    expires_at REAL NOT NULL
);
```

### Requêtes principales

- **Charger historique:** `SELECT * FROM chat_messages ORDER BY id DESC LIMIT ?` → inversé côté client
- **Insérer message:** `INSERT INTO chat_messages (discord_id, username, avatar_url, content, is_wally, created_at) VALUES (?, ?, ?, ?, ?, ?)`
- **Cleanup refresh tokens:** `DELETE FROM chat_refresh_tokens WHERE expires_at < ?` (cron ou au login)

---

## 5. Configuration

### `config.yaml` — nouvelle section

```yaml
web_chat:
  cooldown_seconds: 10        # cooldown par utilisateur entre messages
  history_limit: 50           # nombre de messages chargés à l'arrivée
  random_avatar_chance: 0.05  # probabilité d'animation random (5%)
```

### `.env` — nouvelles variables

```
DISCORD_CLIENT_ID=...        # ID application Discord (Developer Portal)
DISCORD_CLIENT_SECRET=...   # Secret OAuth2 (Developer Portal, jamais exposé au client)
```

---

## 6. Fichiers à créer/modifier

### Nouveaux fichiers

| Fichier | Rôle |
|---|---|
| `bot/dashboard/routes/chat_auth.py` | Routes OAuth2: login, callback, refresh, me |
| `bot/dashboard/routes/chat.py` | WebSocket `/ws/chat`, logique message, broadcast |
| `bot/dashboard/static/avatar/` | Arborescence complète avec README.txt par dossier |

### Fichiers à modifier

| Fichier | Modification |
|---|---|
| `bot/db/database.py` | Tables `chat_messages` + `chat_refresh_tokens`, query helpers |
| `bot/config.py` | Dataclass `WebChatConfig`, intégration dans Config |
| `bot/dashboard/app.py` | Enregistrement des nouvelles routes + WS |
| `bot/dashboard/auth.py` | Exempter les routes `/api/chat/auth/*` du bearer token |
| `bot/dashboard/static/index.html` | Nouvel onglet "Chat" dans la sidebar (public) |
| `bot/dashboard/static/app.js` | UI chat: connexion Discord, messages, avatar, WS |
| `bot/dashboard/static/style.css` | Styles du chat et de l'avatar |

### Tests

| Fichier | Couverture |
|---|---|
| `tests/test_chat_auth.py` | OAuth2 flow, JWT generation/validation, refresh |
| `tests/test_chat_websocket.py` | WS connect, message broadcast, cooldown, history |
| `tests/test_chat_db.py` | Tables, insert, load history, refresh token CRUD |

---

## 7. Onglet Chat — UX

### Layout

```
┌──────────────────────────────────────┐
│  [Avatar Wally]   Wally est joyeux   │  ← avatar + résumé émotion
├──────────────────────────────────────┤
│                                      │
│  KingsRequin: Salut Wally !          │
│  Wally: Hey ! Quoi de neuf ?         │  ← zone messages scrollable
│  Alice: Il est en forme aujourd'hui  │
│  Wally: Toujours ! 😄               │
│                                      │
├──────────────────────────────────────┤
│  [Message...]              [Envoyer] │  ← input + bouton
└──────────────────────────────────────┘
```

- L'avatar se met à jour toutes les 5s via SSE émotions
- Typing indicator ("Wally réfléchit...") affiché entre la zone messages et l'input
- Messages de Wally visuellement distincts (fond/couleur différente)
- Avatar Discord de chaque utilisateur affiché à côté de son message
- Bouton "Se connecter avec Discord" affiché si pas authentifié, remplace la zone chat
- Design cohérent avec le reste du dashboard (dark theme existant)

---

## 8. Sécurité

- **OAuth2:** Le `DISCORD_CLIENT_SECRET` reste côté serveur, jamais envoyé au client
- **JWT:** Signé avec `dashboard_token`, vérifié à chaque connexion WS
- **Refresh token rotation:** Chaque refresh génère un nouveau token (l'ancien est invalidé)
- **Cooldown:** Prévient le spam et les coûts OpenAI excessifs
- **Validation input:** Longueur max du message (2000 chars), strip, pas de messages vides
- **XSS:** Tout contenu utilisateur échappé avant affichage (même pattern que le dashboard existant)
