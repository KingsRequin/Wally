# Réactivité aux réactions post-Wally

**Date :** 2026-03-19
**Scope :** `bot/core/reaction_tracker.py`, `bot/discord/bot.py`, `bot/discord/handlers.py`, `bot/twitch/handlers.py`, `bot/main.py`

---

## Problème

Wally ne sait pas si ses réponses sont bien reçues. Il n'a aucun feedback sur le "succès conversationnel" de ses messages. Quand il fait une vanne et que 5 personnes réagissent "mdr", ça ne change rien à son état émotionnel.

---

## Solution : Tracker les réactions et booster joy

### Principe

Après chaque réponse de Wally, le système surveille les réactions des utilisateurs. Si des réactions positives sont détectées, la joy de Wally est boostée proportionnellement au volume.

### Deux mécanismes par plateforme

**Discord — données structurées (pas de fenêtre temporelle) :**
- Réactions emoji sur le message de Wally → event `on_raw_reaction_add`
- Réponses directes (reply) au message de Wally → détectées dans `handle_message` via `message.reference`
- La liaison est structurelle (message_id) — pas besoin de fenêtre temporelle
- Filtrage : ignorer les réactions de Wally lui-même et des bots

**Twitch — fenêtre temporelle (120 secondes) :**
- Après chaque réponse de Wally, on mémorise le timestamp + channel_id
- Les messages des 120 secondes suivantes dans le même canal sont scannés pour des mots-clés/emoji positifs
- Pas de reply structurel sur Twitch, donc le timing est le seul signal

### Signaux positifs

**Mots-clés texte** (pour les replies Discord et les messages Twitch dans la fenêtre) :
`mdr`, `lol`, `ptdr`, `xd`, `haha`, `😂`, `🤣`, `pog`, `gg`, `bien joué`, `trop bon`

La détection est case-insensitive et cherche les mots-clés dans le message (substring match).

**Réactions emoji Discord** (sur le message de Wally) :
`😂`, `🤣`, `❤️`, `👍`, `💀`, `😭`, `🔥`, `👏`

Les réactions négatives ne sont pas traitées pour l'instant.

### Impact émotionnel gradué

| Réactions positives | Joy delta |
|---------------------|-----------|
| 1-2 | +0.05 |
| 3-5 | +0.10 |
| 6+ | +0.15 (max) |

Le compteur est **par message de Wally**. Chaque réaction (emoji ou reply positif) incrémente le compteur. Le delta joy est appliqué **différentiellement** : quand on passe d'un palier au suivant, on applique seulement la différence (ex: de 2→3 réactions = passage du palier 0.05 au palier 0.10, on applique +0.05 de delta supplémentaire).

---

## `bot/core/reaction_tracker.py` — Nouveau module

### Classe `ReactionTracker`

```python
class ReactionTracker:
    def __init__(self, emotion_engine):
        ...
```

**État interne :**
- `_discord_messages: dict[int, _DiscordReactionState]` — message_id → état
  - `_DiscordReactionState` : `count: int`, `last_applied_tier: int` (0, 1, 2, 3)
- `_twitch_windows: dict[str, _TwitchWindow]` — channel_id → fenêtre active
  - `_TwitchWindow` : `timestamp: float`, `count: int`, `last_applied_tier: int`
- `_emotion: EmotionEngine` — référence pour appliquer les deltas

**Constantes :**
- `TWITCH_WINDOW_SECONDS = 120`
- `CLEANUP_AGE_SECONDS = 600` (10 minutes, nettoyage des vieilles entrées)
- `JOY_TIERS = [(2, 0.05), (5, 0.10), (float('inf'), 0.15)]` — (seuil max pour ce palier, delta cumulé)
- `POSITIVE_KEYWORDS` — set des mots-clés texte
- `POSITIVE_EMOJIS` — set des emoji réactions Discord. Inclure les variantes avec et sans variation selector : `❤️` (U+2764+FE0F) ET `❤` (U+2764) car Discord peut retourner l'un ou l'autre via `str(payload.emoji)`.

**Méthodes publiques :**

`track_discord_message(message_id: int)` — enregistre un message de Wally à surveiller

`record_discord_reaction(message_id: int, emoji: str, is_bot: bool) -> None` — appelé par `on_raw_reaction_add`. Si le message est tracké, l'emoji est positif, et pas un bot → incrémente le compteur et applique le delta joy si changement de palier.

`record_discord_reply(message_id: int, text: str, is_bot: bool) -> None` — appelé quand un message est un reply à un message tracké. Si le texte contient un mot-clé positif et pas un bot → incrémente et applique.

`track_twitch_response(channel_id: str)` — enregistre que Wally vient de répondre dans ce canal. Crée toujours une **nouvelle** `_TwitchWindow(timestamp=now, count=0, last_applied_tier=0)`, remplaçant toute fenêtre existante pour ce canal.

`check_twitch_message(channel_id: str, text: str) -> None` — appelé pour chaque message Twitch. Si une fenêtre est active (< 120s) et le texte contient un mot-clé positif → incrémente et applique.

`cleanup()` — supprime les entrées > 10 minutes. Appelé périodiquement (à chaque track).

**Méthode privée :**

`_apply_tier_delta(count: int, last_tier: int) -> tuple[int, float]` — retourne `(new_tier, delta_to_apply)`. Calcule le palier actuel selon le count, compare au dernier palier appliqué, retourne la différence.

### Logique des paliers

```
count 1-2 → tier 1 → delta cumulé 0.05
count 3-5 → tier 2 → delta cumulé 0.10
count 6+  → tier 3 → delta cumulé 0.15
```

Quand on passe de tier 1 à tier 2, on applique `0.10 - 0.05 = 0.05` de delta joy.
Quand on est déjà tier 2 et on reçoit une 4e réaction (toujours tier 2), delta = 0.

---

## Intégration Discord

### `bot/discord/bot.py`

Ajouter `self.reaction_tracker = None` dans `__init__` (même pattern que `self.journal = None`, `self.session_manager = None`). Injecté depuis `main.py`.

Les handlers doivent utiliser `getattr(bot, 'reaction_tracker', None)` avant d'appeler les méthodes du tracker — même pattern de guard que pour `dashboard_state` et `session_manager`.

Ajouter l'event handler :

```python
async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
    if payload.user_id == self.user.id:
        return
    # Vérifier si c'est un bot via le cache du guild
    guild = self.get_guild(payload.guild_id) if payload.guild_id else None
    member = payload.member or (guild.get_member(payload.user_id) if guild else None)
    is_bot = member.bot if member else False
    self.reaction_tracker.record_discord_reaction(
        payload.message_id, str(payload.emoji), is_bot,
    )
```

### `bot/discord/handlers.py`

Dans `_respond()`, après `_send_in_parts` :
- Récupérer le message_id du premier message envoyé (le reply)
- Appeler `bot.reaction_tracker.track_discord_message(message_id)`

Dans `handle_message()`, avant le trigger check :
- Si `message.reference` et `message.reference.message_id` est tracké → `bot.reaction_tracker.record_discord_reply(ref_id, message.content, message.author.bot)`

### Modification de `_send_in_parts`

`_send_in_parts` doit retourner le message_id du premier message (le reply) pour que `_respond` puisse le passer au tracker.

Actuellement `_send_in_parts` ne retourne rien. Modifier pour retourner `int | None` — le message_id du premier message envoyé.

---

## Intégration Twitch

### `bot/twitch/handlers.py`

Dans `handle_message()`, après l'envoi de la réponse :
- `bot.reaction_tracker.track_twitch_response(channel_id)`

Au début de `handle_message()`, avant le trigger check (pour tout message, pas seulement les triggers) :
- `bot.reaction_tracker.check_twitch_message(channel_id, content)`

---

## `bot/main.py`

Créer le `ReactionTracker` et l'injecter :

```python
from bot.core.reaction_tracker import ReactionTracker
reaction_tracker = ReactionTracker(emotion)
discord_bot.reaction_tracker = reaction_tracker
twitch_bot.reaction_tracker = reaction_tracker
```

---

## Tests

### Tests unitaires `ReactionTracker`

- `test_apply_tier_delta_tiers` — vérifie les 3 paliers : count 1→tier1(0.05), count 3→tier2(+0.05), count 6→tier3(+0.05)
- `test_discord_reaction_increments_and_applies_joy` — track message, record 3 réactions positives → joy a été boostée
- `test_discord_reaction_ignores_unknown_message` — réaction sur un message non tracké → rien
- `test_discord_reaction_ignores_negative_emoji` — 👎 sur un message tracké → compteur ne bouge pas
- `test_discord_reaction_ignores_bot` — réaction d'un bot → ignorée
- `test_discord_reply_positive_keyword` — reply contenant "mdr" → compteur incrémenté
- `test_discord_reply_no_keyword` — reply sans mot-clé positif → ignoré
- `test_twitch_window_active` — track réponse, check message dans les 120s avec "lol" → compteur incrémenté
- `test_twitch_window_expired` — track réponse, check message après 120s → ignoré
- `test_cleanup_removes_old_entries` — entries > 10 min supprimées

### Limitations connues

- **Messages split** : quand `_send_in_parts` découpe une réponse en plusieurs messages, seul le premier (le reply) est tracké. Les réactions sur les parties suivantes sont ignorées.
- **DMs** : `payload.member` est `None` en DM, donc le filtre bot ne fonctionne pas. Impact négligeable (les bots ne réagissent pas en DM).

### Tests existants

Le `intents.reactions` est déjà inclus dans `Intents.default()` — pas de changement d'intent nécessaire. Les tests existants ne devraient pas casser (nouveaux handlers sont additifs).

---

## Résumé des fichiers

| Fichier | Changement |
|---------|-----------|
| `bot/core/reaction_tracker.py` | Nouveau — ReactionTracker avec Discord + Twitch |
| `bot/discord/bot.py` | Attribut `reaction_tracker`, event `on_raw_reaction_add` |
| `bot/discord/handlers.py` | Track message_id après envoi, détecter replies positifs, `_send_in_parts` retourne message_id |
| `bot/twitch/handlers.py` | Track réponse Twitch, scanner fenêtre pour mots-clés |
| `bot/main.py` | Créer et injecter ReactionTracker |
| `tests/test_reaction_tracker.py` | Nouveau — 10 tests unitaires |
