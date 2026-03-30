# Spec — Authentification Twitch OAuth dans le dashboard admin

**Date** : 2026-03-30
**Scope** : Système > Twitch tab du dashboard admin (bot principal + instances)

---

## Contexte

Le bot Twitch nécessite deux tokens OAuth distincts stockés dans `.env` :

- `BOT_ACCESS_TOKEN` / `BOT_REFRESH_TOKEN` — compte bot (ex. WallyTeBully)
- `STREAMER_ACCESS_TOKEN` / `STREAMER_REFRESH_TOKEN` — compte broadcaster (différent par instance)

Ces tokens expirent et, quand le refresh échoue, le bot Twitch ne démarre plus. Actuellement il faut éditer `.env` manuellement. Cette spec ajoute un flux OAuth complet dans le dashboard admin, accessible depuis **Système > Twitch**, fonctionnel pour le bot principal et pour chaque instance (même code, `.env` différent).

---

## Architecture

### Nouveau fichier : `bot/dashboard/routes/twitch_auth.py`

Monté sur le router admin existant (Bearer auth héritée).

| Route | Méthode | Rôle |
|---|---|---|
| `/api/admin/twitch/auth-status` | GET | Statut bot + streamer (username, valide ou non) |
| `/api/admin/twitch/auth-url` | POST | Génère l'URL OAuth Twitch |
| `/api/admin/twitch/auth/callback` | GET | Callback OAuth — échange code, écrit `.env`, push SSE |
| `/api/admin/twitch/restart` | POST | Redémarre le container via `docker compose restart wally` |

### État OAuth en mémoire

```python
_pending_states: dict[str, dict] = {}
# state_key -> {"account": "bot"|"streamer", "expires_at": float}
```

Expiration : 10 minutes. Nettoyage à chaque appel (supprime les entrées expirées).
Pas de persistance DB — un state non utilisé expire silencieusement.

---

## Scopes OAuth

### Bot (`BOT_ACCESS_TOKEN`)

Utilisé pour : envoyer/recevoir messages via EventSub, IRC fallback, badge bot, follows.

```
user:read:chat
user:write:chat
user:bot
moderator:read:followers
chat:read
chat:edit
```

### Streamer (`STREAMER_ACCESS_TOKEN`)

Utilisé pour : EventSub subscriptions (subs, resub, gift, end) et bits.

```
channel:read:subscriptions
bits:read
```

---

## Flux OAuth

```
Admin clique "Connecter"
  → POST /api/admin/twitch/auth-url {account: "bot"|"streamer"}
    → backend génère state aléatoire (uuid4), stocke en mémoire 10 min
    → retourne {url: "https://id.twitch.tv/oauth2/authorize?..."}
  → dashboard ouvre popup window.open(url, "_blank", "width=600,height=700")
  → Twitch redirige vers /api/admin/twitch/auth/callback?code=...&state=...
    → backend valide state (existence + expiration)
    → échange code contre tokens via POST https://id.twitch.tv/oauth2/token
    → GET /helix/users pour récupérer username + user_id
    → écrit tokens dans .env via token_manager._write_env()
    → écrit aussi les IDs dans .env :
        bot     → TWITCH_BOT_ID, TWITCH_BOT_NICK
        streamer → TWITCH_BROADCASTER_ID
    → met à jour token_manager._bot_token / _streamer_token en mémoire
    → push SSE {"type": "twitch_auth", "account": "bot", "username": "..."}
    → retourne HTML "✅ Connecté — tu peux fermer cet onglet" + window.close()
  → dashboard reçoit SSE, met à jour la card, affiche bouton "Redémarrer"
Admin clique "Redémarrer le container"
  → POST /api/admin/twitch/restart
    → subprocess.Popen([docker, compose, -f, COMPOSE_FILE, restart, wally], start_new_session=True)
    → retourne {status: "restarting"} immédiatement
```

### URL de callback

```python
base_url = os.getenv("WEB_BASE_URL", str(request.base_url).rstrip("/"))
redirect_uri = f"{base_url}/api/admin/twitch/auth/callback"
```

`WEB_BASE_URL` est déjà défini dans `.env` pour le setup wizard — même variable réutilisée.

### Gestion d'erreurs callback

- `state` inconnu ou expiré → HTML d'erreur "Lien expiré, réessaie depuis le dashboard"
- Échange de code échoué (Twitch erreur) → HTML d'erreur + log
- `/helix/users` échoue → tokens sauvés quand même, username = "" (non bloquant)

---

## Endpoint `auth-status`

```python
GET /api/admin/twitch/auth-status
→ {
    "bot": {
      "connected": bool,      # token_manager.bot_token non vide ET validation OK
      "username": str,         # depuis /helix/users ou "" si inconnu
      "user_id": str,
    },
    "streamer": {
      "connected": bool,
      "username": str,
      "user_id": str,
    },
    "client_id_set": bool      # TWITCH_CLIENT_ID présent dans env
  }
```

La validation se fait via `GET https://id.twitch.tv/oauth2/validate` (même endpoint que `token_manager.startup_validate`). Résultat mis en cache 60 secondes côté backend pour éviter les appels répétés.

---

## Endpoint `restart`

```python
POST /api/admin/twitch/restart
```

Même pattern que `POST /api/admin/self-update` :

```python
compose_file = os.getenv("COMPOSE_FILE", "/app/docker-compose.yml")
subprocess.Popen(
    ["/usr/bin/docker", "compose", "-f", compose_file, "restart", "wally"],
    start_new_session=True,
)
return {"status": "restarting"}
```

---

## SSE

Réutilise le canal SSE existant (`/api/admin/sse/`). Nouvel event type :

```json
{"type": "twitch_auth", "account": "bot", "username": "WallyTeBully"}
```

Le dashboard écoute déjà le SSE admin (pour les actions, les logs) — pas de nouvelle connexion SSE.

---

## UI — Système > Twitch

`_renderSystemeTwitch` est réécrit pour afficher :

### Structure

```
┌──────────────────────────────────────────────────────────────┐
│ AUTHENTIFICATION TWITCH                                       │
│                                                               │
│ ┌─────────────────────────┐  ┌─────────────────────────┐    │
│ │ 🤖 Compte Bot           │  │ 📺 Compte Streamer       │    │
│ │ ● WallyTeBully (validé) │  │ ○ Non connecté           │    │
│ │ Scopes : user:read:chat │  │ Scopes requis :           │    │
│ │  user:write:chat …      │  │  channel:read:sub…       │    │
│ │ [Reconnecter]           │  │ [Connecter]              │    │
│ └─────────────────────────┘  └─────────────────────────┘    │
│                                                               │
│ ─────────────────────────────────────────────────────────    │
│                                                               │
│ CHAÎNES INVITÉES                                             │
│ [liste existante]                                            │
└──────────────────────────────────────────────────────────────┘

[🔄 Redémarrer le container]  ← affiché si _pendingRestart = true
```

### Comportement

- Statut chargé depuis `GET /api/admin/twitch/auth-status` à l'ouverture du tab
- `TWITCH_CLIENT_ID` absent → message d'avertissement "Configure TWITCH_CLIENT_ID dans .env"
- Après réception du SSE `twitch_auth` : card mise à jour, `_pendingRestart = true`
- Bouton "Redémarrer" visible uniquement si `_pendingRestart = true`
- Les scopes sont affichés en liste compacte sous le username

### Design

Suit le système glassmorphism existant (même style que les cards overlay) :
- `rgba(255,255,255,0.03)` + `backdrop-filter: blur(10px)`
- Dot vert/rouge pour statut connecté/déconnecté
- Bouton "Connecter" : style `btn btn-success`
- Bouton "Redémarrer" : style amber pulse (comme le bouton self-update existant)

---

## Fichiers modifiés / créés

| Fichier | Action |
|---|---|
| `bot/dashboard/routes/twitch_auth.py` | **Créer** — 4 routes OAuth |
| `bot/dashboard/app.py` | **Modifier** — monter le nouveau router |
| `bot/dashboard/static/app.js` | **Modifier** — réécrire `_renderSystemeTwitch`, handler SSE `twitch_auth` |

---

## Ce qui n'est PAS dans le scope

- Réinitialisation "à chaud" du bot Twitch sans redémarrage
- Modification de `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` depuis le dashboard (déjà dans `/wally setup`)
- Flux OAuth pour les instances via le setup wizard (les instances utilisent le même dashboard admin après déploiement)
