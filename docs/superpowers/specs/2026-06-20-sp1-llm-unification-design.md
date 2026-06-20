# SP1 — Unification de la couche LLM

**Statut :** approuvé (design)
**Date :** 2026-06-20
**Contexte :** Premier sous-projet du chantier « migrer V2, virer V1 ». Voir décomposition SP1→SP4.

## Objectif

Supprimer la duplication de la couche LLM (deux `base.py` identiques, deux `factory.py` qui se renvoient la balle, clients dispersés entre `bot/core/llm/` et `wally_v2/core/llm/`). État final : **un seul client texte (DeepSeek)**, OpenAI conservé **uniquement** pour la génération d'images, **aucun fallback**.

## Décisions arrêtées

1. **Texte = DeepSeek uniquement.** Claude n'est plus un provider texte → `claude_client.py` supprimé.
2. **Images = OpenAI uniquement.** DeepSeek n'a pas d'API image. `openai_client.py` conservé, mais utilisé seulement pour `image_client` (gpt-image-1.5). OpenAI n'est plus un provider texte.
3. **Aucun fallback.** `fallback.py` supprimé, section `llm.fallback` retirée de la config. Si DeepSeek est down, le bot est muet (accepté).
4. **Emplacement unique : `bot/core/llm/`.** `wally_v2/core/llm/` est entièrement supprimé. Cohérent avec SP4 (tout converge dans `bot/`).

## État cible

```
bot/core/llm/
├── __init__.py        # exports recâblés
├── base.py            # BaseLLMClient (copie unique, déjà ici)
├── deepseek.py        # DÉPLACÉ depuis wally_v2/core/llm/deepseek.py — seul client texte
├── openai_client.py   # CONSERVÉ — images uniquement (generate_image)
└── factory.py         # create_llm_client : deepseek pour texte, lève ValueError sinon
```

### Fichiers supprimés
- `bot/core/llm/claude_client.py`
- `wally_v2/core/llm/base.py` (doublon de `bot/core/llm/base.py`)
- `wally_v2/core/llm/factory.py`
- `wally_v2/core/llm/deepseek.py` (migré vers `bot/core/llm/deepseek.py`)
- `wally_v2/core/llm/fallback.py`
- `wally_v2/core/llm/__init__.py` (le package disparaît)

## Flux de données

- **Texte** (réponses Discord/Twitch, ResponseGate, CognitiveLoop) → `DeepSeekLLMClient` obtenu via `bot.core.llm.factory.create_llm_client(role_config, db)`.
- **Images** → `OpenAILLMClient` construit directement dans `bot/bootstrap.py` (`image_client`), ne passe pas par la factory.
- `wally_v2` (gate, cognitive_loop, etc.) importe désormais `bot.core.llm.*` au lieu de `wally_v2.core.llm.*`.

## Importeurs à recâbler

Tirés de la cartographie V1↔V2 :

| Fichier | Changement |
|---------|-----------|
| `bot/core/llm/factory.py` | importe `deepseek` en local (`from bot.core.llm.deepseek import DeepSeekLLMClient`) ; retire branches claude/openai du dispatch texte ; lève `ValueError` sur provider ≠ deepseek |
| `bot/bootstrap.py` | retire le bloc `FallbackLLMClient` (import + wrapping primary/secondary) |
| `bot/discord/bot.py` | `create_v2_llm` pointe sur `bot.core.llm.factory.create_llm_client` (au lieu de `wally_v2.core.llm.factory`) |
| `bot/discord/handlers.py` | inchangé (importe `wally_v2.core.memory.facts`, pas la couche llm) |
| `wally_v2/core/gate.py`, `cognitive_loop.py`, agents | imports `wally_v2.core.llm.base` → `bot.core.llm.base` si présents |
| `tests/v2/core/llm/test_deepseek_client.py` | import `bot.core.llm.deepseek` |
| `tests/v2/` (fallback) | tests de `fallback.py` supprimés |

**Vérification grep obligatoire (NO SEMANTIC SEARCH) :** rechercher séparément `wally_v2.core.llm`, `wally_v2/core/llm`, `from wally_v2.core.llm`, `import.*fallback`, `claude_client`, `ClaudeLLMClient`, `FallbackLLMClient` sur tout le repo (code + tests + mocks) pour garantir zéro référence résiduelle.

## Config

- `config.yaml` : `llm.primary.provider` et `llm.secondary.provider` forcés à `deepseek` ; `llm.fallback` supprimé.
- `bot/config.py` : champ `LLMConfig.fallback` retiré ; parsing de `llm.fallback` retiré dans `_build_llm_config` ; `save()` ne sérialise plus `fallback`.
- Section legacy `openai:` (OpenAIConfig) : **conservée** — alimente `image_client`.

## Gestion d'erreur

- `factory.create_llm_client` : sur provider texte ≠ `deepseek`, lève `ValueError(f"Unknown text LLM provider: {provider!r}. Only 'deepseek' supported.")`.
- `DeepSeekLLMClient` conserve son comportement actuel (try/except interne, renvoie `FALLBACK_RESPONSE` sur échec). Plus de bascule provider derrière.

## Tests / critères de succès

1. `bot/core/llm/factory.py` : `create_llm_client(LLMRoleConfig(provider="deepseek", ...), db)` renvoie un `DeepSeekLLMClient` ; provider ≠ deepseek lève `ValueError`.
2. Import sanity : `from bot.core.llm.deepseek import DeepSeekLLMClient` réussit ; `import wally_v2.core.llm` échoue (package supprimé).
3. Grep : zéro occurrence de `wally_v2.core.llm`, `claude_client`, `ClaudeLLMClient`, `FallbackLLMClient` hors historique git.
4. Suite `tests/v2/` verte après recâblage (hors tests fallback supprimés).
5. Démarrage bot (rebuild + up) : logs montrent 1 client texte DeepSeek (primary+secondary), `image_client` OpenAI intact, ResponseGate + CognitiveLoop initialisés, aucune ImportError.
6. `/wally imagine` fonctionne toujours (image_client OpenAI).

## Hors scope (autres sous-projets)

- SP2 : unification mémoire (V1 MemoryService → V2 AtomicFacts).
- SP3 : génération de réponse en V2.
- SP4 : suppression code mort V1 + restructure finale de l'arbo.
