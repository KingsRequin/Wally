# Spec : Migration mémoire Qdrant → Graphiti

**Date :** 2026-04-04  
**Statut :** Approuvé pour implémentation  
**Périmètre :** Faire de Graphiti/Neo4j la source principale de mémoire long-terme, Qdrant en lecture seule pendant la transition puis retraité.

---

## Contexte

Qdrant stocke actuellement les faits extraits par `FactExtractor` (FAIT, PREF, LANG, REL) sous forme de vecteurs par utilisateur. Graphiti/Neo4j est déjà en place pour les épisodes conversationnels et le graphe social, mais pas encore pour la mémoire utilisateur individuelle.

Problèmes identifiés avec Qdrant :
- Zéro déduplication (`uuid4()` à chaque `upsert()`) → doublons fréquents intra-conversation
- Pas de décroissance temporelle → vieux souvenirs pèsent autant que récents
- Consolidation à 25 entrées → synthèse brutale, perte de granularité

Graphiti résout ces problèmes nativement (déduplication LLM, validité temporelle, graphe d'entités).

---

## Décisions architecturales

### Isolation utilisateur
**Décision : group_id par contexte, entités par username** (pas un group_id par user).

- `group_id = config.graphiti.group_id` (ex: `"discord:default"`, `"twitch:default"`)
- Les faits sont préfixés par le username dans le body → Graphiti crée/fusionne les nœuds entité automatiquement
- Permet de conserver le graphe social entre utilisateurs
- Alias injectés dans `source_description` pour résolution LLM

### Transition
**Décision : Progressive via 3 flags config** (pas de migration Qdrant, pas de coupure brutale).

- Qdrant existant reste accessible en lecture pendant la transition
- Aucune migration des données historiques (acceptable — Graphiti apprend vite)
- Rollback instantané par toggle de flag

### Alias
- Alias connus (depuis `memory._alias_cache`) injectés dans `source_description` de l'épisode
- Graphiti peut les résoudre lors de futures ingestions via son LLM
- Pas d'API dédiée alias dans Graphiti → fallback Cypher manuel si besoin

---

## Format des épisodes utilisateur

```
name        = "{username} — {category} — {date}"
              ex: "KingsRequin — PREF — 2026-04-04"

body        = "{username} : {content}"
              ex: "KingsRequin : préfère le café au thé"

source_desc = "Souvenir {platform}. Utilisateur: {username} ({platform}:{user_id}).
               Alias connus: {alias1}, {alias2}."

group_id    = config.graphiti.group_id
reference_time = datetime.utcnow()
```

**Catégories mappées :** FAIT, PREF, REL, LANG → incluses dans le `name` de l'épisode.

---

## Fichiers et responsabilités

### `bot/config.py` — 3 flags dans `GraphitiConfig`

```python
memory_write: bool = False      # true = écriture vers Graphiti, Qdrant gelé
memory_primary: bool = False    # true = lecture depuis Graphiti en priorité
memory_dual_read: bool = True   # true = merge Graphiti + Qdrant (transition)
```

Config YAML correspondante :
```yaml
graphiti:
  memory_write: false
  memory_primary: false
  memory_dual_read: true
```

Modifiables depuis le dashboard sans redéploiement.

### `bot/core/graph_memory.py` — Nouveau fichier (~100 LOC)

Deux fonctions publiques, zéro état global :

**`add_user_fact(graph, platform, user_id, username, content, category, alias_cache) -> None`**
- Résout les alias depuis `alias_cache` pour cet uid
- Construit `name`, `body`, `source_description`
- Appelle `graph.add_episode(body, name, source_desc, group_id)`
- Fire-and-forget depuis `memory.add()` (pas de await bloquant)

**`search_user_facts(graph, username, query, limit=8) -> str`**
- Appelle `graph.get_entity_uuid(username)` pour centrer la recherche
- Si UUID trouvé → `graph.search_by_entity(query, center_node_uuid=uuid, limit=limit)`
- Fallback : `graph.search(f"{username} {query}", limit=limit)` si UUID introuvable
- Retourne une string formatée identique au format Qdrant actuel :
  ```
  username aime le café [depuis 2026-04-01]
  username joue à Valorant [depuis 2026-03-15]
  ```

### `bot/core/graph.py` — 2 nouvelles méthodes

**`get_entity_uuid(username: str) -> str | None`**
- Cypher : `MATCH (e:Entity {name: $name}) RETURN e.uuid LIMIT 1`
- Fallback : `MATCH (e:Entity) WHERE e.name CONTAINS $name RETURN e.uuid LIMIT 1`
- Retourne `None` si introuvable (pas d'exception)

**`search_by_entity(query, center_node_uuid, limit=8) -> list[dict]`**
- Appelle `self._graphiti.search(query, center_node_uuid=uuid, num_results=limit)`
- Filtre `invalid_at IS NULL`
- Retourne liste de `{"fact": str, "valid_at": str | None}`

### `bot/core/memory.py` — Modifications ciblées

**`add()` :**
```
if memory_write=true:
    → graph_memory.add_user_fact() [fire-and-forget]
    → return  # skip Qdrant, skip consolidation, skip account_linker
else:
    → comportement actuel Qdrant (inchangé)
```

**`search()` :**
```
if memory_primary=true:
    → graph_memory.search_user_facts()
    if dual_read=true:
        → merge avec _qdrant_search() (Graphiti en premier)
    else:
        → Graphiti only
else:
    → comportement actuel Qdrant (inchangé)
```

**`_post_add_maintenance()` :**
```
if memory_write=true:
    → return early (Graphiti gère la déduplication nativement)
else:
    → comportement actuel (consolidation Qdrant à 25)
```

**`_evaluate()` (questions de suivi) :** inchangé — généré depuis le contenu du fait, indépendant du backend.

**`_merge_contexts(graphiti_ctx, qdrant_ctx) -> str` (privé) :**
- Graphiti en premier (données récentes)
- Qdrant dessous, séparé par `---`
- Budget tokens global : `memory_context_max_tokens` (déjà en place)

### `bot/core/fact_extractor.py` — Aucun changement

Les faits extraits passent déjà par `memory.add()`. Le routing est transparent.

### `bot/discord/handlers.py`, `bot/twitch/handlers.py` — Aucun changement

L'interface `memory.search()` retourne toujours une string. Transparent.

---

## Transition en 4 étapes

| Étape | Flags | Effet |
|---|---|---|
| **Jour 0** — Deploy | tous `false` | Aucun changement, validation du déploiement |
| **Jour 1** — Écriture | `memory_write: true` | Qdrant gelé, Graphiti enrichi |
| **Semaine 2** — Lecture hybride | + `memory_primary: true` | Graphiti lu en priorité, Qdrant fallback |
| **Semaine 6+** — Qdrant retraité | `dual_read: false` | Graphiti seul, Qdrant ignoré |

Qdrant n'est jamais supprimé programmatiquement — il reste accessible mais n'est plus consulté.

---

## Tests

- `test_graph_memory.py` (nouveau) :
  - `test_add_user_fact_calls_graph_add_episode()`
  - `test_search_user_facts_with_entity_uuid()`
  - `test_search_user_facts_fallback_no_uuid()`
  - `test_merge_contexts_graphiti_first()`
- `test_memory.py` (existant, à enrichir) :
  - `test_add_routes_to_graphiti_when_memory_write_true()`
  - `test_add_skips_qdrant_when_memory_write_true()`
  - `test_search_dual_read_merges_results()`
  - `test_post_add_maintenance_skipped_when_memory_write_true()`
- `test_graph.py` (existant, à enrichir) :
  - `test_get_entity_uuid_found()`
  - `test_get_entity_uuid_not_found_returns_none()`
  - `test_search_by_entity_with_center_node()`

---

## Ce qui n'est PAS dans ce spec

- Migration des données Qdrant existantes (hors scope, décision intentionnelle)
- Déduplication Qdrant (abandonné — Qdrant sera retraité)
- Decay temporel Qdrant (abandonné — Graphiti gère nativement)
- Consolidation Qdrant (contournée — skip quand `memory_write=true`)
- Décommissionnement explicite de Qdrant (fait manuellement quand prêt)
