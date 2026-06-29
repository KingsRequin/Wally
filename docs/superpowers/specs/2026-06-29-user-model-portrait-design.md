# User Model — Portrait dialectique nocturne — Design

**Statut :** approuvé (design)
**Date :** 2026-06-29
**Contexte :** Premier des deux sous-projets « connaître les gens comme un humain » (le second = topics). Suite de la mémoire V2 : la consolidation nocturne ([[project_memory_consolidation_nocturne]]) a posé le pattern « passe nocturne LLM → stockage → réinjection au prompt ». Voir aussi [[project_v2_memory_health]] et le North Star [[project_wally_north_star]].

## Problème

Wally connaît déjà beaucoup de **faits atomiques** par personne (`atomic_facts` : S-P-O, préférences, buts, confidence, decay) mais :
1. **Aucune synthèse** : il redécouvre une personne à chaque message (recherche FTS fraîche) et injecte une **liste de faits bruts**. Pas de « portrait » de qui elle est.
2. **Le récit dialectique est jeté** : quand un fait en contredit un autre, `MemoryIngest` masque l'ancien (`status='superseded'`) et écrit la relation dans `fact_relations` — **table jamais relue**. L'évolution d'une personne (« avant X, maintenant Y ») est perdue.

## Objectif

Construire un **portrait en prose, évolutif et dialectique** par personne : qui elle est, ce qui compte pour elle, comment elle a changé. Régénéré chaque nuit pour les personnes actives du jour, injecté au prompt quand Wally leur parle. Réutilise le pattern de la consolidation nocturne.

## Décisions arrêtées

1. **Forme : portrait en prose** (pas d'attributs structurés). Narratif, nuancé, intègre les revirements en toutes lettres. Aligné North Star.
2. **Déclencheur : nocturne**, greffé sur le **même scheduler que la consolidation** (job cron à `journal_time`). Job séparé (`id="user_model_refresh"`) pour découpler.
3. **Sélection émergente** : on ne régénère QUE les personnes dont des faits ont été créés ou confirmés aujourd'hui (`atomic_facts.last_seen_at >= minuit OR created_at >= minuit`, GROUP BY user_id). Coût borné, pas de gaspillage sur les inactifs.
4. **Pleinement dialectique** : la génération reçoit les faits **actifs** ET les faits **superseded + `fact_relations`** (ressuscités), plus `trust`/`love`.
5. **Le portrait s'ajoute, ne remplace pas** : la recherche sémantique de faits frais (pertinence au message courant) reste inchangée. Le portrait = « qui est cette personne » ; la recherche = « ce qui touche au sujet du moment ».
6. **Identité** : portrait par `user_id` canonique (résolu via alias cache, comme le reste de la mémoire).
7. **Non-fatal** : une personne qui échoue n'arrête pas les autres ; un échec LLM = pas de mise à jour de ce portrait.

## Composants

### Stockage — table `user_profiles` (nouvelle, `schema_v2.py`)
```sql
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id    TEXT PRIMARY KEY,   -- canonical "discord:123" / "twitch:456"
    portrait   TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```
Helpers DB (mixin) :
- `upsert_user_profile(user_id, portrait) -> None` (INSERT OR REPLACE).
- `get_user_profile(user_id) -> str | None`.

### Lecture de la matière (DB / fact_store)
- `get_by_user(user_id)` (existant) → faits actifs.
- **Nouveau** : `get_superseded_by_user(user_id, limit)` → faits `status='superseded'` récents, pour le récit d'évolution. (Optionnellement enrichi des `fact_relations` pour relier ancien→nouveau ; au minimum, le contenu des faits superseded suffit au LLM pour percevoir le changement.)
- **Nouveau** : `get_users_with_recent_facts(since) -> list[str]` → `user_id` distincts dont un fait a `last_seen_at >= since` ou `created_at >= since`.

### `UserModeler` (nouveau) — `bot/intelligence/memory/user_modeler.py`
```python
class UserModeler:
    def __init__(self, db, llm_secondary): ...
    async def refresh_profiles(self, since: float | None = None) -> None
```
- `refresh_profiles` :
  1. `since = since or minuit_local`.
  2. `user_ids = await db.get_users_with_recent_facts(since)`.
  3. pour chaque `user_id` (isolé en try/except) : rassemble faits actifs + superseded + trust/love → `_build_portrait` (LLM) → `db.upsert_user_profile(user_id, portrait)`.
  4. skip si aucun fait actif pour la personne.
- `_build_portrait` : `secondary_llm.complete_structured(load_prompt("user_portrait"), [...], schema, schema_name="user_portrait", purpose="user_model")` → `{portrait: str}`. Non-fatal → None.

### Prompt — `bot/persona/prompts/user_portrait.md`
Directive : à partir des faits (présents + révolus) et de la relation, écrire un portrait court (3-5 phrases), du point de vue de Wally, intégrant l'évolution/contradictions. Comme une impression qu'on se fait de quelqu'un, pas une fiche.

### Câblage
- `bootstrap.py` : construire `UserModeler(db, secondary_llm)`, l'injecter au `DailyJournal` (`set_user_modeler`).
- `journal.py:start` : ajouter le job cron `id="user_model_refresh"` à `journal_time` quand un user_modeler est présent (même pattern que `memory_consolidation`).

### Injection au prompt
Là où le bloc « Relation » (trust/love) et « Ce que tu sais de cet utilisateur » sont assemblés (handlers Discord + Twitch / `prompts.py`) : ajouter un bloc **« --- Qui est {personne} --- »** alimenté par `get_user_profile(user_id)`, en `try/except` non-fatal, budgété via le mécanisme de contexte existant. Cloisonné par personne. S'ajoute à la recherche sémantique (ne la remplace pas).

## Data flow

```
nuit (cron journal_time)
  └─ UserModeler.refresh_profiles()
       ├─ db.get_users_with_recent_facts(since=minuit)        # personnes actives du jour
       └─ par user_id (isolé):
            ├─ faits actifs (get_by_user) + superseded (get_superseded_by_user) + trust/love
            ├─ LLM portrait (user_portrait.md)
            └─ db.upsert_user_profile(user_id, portrait)

réponse à une personne
  └─ build prompt
       └─ get_user_profile(user_id) → bloc "Qui est {personne}" (budgété)
          + recherche sémantique de faits (inchangée)
```

## Gestion d'erreur
- `db` absent / aucune personne active → no-op.
- Échec lecture faits d'une personne → log warning, continue les autres.
- Échec LLM portrait → portrait non mis à jour pour cette personne (l'ancien reste), non-fatal.
- Injection : si lecture profil échoue → bloc omis, prompt normal.

## Tests / critères de succès
1. `refresh_profiles` sans personne active → no-op (aucun appel LLM/upsert).
2. Sélection : seules les personnes avec faits récents (`since`) sont traitées.
3. Une personne avec faits actifs + superseded → le LLM reçoit les deux (vérifier que la matière dialectique est passée) ; `upsert_user_profile` appelé avec le portrait.
4. Isolation : une personne qui lève n'empêche pas les autres.
5. Échec LLM → pas d'upsert pour cette personne, pas d'exception propagée.
6. Helpers DB : `upsert_user_profile` + `get_user_profile` roundtrip ; `get_users_with_recent_facts` filtre correctement ; `get_superseded_by_user` ne renvoie que des superseded.
7. Injection : bloc « Qui est {personne} » présent quand un profil existe, budgété, cloisonné ; absent sinon.
8. Scheduling : job `user_model_refresh` enregistré quand un user_modeler est injecté, absent sinon. Non-régression suite + démarrage bot.

## Hors scope
- `emotional_memory` (table morte — réutilisation possible plus tard pour teinter le portrait de l'émotion dominante déclenchée).
- Attributs structurés (tempérament/préférences en champs).
- Topics / clustering thématique (sous-projet suivant).
- Régénération incrémentale ou à la volée (nocturne uniquement).
