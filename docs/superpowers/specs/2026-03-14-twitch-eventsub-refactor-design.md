# Twitch EventSub Refactor — Design Spec

**Date:** 2026-03-14
**Status:** Approved

---

## Contexte

Le bot Twitch utilise actuellement deux mécanismes distincts :
- Une connexion **IRC** via twitchio pour lire et envoyer les messages chat
- Un client **EventSub WebSocket** (twitchio `EventSubWSClient`) pour les events canal (follows, subs, bits, raids)

IRC est une technologie legacy que Twitch n'investit plus. Ce refactoring migre la lecture des messages chat vers EventSub (`channel.chat.message`) et l'envoi de réponses vers l'API Helix (`POST /helix/chat/messages`). Il ajoute également la gestion propre du cycle de vie des tokens (refresh natif Twitch, validation au démarrage, persistance dans `.env`).

---

## Objectifs

1. Supprimer la connexion IRC — tout passe par EventSub WebSocket
2. Envoyer les messages via l'API Helix au lieu d'IRC
3. Implémenter le refresh automatique des tokens pour les deux comptes (bot + streamer) via l'endpoint natif Twitch
4. Valider les tokens au démarrage
5. Persister les tokens rafraîchis dans `.env` de manière atomique
6. Ajouter les events `channel.subscription.gift` et `channel.subscription.end`
7. Renommer les variables d'environnement pour clarifier bot vs streamer

---

## Variables d'environnement

### Ancien → Nouveau

| Ancien | Nouveau | Notes |
|---|---|---|
| `TWITCH_BOT_TOKEN` | `BOT_ACCESS_TOKEN` | |
| `TWITCH_REFRESH_TOKEN` | `BOT_REFRESH_TOKEN` | |
| `TWITCH_EVENTSUB_TOKEN` | supprimé | fusionné dans `BOT_ACCESS_TOKEN` |
| `TWITCH_BROADCASTER_TOKEN` | `STREAMER_ACCESS_TOKEN` | |
| *(absent)* | `STREAMER_REFRESH_TOKEN` | nouveau |
| *(absent)* | `TWITCH_CLIENT_SECRET` | nouveau — requis pour refresh natif |
| `TWITCH_CLIENT_ID` | `TWITCH_CLIENT_ID` | inchangé |
| `TWITCH_BROADCASTER_ID` | `TWITCH_BROADCASTER_ID` | inchangé |
| `TWITCH_BOT_ID` | `TWITCH_BOT_ID` | inchangé |
| `TWITCH_BOT_NICK` | `TWITCH_BOT_NICK` | inchangé |

### `.env.example` final

```env
TWITCH_CLIENT_ID=
TWITCH_CLIENT_SECRET=

TWITCH_BROADCASTER_ID=
TWITCH_BOT_ID=
TWITCH_BOT_NICK=wallybot

BOT_ACCESS_TOKEN=
BOT_REFRESH_TOKEN=

STREAMER_ACCESS_TOKEN=
STREAMER_REFRESH_TOKEN=
```

---

## Architecture

### Nouveaux fichiers

#### `bot/twitch/token_manager.py` — `TwitchTokenManager`

Service autonome gérant le cycle de vie des deux tokens.

**Interface publique :**
```python
class TwitchTokenManager:
    bot_token: str        # propriété, toujours la valeur courante
    streamer_token: str   # propriété, toujours la valeur courante

    @classmethod
    def load(cls) -> "TwitchTokenManager":
        """Charge les tokens depuis les variables d'environnement."""

    async def startup_validate(self) -> None:
        """Valide les deux tokens via GET /oauth2/validate.
        Si un token est invalide (401), tente un refresh immédiat.
        Log les scopes et expires_in pour chaque token."""

    async def refresh(self, token_type: Literal["bot", "streamer"]) -> bool:
        """Rafraîchit le token via POST /id.twitch.tv/oauth2/token.
        Met à jour en mémoire et persiste dans .env.
        Retourne True si succès."""
```

**Flux de validation (startup) :**
```
GET https://id.twitch.tv/oauth2/validate
Authorization: OAuth <access_token>

→ 200 : log scopes + expires_in
→ 401 : appel refresh() immédiat
```

**Flux de refresh :**
```
POST https://id.twitch.tv/oauth2/token
  client_id=TWITCH_CLIENT_ID
  client_secret=TWITCH_CLIENT_SECRET
  grant_type=refresh_token
  refresh_token=<current_refresh_token>

→ reçoit { access_token, refresh_token, ... }
→ met à jour self._bot_token / self._streamer_token en mémoire
→ persiste dans .env (écriture atomique)
```

**Réécriture atomique du `.env` :**
1. Lire le contenu complet du `.env`
2. Remplacer les lignes `BOT_ACCESS_TOKEN=...`, `BOT_REFRESH_TOKEN=...` (ou STREAMER) par les nouvelles valeurs via regex
3. Écrire dans `.env.tmp`
4. `os.replace(".env.tmp", ".env")` — atomique sur Linux, évite la corruption si crash

#### `bot/twitch/api.py` — `TwitchAPI`

Thin wrapper httpx pour l'API Helix.

**Interface publique :**
```python
class TwitchAPI:
    def __init__(self, token_manager: TwitchTokenManager, client_id: str, bot_id: str):
        ...

    async def send_message(self, broadcaster_id: str, text: str) -> None:
        """POST /helix/chat/messages. Retry sur 401 (refresh bot token + 1 essai)."""
```

**Endpoint d'envoi :**
```
POST https://api.twitch.tv/helix/chat/messages
Authorization: Bearer <BOT_ACCESS_TOKEN>
Client-Id: <TWITCH_CLIENT_ID>
{
  "broadcaster_id": "<TWITCH_BROADCASTER_ID>",
  "sender_id": "<TWITCH_BOT_ID>",
  "message": "<text>"
}
```

### Fichiers modifiés

#### `bot/twitch/bot.py`

- Reçoit `token_manager: TwitchTokenManager` et `twitch_api: TwitchAPI` en injection DI
- `super().__init__(initial_channels=[])` — aucune connexion IRC établie
- `event_token_expired()` délègue à `token_manager.refresh("bot")`
- `event_message()` supprimé
- `event_ready()` appelle toujours `start_eventsub_client()`

#### `bot/twitch/events.py`

**Abonnements EventSub :**

| Event | Token | Nouveau ? |
|---|---|---|
| `channel.follow` v2 | Bot | non |
| `channel.raid` | Bot | non |
| `channel.chat.message` | Bot | **oui** |
| `channel.subscribe` | Streamer | non |
| `channel.subscription.message` | Streamer | non |
| `channel.subscription.gift` | Streamer | **oui** |
| `channel.subscription.end` | Streamer | **oui** (abonnement seul) |
| `channel.cheer` | Streamer | non |

**Nouveau handler `channel.chat.message` :**
```python
async def event_eventsub_notification_channel_chat_message(payload):
    # payload.chatter.name  → auteur
    # payload.chatter.id    → user_id
    # payload.message.text  → contenu
    # payload.broadcaster.name → channel
    await handle_message(bot, payload)
```

**Nouveau handler `channel.subscription.gift` :**
```python
async def event_eventsub_notification_subscription_gift(payload):
    cfg = bot.config.twitch_events.get("gift_sub")
    if not cfg or not cfg.active:
        return
    bot.emotion.apply_delta("joy", 0.5)
    gifter = payload.user.name if not payload.is_anonymous else "Anonyme"
    await _generate_and_send(
        bot, payload.broadcaster.name, cfg.message,
        username=gifter,
        amount=payload.total,   # nb de gifts dans cette transaction
        months=0,
        raiders_count=0,
    )
    # payload.cumulative_total disponible pour un futur template "X gifts au total"
```

**Handler `channel.subscription.end` :**
```python
async def event_eventsub_notification_subscription_end(payload):
    logger.debug("Sub end: {user}", user=payload.user.name)
    # Pas de réaction visible dans le chat
```

#### `bot/twitch/handlers.py`

`handle_message()` adapté pour un payload EventSub :
```python
async def handle_message(bot: "WallyTwitch", payload) -> None:
    content: str = payload.message.text
    author: str  = payload.chatter.name
    user_id: str = str(payload.chatter.id)
    channel_name: str = payload.broadcaster.name

    # ... logique inchangée ...

    # Envoi via Helix au lieu d'IRC
    await bot.twitch_api.send_message(
        broadcaster_id=os.getenv("TWITCH_BROADCASTER_ID"),
        text=reply,
    )
```

#### `bot/main.py`

- `_resolve_twitch_token()` supprimé
- `TwitchTokenManager.load()` + `await token_manager.startup_validate()` avant l'initialisation des bots
- `TwitchAPI` instancié et injecté dans `WallyTwitch`

#### `config.yaml`

Ajout de l'event `gift_sub` dans `twitch_events` :
```yaml
twitch_events:
  gift_sub:
    active: true
    message: "{username} vient d'offrir {amount} sub(s) ! Merci pour ta générosité !"
```

---

## Gestion des erreurs

| Situation | Comportement |
|---|---|
| Token invalide au démarrage | Refresh immédiat ; si refresh échoue → log ERROR, bot démarre sans ce token |
| 401 sur `send_message` | Refresh bot token + 1 retry ; si toujours 401 → log ERROR, message non envoyé |
| `event_token_expired` twitchio | Délègue à `token_manager.refresh("bot")` |
| Refresh échoue (réseau, secret invalide) | Log ERROR, retourne False, token précédent conservé en mémoire |
| `.env.tmp` write crash | `.env` original intact (rename atomique non effectué) |
| EventSub subscription échoue | Log WARNING par subscription, les autres continuent (comportement existant) |

---

## Tests

- `tests/test_twitch_token_manager.py` — validate, refresh (success + failure), réécriture `.env`
- `tests/test_twitch_api.py` — send_message, retry sur 401
- `tests/test_twitch_handlers.py` — mise à jour pour payload EventSub (remplace objet twitchio Message)
- `tests/test_twitch_events.py` — handlers gift_sub, subscription_end, chat_message

---

## Fichiers créés / modifiés

| Fichier | Action |
|---|---|
| `bot/twitch/token_manager.py` | Créé |
| `bot/twitch/api.py` | Créé |
| `bot/twitch/bot.py` | Modifié |
| `bot/twitch/events.py` | Modifié |
| `bot/twitch/handlers.py` | Modifié |
| `bot/main.py` | Modifié |
| `.env.example` | Modifié |
| `config.yaml` | Modifié (ajout gift_sub) |
| `tests/test_twitch_token_manager.py` | Créé |
| `tests/test_twitch_api.py` | Créé |
| `tests/test_twitch_handlers.py` | Modifié |
