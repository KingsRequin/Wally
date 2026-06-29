# Topics — Sujets de communauté enrichis — Design

**Statut :** approuvé (design)
**Date :** 2026-06-29
**Contexte :** Second des deux sous-projets « connaître les gens comme un humain » (le premier = user model, livré : [[project_user_model_portrait]]). Réutilise la passe nocturne du journal. Voir North Star [[project_wally_north_star]].

## Problème

Wally a déjà un embryon de topics : la table `opinions(topic UNIQUE, opinion)`, alimentée chaque nuit par `DailyJournal._form_opinions` (le LLM extrait « max 3 sujets marquants » du résumé du jour → `{topic, opinion}`), injectée au prompt (bloc « Tes opinions sur les sujets de la communauté », Discord + Twitch). Mais ce n'est qu'un **sujet + l'avis de Wally**. Il manque le **transversal** : qui parle de quoi (recoupement social), ce qui s'est dit (mémoire thématique), et ce qui monte (tendances).

## Objectif

Faire évoluer `opinions` en une table **`topics`** plus riche — un sujet devient un objet à plusieurs facettes, formé chaque nuit, injecté au prompt. **On converge sur l'existant, on ne crée pas de système parallèle.**

## Décisions arrêtées

1. **`topics` remplace `opinions`.** Nouvelle table ; l'ancienne `opinions` est retirée (`DROP`). **Pas de migration de données** : les opinions sont éphémères (max 10, 30 j) et se reforment en topics dès la première nuit (cohérent avec l'esprit émergent).
2. **Un topic = name + summary + participants + opinion + mention_count + last_seen_at**, couvrant les trois facettes (mémoire thématique, recoupement social, tendances) en un seul objet.
3. **Formation nocturne par extension de `_form_opinions`** → `_form_topics` (dans le journal, déjà lancé le soir). Pas de nouveau composant.
4. **Amélioration A — participants reliés aux vraies personnes** : les pseudos extraits par le LLM sont résolus vers les `user_id` canoniques via l'alias cache existant (`memory._alias_cache["nickname:{pseudo_lower}"]`) ; fallback = le nom brut si inconnu. Relie les topics au user model.
5. **Amélioration B — anti-fragmentation** : la liste des topics existants (`name`) est injectée dans le prompt de formation pour que le LLM **réutilise** un nom existant (« Apex Legends ») plutôt qu'inventer une variante (« Apex », « le BR »).
6. **Non-fatal** : la formation est en `try/except` (déjà le cas pour `_form_opinions`) ; l'injection aussi.

## Composants

### Stockage — table `topics` (`bot/db/database.py`, remplace `opinions`)
```sql
CREATE TABLE IF NOT EXISTS topics (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL UNIQUE,
    summary       TEXT,
    participants  TEXT,                       -- JSON list de user_id/noms
    opinion       TEXT,
    mention_count INTEGER NOT NULL DEFAULT 1,
    last_seen_at  REAL    NOT NULL,
    created_at    REAL    NOT NULL
);
```
`DROP TABLE IF EXISTS opinions` dans l'init (la table morte est retirée après bascule).

Helpers DB (`SocialMixin`, remplacent `upsert_opinion`/`get_opinions`/`cleanup_opinions`) :
- `upsert_topic(name, summary, participants: list[str], opinion) -> None` : ON CONFLICT(name) → **fusionne** (summary remplacé, participants **unionnés**, `mention_count += 1`, `last_seen_at` = now). L'union des participants se fait en Python (lecture de l'existant + merge) pour rester lisible.
- `get_topics(limit=10) -> list[dict]` : ordonnés par **chaleur** (`last_seen_at DESC, mention_count DESC`) → les sujets chauds d'abord. Chaque dict : `{name, summary, participants, opinion, mention_count, last_seen_at}`.
- `cleanup_topics(max_age_days=30, max_count=15)` : retire les topics froids/anciens (équivalent `cleanup_opinions`).

### Formation — `DailyJournal._form_topics` (remplace `_form_opinions`)
Appelée là où `_form_opinions(context_text)` l'est aujourd'hui (`journal.py:603`). Pour le résumé du jour :
1. Charger `existing = await db.get_topics(limit=15)` → liste de `name` injectée au prompt (B).
2. LLM `secondary` via **`complete_structured`** (plus robuste que le `json.loads` brut de l'actuel `_form_opinions` ; cohérent avec consolidation/user_model) → `{topics: [{name, summary, participants: [pseudos], opinion}]}` (max ~3). Prompt dédié `topic_formation.md` (remplace l'inline actuel), garde le ton persona pour l'opinion.
3. **Résolution participants (A)** : pour chaque pseudo, `canonical = memory._alias_cache.get(f"nickname:{pseudo.lower()}")` ; stocker `canonical` si trouvé, sinon le pseudo brut. (Le journal a déjà `self._memory`.)
4. `await db.upsert_topic(name, summary, participants_resolus, opinion)`.
5. `await db.cleanup_topics()`.
Tout en `try/except` non-fatal (comme l'actuel).

### Injection au prompt — bloc topics enrichi (remplace le bloc opinions)
Là où le bloc `--- Tes opinions sur les sujets de la communauté ---` est assemblé (handlers Discord `~1259`, Twitch `~254`, priorité 5 dans `memory_parts`) : le remplacer par un bloc topics compact, alimenté par `get_topics(limit=5)` (les plus chauds), budgété. Format par topic :
```
- {name} — {participants lisibles} en parlent — ton avis : {opinion}
```
Les `participants` (user_id canoniques) sont rendus en noms lisibles si possible (via le nom courant), sinon tels quels. Budgété via `assemble_memory_context` (déjà le cas pour le bloc priorité 5).

## Data flow

```
nuit (journal generate_and_send → _form_topics)
  ├─ db.get_topics(15) → noms existants (anti-fragmentation B)
  ├─ LLM(résumé du jour + noms existants) → [{name, summary, participants[], opinion}]
  ├─ résolution participants via memory._alias_cache (A)
  ├─ db.upsert_topic(...) (fusion : summary, participants unionnés, count++, last_seen)
  └─ db.cleanup_topics()

réponse à quelqu'un
  └─ build prompt → get_topics(5) → bloc "Sujets de la communauté" (budgété)
```

## Gestion d'erreur
- Formation LLM échoue / JSON invalide → log warning, aucun topic écrit ce soir (comme `_form_opinions` aujourd'hui).
- Pseudo non résolu → on garde le nom brut (jamais bloquant).
- Lecture `get_topics` à l'injection échoue → bloc omis, prompt normal.

## Tests / critères de succès
1. `upsert_topic` : insertion ; ré-upsert du même `name` **fusionne** (mention_count incrémenté, participants unionnés sans doublon, summary remplacé, last_seen mis à jour).
2. `get_topics` : ordre par chaleur (last_seen puis mention_count), limit respecté.
3. `cleanup_topics` : retire les anciens/au-delà du max.
4. Résolution participants : un pseudo présent dans l'alias cache → user_id canonique ; absent → nom brut.
5. `_form_topics` : sur un résumé mocké, le LLM est appelé avec les noms existants dans le prompt (B) ; les topics retournés sont upsertés avec participants résolus (A) ; non-fatal si le LLM lève.
6. Injection : bloc topics présent quand des topics existent, budgété ; absent sinon. Grep : plus aucune référence à `opinions`/`upsert_opinion`/`get_opinions`/`_form_opinions` hors historique git.
7. Migration : `DROP TABLE IF EXISTS opinions` idempotent ; `topics` créée ; démarrage bot + suite verts.

## Hors scope
- Résolution stricte/fuzzy des participants (on s'appuie sur l'alias cache exact ; pas de fuzzy matching).
- Relance proactive des sujets chauds en idle (le `cognitive_loop` pourra lire `get_topics` plus tard).
- Lien bidirectionnel topic↔user_model (le portrait ne liste pas encore les sujets de la personne).
- Alimentation depuis les résumés de session par canal (le résumé du jour suffit).
