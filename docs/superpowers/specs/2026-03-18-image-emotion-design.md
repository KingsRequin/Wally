# Spec — Analyse émotionnelle des images Discord

**Date :** 2026-03-18
**Statut :** Approuvé

---

## Contexte

Wally analyse déjà le contenu émotionnel des messages texte (NRCLex + LLM). Quand un
utilisateur Discord envoie une image (mème, screenshot, photo), l'image est déjà passée
au LLM pour générer la réponse principale, mais elle est **ignorée** lors de l'analyse
émotionnelle. Ce spec décrit l'extension du pipeline pour inclure les images.

---

## Objectif

Quand un message Discord contient une ou plusieurs images, leur contenu visuel est pris
en compte dans le calcul des deltas émotionnels de Wally — au même titre que le texte.

---

## Périmètre

- **Plateforme concernée :** Discord uniquement. Twitch ne supporte pas les pièces jointes
  image en chat, aucun changement côté Twitch.
- **Modèle LLM :** Le modèle secondaire (`secondary_model`) est utilisé — il supporte déjà
  la vision (même modèle que pour la réponse principale).
- **Fallback NRCLex :** Si le LLM échoue (exception, timeout), l'analyse tombe en fallback
  NRCLex sur le texte uniquement. Cette logique try/except existe déjà dans
  `process_message()` et n'est pas modifiée. Si le message est image-seul (texte vide),
  NRCLex retourne `{}` → aucun delta appliqué. Log DEBUG dans ce cas.

---

## Flux de données

```
Discord message (texte + images)
  → handlers._post_process(text, image_urls=[...])
    → EmotionEngine.process_message(text, trust_score, context_messages, image_urls=[...])
      → EmotionEngine._analyze_llm(text, trust_score, context_messages, image_urls=[...])
        → openai.complete_secondary(system_prompt, messages, image_urls=[...])
```

Les `image_urls` sont extraites dans `_respond()` (déjà présent, lignes 191-194 de
`handlers.py`) et passées à `_fire(_post_process(..., image_urls=image_urls or None))`.

---

## Changements de signatures

| Fichier | Fonction | Paramètre ajouté |
|---|---|---|
| `bot/discord/handlers.py` | `_post_process()` | `image_urls: list[str] \| None = None` |
| `bot/core/emotion.py` | `EmotionEngine.process_message()` | `image_urls: list[str] \| None = None` |
| `bot/core/emotion.py` | `EmotionEngine._analyze_llm()` | `image_urls: list[str] \| None = None` |

Toutes les modifications sont **additives** (paramètre optionnel avec valeur par défaut
`None`) — les appels existants (Twitch, tests) restent compatibles sans changement.

---

## Enrichissement du prompt LLM

Quand `image_urls` est non-vide, une instruction est ajoutée **en ligne** au bas du
`system_prompt` de `_analyze_llm()`, juste avant la section "Format de sortie" :

```
## Images jointes
Des images accompagnent ce message. Analyse leur contenu émotionnel (ton visuel,
sujet représenté, contexte apparent) pour affiner les deltas. Une image de rage,
un mème sarcastique ou une photo triste doit influencer les deltas au même titre
que le texte.
```

Cette injection est locale à `_analyze_llm()` — elle n'implique pas `prompts.py`,
`PersonaService`, ni les `emotion_directives`. C'est une directive contextuelle,
pas une directive de persona.

---

## Appel multimodal à `complete_secondary`

`complete_secondary()` délègue à `complete()` qui accepte déjà `image_urls` et gère
lui-même la construction des blocs multimodaux via `_build_image_content()`.
Il suffit de passer `image_urls` directement :

```python
raw = await self._openai.complete_secondary(
    system_prompt,
    [{"role": "user", "content": user_msg}],
    purpose="emotion_analysis",
    image_urls=image_urls or None,
)
```

`user_msg` reste une chaîne de texte ordinaire (le texte déclencheur formaté). La
conversion en contenu multimodal est faite par `OpenAIClient.complete()` sur le dernier
message, exactement comme pour la réponse principale.

---

## Texte par défaut pour les messages image-seul

Dans `handlers.py`, le texte de substitution `"Regarde cette image."` est **déjà généré**
à la ligne 197 :

```python
text_content = message.content or ("Regarde cette image." if image_urls else "")
```

Ce `text_content` est utilisé dans `user_content` (prompt LLM principal) mais pas dans
`_post_process`. Il faut passer ce même `text_content` (et non `message.content`) à
`_post_process` pour que l'analyse émotionnelle reçoive un texte non-vide quand le
message est image-seul.

**Changement dans `_respond()` :** remplacer `message.content` par `text_content` dans
l'appel à `_fire(_post_process(...))`.

---

## Images dans le sliding window

Les images ne sont **pas** ajoutées à `context_messages` (sliding window texte). La mémoire
canal stocke uniquement `[image]` comme contenu quand le message est image-seul (déjà fait
à la ligne 230 : `stored_content = message.content or "[image]"`). Le budget tokens du
sliding window n'est pas impacté.

---

## Comportement par cas

| Cas | Comportement |
|---|---|
| Texte + image(s), LLM disponible | Analyse LLM multimodale (texte + images) |
| Image seule, LLM disponible | Analyse LLM sur l'image ; texte = "Regarde cette image." |
| Texte + image(s), LLM échoue (exception) | Fallback NRCLex sur le texte uniquement |
| Image seule, LLM échoue (exception) | NRCLex sur "Regarde cette image." → deltas quasi-nuls, log WARNING |
| Twitch (tout cas) | Aucun changement — pas d'images |

---

## Tests à ajouter / modifier

- `test_process_message_with_images` : vérifie que `image_urls` est transmis jusqu'à
  `_analyze_llm` et que `complete_secondary` est appelé avec `image_urls`.
- `test_process_message_image_only_llm` : texte vide + images, LLM disponible → appel LLM
  avec `text_content = "Regarde cette image."` et `image_urls` non-vide.
- `test_process_message_image_only_fallback` : texte vide + images, LLM indisponible
  (exception levée) → fallback NRCLex, aucun delta significatif.
- `test_process_message_text_image_llm_error` : texte non-vide + images, LLM timeout →
  fallback NRCLex sur le texte seul, deltas appliqués depuis le texte.
- Tests existants de `process_message` : aucune modification nécessaire (paramètre
  optionnel, rétrocompatible).

---

## Non-inclus dans ce spec

- Analyse d'images sur Twitch (non supporté par la plateforme).
- Cache ou déduplication des analyses d'images.
- Limite du nombre d'images analysées (déjà plafonnée à 4 dans `handlers.py`).
