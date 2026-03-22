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

### 1. Trigger spontané mémoire

**Intégration dans `_check_spontaneous_trigger()` (Discord + Twitch) :**

Après les checks existants (passion keywords, émotions extrêmes), si le cooldown est écoulé et qu'aucun autre trigger n'a été trouvé :
1. Appel `memory.search(platform, user_id, message_content)` sur l'auteur du message
2. Si le meilleur résultat a un score >= `memory_recall_min_score` (config, défaut 0.65), retourner un trigger `"memory_recall"` avec le souvenir en payload
3. Ce trigger est soumis à `spontaneous_memory_probability` (config, défaut 0.4)

**Modification de `_spontaneous_respond()` / `_spontaneous_respond_twitch()` :**

Quand le trigger est `"memory_recall"` :
- Le souvenir est injecté dans le system prompt via un bloc dédié : `"--- Souvenir qui te revient ---\n{memory_text}"`
- Une directive contextuelle est ajoutée : "Tu viens de te rappeler quelque chose en lien avec ce que dit {user}. Évoque-le naturellement dans ta réponse."
- Passage de `memory_context` au `build_system_prompt()` (actuellement absent des réponses spontanées)
- Le reste du flow spontané reste identique (cooldown, envoi, post-processing)

### 2. Directive pour les réponses normales

**Nouveau fichier `bot/persona/prompts/memory_recall_directive.md` :**

Court paragraphe injecté dans le system prompt qui instruit le LLM de :
- Évoquer naturellement les souvenirs quand ils sont en lien avec la conversation
- Utiliser des formulations comme "ça me rappelle quand tu parlais de...", "d'ailleurs tu m'avais dit que...", "tiens, la dernière fois tu..."
- Ne pas le faire systématiquement — seulement quand c'est pertinent et enrichit l'échange
- Ne jamais inventer de faux souvenirs — se baser uniquement sur le contexte mémoire fourni

**Injection dans `build_system_prompt()` :**

Ajouté juste après le bloc mémoire utilisateur (`memory_context`), conditionné à `memory_context` non vide. Chargé une seule fois au niveau module via `load_prompt("memory_recall_directive")`.

### 3. Configuration

Deux nouveaux champs dans `BotConfig` (`bot/config.py`) :

```yaml
bot:
  spontaneous_memory_probability: 0.4    # probabilité de trigger sur souvenir pertinent
  memory_recall_min_score: 0.65          # score Qdrant minimum pour considérer un souvenir pertinent
```

### 4. Performance

- **Coût Qdrant** : un seul `memory.search()` par message, uniquement quand le cooldown spontané est écoulé et qu'aucun autre trigger n'a matché. ~20ms par appel.
- **Pas d'appel LLM supplémentaire** pour juger la pertinence — le score Qdrant sert de proxy.
- **Pas de cache** — le search Qdrant est suffisamment rapide.

## Files Changed

| File | Change |
|---|---|
| `bot/discord/handlers.py` | `_check_spontaneous_trigger()` : ajout check mémoire. `_spontaneous_respond()` : injection souvenir si trigger `"memory_recall"` |
| `bot/twitch/handlers.py` | Modifications symétriques |
| `bot/core/prompts.py` | `build_system_prompt()` : injection directive recall après bloc mémoire |
| `bot/config.py` | 2 champs : `spontaneous_memory_probability`, `memory_recall_min_score` |
| `bot/persona/prompts/memory_recall_directive.md` | **Nouveau** — directive LLM pour évoquer les souvenirs |

## Tests

| Test | Validates |
|---|---|
| `test_spontaneous_memory_trigger` | `_check_spontaneous_trigger()` retourne `"memory_recall"` quand score >= seuil |
| `test_spontaneous_memory_below_threshold` | Pas de trigger quand score < seuil |
| `test_spontaneous_memory_probability` | La probabilité `spontaneous_memory_probability` est respectée (mock random) |
| `test_spontaneous_memory_cooldown` | Le cooldown spontané s'applique aux triggers mémoire |
| `test_spontaneous_respond_with_memory` | Le souvenir est injecté dans le prompt quand trigger = `"memory_recall"` |
| `test_memory_recall_directive_injected` | `build_system_prompt()` injecte la directive quand `memory_context` non vide |
| `test_memory_recall_directive_absent` | Directive absente quand `memory_context` est vide |
