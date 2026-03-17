# Discord Vision — Design Spec
Date: 2026-03-17

## Objectif

Permettre à Wally d'analyser les images envoyées sur Discord quand il est mentionné ou triggeré, en s'intégrant naturellement dans le pipeline de messages existant.

## Comportement

- Wally ne traite les images que lorsqu'il est triggeré (mention ou nom déclencheur) — même règle que pour le texte.
- Les images envoyées passivement (sans trigger) sont ignorées complètement : pas de notation dans le prelude.
- Les images sont traitées dans le même appel OpenAI que le texte — pas d'appel séparé.
- Limite : max 4 images par message pour maîtriser la consommation de tokens.

## Fichiers modifiés

### `bot/discord/handlers.py`

Dans `_respond()` :

1. Extraire les URLs des pièces jointes image (max 4) :
   ```python
   image_urls = [
       a.url for a in message.attachments
       if a.content_type and a.content_type.startswith("image/")
   ][:4]
   ```

2. Si le message n'a pas de texte mais a des images, utiliser `"Regarde cette image."` comme texte transmis à OpenAI (uniquement dans l'appel API — `message.content` reste intact).

3. Passer `image_urls` à `openai.complete()` :
   ```python
   reply = await bot.openai.complete(
       system_prompt, openai_messages, purpose="discord_response",
       image_urls=image_urls or None
   )
   ```

4. Pour `bot.memory.append_message()`, stocker `message.content or "[image]"` afin que le prelude ne soit pas vide si le message est image-only. Cette substitution est faite dans `handlers.py` avant d'appeler `append_message()` (le dict `{author, content, timestamp}` reste identique, seule la valeur de `content` change) :
   ```python
   stored_content = message.content or "[image]"
   bot.memory.append_message(str(message.channel.id), message.author.display_name, stored_content)
   ```

### `bot/core/openai_client.py`

1. Ajouter une constante :
   ```python
   FALLBACK_IMAGE_RESPONSE = "Désolé, j'ai une poussière dans l'œil… j'arrive pas à la voir 👁️"
   ```

2. Ajouter `image_urls: list[str] | None = None` à la signature de `complete()`.

3. Ajouter un helper privé :
   ```python
   def _build_image_content(self, text: str, image_urls: list[str], use_responses_api: bool) -> list[dict]:
   ```
   Construit le tableau multimodal selon le format de l'API (format vérifié via SDK officiel) :

   **Chat Completions** (`gpt-4o`, etc.) :
   ```python
   [
       {"type": "text", "text": text},
       {"type": "image_url", "image_url": {"url": url}}  # répété par image
   ]
   ```

   **Responses API** (`gpt-5.*`, `o1`, `o3`, `o4`) :
   ```python
   [
       {"type": "input_text", "text": text},
       {"type": "input_image", "image_url": url}  # string directe, répété par image
   ]
   ```

4. Dans `complete()`, la transformation est appliquée **après** l'assemblage de `full_messages`, sur le dernier message `{"role": "user"}` :
   ```python
   if image_urls:
       last_msg = full_messages[-1]
       last_msg["content"] = self._build_image_content(
           last_msg["content"], image_urls, _uses_responses_api(model)
       )
   ```

5. **Gestion d'erreur image** : quand `image_urls` est fourni (non-None) et qu'une exception est levée pendant l'appel API, retourner `FALLBACK_IMAGE_RESPONSE` plutôt que `FALLBACK_RESPONSE`. La distinction est simple — `image_urls` est déjà connu dans la portée de `complete()` :
   ```python
   except Exception as exc:
       logger.error("OpenAI error: {e}", e=exc)
       return FALLBACK_IMAGE_RESPONSE if image_urls else FALLBACK_RESPONSE
   ```
   Cela couvre les échecs partiels (certaines URLs invalides) : en cas d'erreur quelle qu'en soit la cause, on retourne le fallback image. Pas de retry partiel.

## Non-modifié

- `handle_message()` : aucun changement.
- `_post_process()` : inchangé.
- `complete_secondary()` : pas de support vision (utilisé pour résumés/journal).
- Schéma DB : aucun changement.
- Config : aucun changement.

## Tests

Les tests vérifient le comportement observable via les API publiques :

- `test_build_image_content_chat_completions` : `_build_image_content()` génère le bon format Chat Completions
- `test_build_image_content_responses_api` : `_build_image_content()` génère le bon format Responses API
- `test_complete_with_images_transforms_content` : `complete()` avec `image_urls` transforme bien le dernier message en multimodal
- `test_complete_image_error_returns_image_fallback` : exception pendant un appel avec `image_urls` → `FALLBACK_IMAGE_RESPONSE`
- `test_complete_no_images_uses_generic_fallback` : exception sans `image_urls` → `FALLBACK_RESPONSE` inchangé
- `test_respond_extracts_image_urls` : `_respond()` extrait les URLs et les passe à `complete()`
- `test_respond_limits_4_images` : `_respond()` limite à 4 URLs
- `test_respond_no_text_uses_default_prompt` : message image-only → texte `"Regarde cette image."` dans l'appel API
- `test_respond_image_only_memory_tag` : `append_message` reçoit `"[image]"` si pas de texte
