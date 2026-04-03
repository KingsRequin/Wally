# Graphiti — Améliorations fonctionnelles

**Date :** 2026-04-03  
**Contexte :** Neo4j + Graphiti déployé (commit 94b30d7). Trois axes fonctionnels identifiés comme insuffisants ou non fonctionnels.

---

## Axe 1 — Fix affinity + community detection

### Problème actuel

`get_affinity()` utilise `graphiti.search(f"{user_a} {user_b}")` — un semantic search qui retourne des arêtes voisines, puis filtre en vérifiant si les deux noms apparaissent dans le texte du fact. Cette heuristique est fragile et retourne 0.0 dans la majorité des cas réels.

La community detection (`update_communities=True`) n'est jamais activée : le paramètre par défaut est `False` partout, et aucun job nocturne n'existe. L'endpoint `/api/admin/social-graph/communities` retourne toujours `[]`.

### Solution

**`get_affinity()` — Cypher direct**

Remplacer le semantic search par une requête Cypher directe sur les arêtes entre les deux entités :

```cypher
MATCH (a:Entity {group_id: $gid})-[r:RELATES_TO]-(b:Entity {group_id: $gid})
WHERE toLower(a.name) = $name_a AND toLower(b.name) = $name_b
  AND r.invalid_at IS NULL
RETURN r.name AS type, count(r) AS cnt
```

Le score est calculé en appliquant les `affinity_weights` config sur les compteurs par type (`vocal`, `reply`, `mention`, `reaction`, `thread`, `game`). Le mapping type→weight utilise les keywords actuels (`vocal`, `répondu`, `mentionné`…) mais sur le champ `r.name` (plus fiable que le texte du fact).

**Job nightly community detection**

Nouveau module `bot/core/graph_jobs.py` avec une fonction `schedule_community_detection(graph, scheduler)`. Lance un job apscheduler à 3h00 UTC chaque nuit. Le job vérifie `graph.ready` avant d'agir (skip silencieux si Neo4j down). Il appelle `graphiti.add_episode(update_communities=True)` sur un épisode synthétique de déclenchement, ou via l'API interne Graphiti si elle expose un `update_communities()` standalone. Intégré dans `main.py` après `graph.initialize()`.

### Fichiers touchés

- `bot/core/graph.py` — réécriture de `get_affinity()`
- `bot/core/graph_jobs.py` — nouveau, job nightly
- `bot/main.py` — appel `schedule_community_detection()`

---

## Axe 2 — Graph context enrichi dans le prompt

### Problème actuel

Dans `handlers.py`, la recherche graph utilise `message.content` brut comme query, retourne 5 résultats sans filtrer les facts invalides (`invalid_at` non nul), et injecte un bloc non structuré (`- fact`).

### Solution

**Requête améliorée**

```python
query = f"{author_label}: {message.content}"
```

Filtrage Python des results : garder uniquement `edge["invalid_at"] is None`.

`num_results` passe de 5 à 10.

**Format du bloc**

```
--- Connaissances du graphe ---
• Keychka joue souvent à Valorant avec Azrael  [depuis 2026-03-10]
• Azrael déteste les lundis  [depuis 2026-02-14]
```

Chaque ligne préfixée `•`, avec `[depuis {valid_at.date()}]` si `valid_at` est présent.

**Budget tokens**

Nouveau paramètre config `graphiti.graph_context_max_tokens` (défaut : 400). Tronquer les facts en excès (même logique que `memory_context_max_tokens`). Ajouté dans `GraphitiConfig` dans `config.py`.

### Fichiers touchés

- `bot/discord/handlers.py` — requête enrichie + filtrage + format
- `bot/config.py` — `graph_context_max_tokens` dans `GraphitiConfig`

---

## Axe 3 — Social awareness proactive dans le prompt

### Problème actuel

Le graphe capture les relations sociales (vocal, jeux, mentions) via `SocialTracker`, mais ces relations ne sont jamais injectées dans le prompt système. Wally répond sans savoir que Keychka et Azrael sont proches, ou que tel groupe joue ensemble.

### Solution

**Nouvelle méthode `GraphService.get_social_context()`**

Requête Cypher légère sur les arêtes les plus fréquentes du groupe :

```cypher
MATCH (a:Entity {group_id: $gid})-[r:RELATES_TO]-(b:Entity {group_id: $gid})
WHERE r.invalid_at IS NULL
WITH a.name AS ua, b.name AS ub, count(r) AS strength
WHERE strength >= 3
RETURN ua, ub, strength
ORDER BY strength DESC
LIMIT 10
```

Retourne une liste de tuples `(name_a, name_b, strength)`.

**Label de proximité**

| Score | Label |
|-------|-------|
| ≥ 10  | très proches |
| ≥ 5   | proches |
| ≥ 3   | interagissent |

**Bloc injecté**

```
--- Relations sociales connues ---
• Keychka ↔ Azrael  (très proches)
• Saphira ↔ Keychka  (proches)
```

**Intégration prompt**

Nouveau paramètre `social_context: str` dans `PromptBuilder.build_system_prompt()`. Injecté après `graph_context` dans le system prompt.

**Appel depuis handlers.py**

Lancé en parallèle avec la recherche graph existante (deux `asyncio.create_task`). Rate-limité à 1 appel / 60s par channel via `_social_context_cooldowns: dict[int, float]` (même pattern que `_memory_check_cooldowns`).

### Fichiers touchés

- `bot/core/graph.py` — nouvelle méthode `get_social_context()`
- `bot/core/prompts.py` — paramètre `social_context` dans `build_system_prompt()`
- `bot/discord/handlers.py` — appel parallèle + rate-limiting + injection

---

## Récapitulatif des fichiers

| Fichier | Changement |
|---------|-----------|
| `bot/core/graph.py` | `get_affinity()` Cypher + `get_social_context()` |
| `bot/core/graph_jobs.py` | Nouveau — job community detection nightly |
| `bot/core/prompts.py` | Paramètre `social_context` |
| `bot/config.py` | `graph_context_max_tokens` |
| `bot/discord/handlers.py` | Query enrichie, social_context parallèle, rate-limit |
| `bot/main.py` | `schedule_community_detection()` |

6 fichiers, tous indépendants — adaptés à une exécution phasée.

---

## Hors scope

- Remplacement de Qdrant par Graphiti pour la recherche mémoire (projet séparé)
- Multi-hop traversal (friends of friends) — nécessite Graphiti v0.30+
- Injection des communities dans le prompt (dépend du peuplement effectif des communities)
