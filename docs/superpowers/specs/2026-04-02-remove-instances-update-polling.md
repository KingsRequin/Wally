# Suppression système d'instances + mise à jour autonome — Design Spec
**Date :** 2026-04-02  
**Statut :** Approuvé

---

## Contexte et objectifs

Le système multi-instances (provisioner, onglet Instances, publish-update) était temporaire. Chaque bot (Wally, Cindy, etc.) sera désormais un projet indépendant avec son propre repo cloné. Le mécanisme de mise à jour est simplifié : chaque bot poll GHCR pour détecter une nouvelle image et propose un bouton dans le panel pour se mettre à jour en un clic.

**Contraintes :**
- Wally et Cindy continuent de tourner sans interruption pendant la migration
- Cindy reste à `/opt/stacks/wally-instances/cindy/` — hors scope de ce chantier
- L'image publique sera publiée sur GHCR (`ghcr.io/<user>/wally-ai:latest`)

---

## Ce qui est supprimé

### `bot/core/provisioner.py`
Fichier entièrement supprimé. Contenait la logique de provisioning des instances (création dossiers, .env, config.yaml, docker-compose, persona files, docker compose up).

### `bot/dashboard/routes/setup.py` — routes instances uniquement
Routes supprimées (tout ce qui contient `/instances/`) :
- `GET /setup/instances`
- `POST /setup/instances/{slug}/stop`
- `POST /setup/instances/{slug}/start`
- `GET /setup/instances/{slug}/persona`
- `POST /setup/instances/{slug}/persona/{filename}`
- `GET /setup/instances/{slug}/update-config`
- `POST /setup/instances/{slug}/update-config`
- `POST /setup/instances/{slug}/notify-update`
- `POST /setup/notify-all-updates`
- `POST /setup/instances/{slug}/update`
- `POST /setup/instances/{slug}/publish-update`
- `DELETE /setup/instances/{slug}/publish-update`
- `POST /setup/instances/publish-all-updates`
- `POST /setup/webhook/update`

Routes **conservées** dans `setup.py` :
- `POST /setup/invite`
- `GET /setup/invites`
- `DELETE /setup/invite/{token}`
- `GET /setup/persona-template/{filename}`
- Wizard d'invite (`/setup/wizard/*`)

Si `setup.py` ne contient plus que les invites et le wizard, il reste utile — pas besoin de le fusionner ailleurs.

### `bot/dashboard/routes/admin.py`
- Supprimer l'import `from bot.core.provisioner import INSTANCES_DIR`
- Supprimer le champ `"is_main"` dans `GET /api/admin/config`
- Supprimer la lecture du flag fichier `data/update_available` dans `GET /api/admin/bot/status` — remplacé par le champ `update_available` issu du nouveau `UpdateChecker`
- Modifier `POST /api/admin/self-update` : faire `docker compose pull` avant `docker compose up -d --force-recreate`

### `bot/dashboard/static/app.js`
- Supprimer la fonction `renderInstancesTab()` (~200 lignes, ligne 7462)
- Supprimer `loadInstances()` et `notifyAllInstancesUpdate()`
- Supprimer le sous-onglet "Instances" dans l'onglet Système (bouton + conteneur)
- Supprimer la logique `is_main` (`if (data.is_main) { ... }`)
- Supprimer le legacy redirect `'admin-instances': 'admin-systeme'`
- Conserver le bouton "Mise à jour disponible" (amber, pulse) — il reste piloté par `data.update_available` dans `pollBotStatus()`

---

## Ce qui est ajouté

### `bot/core/update_checker.py` (nouveau fichier)

Responsabilité unique : détecter si une nouvelle image est disponible sur GHCR.

```
UpdateChecker
├── __init__(image_ref: str, check_interval_seconds: int = 3600)
├── start()          — démarre la tâche apscheduler
├── stop()           — arrête la tâche
├── update_available → bool   — propriété lue par le dashboard
└── _check()         — logique de comparaison des digests
```

**Logique de `_check()` :**
1. Lire le digest de l'image en cours via Docker socket : `GET /v1.41/containers/<hostname>/json` → champ `Image` (sha256 du layer digest)
2. Interroger l'API GHCR (sans auth, image publique) :
   `GET https://ghcr.io/v2/<user>/<image>/manifests/latest`
   Header : `Accept: application/vnd.oci.image.index.v1+json`
   → digest retourné dans le header `Docker-Content-Digest`
3. Comparer les deux digests. Si différents → `update_available = True`
4. En cas d'erreur réseau ou Docker socket absent → log WARNING, `update_available` inchangé

**Configuration dans `config.yaml` :**
```yaml
bot:
  update_image: ""   # ex: "ghcr.io/user/wally-ai:latest" — vide = polling désactivé
```

**Wiring dans `main.py` :**
- `UpdateChecker` créé si `config.bot.update_image` est non vide
- Injecté dans `AppState`
- `start()` appelé dans le lifespan startup, `stop()` dans le shutdown

### `POST /api/admin/self-update` (modifié)

Séquence mise à jour :
```python
subprocess.Popen(
    ["sh", "-c", f"docker compose -f {compose_file} pull && docker compose -f {compose_file} up -d --force-recreate"],
    start_new_session=True,
    ...
)
```

Après déclenchement : `update_checker.update_available = False` (reset optimiste).

### `GET /api/admin/bot/status` (modifié)

Remplacer :
```python
"update_available": Path("/app/data/update_available").exists()
```
Par :
```python
"update_available": state.update_checker.update_available if state.update_checker else False
```

---

## README.md — sections à mettre à jour

### Section "Dashboard Web" — Mode admin
- Retirer la mention de la gestion d'instances
- Ajouter : "Mise à jour automatique : le bot poll GHCR et affiche un bouton quand une nouvelle image est disponible"

### Section "Docker"
- Retirer "Trois services" → "Deux services : `wally` et `qdrant`" (cloudflared est optionnel, pas un service core)
- Ajouter section "Mise à jour"  :
```
## Mise à jour

Configurer `bot.update_image` dans `config.yaml` avec la référence GHCR.
Le bot poll toutes les heures. Quand une mise à jour est disponible, un bouton
amber apparaît dans le panel admin → un clic suffit pour mettre à jour.
```

### Section "Configuration — `config.yaml`" — Section `bot`
Ajouter la ligne `update_image` dans le tableau.

---

## Tests

### `tests/test_update_checker.py` (nouveau)
- `test_update_available_when_digests_differ` — mock Docker socket + mock GHCR API → `update_available = True`
- `test_no_update_when_digests_match` — même digest → `update_available = False`
- `test_update_disabled_when_image_empty` — `update_image = ""` → checker non créé, `update_available` absent de status
- `test_network_error_does_not_crash` — GHCR injoignable → `update_available` inchangé, pas d'exception

### `tests/test_setup_routes.py` (existant)
- Vérifier que les routes `/instances/*` retournent 404 après suppression

---

## Fichiers à créer / modifier

| Fichier | Action |
|---|---|
| `bot/core/provisioner.py` | Supprimer |
| `bot/core/update_checker.py` | Créer |
| `bot/dashboard/routes/setup.py` | Supprimer toutes les routes `/instances/*` et helpers associés |
| `bot/dashboard/routes/admin.py` | Supprimer `is_main`, adapter `update_available`, modifier `self-update` |
| `bot/dashboard/static/app.js` | Supprimer code instances, conserver bouton update |
| `bot/main.py` | Wiring `UpdateChecker` dans AppState + lifespan |
| `bot/config.py` | Ajouter `update_image: str = ""` dans `BotConfig` |
| `bot/dashboard/state.py` | Ajouter `update_checker: UpdateChecker | None` |
| `README.md` | Mettre à jour sections Dashboard, Docker, Configuration |
| `tests/test_update_checker.py` | Créer |

---

## Ce qui ne change pas

- Toute la logique bot (Discord, Twitch, mémoire, émotions, actions)
- Le wizard d'invite (`/setup/wizard/*`)
- La gestion des invites (`/setup/invite`, `/setup/invites`)
- Tous les autres endpoints `/api/admin/*`
- Le déploiement de Cindy — hors scope
