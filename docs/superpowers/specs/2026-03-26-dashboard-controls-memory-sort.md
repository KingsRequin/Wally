# Spec: Dashboard Controls & Memory Sort

**Date:** 2026-03-26
**Scope:** 2 améliorations dashboard

---

## 1. Barre de contrôle bot (admin)

### UI
- Barre fixe en haut du dashboard, visible uniquement en mode admin
- Style glassmorphism cohérent avec le dashboard existant
- Contenu :
  - Pastilles de statut (vert/rouge) pour Discord et Twitch avec label
  - Boutons Stop/Start par adapter (toggle selon état)
  - Bouton Restart container (avec confirmation modale)
- Après un restart : message "Reconnexion en cours..." + auto-reconnexion (polling `/api/admin/bot/status`)

### Endpoints

**`GET /api/admin/bot/status`**
- Retourne l'état de chaque adapter
- Response : `{"discord": "connected"|"disconnected", "twitch": "connected"|"disconnected"}`
- Déterminé via `discord_bot.is_ready()` et `twitch_bot.connected`

**`POST /api/admin/bot/discord/stop`**
- Appelle `discord_bot.close()`
- Response : `{"ok": true}`

**`POST /api/admin/bot/discord/start`**
- Relance le bot Discord (`asyncio.create_task(discord_bot.start(token))`)
- Response : `{"ok": true}`

**`POST /api/admin/bot/twitch/stop`**
- Appelle `twitch_bot.close()`
- Response : `{"ok": true}`

**`POST /api/admin/bot/twitch/start`**
- Relance le bot Twitch
- Response : `{"ok": true}`

**`POST /api/admin/bot/restart`**
- Requiert le socket Docker monté dans le container
- Exécute `docker compose restart wally` via le Docker SDK ou subprocess
- Le container redémarre — le dashboard se déconnecte et le client JS poll pour la reconnexion
- Response : `{"ok": true}` (envoyée avant le restart effectif)

### Docker
- Ajouter `/var/run/docker.sock:/var/run/docker.sock` dans les volumes du service `wally` dans `docker-compose.yml`

---

## 2. Tri des mémoires par date

### UI
- Dropdown de tri dans la modal mémoire utilisateur (au-dessus de la liste des mémoires)
- 3 options :
  - **Plus récent** — tri par `created_at` décroissant
  - **Plus ancien** — tri par `created_at` croissant
  - **Par défaut** — ordre retourné par Qdrant (pas de tri)
- Tri côté client (toutes les mémoires sont déjà chargées dans la modal)
- Le dropdown garde son état pendant la session (pas persisté)

### Données
- Le champ `created_at` existe déjà dans les payloads Qdrant
- Fallback sur `date` si `created_at` absent (anciennes entrées mem0 migrées)
- Entrées sans date triées en dernier

---

## Hors scope
- Build + up Docker (annulé)
- Persistance du choix de tri
- Contrôle d'autres services Docker
