# Spec : Contexte pré-mention (Prelude Context)

**Date :** 2026-03-14
**Statut :** Approuvé

---

## Problème

Wally n'accumule de contexte de conversation (`_context_windows`) que lorsqu'il répond. Si une
discussion est en cours dans un canal et qu'un utilisateur le mentionne pour la première fois,
Wally n'a aucun historique de ce qui précédait sa mention — il répond sans contexte.

---

## Objectif

Quand Wally est mentionné au milieu d'une discussion en cours, il doit disposer d'un historique
des N derniers messages qui précédaient sa mention, afin de répondre de façon cohérente avec le
fil de la conversation.

---

## Approche retenue

**Buffer passif + fallback API Discord** avec bloc séparé dans le prompt.

- Wally écoute passivement **tous** les messages d'un canal (même sans trigger) et les stocke
  dans un buffer circulaire dédié (`_prelude_windows`), distinct du `_context_windows` existant.
- Au moment d'une mention, le buffer prelude est utilisé comme contexte pré-mention.
- Si le buffer est vide (démarrage à froid), fallback sur `channel.history(limit=N)`.
- Le contexte pré-mention apparaît dans le prompt comme un bloc distinct, clairement libellé.

---

## Architecture

### 1. Config (`bot/config.py` + `config.yaml`)

Nouveau champ dans `BotConfig` :

```python
prelude_window_size: int  # default: 15
```

### 2. `MemoryService` (`bot/core/memory.py`)

Nouveau buffer :

```python
_prelude_windows: dict[str, list[dict]]  # channel_id → list[{author, content, timestamp}]
```

Nouvelles méthodes :

- `append_prelude(channel_id: str, author: str, content: str) -> None`
  Ajoute un message au buffer circulaire (max `prelude_window_size`).

- `get_prelude(channel_id: str) -> list[dict]`
  Retourne une copie du buffer. Appelé **avant** `append_prelude` dans `handle_message` — le message courant n'est donc pas encore dans le buffer.

### 3. `handle_message` (`bot/discord/handlers.py`)

**Avant** le check `if not triggered` :

```python
memory.append_prelude(channel_id, message.author.display_name, message.content)
```

**Capture passive — placement exact dans `handle_message`** :

```python
async def handle_message(bot, message):
    if message.author.bot:
        return

    # Capture passive : seulement dans les canaux autorisés
    allowed = bot.config.discord.allowed_channels
    if not allowed or message.channel.id in allowed:
        # Appel AVANT d'ajouter le message courant au prelude
        prelude = bot.memory.get_prelude(str(message.channel.id))
        bot.memory.append_prelude(str(message.channel.id), message.author.display_name, message.content)
    else:
        prelude = []

    # ... check trigger, allowed_channels, etc.
```

Appeler `get_prelude` **avant** `append_prelude` évite d'avoir à filtrer le message courant.

**Au moment du trigger**, dans `_respond()` :

```python
# prelude est passé depuis handle_message (déjà calculé avant append)
if not prelude:
    # Fallback cold start
    prelude = await _fetch_discord_history(message.channel, bot.config.bot.prelude_window_size)

prelude_block = bot.prompts.build_prelude_block(prelude)
context_block = bot.prompts.build_context_block(context_messages)
user_content = prelude_block + context_block + f"\n[{message.author.display_name}]: {message.content}"
```

Nouvelle fonction helper :

```python
async def _fetch_discord_history(channel, limit: int) -> list[dict]:
    """Fallback cold start : récupère l'historique Discord via API.
    Retourne [] en cas d'erreur de permission (log WARNING)."""
```

### 4. `prompts.py` (`bot/core/prompts.py`)

Nouvelle méthode :

```python
def build_prelude_block(self, messages: list[dict]) -> str:
    """Retourne '' si messages vide, sinon bloc formaté."""
```

### 5. Twitch (`bot/twitch/`)

- Même logique `append_prelude` pour les messages passifs.
- `channel_id` = `f"twitch:{channel_name}"` — même namespace que `_context_windows`, garantit l'isolation Discord/Twitch.
- **Pas de fallback API** (Twitch n'expose pas d'historique de chat).
- Prelude vide au démarrage → aucun bloc prelude dans le prompt.

---

## Structure du prompt résultant

```
[System prompt]
[Prelude block]   ← "Discussion récente dans le canal :" — nouveau, optionnel
[Context block]   ← conversation Wally — existant, optionnel
[Message courant] ← "[Auteur]: contenu"
```

---

## Gestion d'erreurs

| Situation | Comportement |
|---|---|
| `channel.history()` échoue (permissions) | log WARNING, continuer sans prelude |
| Prelude vide après fallback | aucun bloc prelude, pas d'erreur |
| Prelude contient des messages de Wally | acceptable, le modèle gère le contexte mixte |
| Qdrant/mem0 indisponible | sans effet sur le prelude (indépendant) |
| Message hors `allowed_channels` | ignoré pour capture passive — pas ajouté au buffer |

## Reset administratif

`MemoryService.reset_all()` doit également purger `_prelude_windows` :

```python
self._prelude_windows.clear()
```

---

## Tests

### `tests/test_memory.py`
- `test_append_prelude_circular` — buffer tronqué à `prelude_window_size`
- `test_get_prelude_returns_copy` — pas de mutation externe
- `test_prelude_independent_from_context_windows` — isolation des deux buffers

### `tests/test_prompts.py`
- `test_build_prelude_block_empty` → retourne `""`
- `test_build_prelude_block_formats_messages` → format `[Auteur]: contenu`

### `tests/test_discord_handlers.py`
- `test_passive_capture_non_triggered_message` — `append_prelude` appelé sans trigger
- `test_prelude_included_in_prompt_on_mention` — prelude dans `user_content`
- `test_cold_start_fallback_to_channel_history` — `channel.history()` appelé si prelude vide
- `test_channel_history_permission_error_graceful` — erreur Discord → log + continuer

---

## Fichiers modifiés

| Fichier | Nature |
|---|---|
| `bot/config.py` | +1 champ `prelude_window_size` |
| `config.yaml` | +1 clé `prelude_window_size: 15` |
| `bot/core/memory.py` | +buffer `_prelude_windows`, +2 méthodes |
| `bot/core/prompts.py` | +`build_prelude_block()` |
| `bot/discord/handlers.py` | +écoute passive, +fallback `channel.history()` |
| `bot/twitch/handlers.py` | +écoute passive (sans fallback) |
| `tests/test_memory.py` | +3 tests |
| `tests/test_prompts.py` | +2 tests |
| `tests/test_discord_handlers.py` | +4 tests |
