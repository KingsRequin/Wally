# SP2 — Mémoire V2 comme backend unique

**Statut :** approuvé (design)
**Date :** 2026-06-20
**Contexte :** Deuxième sous-projet du chantier « migrer V2, virer V1 ». Suit SP1 (couche LLM unifiée). Voir `project_v1_v2_migration`.

## Objectif

Remplacer le backend mémoire long-terme V1 (`QdrantMemoryStore`, payload monolithe) par la mémoire V2 (`SQLiteFactStore` + `QdrantEmbeddingStore` via `MemoryRetrieval`). `MemoryService` **reste** comme façade (il porte aussi la fenêtre de contexte conversationnel, non concernée). La mémoire est **réinitialisée** (pas de migration de données — l'ancienne « ne fonctionnait pas bien »).

## Décisions arrêtées

1. **Pas de migration de données.** Mémoire long-terme repart vide. Nouvelle collection Qdrant V2 dédiée.
2. **`MemoryService` reste la façade.** On vide ses tripes Qdrant long-terme, on les rebranche sur V2. On **garde intacte** la fenêtre de contexte conversationnel (`append_message`/`get_context`/`append_prelude`/`get_prelude`/`get_all_contexts`/`get_context_summarized_if_needed`) — c'est du RAM, pas de la mémoire Qdrant.
3. **`bot/core/memory_store.py` (QdrantMemoryStore) supprimé.**
4. **Embeddings = OpenAI `text-embedding-3-small`** (1536 dims), réutilisé via un `embedding_fn` partagé (cache LRU + log coût `purpose="embedding"`), comme V1. OpenAI est déjà conservé (images). `QdrantEmbeddingStore` instancié avec `vector_size=1536`.
5. **Collection Qdrant V2** : `wally_v2_facts` (ou `wally_v2_{slug}` multi-instance via `QDRANT_COLLECTION_NAME` si présent).
6. **API façade conservée** : `add(platform, user_id, content, ...)`, `search(platform, user_id, query, ...)`, `get_all(platform, user_id)`, `delete_user_memories(platform, user_id)`, `reset_all()`. Le namespace `platform:user_id` est construit en interne (convention V1 préservée). `add` mappe vers `AtomicFact` (catégorie FAIT par défaut, confidence 1.0).
7. **API abandonnée** (cassée/peu utile, mémoire reset) : `add_global` / `search_global` (mémoire globale), `search_relationships` (les relations vivent dans Graphiti/Neo4j), `search_top_match` (rappel spontané), `_consolidate`, `_evaluate` + `get_pending_question_directive` (questions mémoire). Les appelants sont retirés ou neutralisés.
8. **Aliases conservés** (`load_aliases`/`add_alias`/`remove_alias`) — simple dict en RAM, utilisé par fact_extractor + dashboard, sans rapport avec le backend Qdrant.

## Catégories

`AtomicFact.category` (FactCategory) : FAIT, PREF, REL, LANG, DESIRE, GOAL, EMOTION, THOUGHT. `MemoryService.add` accepte un `category: str` optionnel (défaut "FAIT") et le mappe vers `FactCategory`. Valeur inconnue → FAIT.

## Composants

### `bot/core/embeddings.py` (nouveau)
Fonction d'embedding partagée :
```python
async def make_embedding_fn(image_client, db) -> Callable[[str], Awaitable[list[float]]]
```
Wrappe `OpenAI embeddings.create(model="text-embedding-3-small")` avec cache LRU (clé sha256) + `db.log_cost(purpose="embedding")`. Renvoie une coroutine `embed(text) -> list[float]`.

### `MemoryService` (réécrit en façade V2)
- `__init__` : crée `SQLiteFactStore(db_path)` + `QdrantEmbeddingStore(url, collection, embedding_fn, vector_size=1536)` + `MemoryRetrieval`. (db_path + embedding_fn injectés via setters, comme le client OpenAI aujourd'hui.)
- `add(platform, user_id, content, category="FAIT", username=None, ...)` → `MemoryRetrieval.add_fact(AtomicFact(user_id=f"{platform}:{user_id}", content=content, category=..., confidence=1.0, created_at=now, last_seen_at=now))`.
- `search(platform, user_id, query, limit=20, ...) -> str` → `MemoryRetrieval.search(query, f"{platform}:{user_id}", limit)` → formate en texte (mêmes lignes que V1 attend).
- `get_all(platform, user_id) -> str` → `SQLiteFactStore.get_by_user(f"{platform}:{user_id}")` formaté.
- `delete_user_memories` / `reset_all` → délèguent à `SQLiteFactStore` + purge Qdrant V2.
- Fenêtre de contexte : **inchangée** (copiée verbatim de l'actuel).
- Signatures supprimées : `add_global`, `search_global`, `search_relationships`, `search_top_match`, `get_pending_question_directive`, `_consolidate`, `_evaluate`, `_post_add_maintenance`, `store` property.

## Consommateurs à repointer

| Site | Action |
|------|--------|
| `bot/discord/handlers.py:333,1293,1315` (`add`) | OK — signature conservée |
| `bot/discord/handlers.py:846` (`search`) | OK |
| `bot/discord/handlers.py:847` (`search_global`) | **retirer** l'appel + son injection contexte |
| `bot/discord/handlers.py:877` (`search_relationships`) | **retirer** (relations via Graphiti déjà dans social_context) |
| `bot/discord/handlers.py:692` (`search_top_match`, rappel spontané) | **retirer** le bloc rappel spontané mémoire |
| `bot/discord/handlers.py:518` (`search` third-party) | OK |
| `bot/twitch/handlers.py:155,193,194,222,350,460` | idem Discord : garder add/search, retirer global/relationships/top_match |
| `bot/core/fact_extractor.py` (`add`) | OK |
| `bot/core/journal.py:309-375` (`store.get_all/delete/upsert`) | réécrire sur `SQLiteFactStore` (get_by_user) ou retirer la consolidation journal |
| `bot/discord/commands/ask.py:24` (`search`) | OK |
| `bot/discord/commands/memory_cmd.py:82` (`get_all`) | OK |
| `bot/discord/commands/imagine.py:176` (`add`) | OK |
| `bot/dashboard/routes/chat.py:236,414` (`search`/`add`) | OK ; `store` (337,519) → adapter ou désactiver (refonte site #14/#15) |
| `bot/dashboard/routes/memory.py` (CRUD via `store`) | adapter minimal sur SQLiteFactStore OU désactiver routes V1-spécifiques (différé refonte site) |
| `bot/dashboard/routes/links.py:53-55` (`add_alias`/`store`) | aliases OK ; `store` adapté/retiré |
| `bot/main.py:428` (`store`) | sync compte mémoire → adapter sur SQLiteFactStore ou retirer |

## Suppressions

- `bot/core/memory_store.py` (QdrantMemoryStore) — supprimé.
- Toute référence à `memory.store` (property retirée) — adaptée ou supprimée.
- `bot/dashboard/routes/memory.py` routes dépendant de `store` CRUD V1 : neutralisées (retour vide/501) en attendant la refonte site, OU réécrites minimalement sur SQLiteFactStore.

## Gestion d'erreur

- Qdrant V2 indisponible : `QdrantEmbeddingStore` log WARNING et renvoie `[]` (déjà le cas) → `MemoryRetrieval.search` fallback SQLite `get_by_user`. La mémoire dégrade gracieusement.
- Embedding OpenAI échoue : embedding_fn log WARNING, `upsert` skip (fait reste en SQLite, juste pas indexé sémantiquement).

## Tests / critères de succès

1. `make_embedding_fn` : cache hit ne rappelle pas l'API ; log_cost appelé `purpose="embedding"`.
2. `MemoryService.add` crée un AtomicFact avec `user_id = "platform:raw_id"` et catégorie mappée.
3. `MemoryService.search` renvoie le texte formaté des faits V2 du bon user.
4. Fenêtre de contexte (`append_message`/`get_context`/prelude) : tests existants restent verts (comportement inchangé).
5. Grep : zéro référence à `QdrantMemoryStore`, `memory_store`, `search_global`, `search_relationships`, `search_top_match`, `add_global` hors historique git.
6. Démarrage bot : `MemoryService` initialisé sur backend V2, collection `wally_v2_facts` créée, aucun ImportError.
7. Test fonctionnel : message Discord → fait ajouté en SQLite + indexé Qdrant V2 → `search` le retrouve.

## Hors scope

- SP3 (si encore pertinent) / refonte dashboard mémoire (#14/#15).
- SP4 : suppression code mort résiduel + restructure finale arbo.
- Génération de réponse : inchangée (le pipeline lit la mémoire via la façade, qui marche pareil).
