# Memory System Redesign — Direct Qdrant + Structured Metadata

**Date:** 2026-03-25
**Scope:** B — Remplacement mem0, correction de bugs, améliorations structurelles
**Scope C (futur):** Consolidation incrémentale, cleanup inactifs, dédup explicite, séparation trust/love — voir TODO.md

---

## Motivation

mem0 servait de couche d'abstraction entre Wally et Qdrant. Aujourd'hui, Wally a ses propres systèmes de consolidation, cleanup et evaluate qui font le même travail en mieux. mem0 ajoute :

- Un appel LLM OpenAI caché (non tracké) sur chaque `add()`
- Du double travail (dédup mem0 + consolidation Wally)
- Une boîte noire qui empêche le contrôle des métadonnées
- Une API instable (2 formats de réponse gérés dans le code)

Le retrait de mem0 simplifie l'architecture et débloque les améliorations structurelles.

---

## Section 1 — QdrantMemoryStore

Nouvelle classe dans `bot/core/memory_store.py` qui encapsule `qdrant_client.QdrantClient`.

### Interface publique

```python
class QdrantMemoryStore:
    async def upsert(self, user_id: str, text: str, metadata: MemoryMetadata) -> str:
        """Génère l'embedding, stocke dans Qdrant. Retourne le point_id."""

    async def search(
        self, query: str, user_id: str | None = None,
        limit: int = 10, min_score: float = 0.5,
        filters: dict | None = None
    ) -> list[MemoryResult]:
        """Recherche vectorielle avec filtrage natif Qdrant."""

    async def get_all(
        self, user_id: str,
        filters: dict | None = None
    ) -> list[MemoryRecord]:
        """Scroll tous les points d'un user, avec filtres optionnels."""

    async def count(self, user_id: str, filters: dict | None = None) -> int:
        """Count rapide sans charger les données."""

    async def delete(self, point_id: str) -> None:
        """Suppression par ID."""

    async def delete_by_user(self, user_id: str) -> None:
        """Suppression de tous les points d'un user."""

    async def update_payload(self, point_id: str, payload: dict) -> None:
        """Mise à jour de métadonnées sans re-embed."""

    async def update(self, point_id: str, text: str, metadata: MemoryMetadata) -> None:
        """Met à jour texte + métadonnées avec re-embedding (pour édition dashboard)."""

    async def reset(self) -> None:
        """Supprime tous les points de la collection (reset complet)."""
```

### Payload structuré

Chaque point Qdrant contient :

```json
{
  "text": "Préfère le café au thé",
  "user_id": "discord:610550333042589752",
  "category": "PREF",
  "date": "2026-03-25",
  "source": "fact_extractor",
  "platform": "discord",
  "created_at": "2026-03-25T14:30:00Z"
}
```

| Champ | Type | Description |
|---|---|---|
| `text` | str | Le fait mémorisé |
| `user_id` | str | Namespace complet `platform:raw_id` |
| `category` | str | `FAIT`, `PREF`, `LANG`, `REL` |
| `date` | str | Date ISO du fait (YYYY-MM-DD) |
| `source` | str | `fact_extractor`, `emotion`, `image`, `session`, `manual`, `consolidation` |
| `platform` | str | `discord`, `twitch`, `global` |
| `created_at` | str | Timestamp ISO de création du point |

### Embeddings

- Modèle : `text-embedding-3-small` (identique à mem0 — vecteurs existants compatibles)
- Appel direct via `openai.embeddings.create()`
- Exécuté dans `asyncio.to_thread()` (l'API OpenAI sync est plus simple ici)
- Chaque appel loggé via `db.log_cost(model="text-embedding-3-small", ...)`

### Initialisation

Lazy, thread-safe, identique au pattern actuel. Connexion à `QDRANT_URL` (env var).
Collection : réutilise la collection existante (pas de recréation).

Constructeur : `QdrantMemoryStore(qdrant_url: str, collection_name: str, db: Database)`.
Le `db` est nécessaire pour `db.log_cost()` sur chaque appel d'embedding.

---

## Section 2 — Migration des données existantes

Script one-shot `scripts/migrate_mem0_to_qdrant.py` :

1. Scroll tous les points de la collection existante
2. Pour chaque point, extraire le champ `memory` du payload mem0
3. Réécrire le payload au nouveau format :
   - `text` ← `memory`
   - `user_id` ← existant
   - `category` ← `"FAIT"` (défaut, pas d'info dans l'ancien format)
   - `date` ← parser le préfixe `[YYYY-MM-DD]` du texte si présent, sinon date de création du point
   - `source` ← `"legacy_mem0"`
   - `platform` ← extraire du `user_id` (`discord:...` → `discord`)
   - `created_at` ← timestamp existant ou now
4. `qdrant_client.set_payload()` pour chaque point (pas de re-embedding)

**Les vecteurs ne changent pas.** Seuls les payloads sont mis à jour. Opération idempotente et sans perte.

**Note namespace global :** Les souvenirs communautaires ont `user_id="global:server"`. Le script doit parser correctement : `platform="global"`, `user_id` inchangé.

---

## Section 3 — Corrections de bugs

### 3a. Catégorie individuelle par fait

**Problème :** `_extract_facts()` calcule une `dominant_category` par batch. Les faits REL dans un batch à majorité PREF sont mal taggés.

**Fix :** Le schema `FACT_EXTRACTION_SCHEMA` retourne déjà une `category` par fait. Passer cette catégorie individuelle à `memory_store.upsert()` au lieu de la réduire à une dominante.

```python
# Avant (bug)
dominant_category = max(set(categories), key=categories.count)
await memory.add(..., metadata={"category": dominant_category})

# Après (fix)
for fact in fact_items:
    await memory.add(..., metadata={"category": fact["category"]})
```

### 3b. Score de recherche minimum

**Problème :** `_MIN_SEARCH_SCORE = 0.3` est trop permissif, des souvenirs vaguement liés polluent le prompt.

**Fix :** Monter à `0.5`. Le seuil de recall spontané reste à `0.75` (config).

```python
_MIN_SEARCH_SCORE = 0.5  # était 0.3
```

Valeur rendue configurable dans `config.yaml` sous `bot.memory_search_min_score` pour ajustement futur.

### 3c. Fusion consolidation + evaluate

**Problème :** `_maybe_consolidate()` et `_evaluate_memory()` appellent chacun `get_all()` après chaque `add()`. Double traffic Qdrant + double appel LLM potentiel.

**Fix :** Un seul background task `_post_add_maintenance(user_id)` :

```python
async def _post_add_maintenance(self, user_id: str, new_text: str):
    all_memories = await self._store.get_all(user_id)  # 1 seul appel
    count = len(all_memories)

    if count > _CONSOLIDATION_THRESHOLD:
        await self._consolidate(user_id, all_memories)
    else:
        # _evaluate utilise all_memories + pending questions (query SQLite séparée)
        pending_questions = await self._db.get_all_pending_questions(user_id)
        await self._evaluate(user_id, new_text, all_memories, pending_questions)
```

---

## Section 4 — Filtrage natif Qdrant

### `search_relationships()`

**Avant :** `get_all()` → filtre `category == "REL"` en Python.
**Après :** `search()` avec filtre Qdrant natif :

```python
await self._store.search(
    query=context,
    user_id=user_id,
    filters={"category": "REL"},
    limit=10
)
```

### `run_memory_cleanup()`

Peut utiliser `count()` pour vérifier le seuil au lieu de `get_all()`.
Peut filtrer par date pour prioriser les vieux souvenirs.

### `_maybe_consolidate()`

Utilise `count()` pour le check de seuil rapide, puis `get_all()` seulement si consolidation nécessaire.

---

## Section 5 — Budget token pour le bloc mémoire

### Config

```yaml
bot:
  memory_context_max_tokens: 800  # budget token pour le bloc mémoire
```

### Ordre de priorité d'injection

Quand le budget est atteint, les éléments suivants sont coupés en partant de la fin :

| Priorité | Contenu | Budget typique |
|---|---|---|
| 1 (haute) | Souvenirs sémantiques (`search()`) | ~300 tokens |
| 2 | Relations (`search_relationships()`) | ~150 tokens |
| 3 | Souvenirs globaux (`search_global()`) | ~100 tokens |
| 4 | Question pending | ~50 tokens |
| 5 | Jokes récentes | ~100 tokens |
| 6 (basse) | Opinions communautaires | ~100 tokens |

### Séparation trust/love

Trust et love sortent du bloc `--- Ce que tu sais de cet utilisateur ---` et vont dans un mini-bloc séparé `--- Relation ---` injecté après. Ce bloc est toujours présent (même pour les nouveaux users), mais ne pollue plus le bloc mémoire sémantique.

### Estimation token

Même heuristique que la context window : `len(text) / 4`. Simple et cohérent avec le reste du code.

---

## Section 6 — Filtre interjections élargi

Ajout à `_INTERJECTION_PATTERNS` dans `fact_extractor.py` :

**Anglais :** `sure`, `yeah`, `yep`, `nope`, `nah`, `lmao`, `lmfao`, `rofl`, `bruh`, `damn`, `nice`, `cool`, `true`, `fr`, `idk`, `ikr`, `ngl`, `tbh`, `omg`, `wow`, `welp`, `yikes`, `sheesh`, `bet`

La logique reste identique : si le message entier (nettoyé) ne contient que des interjections connues, `_is_memorable()` retourne `False`.

---

## Fichiers impactés

| Fichier | Changement |
|---|---|
| `bot/core/memory_store.py` | **Nouveau** — QdrantMemoryStore |
| `bot/core/memory.py` | Remplacer mem0 par QdrantMemoryStore, fusionner consolidate+evaluate |
| `bot/core/fact_extractor.py` | Fix catégorie individuelle (boucle par fait), interjections élargies |
| `bot/core/prompts.py` | Séparation trust/love dans bloc Relation |
| `bot/core/journal.py` | Rewire `run_memory_cleanup()` — accède `_mem0` directement, passer par `_store` |
| `bot/config.py` | Nouveaux champs `memory_context_max_tokens`, `memory_search_min_score` dans `BotConfig` |
| `bot/discord/handlers.py` | Adapter l'assemblage du `mem_context` au budget token |
| `bot/twitch/handlers.py` | Idem |
| `bot/dashboard/routes/memory.py` | Rewire ~15 appels directs `_mem0` → `_store` (get_all, add, delete, update) |
| `bot/dashboard/routes/links.py` | Rewire merge mémoire (get_all, add, delete_all) → `_store` |
| `bot/dashboard/routes/chat.py` | Rewire `/api/chat/memories` → `_store` |
| `bot/db/database.py` | Vérifier `sync_memory_users_from_qdrant()` — lire `text` au lieu de `memory` si applicable |
| `scripts/migrate_mem0_to_qdrant.py` | **Nouveau** — migration one-shot |
| `config.yaml` | Ajout `memory_context_max_tokens`, `memory_search_min_score` |
| `requirements.txt` | Retrait de `mem0ai` |
| `tests/test_memory.py` | Adapter mocks mem0 → QdrantMemoryStore |
| `tests/test_memory_maintenance.py` | Idem |
| `tests/test_memory_set_db.py` | Idem |
| `tests/test_memory_tag.py` | Idem |
| `tests/test_journal.py` | Adapter mocks mem0 dans cleanup |
| `tests/test_dashboard_memory_routes.py` | Adapter mocks mem0 dashboard |
| `tests/test_dashboard_links.py` | Adapter mocks mem0 merge |
| `tests/test_proactive_recall.py` | Adapter mocks mem0 search |
| `tests/test_dashboard_logs.py` | Vérifier si affecté |

---

## Ce qui ne change PAS

- Le sliding context window (court terme) — fonctionne bien
- Le FactExtractor (pipeline, buffers, flush) — la boucle de stockage change (catégorie par fait) mais le pipeline d'extraction reste identique
- Les prompts LLM (consolidation, cleanup, evaluate) — gardent leur logique
- La spontaneous memory recall — même mécanisme, meilleur filtrage
- L'alias cache et l'account linker — inchangés
- Les tables SQLite (trust_scores, memory_questions, etc.) — inchangées

---

## Ordre d'implémentation

1. `QdrantMemoryStore` — nouvelle classe + tests unitaires
2. Script de migration — tester sur dump avant prod
3. Rewire `MemoryService` — remplacer `self._mem0` par `self._store`
4. Rewire `journal.py` — `run_memory_cleanup()` passe par `_store`
5. Rewire dashboard — `routes/memory.py`, `routes/links.py`, `routes/chat.py`
6. Fix catégorie individuelle dans `_extract_facts()`
7. Fusion `_post_add_maintenance()` (consolidate + evaluate)
8. Score minimum → 0.5, nouveau config `memory_search_min_score`
9. Budget token + séparation trust/love + config `memory_context_max_tokens`
10. Interjections élargies
11. Retrait de `mem0ai` des dépendances
12. Adaptation de tous les tests (9 fichiers identifiés)
13. Vérifier `db.sync_memory_users_from_qdrant()` — champ payload
