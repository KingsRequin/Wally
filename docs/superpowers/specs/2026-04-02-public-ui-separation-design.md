# Séparation Public UI / Admin — Design Spec
**Date :** 2026-04-02  
**Statut :** Approuvé

---

## Contexte et objectifs

Wally doit pouvoir être utilisé par d'autres personnes qui veulent leur propre identité visuelle sur le dashboard public (HTML, CSS, JS entièrement custom — pas juste des couleurs). Le panel admin peut rester standard et partagé entre tous.

Contraintes :
- Mise à jour du bot ne doit jamais écraser le frontend public custom
- Déploiement simple (pas de second service à gérer)
- Panel admin inchangé et toujours à jour automatiquement

---

## Architecture

```
wally-bot (Python, port 8080)
│
├── /                    → sert ./public-ui/ (volume Docker, propriété de l'utilisateur)
├── /static/public-ui/*  → fichiers statiques du volume public-ui/
├── /admin               → panel admin (embarqué dans l'image Docker, jamais overridé)
│
├── /api/public/*        → contrat stable documenté (sans auth)
└── /api/admin/*         → inchangé (protégé par Bearer token)
```

---

## Volume Docker

```yaml
# docker-compose.yml
volumes:
  - ./public-ui:/app/public-ui
```

Au **premier démarrage** : si `public-ui/` est vide ou absent, le bot y copie le starter kit depuis `bot/dashboard/static/public-starter/`. Les démarrages suivants ne touchent jamais ce dossier.

Les `docker compose pull && up -d` ne touchent jamais `public-ui/`.

---

## Starter kit

Fourni dans le repo sous `bot/dashboard/static/public-starter/`. Copié dans `public-ui/` uniquement si vide.

**Structure :**
```
public-ui/
├── index.html      — page principale (SPA minimaliste)
├── style.css       — variables CSS pour couleurs/fonts/logo
└── app.js          — appels /api/public/* uniquement
```

**Contenu du starter :**
- Status bot (online/offline, uptime, plateformes)
- Émotions en temps réel (jauges + graphe historique via SSE)
- Stream Twitch live (titre, jeu, viewers)
- Graphe social
- Galerie images
- Chat web (si activé)

---

## Routing dans app.py

```python
# Panel admin — embarqué dans l'image, jamais overridé
@app.get("/admin")
async def admin_panel():
    return FileResponse("bot/dashboard/static/index.html")

# Fichiers statiques public-ui (CSS, JS, assets)
app.mount("/static/public-ui", StaticFiles(directory="public-ui"), name="public-ui-static")

# SPA catch-all — sert index.html pour toutes les routes non-API
@app.get("/{path:path}")
async def public_ui(path: str = ""):
    _maybe_seed_public_ui()   # copie le starter si public-ui/ est vide
    return FileResponse("public-ui/index.html")
```

`_maybe_seed_public_ui()` : copie récursive de `bot/dashboard/static/public-starter/` vers `public-ui/` si le dossier est vide. Exécuté une seule fois au démarrage (flag en mémoire).

---

## Contrat API public (`PUBLIC_API.md`)

Endpoints garantis stables entre versions :

| Endpoint | Description |
|---|---|
| `GET /api/public/status` | Statut bot, plateformes, uptime, version |
| `GET /api/public/emotions/history?since=N` | Historique émotions (snapshots 5min) |
| `GET /api/public/emotions/current` | État émotionnel actuel |
| `SSE /api/public/sse/emotions` | Stream temps réel des émotions |
| `GET /api/public/twitch/stream` | Infos stream live (titre, jeu, viewers) |
| `GET /api/public/social-graph/data` | Nœuds et relations du graphe social |
| `GET /api/public/gallery` | Liste images galerie avec pagination |
| `GET /api/public/gallery/{id}/image` | Fichier image |
| `GET /api/public/roadmap` | Contenu ROADMAP.md |
| `WS /api/chat/ws/{token}` | Chat web (JWT Discord OAuth) |

Documenté dans `PUBLIC_API.md` à la racine du repo.

---

## Workflow de mise à jour

**Pour l'utilisateur du projet :**
```bash
git pull
docker compose up -d --build wally
# → /admin et logique Python à jour
# → public-ui/ intact, aucune modification
```

**Pour les instances multi-tenant** (bouton "Update dispo") :
- `docker compose up -d --force-recreate` préserve le volume `public-ui/`
- Identique au comportement actuel

---

## Ce qui ne change pas

- Toute la logique Python (bot, émotions, mémoire, graphe)
- Panel admin `/admin` — même fonctionnement, même auth Bearer
- Instances multi-tenant — inchangées
- Tous les endpoints `/api/*` — inchangés

---

## Fichiers à créer / modifier

| Fichier | Action |
|---|---|
| `bot/dashboard/app.py` | Ajouter routing `/admin`, catch-all SPA, `_maybe_seed_public_ui()` |
| `bot/dashboard/static/public-starter/index.html` | Nouveau — starter HTML |
| `bot/dashboard/static/public-starter/style.css` | Nouveau — starter CSS |
| `bot/dashboard/static/public-starter/app.js` | Nouveau — starter JS (appels /api/public/*) |
| `docker-compose.yml` | Ajouter volume `./public-ui:/app/public-ui` |
| `PUBLIC_API.md` | Nouveau — documentation contrat API public |
| `TODO.md` | Mettre à jour avec les tâches du chantier |
| `.gitignore` | Ajouter `public-ui/` (contenu custom, pas versionné) |
