# Design : Recherche Web Tavily via Function Calling

## Contexte

Wally doit pouvoir chercher sur le web quand il a besoin d'informations actuelles.
On utilise l'API Tavily (1000 crédits gratuits/mois) via le function calling OpenAI.

## Flow

1. L'utilisateur envoie un message à Wally
2. On envoie le message à OpenAI avec un tool `web_search` déclaré
3. Si le modèle décide qu'il a besoin d'une recherche → il retourne un `tool_call` avec la query
4. On ajoute la réaction 🌐 sur le message Discord (en plus du 🔍 existant)
5. On appelle l'API Tavily avec la query
6. On renvoie les résultats au modèle pour qu'il formule sa réponse finale
7. On retire la réaction 🌐 (et 🔍) après envoi

## Composants

### `config.yaml` — nouveau bloc

```yaml
tavily:
  monthly_limit: 200
```

### `.env` — nouvelle variable

`TAVILY_API_KEY`

### `bot/core/openai_client.py` — nouvelle méthode `complete_with_tools()`

- Accepte une liste de tools OpenAI + un callback async pour exécuter les tool calls
- Gère le loop : tool_call → exécution callback → renvoi résultats → réponse finale
- Réutilise la logique de coût/retry existante
- Supporte les deux APIs (Chat Completions et Responses API)

### `bot/core/web_search.py` — nouveau fichier

- Classe `WebSearchService` : appelle Tavily, gère le compteur mensuel (stocké en SQLite)
- Méthode `search(query) -> dict` avec les résultats formatés
- Méthode `is_quota_exceeded() -> bool`
- Warning log à 80% du quota

### `bot/db/database.py` — nouvelle table `web_search_log`

- Colonnes : `id`, `timestamp`, `query`, `results_count`
- Méthode `count_web_searches_this_month() -> int`
- Méthode `log_web_search(query, results_count)`

### `bot/discord/handlers.py` — modif de `_respond()`

- Utilise `complete_with_tools()` au lieu de `complete()`
- Passe un callback qui appelle `WebSearchService.search()`
- Ajoute la réaction 🌐 quand une recherche est déclenchée
- Retire 🌐 après réponse (en plus du 🔍 existant)

### `bot/twitch/handlers.py` — même intégration (sans réactions emoji)

### Tool OpenAI déclaré

```json
{
  "type": "function",
  "function": {
    "name": "web_search",
    "description": "Search the web for current information when you need up-to-date facts, news, or data you don't have.",
    "parameters": {
      "type": "object",
      "properties": {
        "query": { "type": "string", "description": "The search query" }
      },
      "required": ["query"]
    }
  }
}
```

### Gestion du quota

- Compteur basé sur `web_search_log` (mois courant via SQL)
- Si quota dépassé → on ne déclare pas le tool dans l'appel OpenAI
- Log WARNING quand on atteint 80% du quota

### DI Wiring (main.py)

```python
web_search = WebSearchService(config, db)
# Injecté dans discord_bot et twitch_bot
```
