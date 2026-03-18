# Dashboard — Onglet Coûts OpenAI

## Résumé

Ajout d'un onglet "COÛTS" au dashboard admin pour suivre les dépenses OpenAI : total mensuel, coût moyen par message, graphe journalier avec comparaison mois précédent, breakdown par modèle/purpose/utilisateur, et seuil d'alerte configurable avec badge visible depuis tous les onglets.

---

## 1. Base de données

### Migration

Ajout colonne `user_id TEXT` (nullable) à la table `cost_log` existante. Migration additive, pas de breaking change.

```sql
ALTER TABLE cost_log ADD COLUMN user_id TEXT;
CREATE INDEX IF NOT EXISTS idx_cost_log_ts ON cost_log(timestamp);
```

Les appels sans contexte utilisateur (journal, consolidation mémoire) restent à `NULL`.

### Nouvelles méthodes Database

| Méthode | Description |
|---|---|
| `get_daily_costs(since_ts, until_ts=None)` | Coûts agrégés par jour pour le graphe |
| `get_cost_breakdown(since_ts, group_by)` | Agrège par `model`, `purpose`, ou `user_id` |
| `get_cost_stats(since_ts)` | Total + nombre d'entrées (pour coût moyen/msg) |

---

## 2. Propagation user_id

Paramètre optionnel `user_id=None` ajouté à :
- `OpenAIClient.complete()` — propagé dans les **deux chemins** internes : `_complete_responses_api()` (modèles o1/o3/o4/gpt-5+) et branche chat completions classique
- `OpenAIClient.complete_secondary()`
- `Database.log_cost()`

Appelants modifiés :
- `bot/discord/handlers.py` → `user_id=f"discord:{message.author.id}"`
- `bot/discord/commands/ask.py` → `user_id=f"discord:{interaction.user.id}"`
- `bot/twitch/handlers.py` → `user_id=f"twitch:{author.name}"`
- `bot/twitch/events.py` → `user_id=f"twitch:{event_user}"` quand disponible

Appelants sans contexte utilisateur (journal, consolidation, emotion_analysis) : `user_id=None` → agrégé sous "Système" dans le top users.

---

## 3. Routes API

Toutes sous `/api/admin/costs/`, Bearer token requis.

| Route | Params | Réponse |
|---|---|---|
| `GET /summary` | `period=month` | `{total, avg_per_msg, msg_count, prev_total, pct_change}` |
| `GET /daily` | `days=30` | `{current: [{date, cost}], previous: [{date, cost}]}` |
| `GET /breakdown/model` | `days=30` | `[{model, total, count}]` trié par total desc |
| `GET /breakdown/purpose` | `days=30` | `[{category, total, count}]` — 4 catégories regroupées |
| `GET /top-users` | `days=30&limit=10` | `[{user_id, username, total, count}]` trié par total desc — `username` résolu via LEFT JOIN `memory_users`, fallback sur `user_id` ; `user_id=NULL` agrégé sous "Système" |
| `GET /alert` | — | `{threshold, current_total, pct_used, status}` (ok/warning/critical) |

### Regroupement des purposes

| Catégorie | Purposes bruts |
|---|---|
| Réponses | `discord_response`, `discord_ask`, `twitch_response`, `twitch_event` |
| Analyse | `session_analysis`, `emotion_analysis` |
| Mémoire | `memory_consolidation`, `context_summary`, `context_summary_final` |
| Journal | `daily_journal`, `journal_chunk_summary`, `journal_final_summary` |
| Autre | tout purpose non mappé (fallback) |

---

## 4. Frontend

### Layout (style A — KPI Top + Graph + 3 Colonnes)

**Rangée 1 — 4 KPIs en ligne :**
- **Mois en cours** : total `$XX.XX` + badge `▼ 18% vs fév.` (vert si baisse, rouge si hausse)
- **Aujourd'hui** : total du jour
- **Coût / msg** : moyenne sur la période sélectionnée
- **Seuil d'alerte** : montant, couleur selon % utilisé (vert < 60%, orange 60–80%, rouge > 80%)

**Rangée 2 — Graphe pleine largeur :**
- Courbe pleine = période courante, pointillée = période précédente
- Alignement : 30J = mois précédent jour par jour ; 7J/90J = même période décalée
- Sélecteur `7J | 30J | 90J` en haut à droite
- Canvas avec axes, ticks auto-adaptés, légende en bas
- Même style que le graphe émotions (cohérence visuelle)

**Rangée 3 — 3 colonnes :**
- **Par modèle** : liste triée par coût décroissant, barre de proportion colorée
- **Par purpose** : 4 catégories (Réponses / Analyse / Mémoire / Journal)
- **Top utilisateurs** : top 10, username + montant, barre proportionnelle

### Badge onglet

Pastille rouge sur l'onglet "COÛTS" visible depuis tous les onglets quand le seuil dépasse 80%. Implémenté via polling du endpoint `/alert` au chargement initial de la page et à chaque changement d'onglet (pas de SSE dédié — les coûts ne changent pas en temps réel).

### Configuration

Nouveau champ `cost_alert_threshold: float = 25.0` ajouté au dataclass `BotConfig` dans `bot/config.py`. Sérialisé dans `config.yaml` via `asdict()` comme les autres champs. Éditable dans l'onglet Config existant, section "Bot".

---

## 5. Tests

Fichier : `tests/test_dashboard_costs.py`

| Test | Vérifie |
|---|---|
| `test_costs_summary` | Total, coût moyen, % variation vs mois précédent |
| `test_costs_daily` | Données jour par jour, courante + précédente |
| `test_costs_breakdown_model` | Agrégation par modèle, tri décroissant |
| `test_costs_breakdown_purpose` | Regroupement en 4 catégories |
| `test_costs_top_users` | Top N par coût, user_id NULL → "Système" |
| `test_costs_alert_states` | ok / warning / critical selon les bornes |
| `test_costs_auth_required` | Tous les endpoints refusent sans token |
| `test_costs_empty_db` | Zéros et listes vides, pas de crash |
| `test_costs_avg_no_division_by_zero` | Coût/msg = 0 quand 0 messages |

---

## 6. Fichiers impactés

### Nouveaux
- `bot/dashboard/routes/costs.py` — routes API coûts
- `tests/test_dashboard_costs.py` — tests

### Modifiés
- `bot/db/database.py` — migration `user_id`, nouvelles méthodes d'agrégation
- `bot/core/openai_client.py` — paramètre `user_id` sur `complete()` et `complete_secondary()`
- `bot/discord/handlers.py` — passe `user_id` à `complete()`
- `bot/discord/commands/ask.py` — passe `user_id` à `complete()`
- `bot/twitch/handlers.py` — passe `user_id` à `complete()`
- `bot/twitch/events.py` — passe `user_id` à `complete()`
- `bot/dashboard/app.py` — enregistre le router costs
- `bot/dashboard/static/index.html` — onglet COÛTS + badge
- `bot/dashboard/static/app.js` — logique fetch, graphe canvas, polling alert
- `bot/config.py` — champ `cost_alert_threshold`
- `config.yaml` — valeur par défaut `cost_alert_threshold: 25.0`
