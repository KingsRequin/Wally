# Spec — Analyse émotionnelle LLM + apprentissage FR_EMOTION_WORDS

Date : 2026-03-15

## Contexte

L'analyse émotionnelle actuelle repose sur NRCLex (lexique anglais uniquement) complété par un dictionnaire français hardcodé (`FR_EMOTION_WORDS`). Cette approche ne comprend pas le contexte, ne distingue pas à qui s'adresse une émotion, et ne peut pas apprendre de nouveaux mots automatiquement.

Ce spec remplace NRCLex par un appel LLM (secondary_model) avec historique de messages, et ajoute un mécanisme d'apprentissage persistant du vocabulaire émotionnel français. Il corrige aussi le bug du journal causé par l'incompatibilité entre `complete()` et les modèles de raisonnement qui utilisent la Responses API.

---

## Périmètre

- `bot/core/emotion.py` — analyse LLM, apprentissage, persistance
- `bot/core/openai_client.py` — support Responses API pour les modèles de raisonnement
- `bot/discord/handlers.py` — `_post_process` reçoit `context_messages`
- `bot/twitch/handlers.py` — idem
- `bot/main.py` — injection OpenAI client dans EmotionEngine
- `data/fr_emotion_words.json` — fichier de persistance (créé automatiquement)

---

## Design

### 1. Analyse LLM des émotions

**Déclenchement** : uniquement sur les messages qui triggent Wally (comportement inchangé).

**Injection OpenAI** : `EmotionEngine` expose `set_openai_client(client)` (même pattern que `MemoryService`). Dans `main.py`, l'appel se fait **après** `openai_client = OpenAIClient(config, db)` et **avant** le démarrage des adapters :
```python
emotion.set_openai_client(openai_client)
```

**Nouvelle signature** :
```python
async def process_message(
    self,
    text: str,
    trust_score: float = 0.5,
    context_messages: list[dict] | None = None,
) -> None
```

**Source du contexte** : `context_messages` provient de `bot.memory.get_context_summarized_if_needed(channel_id)` — la fenêtre glissante par canal avec résumé automatique. Le `prelude` n'est **pas** utilisé pour l'analyse émotionnelle.

**Flux** :
1. Si OpenAI disponible et `context_messages` fourni → `_analyze_llm()`
2. Si succès → appliquer les deltas + apprendre les nouveaux mots
3. Si échec (exception, JSON invalide) → fallback `_analyze_sync()` (NRCLex + FR_EMOTION_WORDS), log WARNING

**Prompt système** envoyé au `secondary_model` :
```
Tu analyses l'état émotionnel de Wally (bot de chat) après un échange.
Wally a 5 émotions : anger, joy, sadness, curiosity, boredom.
Tu retournes des deltas (variations à additionner à l'état courant).

Règles :
- Chaque delta est un float entre 0.0 et 0.3
- Si une émotion (insulte, compliment...) est dirigée vers un autre utilisateur et non vers Wally,
  divise le delta par 3
- Si dirigée vers Wally → impact normal
- trust_score fourni (0.0–1.0) : un trust faible amplifie le delta anger (×2 max à trust=0.0)
- Le dernier message est le plus important
- new_words : mots/expressions français du message utiles pour calibrer les émotions futures
  (max 3, seulement si pertinents et non évidents)

Réponds uniquement en JSON valide, sans markdown :
{
  "deltas": {"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
  "new_words": [{"word": "...", "emotion": "...", "delta": 0.0}]
}
```

**Message user** :
```
trust_score: {trust_score:.2f}

Historique récent :
[Alice]: message 1
[Bob]: message 2

Message déclencheur :
[username]: texte du message
```

**Parsing** : `json.loads()` sur la réponse brute. En cas d'échec → fallback immédiat.

**Validation des deltas** : clampés à `[0.0, MAX_DELTA_PER_MESSAGE]` après réception.

**Validation des new_words** : chaque entrée doit satisfaire :
- `emotion in EMOTIONS` (toute autre valeur ignorée silencieusement)
- `0.0 < delta <= MAX_DELTA_PER_MESSAGE`
- `len(word) >= 2`

**Purpose** : `purpose="emotion_analysis"` pour le log de coût.

---

### 2. Apprentissage et persistance de FR_EMOTION_WORDS

**Fichier** : `data/fr_emotion_words.json`

Format :
```json
{
  "anger": [["relou", 0.10], ["cheh", 0.08]],
  "joy": [["ouf", 0.07]],
  "sadness": [],
  "curiosity": [],
  "boredom": []
}
```

**Séparation hardcodé / appris** : `FR_EMOTION_WORDS` (module-level, hardcodé) reste inchangé. Un second dict `_learned_words: dict[str, list[tuple[str, float]]]` est maintenu en mémoire et persisté séparément. Les deux sont fusionnés au moment de l'analyse fallback.

**Chargement** : dans `EmotionEngine.__init__()`. Erreur → log WARNING, `_learned_words` vide.

**Déduplication** : vérification **globale** (indépendante de l'émotion) case-insensitive sur l'ensemble des mots hardcodés et appris. Un même mot ne peut apparaître que sous une seule émotion.

**Concurrence et atomicité** :
- Un `asyncio.Lock` protège les écritures concurrentes.
- Écriture atomique : fichier temporaire **dans le même répertoire** (`data/fr_emotion_words.json.tmp`) puis `os.replace()`.
- `asyncio.to_thread()` pour ne pas bloquer la boucle événementielle.
- Erreur d'écriture → log WARNING, mots conservés en mémoire pour la session courante.

**Répertoire** : `Path("data/fr_emotion_words.json").parent.mkdir(parents=True, exist_ok=True)` avant la première écriture.

---

### 3. Support Responses API dans `OpenAIClient`

**Contexte** : certains modèles (dont le `secondary_model` actuel `gpt-5.2-mini`) sont des modèles de raisonnement qui utilisent exclusivement la Responses API (`client.responses.create()`). Ils n'acceptent pas `temperature` et ne fonctionnent pas avec `chat.completions.create()`. C'est la cause du bug du journal.

**Détection** : liste de préfixes de modèles qui utilisent la Responses API :
```python
_RESPONSES_API_PREFIXES = ("o1", "o3", "o4", "gpt-5")

def _uses_responses_api(model: str) -> bool:
    return any(model.startswith(p) for p in _RESPONSES_API_PREFIXES)
```

**Nouvelle méthode privée** `_complete_responses_api()` dans `OpenAIClient` :
```python
async def _complete_responses_api(
    self, model: str, messages: list[dict], purpose: str
) -> str:
    response = await self._client.responses.create(
        model=model,
        input=messages,
        reasoning={"effort": "low"},
        text={"verbosity": "medium"},
    )
    text = response.output_text
    # Cost logging — ResponseUsage expose input_tokens/output_tokens (pas prompt_tokens/completion_tokens)
    if response.usage:
        cost = estimate_cost(model, response.usage.input_tokens, response.usage.output_tokens)
        await self._db.log_cost(
            model, response.usage.input_tokens, response.usage.output_tokens, cost, purpose
        )
    return text
```

`AsyncOpenAI.responses.create` est une coroutine native — pas de `asyncio.to_thread()` nécessaire.

**Routing dans `complete()`** :
```python
async def complete(self, system_prompt, messages, model=None, purpose="response") -> str:
    model = model or self._config.openai.primary_model
    full_messages = [{"role": "system", "content": system_prompt}] + messages

    if _uses_responses_api(model):
        return await self._complete_responses_api(model, full_messages, purpose)

    # Chemin Chat Completions (inchangé)
    for attempt in range(3):
        ...
```

Le `system_prompt` est injecté comme premier message avec `role: "system"` dans les deux chemins — format identique, l'API Responses accepte ce format dans `input`.

`complete_secondary()` appelle `complete()` sans changement — le routing est transparent.

---

### 4. Passage du contexte dans les handlers

**Discord `_respond()`** : `context_messages` est déjà calculé. Passé à `_post_process` comme nouveau paramètre optionnel final :

```python
_fire(_post_process(bot, message.content, platform, user_id, guild_id, trust, context_messages))
```

**Discord `_post_process`** :
```python
async def _post_process(
    bot, text, platform, user_id, guild_id, trust,
    context_messages: list[dict] | None = None,
) -> None:
    await bot.emotion.process_message(text, trust_score=trust, context_messages=context_messages)
    ...
```

**Twitch** : même ajout, signature asymétrique maintenue (pas de `guild_id`) :
```python
_fire(_post_process(bot, content, platform, user_id, trust, context_msgs))

async def _post_process(bot, text, platform, user_id, trust,
                        context_messages: list[dict] | None = None) -> None:
    await bot.emotion.process_message(text, trust_score=trust, context_messages=context_messages)
    ...
```

---

## Gestion d'erreur

| Situation | Comportement |
|---|---|
| Appel LLM échoue (exception) | Fallback NRCLex + FR_EMOTION_WORDS, log WARNING |
| LLM retourne JSON invalide | Fallback NRCLex + FR_EMOTION_WORDS, log WARNING |
| LLM retourne deltas hors bornes | Clamp silencieux à `[0.0, MAX_DELTA_PER_MESSAGE]` |
| new_words avec émotion inconnue | Entrée ignorée silencieusement |
| new_words avec delta invalide | Entrée ignorée silencieusement |
| set_openai_client non appelé | Fallback direct NRCLex + FR_EMOTION_WORDS |
| Écriture JSON échoue | Log WARNING, mots conservés en mémoire pour la session |
| Lecture JSON au démarrage échoue | Log WARNING, `_learned_words` vide |
| Responses API échoue | Exception propagée → log ERROR dans `complete()` → FALLBACK_RESPONSE |

---

## Tests

### Nouveaux tests (`test_emotion.py`)
- `test_analyze_llm_returns_deltas` — mock `complete_secondary`, vérifie deltas appliqués
- `test_analyze_llm_fallback_on_failure` — mock lève exception, vérifie fallback NRCLex
- `test_analyze_llm_fallback_on_invalid_json` — mock retourne JSON invalide, vérifie fallback
- `test_learn_new_word_persisted` — nouveau mot ajouté et sauvegardé (tmp dir)
- `test_learn_word_deduplication_hardcoded` — mot présent dans FR_EMOTION_WORDS → ignoré
- `test_learn_word_deduplication_learned` — mot déjà appris → ignoré
- `test_learn_word_invalid_emotion_ignored` — `emotion="fear"` → ignoré
- `test_learn_word_invalid_delta_ignored` — `delta=5.0` → ignoré

### Tests existants à mettre à jour (`test_emotion.py`)
- `test_analyze_message_returns_dict` — `analyze_message()` reste publique (fallback NRCLex), vérifie que le chemin sans OpenAI injecté fonctionne
- Tests appelant `process_message()` — compatibles (paramètre `context_messages` optionnel)

### Nouveaux tests (`test_openai_client.py`)
- `test_uses_responses_api_detection` — vérifie `_uses_responses_api()` pour les préfixes connus
- `test_complete_routes_to_responses_api` — mock `_complete_responses_api`, vérifie le routing pour `gpt-5-mini`
- `test_complete_routes_to_chat_completions` — vérifie que `gpt-4o` reste sur Chat Completions
