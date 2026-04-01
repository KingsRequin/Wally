# Spec — Corrections mémoire + Migration Graphiti

Date: 2026-04-01

---

## Chantier B — Corrections ciblées (quick fixes)

### B1. Compteur dashboard après consolidation

**Problème** : `memory_count` mis à jour dans `add()` mais pas dans `_consolidate()`.

**Correction** : Ajouter dans `_consolidate()`, après `delete_batch` :
```python
count = await self._store.count(uid)
await self._db.execute(
    "UPDATE memory_users SET memory_count=? WHERE user_id=?", (count, uid)
)
```

**Fichier** : `bot/core/memory.py`, fin de `_consolidate()`.

---

### B2. Questions en double — race condition

**Problème** : Deux `_post_add_maintenance()` concurrents lisent le même snapshot de questions pending et insèrent la même question.

**Correction** :
1. Verrou asyncio par utilisateur :
```python
_maintenance_locks: dict[str, asyncio.Lock] = {}

async def _post_add_maintenance(self, uid, content):
    lock = self._maintenance_locks.setdefault(uid, asyncio.Lock())
    async with lock:
        # ... logique existante
```
2. Contrainte UNIQUE au niveau DB : `UNIQUE(user_id, question)` sur `memory_questions`, avec `INSERT OR IGNORE`.

**Fichiers** : `bot/core/memory.py` (`_post_add_maintenance`), `bot/db/database.py` (schema + insert).

---

### B3. Questions pas marquées comme résolues

**Problème** : La résolution dépend du LLM dans `_evaluate()`, qui ne tourne que sur les messages "mémorables". Si l'utilisateur répond mais que le message ne passe pas `_is_memorable()`, la question reste pending.

**Correction** :
1. **Résolution sémantique à l'injection** : Avant d'injecter une question pending via `get_pending_question_directive()`, faire un Qdrant search avec la question comme query. Si score > 0.85, auto-résoudre sans LLM.
2. **Résolution dans le handler** : Déclencher `_evaluate()` aussi sur les messages non-mémorables quand une question est activement injectée dans le prompt (la réponse est probablement dans le message courant).

**Fichiers** : `bot/core/memory.py` (`get_pending_question_directive`, `_evaluate`).

---

### B4. Notes persistantes — le bot ne les utilise pas

**Problème** : Le LLM n'appelle jamais `save_persistent_note` ou `save_user_memory` spontanément. Les descriptions des tools sont trop techniques.

**Correction** :
1. **Reformuler les descriptions des tools** :
   - `save_persistent_note` : "Quand quelqu'un te demande de retenir quelque chose qui concerne tout le serveur (un événement, une règle, une info communautaire), utilise cet outil."
   - `save_user_memory` : "Quand quelqu'un te demande de retenir quelque chose qui le concerne personnellement (préférence, fait bio, opinion), utilise cet outil."
2. **Directive system prompt** : Ajouter dans le persona un bloc :
   > "Si on te demande de retenir ou mémoriser quelque chose, utilise les outils save_persistent_note (info globale) ou save_user_memory (info personnelle). Ne réponds jamais 'je m'en souviendrai' sans appeler l'outil."

**Fichiers** : `bot/discord/handlers.py` (`_NOTE_TOOLS`), `bot/core/prompts.py` ou `bot/persona/prompts/`.

---

### B5. Clarification Notes vs Global dans le dashboard

**Problème** : Deux onglets ("Notes" et "Global") avec des rôles confus.

**Correction** :
1. Renommer :
   - "Notes" → **"Notes du bot"** — sous-titre : "Règles et engagements que Wally garde toujours en tête"
   - "Global" → **"Mémoire communautaire"** — sous-titre : "Faits sur le serveur, retrouvés par pertinence"
2. Ajouter un texte explicatif dans chaque onglet.

**Fichier** : `bot/dashboard/static/app.js`.

---

## Chantier A — Migration Graphiti + Neo4j

### A1. Infrastructure

**docker-compose** :
- Service `neo4j` : image `neo4j:5-community`, ports 7687 (Bolt) + 7474 (Browser), ~1 GB RAM.
- Healthcheck Neo4j, `wally` dépend de `neo4j` + `qdrant`.
- Multi-instance : le provisioner crée un conteneur Neo4j par instance.

**Dépendances Python** : `graphiti-core` (inclut driver Neo4j async).

**Config** : Section `graphiti:` dans `config.yaml` :
```yaml
graphiti:
  neo4j_uri: bolt://neo4j:7687
  neo4j_user: neo4j
  neo4j_password: <from .env>
  llm_model: gpt-5-nano
  community_detection: true
```

---

### A2. Nouveau pipeline mémoire

**Avant** :
```
Message → _is_memorable() → _extract_facts() → Qdrant upsert → _consolidate() ou _evaluate()
```

**Après** :
```
Message → _is_memorable() → Graphiti.add_episode() → (entités + relations + dédup + invalidation temporelle)
```

**Ce qui disparaît** :
- `_consolidate()` — Graphiti gère dédup/invalidation nativement
- Catégories plates FAIT/PREF/LANG/REL — remplacées par entités et relations typées Neo4j

**Ce qui reste** :
- `_is_memorable()` — filtre en amont
- `_evaluate()` — questions de suivi (SQLite, indépendant)
- `MemoryService` comme façade — interface publique inchangée (`add()`, `search()`, `get_all()`)
- Qdrant conservé comme fallback pendant la migration

**Recherche** : `memory.search()` → `Graphiti.search()` (hybride BM25 + vector + graphe). Résultat reformaté en `MemoryRecord`.

**Modèle LLM** : gpt-5-nano pour tous les appels internes Graphiti.

---

### A3. Signaux sociaux

Nouveau module `bot/discord/social.py` — 6 capteurs, 0 appels LLM :

| Signal | Event discord.py | Arête Neo4j | Poids affinité |
|---|---|---|---|
| Vocal | `on_voice_state_update` | `EN_VOCAL_AVEC {count, duration_total, last_seen}` | ×3 |
| Réponses | `on_message` (reply) | `REPOND_A {count, last_seen}` | ×2 |
| Mentions | `on_message` (mentions) | `MENTIONNE {count, last_seen}` | ×1.5 |
| Réactions | `on_reaction_add` | `REAGIT_A {count, last_seen}` | ×1 |
| Threads | `on_message` (in thread) | `THREAD_COMMUN {count, last_seen}` | ×1 |
| Jeux | `on_presence_update` | `JOUE_AVEC {count, game, last_seen}` | ×2.5 |

**Agrégation** : Compteur + `last_seen` par arête, pas d'arête par événement individuel.

**Rate limiting** : `on_presence_update` bufferisé, flush toutes les 5 minutes.

**Score d'affinité** : Calculé à la demande.
```
affinité = vocal×3 + réponses×2 + mentions×1.5 + réactions×1 + threads×1 + jeux×2.5
```
Poids configurables dans `config.yaml`.

---

### A4. Visualisation — Page "Graphe social"

**Neo4j Browser** : Port 7474 exposé dans docker-compose. Admin only.

**Page `/graph`** : Accessible aux membres Discord authentifiés (OAuth2 JWT) et présents sur le serveur du bot.

**Tech** : neovis.js, connecté via API backend (`/api/social-graph`) — pas de connexion Bolt directe depuis le navigateur.

**Vue** :
- Noeuds = utilisateurs, dimensionnés par centralité
- Arêtes colorées par type : vocal (violet), réponses/mentions (bleu), réactions (jaune), jeux (vert), relations Graphiti (cyan)
- Épaisseur proportionnelle au score d'affinité
- Clic noeud → panneau latéral : résumé Graphiti, relations, score d'affinité
- Clic arête → détail type, compteur, dernière activité
- Filtres : par type de relation (toggles), temporel (7j / 30j / tout)

**Style** : Glassmorphism — fond sombre, noeuds avec glow, arêtes semi-transparentes.

**Auth** : Discord OAuth2 + vérification membership serveur. Tous les membres voient tout (mémoires, relations, résumés). Pas de données privées — tout vient de l'activité publique du serveur.

---

## Ordre d'exécution

1. **Chantier B** — quick fixes (B1→B5), commit + push
2. **Chantier A1** — Infra Neo4j + Graphiti
3. **Chantier A2** — Migration pipeline mémoire
4. **Chantier A3** — Signaux sociaux
5. **Chantier A4** — Visualisation graphe
