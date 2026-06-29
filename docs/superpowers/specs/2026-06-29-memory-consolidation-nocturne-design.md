# Consolidation nocturne de la mémoire — Design

**Statut :** implémenté (révisé)
**Date :** 2026-06-29

> **Révision 2026-06-29 (post-revue finale).** La conception initiale sourçait `db.get_recent_session_messages` pour extraire à la fois les faits durables et un résumé. La revue finale a montré que `session_messages` est un buffer transitoire (~10 min, purgé à chaque flush du live) → quasi vide à l'heure du cron. **Correction livrée** : la consolidation lit **`daily_log`** (journal durable de la journée, `get_today_messages`, rétention 7j) et **produit uniquement le résumé de session** (cross-session recall). L'extraction de faits a été retirée de la passe nocturne : elle est déjà assurée en continu par le live (flush à 600 s d'inactivité) et `daily_log` n'a pas de `user_id` pour l'attribution. Le reste du design (déclencheur, stockage `session_analyses`, recall budgété/cloisonné) est inchangé. Le `MemoryConsolidator` ne dépend plus que de `(db, llm_secondary)`.
**Contexte :** Dernier maillon manquant de la mémoire V2. La mémoire V2 (FTS5/SQLite, faits S-P-O, réconciliation 2 étages, retrieval Generative-Agents) est complète et déployée pour les chemins **synchrones** (extraction live message-par-message, recherche). Manque la dimension « vivante » : rien ne relit une conversation après coup, Wally ne « repense » jamais à ses journées et ne se souvient pas de ses sessions passées. Voir `project_v2_memory_health`.

## Objectif

Ajouter une passe **quotidienne nocturne** (« sommeil/rêve ») qui, à partir des conversations du jour, produit :

1. **Faits durables** que l'extraction live a ratés (conversations trop courtes pour déclencher un flush, ou bénéficiant d'une vue d'ensemble de la journée).
2. **Résumés de session** par canal, réinjectés au system prompt les jours suivants → vrai *cross-session recall* (« hier tu m'avais dit… »).

Le tout en **réutilisant le pipeline d'extraction existant** (`_extract_facts` → `MemoryIngest`, déjà testé) pour rester robuste, et en **ressuscitant la table morte `session_analyses`**.

## Décisions arrêtées

1. **Déclencheur : nocturne**, une passe/jour, greffée sur le **scheduler du `DailyJournal`** (`journal.py:_schedule`, qui possède déjà `add_job(generate_and_send)` + `add_job(run_memory_cleanup)` à `bot.journal_time`). Coût LLM borné.
2. **Source des données : `db.get_recent_session_messages(since=minuit)`** (table `session_messages`, déjà persistée par le live, format `{channel_id, platform, user_id, display_name, content, timestamp}`). Pas de parsing des logs JSONL.
3. **Réutilisation du pipeline** : extraction via `FactExtractor._extract_facts(msg_dicts, platform, channel_id)` → routage `MemoryIngest` (réconciliation 2 étages → **pas de doublon** même si un message est re-traité).
4. **Pas de nouveau backend** : faits → `atomic_facts` (existant) ; résumés → `session_analyses` (ressuscitée, schéma étendu).
5. **Non-fatal** : toute erreur de consolidation est isolée (`try/except`), ne casse jamais le journal ni le bot.
6. **Hors scope** (sous-projets suivants) : user model dialectique, topics/clustering, auto-critique de qualité (`issues`/`successes`/`improvement_note` restent dispo mais non remplis ici). Retrait de la table morte `thoughts`.

## Composants

### `MemoryConsolidator` (nouveau) — `bot/intelligence/memory/consolidator.py`
Responsabilité unique : transformer les messages d'une journée en faits + résumés.

```python
class MemoryConsolidator:
    def __init__(self, db, secondary_llm, fact_extractor, memory): ...
    async def consolidate_day(self, since: float | None = None) -> None
```

- `consolidate_day` :
  1. `rows = await db.get_recent_session_messages(since or minuit_local)`.
  2. Groupe `rows` par `channel_id` (conserve `platform`).
  3. Pour chaque canal avec **≥ 2 messages humains** :
     - **(a) Faits** : `await fact_extractor._extract_facts(msgs, platform, channel_id)` (les dicts ont déjà la bonne forme).
     - **(b) Résumé** : `secondary_llm.complete_structured(...)` avec un prompt dédié `memory_session_summary.md` → `{summary: str}` (2-4 phrases : sujets abordés, ce qui compte pour le recall). Écrit via `db.insert_session_analysis(...)`.
  4. Chaque canal est isolé en `try/except` (un canal qui échoue n'arrête pas les autres).
- Skip silencieux si `db` absent, 0 message, ou < 2 messages humains.

### Câblage
- `bootstrap.py` : construire `MemoryConsolidator` (db, secondary_llm, fact_extractor, memory) et l'injecter dans `DailyJournal`.
- `journal.py:_schedule` : `add_job(self._consolidator.consolidate_day, CronTrigger ...)` à la même heure que le journal (ou appel direct en tête de `generate_and_send`, **avant** la génération du texte du journal pour que les faits frais soient dispo). Choix retenu : **job séparé même heure**, pour découpler (un échec de consolidation n'affecte pas le journal).

### Stockage — `session_analyses` (schéma étendu) — `db/schema_v2.py`
Colonnes ajoutées (idempotent, `CREATE TABLE IF NOT EXISTS` mis à jour + migration `ALTER TABLE ... ADD COLUMN` défensive dans l'init) :
```sql
platform   TEXT       -- recall ciblé par plateforme
channel_id TEXT       -- recall ciblé par canal
summary    TEXT       -- le résumé réinjecté
```
Champs existants `quality/issues/successes/improvement_note` conservés (non remplis ici). `session_id` = `{platform}:{channel_id}:{YYYY-MM-DD}` (unique par canal et par jour ; ré-exécution le même jour fait un upsert/remplace au lieu d'empiler).

Helpers DB (`db/mixins/...`) :
- `insert_session_analysis(platform, channel_id, summary, ...)`.
- `get_recent_session_summaries(platform, channel_id, limit=3) -> list[dict]`.

### Recall — réinjection au prompt
Un bloc « Sessions précédentes » dans la construction du contexte mémoire (là où les autres blocs mémoire/journal sont assemblés, côté `handlers.py` / `PromptBuilder`), alimenté par `get_recent_session_summaries(platform, channel courant)`. **Budgété** (N=3 derniers résumés, tronqué pour ne pas exploser le prompt). Cloisonné par canal (cohérent avec l'anti-fuite inter-salons existant, `project_cognitive_channel_coherence`).

## Data flow

```
nuit (cron journal_time)
  └─ MemoryConsolidator.consolidate_day()
       ├─ db.get_recent_session_messages(since=minuit)   [session_messages]
       ├─ group by channel
       └─ par canal (≥2 humains):
            ├─ _extract_facts → MemoryIngest → atomic_facts   (faits durables, dédupés)
            └─ LLM résumé → db.insert_session_analysis        (session_analyses)

jour suivant, message sur le canal
  └─ build prompt
       └─ get_recent_session_summaries(canal) → bloc "Sessions précédentes" (budgété)
```

## Gestion d'erreur

- `db` absent / 0 message / <2 humains → skip, log debug.
- Échec extraction d'un canal → log warning, continue les autres canaux.
- Échec LLM résumé → on garde quand même les faits extraits ; pas de résumé pour ce canal.
- Échec écriture `session_analyses` → log warning, non-fatal.
- Recall : si lecture résumés échoue → bloc omis, prompt normal.

## Tests / critères de succès

1. `consolidate_day` sur 0 message → no-op (aucun appel LLM/DB d'écriture).
2. Canal avec < 2 messages humains → skip ; canal ≥ 2 → `_extract_facts` appelé avec les dicts attendus.
3. Groupement multi-canaux : chaque canal traité indépendamment ; un canal qui lève n'empêche pas les autres.
4. Résumé écrit dans `session_analyses` (platform/channel_id/summary) puis relu par `get_recent_session_summaries`.
5. Réconciliation : re-traiter un message déjà extrait n'ajoute pas de doublon (support_count++ via `MemoryIngest`).
6. Recall : bloc « Sessions précédentes » injecté pour le bon canal, budgété/tronqué, cloisonné (pas de fuite d'un autre canal).
7. Non-régression : `journal.generate_and_send` reste vert ; le bot démarre, scheduler enregistre le nouveau job.
8. Tests critiques manquants comblés au passage : réconciliation 2 étages (`MemoryIngest.reconcile_candidate`), decay/recency scoring.
9. Migration `session_analyses` idempotente (ré-exécution de l'init ne casse pas) ; table `thoughts` retirée sans impact (aucun lecteur).

## Hors scope

- User model dialectique (préférences/contradictions par personne) → sous-projet suivant.
- Topics / clustering thématique.
- Auto-critique de qualité de session (`issues`/`successes`/`improvement_note`).
- Déclenchement à l'inactivité par canal (rejeté au profit du nocturne).
