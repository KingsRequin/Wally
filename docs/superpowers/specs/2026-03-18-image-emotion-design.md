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
- **Modèle LLM :** Le modèle secondaire (`secondary_model`, actuellement `gpt-5-mini`)
  est utilisé — il supporte déjà la vision.
- **Fallback NRCLex :** Si le LLM est indisponible, l'analyse tombe en fallback NRCLex sur
  le texte uniquement. Si le message est image-seul (texte vide), aucun delta est appliqué.
  Comportement silencieux (log DEBUG).

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
`handlers.py`) et passées à `_fire(_post_process(...))`.

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

Quand `image_urls` est non-vide, une instruction est ajoutée au `system_prompt` de
`_analyze_llm` :

> "Si des images sont jointes au message, analyse aussi leur contenu émotionnel (ton
> visuel, sujet représenté, contexte apparent) pour affiner les deltas. Une image de rage,
> un mème sarcastique ou une photo triste doit influencer les deltas au même titre que le
> texte."

Le message utilisateur devient multimodal : le texte déclencheur est converti via
`OpenAIClient._build_image_content()` (déjà disponible) pour inclure les images en
pièces jointes.

---

## Appel `complete_secondary` avec images

`complete_secondary()` délègue à `complete()` qui accepte déjà `image_urls`. Il suffit
de passer le paramètre :

```python
raw = await self._openai.complete_secondary(
    system_prompt,
    [{"role": "user", "content": user_msg_content}],
    purpose="emotion_analysis",
    image_urls=image_urls or None,
)
```

où `user_msg_content` est soit une chaîne (pas d'image) soit une liste de blocs
multimodaux construits par `_build_image_content`.

---

## Comportement par cas

| Cas | Comportement |
|---|---|
| Texte + image(s), LLM disponible | Analyse LLM multimodale (texte + images) |
| Image seule, LLM disponible | Analyse LLM sur l'image ; texte = "Regarde cette image." |
| Texte + image(s), LLM indisponible | Fallback NRCLex sur le texte uniquement |
| Image seule, LLM indisponible | NRCLex sur texte vide → aucun delta, log DEBUG |
| Twitch (tout cas) | Aucun changement — pas d'images |

---

## Tests à ajouter

- `test_process_message_with_images` : vérifie que `image_urls` est bien transmis jusqu'à
  `_analyze_llm` et que `complete_secondary` est appelé avec `image_urls`.
- `test_process_message_image_only_fallback` : texte vide + images, LLM indisponible →
  aucun delta appliqué.
- Mise à jour des tests existants de `process_message` : signature compatible (paramètre
  optionnel, pas de rupture).

---

## Non-inclus dans ce spec

- Analyse d'images sur Twitch (non supporté par la plateforme).
- Cache ou déduplication des analyses d'images.
- Limite du nombre d'images analysées (déjà plafonnée à 4 dans `handlers.py`).
