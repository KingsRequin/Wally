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
| `TWITCH_BOT_NICK` | `TWITCH_BOT_NICK` | inchangé — toujours requis pour la détection de trigger dans handlers.py |

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
    def load(cls, env_path: Path) -> "TwitchTokenManager":
        """Charge les tokens depuis les variables d'environnement.
        env_path : chemin absolu vers le fichier .env (résolu par main.py)."""

    async def startup_validate(self) -> None:
        """Valide les deux tokens via GET /oauth2/validate.
        Si un token est invalide (401), tente un refresh immédiat.
        Log les scopes et expires_in pour chaque token.
        Lève TwitchTokenError si le bot_token est manquant ou irrécupérable."""

    async def refresh(self, token_type: Literal["bot", "streamer"]) -> bool:
        """Rafraîchit le token via POST /id.twitch.tv/oauth2/token.
        Met à jour en mémoire et persiste dans .env.
        Retourne True si succès."""
```

**Résolution du chemin `.env` :**
`main.py` résout le chemin absolu du `.env` via `pathlib.Path(__file__).parent.parent / ".env"` et le passe à `TwitchTokenManager.load()`. Toutes les opérations fichier utilisent ce chemin absolu — jamais un chemin relatif dépendant du CWD.

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
1. Lire le contenu complet du `.env` via le chemin absolu (`env_path`)
2. Remplacer les lignes `BOT_ACCESS_TOKEN=...`, `BOT_REFRESH_TOKEN=...` (ou `STREAMER_*`) par les nouvelles valeurs via regex
3. Écrire dans `env_path.parent / ".env.tmp"`
4. `os.replace(str(env_path.parent / ".env.tmp"), str(env_path))` — atomique sur Linux, évite la corruption si crash entre l'écriture et le rename

#### `bot/twitch/api.py` — `TwitchAPI`

Thin wrapper httpx pour l'API Helix. Toutes les valeurs fixes (broadcaster_id, bot_id, client_id) sont injectées au constructeur — aucune lecture d'env var dans les méthodes.

**Interface publique :**
```python
class TwitchAPI:
    def __init__(
        self,
        token_manager: TwitchTokenManager,
        client_id: str,
        bot_id: str,
        broadcaster_id: str,
    ):
        ...

    async def send_message(self, text: str) -> None:
        """POST /helix/chat/messages. Retry sur 401 (refresh bot token + 1 essai)."""
```

**Endpoint d'envoi :**
```
POST https://api.twitch.tv/helix/chat/messages
Authorization: Bearer <BOT_ACCESS_TOKEN>
Client-Id: <TWITCH_CLIENT_ID>
{
  "broadcaster_id": "<TWITCH_BROADCASTER_ID>",  # injecté au constructeur
  "sender_id": "<TWITCH_BOT_ID>",               # injecté au constructeur
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

**Scopes requis par token :**

- **Bot** (`BOT_ACCESS_TOKEN`) : `user:read:chat`, `user:write:chat`, `user:bot`, `moderator:read:followers`
- **Streamer** (`STREAMER_ACCESS_TOKEN`) : `channel:read:subscriptions`, `bits:read`

**Abonnements EventSub :**

| Event | Token | Scope requis | Méthode twitchio v2 | Nouveau ? |
|---|---|---|---|---|
| `channel.follow` v2 | Bot | `moderator:read:followers` | `subscribe_channel_follows_v2` | non |
| `channel.raid` | Bot | *(aucun)* | `subscribe_channel_raid` | non |
| `channel.chat.message` | Bot | `user:read:chat` | `subscribe_channel_chat_messages` | **oui** |
| `channel.subscribe` | Streamer | `channel:read:subscriptions` | `subscribe_channel_subscriptions` | non |
| `channel.subscription.message` | Streamer | `channel:read:subscriptions` | `subscribe_channel_subscription_messages` | non |
| `channel.subscription.gift` | Streamer | `channel:read:subscriptions` | `subscribe_channel_subscription_gifts` | **oui** |
| `channel.subscription.end` | Streamer | `channel:read:subscriptions` | `subscribe_channel_subscription_end` | **oui** (abonnement seul) |
| `channel.cheer` | Streamer | `bits:read` | `subscribe_channel_cheers` | non |

**`_generate_and_send()` :** Cette fonction helper existante doit être mise à jour pour envoyer via `bot.twitch_api.send_message(text=reply)` au lieu de l'appel IRC `channel.send(reply)`. L'objet twitchio channel (IRC) n'existe plus.

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

`handle_message()` adapté pour un payload EventSub. Le `broadcaster_id` n'est pas lu depuis l'env — `TwitchAPI` le connaît déjà via son constructeur :

```python
async def handle_message(bot: "WallyTwitch", payload) -> None:
    content: str = payload.message.text
    author: str  = payload.chatter.name
    user_id: str = str(payload.chatter.id)

    # Trigger check : @botnick (via TWITCH_BOT_NICK) ou trigger_names configurés
    bot_nick = os.getenv("TWITCH_BOT_NICK", "").lower()
    triggered = (bot_nick and f"@{bot_nick}" in content.lower()) or any(
        name.lower() in content.lower() for name in bot.config.bot.trigger_names
    )
    if not triggered:
        return

    # ... logique inchangée (cooldown, memory, prompts, openai) ...

    # Envoi via Helix au lieu d'IRC
    await bot.twitch_api.send_message(text=reply)
```

Note : `bot.nick` (attribut twitchio IRC) n'est plus fiable sans connexion IRC. Le trigger check utilise directement `TWITCH_BOT_NICK`.

#### `bot/main.py`

- `_resolve_twitch_token()` supprimé
- Résolution du chemin `.env` : `env_path = Path(__file__).parent.parent / ".env"`
- `token_manager = TwitchTokenManager.load(env_path)`
- `await token_manager.startup_validate()` avant toute initialisation des bots
- `TwitchAPI(token_manager, client_id, bot_id, broadcaster_id)` instancié et injecté dans `WallyTwitch`

**Comportement au démarrage selon l'état des tokens :**

| État | Comportement |
|---|---|
| `BOT_ACCESS_TOKEN` valide (ou refresh réussi) | Bot Twitch démarré normalement |
| `BOT_ACCESS_TOKEN` invalide + refresh échoue | `WallyTwitch` non démarré — log WARNING, bot Discord non affecté |
| `STREAMER_ACCESS_TOKEN` invalide + refresh échoue | Bot démarre, subscriptions streamer skippées — log WARNING (comportement existant) |

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
| Token invalide au démarrage | Refresh immédiat ; si refresh échoue → voir table startup ci-dessus |
| 401 sur `send_message` | Refresh bot token + 1 retry ; si toujours 401 → log ERROR, message non envoyé |
| `event_token_expired` twitchio | Délègue à `token_manager.refresh("bot")` |
| Refresh échoue (réseau, secret invalide) | Log ERROR, retourne False, token précédent conservé en mémoire |
| `.env.tmp` write crash | `.env` original intact (rename atomique non effectué) |
| EventSub subscription échoue | Log WARNING par subscription, les autres continuent (comportement existant) |

---

## Tests

- `tests/test_twitch_token_manager.py` — validate, refresh (success + failure), réécriture `.env` atomique
- `tests/test_twitch_api.py` — send_message, retry sur 401
- `tests/test_twitch_handlers.py` — mise à jour pour payload EventSub (remplace objet twitchio Message), trigger check via `TWITCH_BOT_NICK`
- `tests/test_twitch_events.py` — handlers gift_sub (payload.total), subscription_end, chat_message

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
| `tests/test_twitch_events.py` | Modifié |
