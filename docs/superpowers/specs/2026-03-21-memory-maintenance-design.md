# Memory Maintenance — Scoring & Nettoyage quotidien

**Date** : 2026-03-21
**Statut** : Approuvé

---

## Problème

Les souvenirs long-terme de Wally (mem0/Qdrant) accumulent des faits périmés qui ne sont jamais nettoyés. La consolidation existante (`_maybe_consolidate`) ne se déclenche qu'au seuil de 25 souvenirs et ne fait que compresser — elle ne vérifie pas l'obsolescence ni la complétude des informations.

Exemple : "déménage le 1er" reste en mémoire indéfiniment sans date précise, sans que Wally ne cherche à clarifier.

## Solution

Deux mécanismes complémentaires :

1. **Scoring à l'enregistrement** — chaque nouveau souvenir est évalué par le LLM secondaire pour sa complétude. Si l'info est vague ou incomplète, une question est stockée en DB pour que Wally la pose naturellement lors de la prochaine conversation.

2. **Nettoyage quotidien** — 30 minutes avant le journal, un cron passe en revue les souvenirs de chaque utilisateur actif pour supprimer les périmés, reformuler les vagues, et générer de nouvelles questions.

---

## 1. Table DB : `memory_questions`

Nouvelle table dans `bot/db/database.py` :

| Colonne | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `user_id` | TEXT NOT NULL | Namespace mem0 (ex: `discord:123`) |
| `memory_text` | TEXT NOT NULL | Le souvenir qui a déclenché la question |
| `question` | TEXT NOT NULL | La question à poser |
| `priority` | TEXT NOT NULL | `high` / `medium` / `low` |
| `attempts` | INTEGER DEFAULT 0 | Nombre de fois que la question a été injectée dans le prompt |
| `resolved` | INTEGER DEFAULT 0 | 1 quand l'info est obtenue |
| `created_at` | REAL NOT NULL | Timestamp de création |

Méthodes CRUD :
- `insert_memory_question(user_id, memory_text, question, priority)` — insert une question
- `get_pending_question(user_id, max_attempts=3)` — retourne la question non résolue la plus prioritaire (priority HIGH > MEDIUM > LOW, puis la plus ancienne), avec `attempts < max_attempts` et `resolved = 0`
- `increment_question_attempts(question_id)` — `attempts += 1`
- `resolve_question(question_id)` — `resolved = 1`
- `get_all_pending_questions(user_id)` — retourne toutes les questions non résolues pour un utilisateur (pour `_evaluate_memory`)
- `cleanup_old_questions(max_age_days=30)` — supprime les questions résolues ou trop vieilles

## 2. Scoring à l'enregistrement

### Flow

Dans `memory.py`, après le `mem0.add()` réussi dans la méthode `add()` :

```python
self._fire(self._evaluate_memory(uid, content))
```

### `_evaluate_memory(uid, content)` — nouvelle méthode async

1. Récupère les questions en attente pour cet utilisateur (`db.get_all_pending_questions(uid)`)
2. Appel LLM secondaire avec le prompt `memory_evaluate_system.md`, en incluant le souvenir ET les questions en attente
3. Le LLM retourne un JSON :
   ```json
   {
     "complete": false,
     "questions": [
       {"question": "Quel mois exactement ?", "priority": "high"}
     ],
     "resolves": [3, 7]
   }
   ```
4. Si `complete == false` : insert chaque question dans `memory_questions`
5. Si `resolves` contient des IDs : marquer ces questions comme résolues
6. Si `complete == true` et pas de `resolves` : rien à faire

### Prompt `memory_evaluate_system.md`

```
Tu es le module de mémoire de Wally. Tu reçois un souvenir qui vient d'être enregistré
sur un utilisateur, ainsi que la liste des questions en attente pour cet utilisateur.

## Tâche 1 : Évaluer la complétude du nouveau souvenir

Critères d'incomplétude :
- Dates vagues ("le 1er", "bientôt", "la semaine prochaine" sans précision)
- Lieux non spécifiés ("déménage" sans dire où)
- Références ambiguës ("son projet" sans préciser lequel)
- Événements sans contexte temporel ("va se marier" — quand ?)

## Tâche 2 : Vérifier si le nouveau souvenir répond à des questions en attente

Si le nouveau souvenir contient l'information demandée par une question en attente,
inclus son ID dans le champ "resolves".

## Format de réponse

{
  "complete": true/false,
  "questions": [{"question": "...", "priority": "high|medium|low"}],
  "resolves": [id1, id2]
}

Priority :
- high : info cruciale manquante (date d'un événement imminent, lieu d'un déménagement)
- medium : info utile mais pas urgente (quel type de jeu exactement)
- low : détail bonus (pourquoi il aime ça)

Retourne UNIQUEMENT le JSON, sans préambule.
```

## 3. Injection des questions dans le prompt

### Où

Dans le pipeline de construction du prompt (au moment où on injecte les souvenirs dans le system prompt pour une réponse), on ajoute une directive si une question est en attente.

### Comment

Dans `memory.py`, nouvelle méthode `get_pending_question_directive(platform, user_id)` :

1. Appelle `db.get_pending_question(uid)`
2. Si une question existe : incrémente `attempts` et retourne une directive :
   ```
   [Question en attente] Si l'occasion se présente naturellement dans la conversation,
   essaie de savoir : {question}. Ne force pas — si le sujet ne vient pas, laisse tomber.
   ```
3. Si aucune question : retourne `""`

Cette directive est ajoutée au prompt par le code appelant (dans `prompts.py` ou `handlers.py`), dans la section des souvenirs utilisateur.

### Garde-fous

- Max 1 question par conversation (une seule directive injectée)
- Max 3 tentatives (`attempts`) — après 3 injections sans résolution, la question n'est plus injectée
- Auto-résolution : la méthode `_evaluate_memory()` (déjà appelée à chaque `memory.add()`) reçoit aussi la liste des questions en attente pour cet utilisateur. Si le nouveau souvenir répond à une question existante, le LLM l'indique dans sa réponse JSON (`"resolves": [question_id, ...]`) et on marque ces questions comme résolues. Pas de match textuel approximatif — c'est le LLM qui juge.
- `get_pending_question_directive()` est appelé **une seule fois par message entrant**, dans le pipeline de `_respond()` (au moment de la construction du system prompt). Il ne doit jamais être appelé dans une boucle de retry ou dans un appel tool.

## 4. Nettoyage quotidien

### Déclenchement

Nouveau cron dans `DailyJournal.start()` : `journal_time - 30 minutes`.

Calcul du temps : utiliser `datetime(hour, minute) - timedelta(minutes=30)` pour gérer le wraparound minuit automatiquement (ex: `00:15` → `23:45` la veille fonctionne car APScheduler gère les heures normalisées).

Nouvelle méthode `DailyJournal.run_memory_cleanup()` (ou une classe séparée `MemoryCleanup` si on veut découpler — mais le journal a déjà toutes les dépendances nécessaires).

### Flow

```
Pour chaque utilisateur dans memory_users (max 20, triés par activité récente) :
    1. mem0.get_all(user_id=uid) via asyncio.to_thread → liste de dicts avec "id" et "memory"
       (appel direct à mem0, pas memory.get_all() qui retourne un str)
    2. Si < 5 souvenirs → skip
    3. Appel LLM secondary avec prompt memory_cleanup_system.md :
       - Input : liste numérotée des souvenirs + date du jour
       - Output : JSON structuré (indices → IDs résolus côté code)
    4. Appliquer les actions :
       - delete : mem0.delete(id) pour chaque souvenir identifié
       - update : mem0.delete(old_id) + mem0.add(new_text, user_id=uid)
         (appel direct à mem0.add, PAS à memory.add() — pour éviter de
         déclencher _maybe_consolidate et _evaluate_memory en cascade)
       - questions : insert dans memory_questions
    5. Log le résultat
```

**Important** : le cleanup appelle `mem0` directement (comme `_maybe_consolidate` le fait déjà), jamais `memory.add()`, pour éviter les race conditions avec la consolidation et l'évaluation fire-and-forget.

### Prompt `memory_cleanup_system.md`

```
Tu es le gestionnaire de mémoire long-terme de Wally. Nous sommes le {date}.
Tu reçois la liste des souvenirs stockés pour un utilisateur.

Analyse chaque souvenir et identifie :

1. **Périmés** — faits qui ne sont probablement plus vrais ou pertinents :
   - Événements passés ("déménage le 1er mars" et nous sommes en avril)
   - États temporaires révolus ("est en vacances jusqu'au 15")
   - Infos devenues caduques par un souvenir plus récent

2. **À reformuler** — faits dont la formulation peut être améliorée :
   - Trop vagues → reformuler plus précisément
   - Temporels devenus permanents → reformuler au présent ("a déménagé à Lyon" → "Habite à Lyon")

3. **Questions** — informations incomplètes à clarifier :
   - Même critères que l'évaluation à l'enregistrement

Retourne un JSON valide :
{
  "delete": [0, 3],           // indices des souvenirs à supprimer
  "update": [{"index": 2, "new_text": "..."}],  // reformulations
  "questions": [{"question": "...", "priority": "high|medium|low"}]
}

Les indices correspondent à la position dans la liste (commençant à 0).
Si rien à faire, retourne {"delete": [], "update": [], "questions": []}.
```

### Garde-fous

- Max 20 utilisateurs par run (triés par `last_seen` ou nombre de souvenirs)
- Skip si Qdrant est inaccessible
- Skip utilisateurs avec < 5 souvenirs
- `cleanup_old_questions(max_age_days=30)` appelé à la fin pour purger les questions résolues ou trop vieilles
- Timeout global de 5 minutes pour le cleanup complet

## 5. Mise à jour onglet Info du dashboard

Dans `bot/dashboard/static/app.js`, section "Mémoire" (section 3 de l'onglet Info), ajouter après le paragraphe sur la mémoire globale :

### Nouveau paragraphe : Maintenance mémoire

Texte à ajouter dans le `<div class="jd-body">` de la section Mémoire :

> **Maintenance automatique** — Wally ne se contente pas de stocker des souvenirs, il les entretient. Chaque nouveau souvenir est évalué pour sa complétude : si une information est vague ou incomplète (une date sans mois, un lieu non précisé), Wally note une question à poser et la glisse naturellement dans une prochaine conversation. Chaque soir, 30 minutes avant son journal, il fait le tri : il supprime les faits périmés, reformule les vagues, et identifie de nouvelles questions. Maximum 1 question par conversation, maximum 3 tentatives — Wally insiste, mais pas trop.

### Détails techniques (dans le `<details>`)

Ajouter dans le bloc technique existant :

> **Memory scoring** : chaque `memory.add()` déclenche un appel LLM secondaire qui évalue la complétude du souvenir. Les questions générées sont stockées dans la table `memory_questions` et injectées dans le prompt (max 1 par conversation, max 3 tentatives).

> **Nettoyage quotidien** : cron 30min avant le journal. Passe en revue les souvenirs des 20 utilisateurs les plus actifs, identifie les faits périmés/vagues via LLM, et applique suppressions + reformulations.

---

## Fichiers impactés

### À créer
| Fichier | Rôle |
|---|---|
| `bot/persona/prompts/memory_evaluate_system.md` | Prompt d'évaluation de complétude |
| `bot/persona/prompts/memory_cleanup_system.md` | Prompt de nettoyage quotidien |

### À modifier
| Fichier | Changement |
|---|---|
| `bot/db/database.py` | Table `memory_questions` + 6 méthodes CRUD |
| `bot/core/memory.py` | `_evaluate_memory()`, `get_pending_question_directive()` |
| `bot/core/journal.py` | `run_memory_cleanup()`, cron -30min |
| `bot/core/prompts.py` | Intégration directive question dans le prompt (si nécessaire) |
| `bot/dashboard/static/app.js` | Section mémoire de l'onglet Info |

### Coût estimé par jour
- Scoring : ~1 appel secondary par `memory.add()` (~100 tokens)
- Nettoyage : ~1 appel secondary par utilisateur actif (max 20, ~200 tokens chacun)
- Total additionnel : ~5000 tokens/jour — négligeable
