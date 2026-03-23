# Spontaneous Memory Recall — Design Spec

**Date:** 2026-03-22
**Feature:** Références spontanées à la mémoire
**Status:** Approved

---

## Summary

Wally évoque spontanément des souvenirs anciens quand le contexte s'y prête. Deux mécanismes :
1. **Trigger spontané** — Wally intervient sans être mentionné parce qu'un souvenir est pertinent
2. **Directive dans les réponses normales** — Wally glisse naturellement des références mémoire dans ses réponses quand il est mentionné

## Design

### 1. Nouvelle méthode `MemoryService.search_top_match()`

`memory.search()` retourne un `str` (textes joints) sans les scores. On ajoute une méthode dédiée :

```python
async def search_top_match(
    self, platform: str, user_id: str, query: str
) -> tuple[str, float] | None:
```

- Fait un seul appel Qdrant (pas de dual-query comme `search()`)
- Retourne le meilleur match `(memory_text, score)` ou `None` si aucun résultat
- Filtre au seuil `_MIN_SEARCH_SCORE` (0.3) comme l'existant

### 2. Trigger spontané mémoire

**Le check mémoire se fait EN DEHORS de `_check_spontaneous_trigger()`** car cette fonction est synchrone et partagée entre Discord/Twitch. Le flow dans chaque handler :

```
trigger = _check_spontaneous_trigger(text, curiosity, anger, boredom)
if trigger is None and cooldown_elapsed:
    # Nouveau : check mémoire async
    match = await bot.memory.search_top_match(platform, user_id, text)
    if match and match[1] >= config.bot.memory_recall_min_score:
        if random.random() < config.bot.spontaneous_memory_probability:
            trigger = "memory_recall"
            recall_memory = match[0]
```

- `_check_spontaneous_trigger()` reste synchrone et inchangée
- Le check mémoire n'est exécuté que si : (1) aucun autre trigger, (2) cooldown écoulé
- Soumis à `spontaneous_memory_probability` (défaut 0.2)

**Modification de `_spontaneous_respond()` / `_spontaneous_respond_twitch()` :**

Ajout d'un paramètre optionnel `recall_memory: str | None = None`. Quand non-None :
- Injecté dans le system prompt via un bloc : `"--- Souvenir qui te revient ---\n{recall_memory}"`
- Directive contextuelle : "Tu viens de te rappeler quelque chose en lien avec ce que dit {user}. Évoque-le naturellement."
- Log : `logger.info("Memory recall triggered for {user}, score={score}", ...)`

**Twitch :** Le handler Twitch importe `_check_spontaneous_trigger` depuis Discord. Le check mémoire async est dupliqué symétriquement dans le handler Twitch (même pattern, accès à `bot.memory`).

### 3. Directive pour les réponses normales

**Nouveau fichier `bot/persona/prompts/memory_recall_directive.md` :**

Court paragraphe injecté dans le system prompt qui instruit le LLM de :
- Évoquer naturellement les souvenirs quand ils sont en lien avec la conversation
- Utiliser des formulations comme "ça me rappelle quand tu parlais de...", "d'ailleurs tu m'avais dit que..."
- Ne pas le faire systématiquement — seulement quand c'est pertinent et enrichit l'échange
- Ne jamais inventer de faux souvenirs — se baser uniquement sur le contexte mémoire fourni
- Ne jamais révéler des informations qu'un utilisateur a partagées en privé à quelqu'un d'autre
- Ne pas réciter la mémoire mot à mot — la reformuler naturellement

**Injection dans `build_system_prompt()` :**

Ajouté juste après le bloc mémoire utilisateur (`memory_context`), conditionné à `memory_context` non vide. Chargé une seule fois au niveau module via `load_prompt("memory_recall_directive")`.

### 4. Configuration

Deux nouveaux champs dans `BotConfig` (`bot/config.py`) :

```yaml
bot:
  spontaneous_memory_probability: 0.2    # probabilité de trigger sur souvenir pertinent
  memory_recall_min_score: 0.75          # score Qdrant minimum (élevé car intervention non sollicitée)
```

Seuil à 0.75 (pas 0.65) car un faux positif en spontané est plus visible et gênant qu'en réponse normale. Probabilité à 0.2 pour rester discret par rapport aux autres triggers (passion 0.15, base 0.05).

### 5. Performance

- **Coût Qdrant** : un seul appel `search_top_match()` (single query, pas dual), uniquement quand cooldown écoulé ET aucun autre trigger. ~10-20ms.
- **Pas d'appel LLM supplémentaire** pour juger la pertinence — le score Qdrant sert de proxy.

### 6. Error Handling

- **Qdrant indisponible** : `search_top_match()` retourne `None` en cas d'exception (try/except + log WARNING), le trigger mémoire est simplement ignoré. Cohérent avec le pattern existant dans `search()`.
- **Pas de mémoires** : `search_top_match()` retourne `None` → pas de trigger.

## Files Changed

| File | Change |
|---|---|
| `bot/core/memory.py` | Nouvelle méthode `search_top_match()` |
| `bot/discord/handlers.py` | Check mémoire async après `_check_spontaneous_trigger()`. `_spontaneous_respond()` : param `recall_memory`, injection souvenir |
| `bot/twitch/handlers.py` | Modifications symétriques |
| `bot/core/prompts.py` | `build_system_prompt()` : injection directive recall après bloc mémoire |
| `bot/config.py` | 2 champs : `spontaneous_memory_probability`, `memory_recall_min_score` |
| `bot/persona/prompts/memory_recall_directive.md` | **Nouveau** — directive LLM |

## Tests

| Test | Validates |
|---|---|
| `test_search_top_match_returns_best` | `search_top_match()` retourne le match avec le score le plus élevé |
| `test_search_top_match_no_results` | Retourne `None` quand aucun résultat |
| `test_search_top_match_qdrant_error` | Retourne `None` et log WARNING si Qdrant down |
| `test_spontaneous_memory_trigger` | Le handler déclenche `"memory_recall"` quand score >= seuil |
| `test_spontaneous_memory_below_threshold` | Pas de trigger quand score < seuil |
| `test_spontaneous_memory_probability` | La probabilité est respectée (mock random) |
| `test_spontaneous_memory_cooldown` | Le cooldown spontané s'applique aux triggers mémoire |
| `test_spontaneous_respond_with_memory` | Le souvenir est injecté dans le prompt quand `recall_memory` fourni |
| `test_spontaneous_respond_without_memory` | Pas de bloc souvenir quand trigger passion/emotion (régression) |
| `test_memory_recall_directive_injected` | `build_system_prompt()` injecte la directive quand `memory_context` non vide |
| `test_memory_recall_directive_absent` | Directive absente quand `memory_context` est vide |
| `test_spontaneous_memory_twitch` | Le trigger mémoire fonctionne côté Twitch |
