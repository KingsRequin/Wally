# Recall proactif

**Date :** 2026-03-19
**Scope :** `bot/core/memory.py`, `bot/discord/handlers.py`, `bot/twitch/handlers.py`

---

## Problème

`memory.search(platform, user_id, message.content)` ne cherche qu'avec le texte du message de l'utilisateur. Si Alice parle de "il fait beau" dans une conversation où elle a mentionné son chat plus tôt, la recherche vectorielle ne retrouvera pas "Alice a un chat nommé Moustache" car la query n'a aucun rapport sémantique.

---

## Solution : Double recherche parallèle

### Principe

Étendre `search()` avec un paramètre optionnel `context_messages`. Quand fourni, deux recherches mem0 sont lancées en parallèle :

1. **Query directe** — le message de l'utilisateur (comportement actuel)
2. **Query contextuelle** — concaténation des derniers messages du prelude (max 5)

Les résultats sont dédupliqués par contenu et fusionnés.

### `bot/core/memory.py` — Modifier `search()`

Nouvelle signature :

```python
async def search(
    self, platform: str, user_id: str, query: str,
    context_messages: list[dict] | None = None,
) -> str:
```

Logique :
1. Si `context_messages` est `None` ou vide, ou si mem0 n'est pas dispo → comportement actuel inchangé (une seule recherche)
2. Si `context_messages` fourni :
   - Construire la query contextuelle : concaténer les `content` des 5 derniers messages (hors messages de Wally), séparés par `\n`
   - Si la query contextuelle est identique à `query` ou vide → skip, une seule recherche
   - Sinon, lancer les 2 recherches en parallèle avec `asyncio.gather`
   - Dédupliquer : par contenu exact du champ `memory` (set)
   - Garder le meilleur score si un souvenir apparaît dans les deux résultats
   - Appliquer le filtre `_MIN_SEARCH_SCORE` sur les résultats fusionnés
   - Retourner les résultats joints par `\n`

### Construction de la query contextuelle

```python
context_texts = [
    m["content"] for m in context_messages[-5:]
    if m.get("author", "").lower() != "wally"
]
context_query = "\n".join(context_texts)
```

On exclut les messages de Wally pour éviter de chercher ses propres réponses en mémoire. On prend les 5 derniers messages non-Wally pour garder la query pertinente.

### Callers

**`bot/discord/handlers.py`** — `_respond()` :
```python
mem_context = await bot.memory.search(platform, user_id, message.content, context_messages=prelude)
```
Le `prelude` est déjà disponible dans `_respond()`.

**`bot/twitch/handlers.py`** — `handle_message()` :
```python
mem_context = await bot.memory.search(platform, user_id, content, context_messages=prelude)
```
Le `prelude` est déjà disponible.

**`bot/discord/commands/ask.py`** — `ask()` :
Pas de changement. `context_messages` n'est pas passé → fallback sur la recherche simple. C'est correct car `/wally ask` n'a pas de prelude conversationnel.

---

## Tests

### Tests unitaires memory.py

- `test_search_with_context_makes_two_queries` — mock mem0.search, vérifie qu'il est appelé 2 fois (query directe + query contexte)
- `test_search_with_context_deduplicates` — les deux recherches retournent le même souvenir → résultat ne le contient qu'une fois
- `test_search_without_context_unchanged` — `context_messages=None` → une seule recherche (comportement existant)
- `test_search_context_excludes_wally_messages` — les messages de Wally dans le prelude ne sont pas inclus dans la query contextuelle
- `test_search_context_empty_prelude_fallback` — prelude vide → une seule recherche

### Tests existants

Aucune régression — le nouveau paramètre est optionnel avec défaut `None`.

---

## Résumé des fichiers

| Fichier | Changement |
|---------|-----------|
| `bot/core/memory.py` | Param `context_messages` dans `search()`, 2e query parallèle, dedup |
| `bot/discord/handlers.py` | Passer `prelude` comme `context_messages` |
| `bot/twitch/handlers.py` | Passer `prelude` comme `context_messages` |
| Tests | 5 nouveaux tests pour la recherche contextuelle |
