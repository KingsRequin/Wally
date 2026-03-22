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
| `next_run_at` | TEXT NULL | Prochaine exécution prévue |
| `last_run_at` | TEXT NULL | Dernière exécution |

### Table `action_permissions`

| Colonne | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `action_type` | TEXT UNIQUE | Type d'action |
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

- Wraps `AsyncIOScheduler` (même pattern que `journal.py`)
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
- Rate limit : max 10 tâches actives par utilisateur (configurable)
- Intervalle minimum : 5 minutes entre exécutions d'une tâche récurrente (configurable)

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
            "run_at": { "type": "string", "description": "ISO datetime pour les tâches once" },
            "interval_minutes": { "type": "integer", "description": "Intervalle en minutes" },
            "cron_hour": { "type": "integer" },
            "cron_minute": { "type": "integer" },
            "max_executions": { "type": "integer", "description": "Nombre max d'exécutions (null = infini)" }
          },
          "required": ["type"]
        },
        "target": {
          "type": "object",
          "properties": {
            "platform": { "type": "string", "enum": ["discord", "twitch", "web"] },
            "channel_id": { "type": "string" },
            "dm": { "type": "boolean", "description": "Envoyer en DM au créateur" }
          },
          "required": ["platform"]
        }
      },
      "required": ["action_type", "description"],
      "additionalProperties": false
    }
  }
}
```

Retour si infos manquantes :
```json
{
  "status": "need_more_info",
  "missing": ["target.channel_id", "schedule.run_at"],
  "message": "Je dois savoir dans quel salon et à quelle heure."
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

Comportement de la recherche :
- 0 résultat : `{"status": "not_found", "message": "..."}`
- 1 résultat : annule directement, `{"status": "cancelled", "task": {...}}`
- 2+ résultats : `{"status": "ambiguous", "candidates": [...]}`

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

Quand il manque 3+ champs et que la plateforme est Discord, le LLM peut retourner un tag `[modal:create_task]` dans sa réponse. Le handler intercepte ce tag et ouvre un modal avec les champs manquants. À la soumission, le handler appelle `ActionService.create()`.

---

## Boot Sequence

1. Services existants (config, db, emotion, memory, openai...)
2. `ActionRegistry(db)` — charge les permissions depuis SQLite
3. `ActionExecutor(registry)` — créé sans les bots
4. `ActionScheduler(db, executor)` — créé mais pas démarré
5. `ActionService(registry, scheduler, db)` — façade prête
6. Discord/Twitch bots créés avec `action_service` injecté
7. `executor.set_bots(discord_bot, twitch_bot)` — injection tardive
8. `scheduler.reload_all()` — recharge tâches actives, marque les missed
9. `scheduler.start()` — démarre apscheduler
10. `asyncio.gather(...)` — tout tourne

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

- **Max tâches actives par utilisateur** : 10 (configurable dans le dashboard)
- **Intervalle minimum** : 5 minutes entre exécutions récurrentes (configurable)
- **Pas d'escalade de privilèges** : le créateur doit avoir le rôle requis pour l'action
- **Isolation** : un utilisateur ne peut lister/annuler que ses propres tâches (sauf admin)

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
