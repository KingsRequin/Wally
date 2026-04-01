# Design — Coûts détaillés + Mémoire de relation + Alias

Date: 2026-03-29
Status: Approved

---

## 1. Coûts détaillés

### Contexte

La table `cost_log` contient déjà tous les champs nécessaires (model, input_tokens, output_tokens, cost_usd, purpose, user_id, timestamp). Les prix par token sont dans `MODEL_COSTS` (openai_client.py) et `CLAUDE_MODEL_COSTS` (claude_client.py). Le dashboard affiche déjà un résumé, un graphe, et des breakdowns par modèle/purpose/top-users. Il manque : un regroupement par fonctionnalité, un camembert visuel, les prix par token, et un journal des appels individuels.

### Backend — Nouveaux endpoints

**`GET /api/admin/costs/prices`**
Retourne les prix actuels par token pour chaque modèle connu.
```json
{
  "gpt-4o": {"input_per_1k": 0.0025, "output_per_1k": 0.010},
  "claude-sonnet-4-6": {"input_per_1k": 0.003, "output_per_1k": 0.015}
}
```
Lit `MODEL_COSTS` et `CLAUDE_MODEL_COSTS` directement, retourné sous forme de dict.

**`GET /api/admin/costs/by-feature?days=N`**
Agrège `cost_log` par feature via mapping hardcodé `purpose → feature` :

| Feature | Purposes inclus |
|---------|----------------|
| Réponses | discord_response, discord_spontaneous, discord_ask, twitch_response, twitch_spontaneous, web_response, twitch_event |
| Journal | daily_journal, journal_chunk_summary, journal_final_summary, opinion_formation |
| Images | image_generation, image_title, image_description |
| Émotions | emotion_analysis |
| Mémoire | fact_extraction, memory_consolidation, memory_evaluate, context_summary, context_summary_final, memory_cleanup, embedding |
| Système | spam_warning, reminder, twitch_visit_summary, twitch_overlay_announce |

SQL GROUP BY purpose sur la période → agrégé en features côté Python. Retourne `[{feature, cost, count, pct}]` trié par cost DESC.

**`GET /api/admin/costs/logs?days=N&page=P&limit=50`**
Journal paginé des appels individuels, trié par timestamp DESC.
Champs retournés : `datetime` (ISO), `model`, `input_tokens`, `output_tokens`, `cost_usd`, `purpose`, `username` (résolu via JOIN sur `memory_users`).
Retourne aussi `total` pour la pagination côté frontend.

### Frontend — Onglet Coûts > Détail

Le sous-onglet "Détail" existant est réorganisé :

1. **Section "Par fonctionnalité"** (en haut)
   - Camembert (canvas 2D, même style glassmorphism que `costCanvas`) affichant la répartition des coûts par feature, avec légende colorée
   - Barres horizontales sous le camembert : feature + montant + pourcentage

2. **Section "Prix des tokens"** (milieu)
   - Tableau compact : modèle | input/1k | output/1k
   - Uniquement les modèles actifs dans `config.llm.primary` et `config.llm.secondary`

3. **Section "Breakdowns existants"** (conservés : par modèle, par purpose, top users)

4. **Section "Journal des appels"** (en bas)
   - Tableau paginé : date/heure | modèle | in tokens | out tokens | coût | purpose | user
   - Pagination simple (Précédent / N-N sur M / Suivant)
   - Filtre par range de dates synchronisé avec le sélecteur 7d/30d/90d existant

---

## 2. Mémoire de relation + Alias

### Contexte

**Existant :**
- Table `user_aliases` : nickname → canonical_uid, avec source (llm/manual), confidence
- `upsert_alias()`, `delete_alias()`, `list_aliases()`, `get_nickname_alias_map()` dans `database.py`
- FactExtractor extrait déjà automatiquement les alias (source='llm') et les faits `REL`
- `search_relationships()` dans `memory.py` — cherche les faits REL et les injecte dans le prompt (priorité 2)
- `MemoryService._alias_cache` chargé au démarrage via `load_aliases()`

**Manquant :**
- Dashboard UI pour gérer les alias
- Détection de mentions tierces en conversation + injection mémoire
- Question auto Wally "c'est X dont tu parles ?"

### Backend — Routes admin aliases

Dans `bot/dashboard/routes/admin.py` :

```
GET    /api/admin/aliases              → liste tous les alias (optionnel: ?canonical_uid=)
POST   /api/admin/aliases              → crée un alias manuel {nickname, canonical_uid, display_name}
DELETE /api/admin/aliases/{nickname}   → supprime un alias
```

Après chaque POST/DELETE : appeler `memory_service.load_aliases(db)` pour mettre à jour le cache en mémoire immédiatement. Le `memory_service` est accessible via l'app state FastAPI (déjà le pattern utilisé).

### Backend — Détection de mentions tierces

Dans `bot/discord/handlers.py` et `bot/twitch/handlers.py`, dans la phase de construction du contexte mémoire (après `mem_context` pour l'auteur courant) :

**Étape 1 — Extraction des mentions**
Scanner le texte des messages récents du contexte (prelude + context window) pour extraire des tokens qui pourraient être des pseudos. Utiliser une heuristique simple : mots de 3+ caractères commençant par une majuscule ou présents dans `get_nickname_alias_map()`.

**Étape 2 — Résolution**
Pour chaque token candidat :
- Chercher dans `_alias_cache` (clé `nickname:token.lower()`)
- Si match exact → charger memories via `memory.search(platform, canonical_uid, query=token)`
- Si pas de match → fuzzy match avec `difflib.SequenceMatcher` contre tous les usernames connus (seuil 0.75)

**Étape 3 — Injection**
- Si match résolu → ajouter bloc `--- Souvenirs sur [username] ---` au contexte mémoire (après le bloc de l'auteur)
- Si fuzzy match → injecter dans le prompt une note : `"Note interne : '[token]' ressemble à [username] (confiance X%) — si c'est bien lui, mentionne-le naturellement"`
- Si inconnu et aucun fuzzy match → injecter : `"Note interne : '[token]' est mentionné mais inconnu — si pertinent, demande discrètement 'c'est qui ?'"`

**Limite** : max 2 utilisateurs tiers par requête pour éviter le context bloat.

### Frontend — Modal utilisateur : section Alias

Dans la modal de détail d'un utilisateur (onglet Mémoire > Utilisateurs), nouvelle section "Alias" après la liste des souvenirs :

- Titre "Alias connus"
- Liste des alias : badge par alias avec libellé `nickname` + tag `LLM` ou `Manuel` + bouton ×
- Champ texte "Ajouter un alias" + bouton Ajouter
- L'ajout appelle `POST /api/admin/aliases` avec le `canonical_uid` de l'utilisateur ouvert
- La suppression appelle `DELETE /api/admin/aliases/{nickname}`
- Rechargement de la liste après chaque action

---

## Architecture — Pas de nouveaux fichiers

Tous les changements s'intègrent dans les fichiers existants :
- `bot/dashboard/routes/admin.py` — nouveaux endpoints costs + alias
- `bot/dashboard/static/app.js` — nouveaux renders dans les onglets existants
- `bot/discord/handlers.py` — détection mentions tierces
- `bot/twitch/handlers.py` — idem

---

## Non-scope (intentionnellement exclu)

- Scope C memory items (consolidation incrémentale, cleanup inactifs, dédup embeddings)
- Dashboard de visualisation des relations entre utilisateurs (les REL sont déjà injectées dans le prompt)
- Gestion manuelle des relations via dashboard
