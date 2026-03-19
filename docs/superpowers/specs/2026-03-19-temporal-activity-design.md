# Mémoire temporelle d'activité

**Date :** 2026-03-19
**Scope :** `bot/persona/SOUL.md`, `bot/db/database.py`, `bot/discord/handlers.py`, `bot/twitch/handlers.py`

---

## Problème

Wally ne sait pas quand il a parlé à quelqu'un pour la dernière fois. Il ne peut pas remarquer qu'un utilisateur est absent depuis 2 semaines, ni commenter qu'il est là à 3h du matin.

---

## Solution

### Données existantes

`memory_users.last_updated` est déjà mis à jour à chaque interaction via `upsert_memory_user()` dans `_post_process`. L'heure actuelle est déjà dans le prompt via `_now_fr()`. Il manque juste :
1. Une query pour récupérer `last_updated` d'un user
2. L'injection de cette info dans le prompt
3. Une directive pour que Wally l'exploite

### `bot/db/database.py` — Nouvelle méthode

```python
async def get_last_interaction(self, user_id: str) -> float | None:
```

Retourne le timestamp `last_updated` depuis `memory_users` pour un `user_id` donné. Retourne `None` si l'utilisateur n'est pas connu (premier contact).

### Injection dans le prompt

Dans `_respond()` (Discord) et `handle_message()` (Twitch), après avoir récupéré `trust` et `mem_context`, on récupère `last_updated` :

```python
last_seen = await bot.db.get_last_interaction(f"{platform}:{user_id}")
```

Si `last_seen` est non-None et que l'écart avec `time.time()` est > 7 jours, on ajoute au `mem_context` :

```python
if last_seen:
    days_ago = int((time.time() - last_seen) / 86400)
    if days_ago >= 7:
        absence_note = f"\nDernière interaction avec cet utilisateur : il y a {days_ago} jours."
        mem_context = (mem_context + absence_note) if mem_context else absence_note.strip()
```

Si `last_seen` est None → premier contact, pas d'injection (le système `first_contact` gère déjà les bienvenues).

### `bot/persona/SOUL.md` — Directive

```
Tu connais la date et l'heure actuelles (dans le contexte situationnel).
Si tu vois que quelqu'un n'a pas interagi depuis longtemps (indiqué
dans "Ce que tu sais de cet utilisateur"), fais-y une remarque
naturelle — "tiens, t'étais passé où ?" ou "ça faisait un bail".
Pas à chaque fois, mais quand ça fait vraiment longtemps (> 1 semaine).
Si quelqu'un te parle très tard la nuit (après minuit), tu peux
commenter — "qu'est-ce que tu fous debout à cette heure ?" — mais
une seule fois, pas à chaque message.
```

---

## Tests

- `test_get_last_interaction_returns_timestamp` — user connu → retourne le float
- `test_get_last_interaction_unknown_user` — user inconnu → retourne None
- `test_absence_note_injected_when_over_7_days` — dernière interaction > 7j → note ajoutée au mem_context
- `test_absence_note_not_injected_when_recent` — dernière interaction < 7j → pas de note

---

## Fichiers

| Fichier | Changement |
|---------|-----------|
| `bot/persona/SOUL.md` | Directive temporelle d'activité |
| `bot/db/database.py` | `get_last_interaction()` |
| `bot/discord/handlers.py` | Récupérer last_seen, injecter absence_note |
| `bot/twitch/handlers.py` | Idem |
| Tests | DB query + injection |
