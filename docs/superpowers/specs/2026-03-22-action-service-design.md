# ActionService — Design Spec

> Sous-projet 1 : framework ActionService + tâches planifiées.
> Les capacités supplémentaires (Twitch join, message ciblé, mémoire persistante) seront des specs séparées.

---

## Objectif

Permettre au LLM de créer, annuler et lister ses propres tâches via tool calling.
Les tâches sont persistantes en SQLite, survivent au redémarrage, et sont visibles/éditables depuis le dashboard.

Chaque type d'action est configurable en termes d'accessibilité (ACL par rôle Discord / badge Twitch).

---

## Modèle de données

### Table `action_tasks`

| Colonne | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `action_type` | TEXT | Type d'action (`reminder`, `web_search`, `image_generate`...) |
| `description` | TEXT | Texte libre décrivant la tâche (affiché dans le dashboard, utilisé pour la recherche) |
| `creator_id` | TEXT | ID brut de l'utilisateur (`610550333042589752`) |
| `creator_platform` | TEXT | `discord` / `twitch` / `web` |
| `target_channel` | TEXT | ID du salon/canal de destination |
| `target_platform` | TEXT | Plateforme de destination |
| `payload` | TEXT (JSON) | Paramètres de l'action (message, query, prompt...) |
| `schedule_type` | TEXT | `once` / `interval` / `cron` |
| `schedule_spec` | TEXT (JSON) | `{"run_at": "..."}` ou `{"minutes": 30}` ou `{"hour": 10, "minute": 0}` |
| `max_executions` | INTEGER NULL | Nombre max d'exécutions (NULL = infini) |
| `execution_count` | INTEGER DEFAULT 0 | Compteur d'exécutions effectuées |
| `consecutive_failures` | INTEGER DEFAULT 0 | Compteur d'échecs consécutifs (reset à 0 après succès) |
| `last_error` | TEXT NULL | Dernier message d'erreur |
| `status` | TEXT DEFAULT 'active' | `active` / `paused` / `completed` / `cancelled` / `missed` |
| `created_at` | TEXT | ISO timestamp |
| `updated_at` | TEXT | ISO timestamp, mis à jour à chaque changement de statut |
| `next_run_at` | TEXT NULL | Prochaine exécution prévue |
| `last_run_at` | TEXT NULL | Dernière exécution |

> **Statut `missed`** : ne s'applique qu'aux tâches `once`. Pour les tâches récurrentes (`interval`/`cron`), les exécutions manquées pendant un downtime sont ignorées — la tâche reste `active` et reprend son cycle normal au redémarrage.

### Table `action_permissions`

| Colonne | Type | Description |
|---|---|---|
| `action_type` | TEXT PRIMARY KEY | Type d'action |
| `min_role_discord` | TEXT DEFAULT 'admin' | Rôle Discord minimum (`everyone` / `subscriber` / `moderator` / `admin`) |
| `min_role_twitch` | TEXT DEFAULT 'admin' | Badge Twitch minimum (`everyone` / `subscriber` / `vip` / `moderator` / `admin`) |
| `enabled` | INTEGER DEFAULT 1 | 1 = activée, 0 = désactivée globalement |

### Hiérarchie des rôles

- **Discord** : `everyone` < `subscriber` < `moderator` < `admin`
- **Twitch** : `everyone` < `subscriber` < `vip` < `moderator` < `admin`

Un utilisateur avec un rôle supérieur ou égal au minimum configuré a accès à l'action.

---

## Architecture des services

```
bot/core/actions/
├── __init__.py          # Exports publics
├── registry.py          # ActionRegistry
├── scheduler.py         # ActionScheduler
├── executor.py          # ActionExecutor
└── service.py           # ActionService (façade)
```

> **Note architecturale** : c'est le premier sous-package dans `bot/core/` (les autres services sont des fichiers plats). Ce choix est intentionnel — l'ActionService a 4 composants distincts avec des responsabilités claires, ce qui justifie un package dédié plutôt que 4 fichiers éparpillés.

### ActionRegistry (`registry.py`)

Catalogue des actions disponibles et gestion des permissions.

- Maintient un dict `{action_type: ActionDefinition}` en mémoire
- `ActionDefinition` : nom, description, paramètres attendus (JSON schema), callable async handler
- Méthodes :
  - `register(action_type, definition)` — enregistre une action
  - `check_permission(action_type, platform, user_roles) -> bool` — vérifie l'ACL
  - `list_available(platform, user_roles) -> list` — actions accessibles pour ce rôle
  - `get(action_type) -> ActionDefinition | None` — récupère une définition
  - `update_permission(action_type, platform, min_role)` — modifie l'ACL (appelé par le dashboard)
  - `set_enabled(action_type, enabled: bool)` — active/désactive une action
- Charge les permissions depuis `action_permissions` au boot
- Les nouvelles actions enregistrées reçoivent des permissions par défaut (`admin` partout)

### ActionScheduler (`scheduler.py`)

Persistence SQLite + orchestration apscheduler.

- Reçoit une instance `AsyncIOScheduler` partagée (créée dans `main.py`, utilisée aussi par `DailyJournal`). Un seul scheduler pour tout le process — pas de conflit de job stores.
- Méthodes :
  - `schedule(task) -> task_id` — persiste en DB + programme dans apscheduler
  - `cancel(task_id)` — annule dans apscheduler + met à jour le statut DB
  - `pause(task_id)` / `resume(task_id)` — pause/reprend
  - `execute_now(task_id)` — trigger manuel (depuis le dashboard)
  - `reload_all()` — au boot, recharge toutes les tâches `active`, marque `missed` celles dont `next_run_at` est dans le passé
  - `start()` / `stop()` — démarre/arrête le scheduler
- Quand un job se déclenche : appelle `ActionExecutor.execute(task)`
- Met à jour `execution_count`, `last_run_at`, `next_run_at`, `consecutive_failures` après chaque exécution
- Auto-complète les tâches quand `execution_count >= max_executions`
- Auto-pause après 3 échecs consécutifs

### ActionExecutor (`executor.py`)

Routing vers les services existants et livraison des résultats.

- Méthodes :
  - `execute(task) -> str` — résout l'action via le registry, exécute le handler, livre le résultat
  - `send_reminder(payload, target) -> str` — envoie un message texte
  - `do_web_search(payload, target) -> str` — appelle `WebSearchService`
  - `do_image_generate(payload, target) -> str` — appelle `OpenAIClient.generate_image()`
  - `set_bots(discord_bot, twitch_bot)` — injection tardive des bots
- Livraison du résultat vers le bon canal/plateforme :
  - Discord : `channel.send()` via le bot Discord
  - Twitch : `channel.send()` via le bot Twitch
  - DM Discord : `user.send()`
  - Web : WebSocket push
- Guard contre bots `None` : si `set_bots()` n'a pas encore été appelé, log warning et retourne une erreur sans crash
- Try/except + logging sur chaque exécution, jamais de crash

### ActionService (`service.py`)

Façade pour le LLM, expose les tool definitions.

- Méthodes :
  - `get_tool_definitions() -> list[dict]` — les 3 tools pour `complete_with_tools()`
  - `execute_tool(name, args, user_id, platform, user_roles) -> dict` — dispatch les appels tools
  - `create(task_data, user_id, platform, user_roles) -> dict` — crée une tâche après validation
  - `cancel(task_id=None, search_query=None, user_id=None) -> dict` — annule par ID ou recherche
  - `list_tasks(user_id=None, status_filter="active", own_only=True) -> list` — liste filtrée
- Valide les permissions via `ActionRegistry.check_permission()` avant création
- Rate limit : max 10 tâches `active + paused` par utilisateur (configurable)
- Intervalle minimum : 5 minutes entre exécutions d'une tâche récurrente (configurable)
- Validation temporelle : rejette les tâches `once` dont `run_at` est dans le passé (grace window de 30s)

---

## Tool Definitions pour le LLM

### `create_action_task`

```json
{
  "type": "function",
  "function": {
    "name": "create_action_task",
    "description": "Créer une tâche planifiée (rappel, recherche web, génération d'image...)",
    "parameters": {
      "type": "object",
      "properties": {
        "action_type": {
          "type": "string",
          "enum": ["reminder", "web_search", "image_generate"],
          "description": "Type d'action à exécuter"
        },
        "description": {
          "type": "string",
          "description": "Description en langage naturel de la tâche"
        },
        "payload": {
          "type": "object",
          "description": "Paramètres de l'action (message, query, prompt...)"
        },
        "schedule": {
          "type": "object",
          "properties": {
            "type": { "type": "string", "enum": ["once", "interval", "cron"] },
            "run_at": { "type": "string", "description": "ISO datetime (Europe/Paris) pour les tâches once" },
            "interval_minutes": { "type": "integer", "description": "Intervalle en minutes (min 5)" },
            "cron_hour": { "type": "integer" },
            "cron_minute": { "type": "integer" },
            "cron_day_of_week": { "type": "string", "description": "Jour(s) de la semaine: mon,tue,wed,thu,fri,sat,sun" },
            "max_executions": { "type": ["integer", "null"], "description": "Nombre max d'exécutions (null = infini)" }
          },
          "required": ["type"]
        },
        "target": {
          "type": "object",
          "properties": {
            "platform": { "type": "string", "enum": ["discord", "twitch", "web"] },
            "channel_id": { "type": "string" },
            "dm": { "type": "boolean", "description": "Envoyer en DM au créateur" }
          }
        }
      },
      "required": ["action_type", "description"],
      "additionalProperties": false
    }
  }
}
```

> **Timezone** : toutes les heures sont interprétées en `Europe/Paris` (cohérent avec `journal.py`).
> Le LLM doit générer des datetimes dans ce fuseau.

> **Règles de defaulting** : si `target` est omis, le service utilise le canal/plateforme d'origine
> de la conversation. Si `schedule` est omis, le service retourne `need_more_info` — une tâche
> doit toujours avoir un planning explicite.

Réponses du tool :

```json
// Succès
{
  "status": "created",
  "task_id": 42,
  "description": "Rappel: acheter du pain",
  "next_run_at": "2026-03-23T18:00:00+01:00"
}

// Infos manquantes
{
  "status": "need_more_info",
  "missing": ["schedule.run_at"],
  "message": "Je dois savoir à quelle heure."
}

// Permission refusée
{
  "status": "denied",
  "message": "Action image_generate réservée aux modérateurs."
}

// Rate limit
{
  "status": "rate_limited",
  "message": "Maximum 10 tâches actives atteint."
}
```

### `cancel_action_task`

```json
{
  "type": "function",
  "function": {
    "name": "cancel_action_task",
    "description": "Annuler une tâche planifiée par ID ou par description",
    "parameters": {
      "type": "object",
      "properties": {
        "task_id": { "type": "integer", "description": "ID de la tâche à annuler" },
        "search_query": { "type": "string", "description": "Recherche par description en langage naturel" }
      },
      "additionalProperties": false
    }
  }
}
```

Comportement de la recherche (`search_query`) :
- Implémentation : SQL `LIKE '%query%'` sur la colonne `description`, limité aux tâches actives du user (sauf admin)
- 0 résultat : `{"status": "not_found", "message": "..."}`
- 1 résultat : annule directement, `{"status": "cancelled", "task": {"id": 42, "description": "..."}}`
- 2+ résultats : `{"status": "ambiguous", "candidates": [{"id": 42, "description": "..."}, ...]}`

### `list_action_tasks`

```json
{
  "type": "function",
  "function": {
    "name": "list_action_tasks",
    "description": "Lister les tâches planifiées",
    "parameters": {
      "type": "object",
      "properties": {
        "status_filter": { "type": "string", "enum": ["active", "paused", "all"], "default": "active" },
        "own_only": { "type": "boolean", "default": true, "description": "true = mes tâches uniquement, false = toutes (admin)" }
      },
      "additionalProperties": false
    }
  }
}
```

Réponse :
```json
{
  "status": "ok",
  "tasks": [
    {
      "id": 42,
      "action_type": "reminder",
      "description": "Rappel: acheter du pain",
      "status": "active",
      "next_run_at": "2026-03-23T18:00:00+01:00",
      "execution_count": 3,
      "max_executions": 10
    }
  ]
}
```

---

## Intégration dans les handlers

### Collecte des tools

Dans `bot/discord/handlers.py` et `bot/twitch/handlers.py` :

```python
action_service = getattr(bot, "action_service", None)
if action_service:
    tools.extend(action_service.get_tool_definitions())
```

### Tool executor

```python
if name in ("create_action_task", "cancel_action_task", "list_action_tasks"):
    result = await action_service.execute_tool(
        name, args,
        user_id=user_id,
        platform=platform,
        user_roles=user_roles,
    )
    return json.dumps(result)
```

### Résolution des rôles utilisateur

- **Discord** : `message.author.roles` → mapping vers la hiérarchie. Admin = permission `administrator` ou ID dans la config admin
- **Twitch** : `payload.chatter.badges` → mapping (`broadcaster` → admin, `moderator` → moderator, `vip` → vip, `subscriber` → subscriber, sinon `everyone`)
- **Web chat** : token JWT → `admin` si Bearer admin, sinon `everyone`

### Modal Discord

Quand il manque 3+ champs et que la plateforme est Discord, le LLM peut appeler un tool dédié `open_task_modal` (au lieu de parser un tag dans le texte). Ce tool retourne un signal au handler Discord qui ouvre un modal pré-rempli avec les champs manquants. À la soumission du modal, le handler appelle `ActionService.create()`.

Ce mécanisme reste dans le paradigme tool calling — pas de parsing de tags dans le texte libre.

---

## Boot Sequence

1. Services existants (config, db, emotion, memory, openai...)
2. `AsyncIOScheduler()` créé une seule fois dans `main.py` — instance partagée
3. `ActionRegistry(db)` — charge les permissions depuis SQLite
4. `ActionExecutor(registry)` — créé sans les bots
5. `ActionScheduler(db, executor, scheduler)` — reçoit le scheduler partagé, pas encore démarré
6. `ActionService(registry, scheduler, db)` — façade prête
7. Discord/Twitch bots créés avec `action_service` injecté
8. `DailyJournal` reçoit le même scheduler partagé (au lieu de créer le sien)
9. `executor.set_bots(discord_bot, twitch_bot)` — injection tardive (**DOIT** précéder `reload_all`)
10. `scheduler.reload_all()` — recharge tâches actives, marque les `missed` pour les tâches `once` dont `next_run_at` est dans le passé
11. Scheduler partagé `.start()` — démarre une seule fois pour tous les jobs
12. `asyncio.gather(...)` — tout tourne

---

## Dashboard

### Page "Actions" — Onglet "Tâches"

- Liste de toutes les tâches en cards glassmorphism
- Infos affichées : description, type, créateur, plateforme, statut (badge coloré), prochaine/dernière exécution, compteur `execution_count / max_executions`, destination
- Couleurs des statuts : `active` (cyan #06b6d4), `paused` (jaune #eab308), `completed` (vert #22c55e), `cancelled` (gris), `missed` (rouge #ef4444)
- Filtres : par statut, plateforme, créateur, type d'action
- Actions admin : Pause/Resume, Annuler (avec confirmation), Exécuter maintenant
- Tâches missed : indicateur visuel distinct, boutons "Exécuter maintenant" / "Ignorer"

### Page "Actions" — Onglet "Permissions"

- Tableau des types d'actions enregistrés
- Par action : nom, description, toggle enabled/disabled, dropdown rôle minimum Discord, dropdown rôle minimum Twitch
- Sauvegarde immédiate via API (stocké en DB, pas en config.yaml)
- Nouvelles actions enregistrées → permissions par défaut `admin` partout

### API Endpoints

- `GET /api/actions/tasks` — liste filtrée (query params: status, platform, creator, action_type)
- `GET /api/actions/tasks/{id}` — détail d'une tâche
- `POST /api/actions/tasks/{id}/pause` — pause
- `POST /api/actions/tasks/{id}/resume` — resume
- `POST /api/actions/tasks/{id}/cancel` — annulation
- `POST /api/actions/tasks/{id}/execute` — exécution manuelle
- `GET /api/actions/permissions` — toutes les permissions
- `PUT /api/actions/permissions/{action_type}` — modifier rôles min

---

## Gestion des erreurs

| Cas | Comportement |
|---|---|
| Action échoue (API down, salon supprimé) | Log erreur, incrémente `consecutive_failures`, ne l'annule pas |
| 3 échecs consécutifs | Auto-pause, visible dans le dashboard avec `last_error` |
| Tâche `once` qui échoue | Marquée `missed` |
| Salon introuvable / bot sans accès | Erreur loggée, tâche pausée |
| Permissions changées après création | Tâche continue (validée à la création). Option dashboard "Réappliquer les permissions" |
| Rate limit dépassé (>10 tâches actives/user) | Refus de création, message explicatif |
| Intervalle < 5 minutes | Refus de création, message explicatif |
| Escalade de rôle | Refus : un user ne peut pas créer une tâche nécessitant un rôle supérieur au sien |

---

## Limites de sécurité

- **Max tâches par utilisateur** : 10 `active + paused` (configurable dans le dashboard)
- **Intervalle minimum** : 5 minutes entre exécutions récurrentes (configurable)
- **Validation temporelle** : tâches `once` avec `run_at` dans le passé rejetées (grace window 30s)
- **Pas d'escalade de privilèges** : le créateur doit avoir le rôle requis pour l'action
- **Isolation** : un utilisateur ne peut lister/annuler que ses propres tâches (sauf admin)
- **Timezone** : toutes les heures en `Europe/Paris` (cohérent avec le reste du projet)

---

## Tests

### Unitaires

- `test_action_registry.py` — enregistrement, permissions par rôle/plateforme, hiérarchie, action désactivée
- `test_action_scheduler.py` — once/interval/cron, annulation, reload au boot, détection missed, auto-pause après 3 échecs, max_executions
- `test_action_executor.py` — routing handler, livraison canal, gestion erreurs
- `test_action_service.py` — tool definitions, validation infos manquantes, permissions, rate limit, annulation par search_query

### Intégration

- `test_action_handlers.py` — tool calling end-to-end (message → LLM → create_action_task → DB → scheduling)
- `test_action_dashboard.py` — endpoints API (CRUD tâches, permissions, filtres)

### Mocks

- `AsyncIOScheduler` mocké (pas de vrais timers)
- Bots Discord/Twitch mockés (intercepte `channel.send()`)
- `OpenAIClient` mocké (pattern existant)

---

## Futures extensions (hors scope)

Ces capacités seront ajoutées comme des actions enregistrées dans le registry :

- **Twitch join** : rejoindre une chaîne à la demande, quitter au stream offline
- **Message ciblé** : envoyer dans un salon spécifique avec ACL et bypass_blacklist
- **Mémoire persistante** : `save_persistent_note(title, content)` avec injection dans le prompt
