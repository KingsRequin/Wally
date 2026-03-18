# Spec : Chaînes Twitch invitées — Wally

**Date :** 2026-03-18
**Statut :** Approuvé

---

## Contexte

Wally est actuellement connecté à une seule chaîne Twitch (la chaîne "home" identifiée par
`TWITCH_BROADCASTER_ID`). On veut pouvoir l'envoyer chatter sur d'autres chaînes, les gérer
via le dashboard, et le voir quitter automatiquement à la fin de chaque stream.

---

## Objectif

- Ajouter/supprimer des chaînes Twitch invitées via le dashboard (admin)
- Wally répond aux triggers dans ces chaînes exactement comme sur la chaîne home (chat only,
  pas de subs/bits/etc.)
- Wally quitte automatiquement une chaîne invitée quand le stream se termine (suppression
  définitive de la config — il faut re-ajouter manuellement pour le prochain stream)
- Wally ne quitte jamais la chaîne home (Azrael_TTV)
- Le journal de Wally mentionne naturellement les autres chaînes via le contexte existant
  (aucun changement journal requis)

---

## Architecture

### Chaîne home vs chaînes invitées

| | Chaîne home | Chaînes invitées |
|---|---|---|
| Identification | `TWITCH_BROADCASTER_ID` (env var) | `config.twitch.guest_channels` |
| EventSub | chat + follow + sub + bits + raid | chat uniquement |
| Départ automatique | Jamais | Oui, à la fin du stream |
| Suppression config | Jamais | Oui, à la fin du stream |

### Config (`TwitchConfig`)

Le champ `channels` existant est **renommé** en `guest_channels`. La chaîne home n'apparaît
**jamais** dans cette liste. Migration : `channels: [Azrael_TTV]` → `guest_channels: []`.

Les noms de chaînes sont stockés en **minuscules** (logins Twitch normalisés). Les IDs
numériques sont résolus au runtime.

```yaml
twitch:
  guest_channels: []        # ex: [streameurxyz, streameurabc]
  cooldown_seconds: 10
```

### Cache runtime (`WallyTwitch`)

```python
_channel_ids: dict[str, str]        # name (lowercase) → broadcaster_id
_channel_was_live: dict[str, bool]  # name (lowercase) → True si le stream a été détecté live
```

`_channel_was_live[name]` est initialisé à `False` à l'ajout, puis passé à `True` dès que :
- le polling détecte le stream live, OU
- un message est reçu de cette chaîne.

La suppression ne se déclenche que sur une **transition True → False** (stream était live,
maintenant offline). Un stream jamais vu live ne déclenche pas de suppression.

---

## Composants modifiés

### `bot/config.py`

**Renommage du champ** : `TwitchConfig.channels` → `guest_channels: list[str]`

**Migration dans `Config.load()`** — le champ `channels` du YAML existant est relu sous
le nom `guest_channels` avec fallback pour les configs anciennes :

```python
twitch_raw = raw.get("twitch", {})
# Migration : ancien champ "channels" → "guest_channels"
if "guest_channels" not in twitch_raw and "channels" in twitch_raw:
    # Exclure la chaîne home de la liste migrée
    home_login = os.getenv("TWITCH_BROADCASTER_LOGIN", "").lower()
    twitch_raw["guest_channels"] = [
        ch for ch in twitch_raw.pop("channels") if ch.lower() != home_login
    ]
else:
    twitch_raw.setdefault("guest_channels", [])
    twitch_raw.pop("channels", None)
twitch = TwitchConfig(**twitch_raw)
```

Après le premier `config.save()` (ex: ajout d'une chaîne), le YAML sera réécrit avec
`guest_channels` et `channels` disparaîtra.

### `bot/twitch/api.py`

**Nouvelle méthode `get_broadcaster_id`**
```python
async def get_broadcaster_id(self, login: str) -> Optional[str]:
    """GET /helix/users?login={login}. Retourne l'ID ou None si introuvable."""
```
- Login passé en minuscules (Twitch est case-insensitive)
- Retry une fois sur 401 (cohérent avec send_message)
- Retourne `None` si la chaîne n'existe pas ou si l'API est indisponible

**Nouvelle méthode `get_streams_status`**
```python
async def get_streams_status(self, broadcaster_ids: list[str]) -> dict[str, bool]:
    """GET /helix/streams?user_id=id1&user_id=id2...
    Retourne {broadcaster_id: is_live}. Retourne {} si la liste est vide."""
```
- Gère la liste vide (retourne `{}` sans appel API)
- Retry une fois sur 401
- En cas d'erreur : retourne `{}` (pas de faux positif de suppression)

**Modification `send_message`**
```python
async def send_message(self, text: str, broadcaster_id: Optional[str] = None) -> None:
    """broadcaster_id=None → utilise self._broadcaster_id (chaîne home)."""
```

### `bot/twitch/events.py` — `start_eventsub_client()`

Après les souscriptions home existantes et avant `bot._eventsub_client = client`, ajouter :

```python
# Guest channels : chat seulement
for name in bot.config.twitch.guest_channels:
    guest_id = await bot.twitch_api.get_broadcaster_id(name)
    if guest_id:
        bot._channel_ids[name] = guest_id
        try:
            await _subscribe_chat(client, guest_id, bot_id, bot_token)
            logger.info("EventSub subscribed: chat guest {name}", name=name)
        except Exception as exc:
            logger.warning("EventSub guest chat failed [{name}]: {e}", name=name, e=exc)
    else:
        logger.warning("Chaîne invitée introuvable ou API down: {name}", name=name)
    await asyncio.sleep(0.5)  # éviter rate-limit
```

### `bot/twitch/handlers.py`

**Modification obligatoire — normalisation du nom de chaîne** : la ligne existante
```python
channel_name: str = payload.broadcaster.name
```
doit devenir :
```python
channel_name: str = payload.broadcaster.name.lower()
```
Toutes les clés de `_channel_ids` et `_channel_was_live` sont en minuscules — sans cette
normalisation, le lookup `.get(channel_name, ...)` échouerait silencieusement.

**Ajout 1 — Marquage "vu live"** (juste après `channel_name = ...`) :
```python
if channel_name in bot._channel_ids:
    bot._channel_was_live[channel_name] = True
```

**Ajout 2 — Routing de la réponse** (remplace `await bot.twitch_api.send_message(text=reply)`) :
```python
home_id = os.getenv("TWITCH_BROADCASTER_ID", "")
target_broadcaster_id = bot._channel_ids.get(channel_name, home_id)
await bot.twitch_api.send_message(text=reply, broadcaster_id=target_broadcaster_id)
```

### `bot/twitch/bot.py`

**Init** — ajouter dans `__init__` :
```python
self._channel_ids: dict[str, str] = {}
self._channel_was_live: dict[str, bool] = {}
```

**`add_guest_channel(name: str) -> Optional[str]`**
```python
async def add_guest_channel(self, name: str) -> Optional[str]:
    name = name.lower()
    if name in self.config.twitch.guest_channels:
        return "already_added"  # 409
    broadcaster_id = await self.twitch_api.get_broadcaster_id(name)
    if not broadcaster_id:
        return None  # 404 / 503
    self.config.twitch.guest_channels.append(name)
    self.config.save()
    self._channel_ids[name] = broadcaster_id
    self._channel_was_live[name] = False
    await self._restart_eventsub()
    return broadcaster_id
```

**`remove_guest_channel(name: str) -> None`**
```python
async def remove_guest_channel(self, name: str) -> None:
    name = name.lower()
    if name in self.config.twitch.guest_channels:
        self.config.twitch.guest_channels.remove(name)
        self.config.save()
    self._channel_ids.pop(name, None)
    self._channel_was_live.pop(name, None)
    await self._restart_eventsub()
    logger.info("Wally a quitté la chaîne invitée {name}", name=name)
```

**`_poll_guest_streams() -> None`** (tâche background)
```python
async def _poll_guest_streams(self) -> None:
    try:
        while True:
            await asyncio.sleep(60)
            ids = list(self._channel_ids.values())
            if not ids:
                continue
            try:
                statuses = await self.twitch_api.get_streams_status(ids)
            except Exception as exc:
                logger.warning("Guest stream poll failed: {e}", e=exc)
                continue
            # Inverser le dict pour lookup par name
            id_to_name = {v: k for k, v in self._channel_ids.items()}
            for broadcaster_id, is_live in statuses.items():
                name = id_to_name.get(broadcaster_id)
                if not name:
                    continue
                if is_live:
                    self._channel_was_live[name] = True
                elif self._channel_was_live.get(name, False):
                    # Transition live → offline : quitter définitivement
                    logger.info("Stream terminé : Wally quitte {name}", name=name)
                    await self.remove_guest_channel(name)
    except asyncio.CancelledError:
        pass
```

**`start()` — intégration du polling**

Refactoriser pour lancer le polling en parallèle :
```python
async def start(self) -> None:
    logger.info("Twitch bot starting in EventSub-only mode")
    from bot.twitch.events import start_eventsub_client
    await start_eventsub_client(self)
    await asyncio.gather(
        self._token_refresh_loop(),
        self._poll_guest_streams(),
    )

async def _token_refresh_loop(self) -> None:
    try:
        while True:
            await asyncio.sleep(3 * 3600)
            logger.info("Periodic Twitch token refresh + EventSub restart")
            await self.token_manager.startup_validate()
            await self._restart_eventsub()
    except asyncio.CancelledError:
        pass
```

### `bot/dashboard/routes/admin.py`

**Mise à jour du endpoint `POST /config` existant** — le bloc `if "twitch" in body` passe
de `cfg.twitch.channels` à `cfg.twitch.guest_channels` :

```python
if "twitch" in body:
    d = body["twitch"]
    if "guest_channels" in d:
        cfg.twitch.guest_channels = list(d["guest_channels"])  # liste : remplacement intégral
    if "cooldown_seconds" in d:
        cfg.twitch.cooldown_seconds = int(d["cooldown_seconds"])
```

**Nouveaux endpoints** (dans le fichier existant) :

```python
@router.post("/twitch/channels")
async def add_twitch_channel(request: Request, body: dict) -> dict:
    """Ajoute une chaîne invitée. body = {"name": "streameurxyz"}"""
    name = str(body.get("name", "")).strip().lower()
    # Validation format login Twitch : 1-25 chars, alphanumeric + underscore
    if not name or not re.match(r'^[a-z0-9_]{1,25}$', name):
        raise HTTPException(status_code=400, detail="Nom de chaîne invalide")
    state = request.app.state.wally
    if state.twitch_bot is None:
        raise HTTPException(status_code=503, detail="Twitch non disponible")
    result = await state.twitch_bot.add_guest_channel(name)
    if result == "already_added":
        raise HTTPException(status_code=409, detail="Chaîne déjà ajoutée")
    if result is None:
        raise HTTPException(status_code=404, detail="Chaîne introuvable sur Twitch")
    return {"broadcaster_id": result}

@router.delete("/twitch/channels/{name}")
async def remove_twitch_channel(request: Request, name: str) -> dict:
    """Supprime une chaîne invitée."""
    state = request.app.state.wally
    if state.twitch_bot is None:
        raise HTTPException(status_code=503, detail="Twitch non disponible")
    await state.twitch_bot.remove_guest_channel(name.lower())
    return {"status": "removed"}
```

### `bot/dashboard/static/index.html`

Nouvelle section admin "Chaînes Twitch invitées" :

```
┌─ Chaînes Twitch invitées ──────────────────────────┐
│                                                     │
│  streameurxyz  [✕]                                  │
│  streameurabc  [✕]                                  │
│                                                     │
│  [ nom de chaîne... ]  [+ Ajouter]                 │
│                                                     │
│  ⚠ Le broadcaster doit avoir autorisé le bot       │
│    (scope channel:bot) pour que Wally puisse parler │
└─────────────────────────────────────────────────────┘
```

Les chaînes sont lues depuis le endpoint `GET /api/admin/config` → `twitch.guest_channels`.
Les erreurs (404, 409, 503) s'affichent inline sous l'input.

---

## Flux complet

### Ajout d'une chaîne

```
POST /api/admin/twitch/channels {"name": "StreameurXYZ"}
  → validation format + lowercase → "streameurxyz"
  → bot.add_guest_channel("streameurxyz")
    → déjà dans la liste ? → 409
    → TwitchAPI.get_broadcaster_id("streameurxyz") → "987654321" / None
    → None → 404 (introuvable) ou 503 (API down)
    → config.twitch.guest_channels.append("streameurxyz")
    → config.save()
    → bot._channel_ids["streameurxyz"] = "987654321"
    → bot._channel_was_live["streameurxyz"] = False
    → bot._restart_eventsub() → resouscrit home + tous les guests
  → 200 {"broadcaster_id": "987654321"}
```

### Suppression manuelle

```
DELETE /api/admin/twitch/channels/streameurxyz
  → bot.remove_guest_channel("streameurxyz")
    → config update + save + cache nettoyé + restart EventSub
  → 200 {"status": "removed"}
```

### Départ automatique (stream offline)

```
Polling 60s :
  → TwitchAPI.get_streams_status(["987654321", ...])
  → Pour chaque broadcaster_id dans la réponse :
      is_live = True → _channel_was_live["streameurxyz"] = True
      is_live = False et _channel_was_live["streameurxyz"] == True :
        → bot.remove_guest_channel("streameurxyz")
        → config purgée, EventSub restarté
```

### Message reçu d'une chaîne invitée

```
EventSub channel.chat.message (broadcaster = "StreameurXYZ")
  → channel_name = payload.broadcaster.name.lower()  # "streameurxyz"
  → bot._channel_was_live["streameurxyz"] = True
  → handle_message(bot, payload)
    → [traitement normal : mémoire, emotion, prompt, openai]
    → broadcaster_id = bot._channel_ids.get("streameurxyz", home_id)
    → TwitchAPI.send_message(reply, broadcaster_id="987654321")
```

---

## Gestion d'erreurs

| Situation | Comportement |
|---|---|
| Nom de chaîne invalide (format) | `400 {"detail": "Nom de chaîne invalide"}` |
| Chaîne introuvable sur Twitch | `404 {"detail": "Chaîne introuvable sur Twitch"}` |
| Chaîne déjà dans la liste | `409 {"detail": "Chaîne déjà ajoutée"}` |
| API Twitch indisponible à l'ajout | `404` (get_broadcaster_id retourne None) |
| Résolution ID échoue au restart EventSub | Log warning, chaîne ignorée silencieusement |
| `send_message` vers chaîne non autorisée | 403 Twitch logué, pas de crash |
| Polling échoue (API down) | Log warning, `{}` retourné → pas de suppression |
| Twitch bot non démarré | `503 {"detail": "Twitch non disponible"}` |

---

## Contrainte Twitch

Pour que Wally puisse **envoyer** des messages dans une chaîne invitée, le broadcaster doit
avoir autorisé l'application bot via le scope OAuth `channel:bot`. Sans ça, la lecture
(EventSub) fonctionne mais l'envoi retourne 403. Cette information est affichée dans le
dashboard.

Note : le restart EventSub est nécessaire (et non une souscription incrémentale) car twitchio v2
stocke les tokens dans les objets `_Subscription` qui ne peuvent pas être mis à jour en vol.

---

## Non-concerné

- Journal : aucun changement. Le contexte de conversation inclut déjà `twitch:{channel_name}`,
  Wally mentionnera naturellement les chaînes visitées.
- Événements Twitch (follow, sub, bits, raid) : uniquement pour la chaîne home.
- Cooldowns, trust scores, mémoire : fonctionnent déjà par `user_id`, aucun changement.
