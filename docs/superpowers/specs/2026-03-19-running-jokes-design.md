# Running jokes — Mémoire d'humour

**Date :** 2026-03-19
**Scope :** `bot/db/database.py`, `bot/core/reaction_tracker.py`, `bot/discord/handlers.py`, `bot/twitch/handlers.py`, `bot/persona/SOUL.md`

---

## Problème

Wally ne retient pas ses blagues qui fonctionnent. Quand une vanne déclenche 5 réactions "😂", c'est oublié au message suivant. Les inside jokes sont un pilier de la vie communautaire — Wally devrait pouvoir y faire référence.

---

## Solution : Stocker les blagues réussies, les injecter dans le prompt

### Table `jokes`

```sql
CREATE TABLE IF NOT EXISTS jokes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    reaction_count INTEGER DEFAULT 0,
    created_at REAL NOT NULL
);
```

### Flux

1. Wally répond → `ReactionTracker.track_discord_message(msg_id, reply_text)` (ou Twitch equivalent)
2. Les réactions arrivent → compteur incrémente
3. Quand tier 2 est atteint (3+ réactions) → `ReactionTracker` appelle `db.insert_joke(content, channel_id, platform, count)`
4. Au moment de construire le prompt → `db.get_recent_jokes(channel_id, limit=3)` → injecté dans le prompt

### ReactionTracker — changements

**`_DiscordReactionState`** — ajouter `reply_text: str = ""` et `channel_id: str = ""`

**`_TwitchWindow`** — ajouter `reply_text: str = ""`

**`track_discord_message(message_id, reply_text, channel_id)`** — signature étendue pour stocker le texte et le channel_id

**`track_twitch_response(channel_id, reply_text)`** — signature étendue

**`_maybe_apply`** — quand on atteint tier 2 pour la première fois (transition de tier 1 à tier 2), appeler le callback DB. Le tracker reçoit une référence à `db` en plus de `emotion` dans son constructeur.

**Callback condition :** `old_tier < 2 and new_tier >= 2` — une seule insertion par message.

### `bot/db/database.py` — Nouvelles méthodes

```python
async def insert_joke(self, content: str, channel_id: str, platform: str, reaction_count: int) -> None:
```

```python
async def get_recent_jokes(self, channel_id: str, limit: int = 3) -> list[str]:
    """Retourne les `limit` dernières blagues réussies du canal, les plus récentes d'abord."""
```

### Injection dans le prompt

Dans `_respond()` (Discord) et `handle_message()` (Twitch), après le memory_context et avant la construction du system_prompt :

```python
jokes = await bot.db.get_recent_jokes(str(message.channel.id), limit=3)
```

Si `jokes` est non-vide, construire un bloc :

```
--- Tes blagues récentes qui ont bien marché dans ce salon ---
- "blague 1"
- "blague 2"
```

Ajouter ce bloc au `mem_context` ou le passer comme paramètre séparé. Le plus simple : l'ajouter au `mem_context`.

### Directive SOUL.md

```
Tu peux voir tes blagues récentes qui ont fait rire (dans "Tes
blagues récentes qui ont bien marché"). Fais-y référence quand
le contexte s'y prête — un rappel, une variation, un callback.
Les inside jokes renforcent le lien avec la communauté. Ne les
recycle pas mot pour mot, mais fais des clins d'œil.
```

### `main.py` — Injecter DB dans ReactionTracker

Le constructeur de ReactionTracker accepte maintenant `db` en plus de `emotion` :

```python
reaction_tracker = ReactionTracker(emotion, db)
```

---

## Tests

- `test_insert_joke` — insère une joke, vérifie qu'elle est en DB
- `test_get_recent_jokes_returns_latest` — insère 5 jokes, get_recent(limit=3) retourne les 3 dernières
- `test_get_recent_jokes_filters_by_channel` — jokes dans 2 canaux → filtrées par canal
- `test_tracker_stores_reply_text` — après track_discord_message avec reply_text, le state contient le texte
- `test_tracker_inserts_joke_on_tier2` — 3 réactions → joke insérée en DB

---

## Fichiers

| Fichier | Changement |
|---------|-----------|
| `bot/db/database.py` | Table `jokes`, `insert_joke()`, `get_recent_jokes()` |
| `bot/core/reaction_tracker.py` | Stocker reply_text/channel_id, accepter db, callback tier 2 |
| `bot/discord/handlers.py` | Passer reply_text+channel_id au tracker, injecter jokes dans prompt |
| `bot/twitch/handlers.py` | Idem |
| `bot/main.py` | Passer db au ReactionTracker |
| `bot/persona/SOUL.md` | Directive running jokes |
| Tests | DB + tracker callback |
