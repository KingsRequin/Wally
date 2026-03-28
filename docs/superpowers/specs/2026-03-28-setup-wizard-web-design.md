# Setup Wizard Web — Design Spec
**Date :** 2026-03-28
**Statut :** Validé

## Contexte

Wally doit pouvoir être cloné pour d'autres utilisateurs hébergés sur le même serveur. L'opérateur (toi) génère un lien d'invitation unique, l'envoie au client. Le client ouvre le lien dans son navigateur et configure son instance via un wizard guidé, sans aucun accès au serveur. Le serveur crée l'instance et la démarre automatiquement.

---

## Architecture générale

### Principe d'isolation

```
/opt/stacks/wally-ai/                  ← code source partagé (image Docker unique)
  docker-compose.yml                   ← ton instance (Wally)

/opt/stacks/wally-instances/
  {slug}/                              ← une instance par client
    .env
    config.yaml
    bot/persona/
      SOUL.md / IDENTITY.md / VOICE.md / EMOTIONS.md / EXEMPLES.md / WEEKDAYS.md
      prompts/  → symlink vers /opt/stacks/wally-ai/bot/persona/prompts/
    data/
    logs/
    docker-compose.yml
```

**Image Docker unique** : toutes les instances utilisent la même image buildée depuis `/opt/stacks/wally-ai`. Une mise à jour du code (git pull + docker build) se propage à toutes les instances au prochain redémarrage. Seules les configs, `.env` et fichiers persona sont propres à chaque instance.

**Qdrant partagé** : chaque instance configure son propre `collection_name` dans `config.yaml` (ex: `wally_cindy`). Le service Qdrant existant est réutilisé via `QDRANT_URL=http://wally-qdrant:6333` sur le réseau Docker `wally-net`.

**Port** : chaque instance reçoit un port incrémental à partir de 8081 (8081, 8082…). Assigné au moment du provisioning, stocké en base.

---

## Nouveaux fichiers

| Fichier | Rôle |
|---|---|
| `bot/dashboard/routes/setup.py` | Toutes les routes du wizard |
| `bot/dashboard/static/setup.html` | SPA wizard (indépendant de `index.html`) |
| `bot/core/provisioner.py` | Création de l'instance + docker compose up |

---

## Tables SQLite

### `setup_invites`
```sql
CREATE TABLE setup_invites (
    token       TEXT PRIMARY KEY,
    slug        TEXT,                  -- NULL jusqu'à utilisation
    created_at  REAL NOT NULL,
    expires_at  REAL,                  -- NULL si is_preview=1
    used_at     REAL,                  -- NULL = pas encore utilisé
    is_preview  INTEGER DEFAULT 0,     -- 1 = lien admin réutilisable
    port        INTEGER                -- assigné au submit
);
```

### `setup_sessions`
Stocke les données de formulaire entre les étapes (clés saisies, tokens Twitch récupérés).
```sql
CREATE TABLE setup_sessions (
    token       TEXT PRIMARY KEY,
    step_data   TEXT NOT NULL DEFAULT '{}',   -- JSON des champs par étape
    updated_at  REAL NOT NULL
);
```

---

## Routes FastAPI — `bot/dashboard/routes/setup.py`

### Admin (Bearer token requis)
| Méthode | Route | Action |
|---|---|---|
| `POST` | `/api/admin/setup/invite` | Génère un token UUID4, expire dans 7 jours |
| `GET` | `/api/admin/setup/invites` | Liste tokens (statut: pending/used/expired/revoked) |
| `DELETE` | `/api/admin/setup/invite/{token}` | Révoque (marque expiré immédiatement) |
| `GET` | `/api/admin/setup/instances` | Liste instances créées (slug, port, statut Docker) |
| `POST` | `/api/admin/setup/instances/{slug}/stop` | docker compose stop |
| `POST` | `/api/admin/setup/instances/{slug}/start` | docker compose start |

### Wizard (token dans l'URL, validé à chaque requête)
| Méthode | Route | Action |
|---|---|---|
| `GET` | `/setup/{token}` | Sert `setup.html` (vérifie token valide + non expiré) |
| `GET` | `/setup/preview` | Sert `setup.html` en mode test (admin Bearer uniquement) |
| `POST` | `/api/setup/{token}/save` | Sauvegarde les données d'une étape en session |
| `POST` | `/api/setup/{token}/validate-discord` | Teste le Discord token via l'API Discord |
| `POST` | `/api/setup/{token}/twitch-auth-url` | Génère l'URL OAuth Twitch (bot ou streamer) |
| `GET` | `/api/setup/{token}/twitch/callback` | Reçoit le code OAuth, échange contre les tokens |
| `GET` | `/api/setup/{token}/twitch-status` | Polling : statut bot/streamer connecté |
| `POST` | `/api/setup/{token}/submit` | Crée l'instance et lance Docker (ou simule en mode preview) |

---

## Étapes du Wizard

### Navigation
- **En avant** : validation de l'étape courante obligatoire avant de passer à la suivante
- **En arrière** : libre, clic sur n'importe quelle étape complétée dans la barre de progression
- **Sauvegarde automatique** : chaque champ est envoyé à `/api/setup/{token}/save` à la sortie de l'étape (pas à la frappe)

### Barre de progression
- Cercles numérotés ① à ⑥
- Complétées : vert + coche, cliquables
- Active : cyan, bordure glow
- Futures : grisées, non cliquables

---

### Étape 1 — Bienvenue

Texte d'introduction expliquant :
- Ce que le wizard va configurer (Discord, clés API, optionnellement Twitch, personnalité du bot)
- Ce qui est **requis** vs **optionnel** (liste visuelle avec icônes)
- Durée estimée : ~10 minutes
- Un avertissement : "Garde cette page ouverte — le lien expire dans 7 jours"

Aucun champ. Bouton "Commencer →".

---

### Étape 2 — Discord

**Objectif** : configurer la connexion du bot au serveur Discord.

Champs :
| Champ | Requis | Aide contextuelle |
|---|---|---|
| Discord Bot Token | ✅ | Lien + étapes exactes : discord.com/developers → ton app → "Bot" → "Reset Token" |
| Discord Guild ID | ✅ | Paramètres Discord → Mode développeur → clic droit sur le serveur → "Copier l'ID" |
| Discord Client ID | ✅ | Onglet "OAuth2" de l'app Discord |
| Discord Client Secret | ✅ | Onglet "OAuth2" → "Réinitialiser le secret" |

**Bouton "Tester la connexion"** : appelle `POST /api/setup/{token}/validate-discord`. Le serveur tente `GET https://discord.com/api/v10/users/@me` avec le token. Retourne le nom du bot ou une erreur claire.

Validation avant de continuer : tous les champs remplis + test réussi.

---

### Étape 3 — Clés API

Champs :
| Champ | Requis | Aide contextuelle |
|---|---|---|
| OpenAI API Key | ✅ | platform.openai.com/api-keys → "Create new secret key" |
| Anthropic API Key | ❌ | console.anthropic.com → "API Keys". Laisser vide si non utilisé. |
| Tavily API Key | ❌ | app.tavily.com. Permet la recherche web. Laisser vide sinon. |

Validation avant de continuer : clé OpenAI remplie.

---

### Étape 4 — Twitch *(optionnel)*

En-tête : "⚠️ Cette étape est optionnelle. Si ton bot est uniquement pour Discord, clique sur 'Passer cette étape'."

**Sous-étape 4a — Application Twitch**

| Champ | Aide |
|---|---|
| Twitch Client ID | dev.twitch.tv/console → ton app → Client ID |
| Twitch Client Secret | "Nouveau secret" dans la console Twitch |
| Twitch Bot Nick | Nom d'utilisateur du compte bot |

**Sous-étape 4b — Connexion compte bot**

Bouton "Connecter le compte bot →". Ouvre l'URL OAuth dans un nouvel onglet :
```
https://id.twitch.tv/oauth2/authorize
  ?response_type=code
  &client_id={client_id}
  &redirect_uri={WEB_BASE_URL}/api/setup/{token}/twitch/callback
  &scope=user:read:chat+user:write:chat+user:bot+moderator:read:followers+chat:read+chat:edit
  &state={token}:bot
```

Le serveur reçoit le callback, échange le code via `POST https://id.twitch.tv/oauth2/token`.
Stocke `access_token`, `refresh_token`, `user_id` dans `setup_sessions.step_data`.

La page poll `GET /api/setup/{token}/twitch-status` toutes les 2s. Quand `bot_connected: true`, affiche "✅ Compte bot connecté : @{username}".

**Sous-étape 4c — Connexion compte streamer**

Même flow avec `state={token}:streamer` et scope `bits:read+channel:read:subscriptions+moderator:read:followers`.

---

### Étape 5 — Personnalité

**Sous-étape 5a — Paramètres de base**

| Champ | Défaut | Description |
|---|---|---|
| Nom du bot | `"monbot"` | Utilisé dans `trigger_names` et les fichiers persona |
| Langue par défaut | `"fr"` | Dropdown : fr / en |
| Mots déclencheurs | `["monbot"]` | Tags éditables (chips) |

**Sous-étape 5b — Fichiers persona**

Onglets : `SOUL.md` | `IDENTITY.md` | `VOICE.md` | `EMOTIONS.md`

Chaque onglet = textarea pleine largeur pré-remplie avec le contenu des fichiers persona de Wally (template de départ). Le client édite librement.

---

### Étape 6 — Lancement

**Récapitulatif** : tableau de toutes les infos configurées (tokens masqués par `***`, ✅/❌ par section).

**Mode normal** : bouton "🚀 Créer mon instance".

**Mode preview (admin)** : toggle "Simulation / Créer vraiment". En simulation, affiche le `.env` et `config.yaml` qui auraient été générés (valeurs sensibles masquées).

**À la soumission** — barre de progression :
"Création des fichiers…" → "Configuration Docker…" → "Démarrage…" → "✅ Prêt !"

En cas d'erreur : message clair + bouton "Réessayer".
En cas de succès : URL de l'instance + instructions DNS.

---

## Provisioner — `bot/core/provisioner.py`

```python
async def provision_instance(slug: str, port: int, data: dict) -> str:
    """Crée le répertoire d'instance, génère les fichiers, lance Docker. Retourne l'URL."""
```

**Étapes** :
1. Créer `/opt/stacks/wally-instances/{slug}/` avec `data/`, `logs/`, `bot/persona/`
2. Générer `.env` : tous les tokens + `JWT_SECRET` auto-généré via `secrets.token_hex(32)` + `QDRANT_URL=http://wally-qdrant:6333` + `DB_PATH=data/wally.db`
3. Générer `config.yaml` depuis les défauts + `trigger_names`, `language_default`, `collection_name=wally_{slug}`
4. Écrire les 4 fichiers persona
5. Créer symlink `bot/persona/prompts → /opt/stacks/wally-ai/bot/persona/prompts`
6. Générer `docker-compose.yml` (réseau `wally-net` external, image `wally-ai-wally`, port `{port}:8080`)
7. Lancer `docker compose -f .../docker-compose.yml up -d` via `asyncio.create_subprocess_exec` (timeout 60s)
8. Marquer le token comme utilisé dans `setup_invites`

---

## Intégration dans le dashboard admin

Nouvel onglet **"Instances"** dans le panel admin, avec trois sous-sections :

- **Invitations** : tableau (token tronqué, créé le, expire le, statut: pending/used/expired/revoked). Bouton "Générer un lien" + copier. Bouton "Révoquer".
- **Instances actives** : cards avec nom, port, URL, statut Docker. Boutons démarrer/arrêter.
- **Prévisualiser** : bouton qui ouvre `/setup/preview` dans un nouvel onglet (badge "MODE TEST" visible).

---

## Mode preview — implémentation

`/setup/preview` sert `setup.html` avec `token="__preview__"` injecté en variable JS.
Toutes les routes `/api/setup/{token}/...` vérifient si `token == "__preview__"` : si oui, exigent le **Bearer token admin** en plus. Cela permet de réutiliser exactement les mêmes routes API sans code dupliqué.

Une entrée fixe `token="__preview__", is_preview=1, expires_at=NULL` est insérée au démarrage du dashboard si elle n'existe pas déjà.

---

## Sécurité

- Token wizard validé à **chaque requête** (présence, non-expiré, non-utilisé)
- Token `__preview__` nécessite en plus le Bearer admin — jamais accessible à un client externe
- Tokens secrets jamais renvoyés au client après sauvegarde (masqués par `***`)
- `.env` généré jamais lisible via l'API
- `JWT_SECRET` auto-généré — jamais fourni par le client
- Répertoire `wally-instances/` hors du webroot

---

## Hors scope

- Interface de mise à jour des instances (un `docker pull` + restart suffit)
- Migration de config entre versions
- Reverse proxy / SSL automatique (le client configure son DNS manuellement)
