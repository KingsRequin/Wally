# Image Generation & Gallery — Design Spec

## Summary

Ajouter la génération d'images via l'API OpenAI Images, une galerie publique sur le dashboard web, un système de votes par flammes, des commandes slash avec autocomplétion sur le web chat, et un overlay OBS dédié pour afficher des images aléatoires de la galerie via `!image` sur Twitch.

---

## 1. Génération d'images

### `OpenAIClient.generate_image()`

Nouvelle méthode async dans `bot/core/openai_client.py` :

```python
async def generate_image(self, prompt: str, sender_id: str = None) -> dict:
    # Returns {"path": str, "cost_usd": float, "revised_prompt": str}
```

**Comportement :**
1. Lit les paramètres depuis `config.image_generation` (model, quality, size, background, format)
2. Vérifie les limites (daily global + per user) via requête SQLite sur `gallery_images`
3. Appelle `self._client.images.generate(...)` avec `response_format="b64_json"`
   - **Retry logic** : même pattern que `complete()` — 3 tentatives, backoff exponentiel (1s, 2s, 4s) sur `RateLimitError` et 5xx
   - **Erreur 400 (content policy)** : ne pas retry, retourner un message d'erreur clair à l'utilisateur ("Prompt refusé par la modération OpenAI")
   - **Logging** : toute erreur loguée via loguru
4. Décode le base64, sauvegarde sur disque dans `data/gallery/{uuid}.{format}`
   - Le dossier `data/gallery/` est créé au démarrage si absent (`os.makedirs(exist_ok=True)`)
5. Calcule le coût via la table de pricing statique `IMAGE_COSTS`
6. Log le coût via `self._db.log_cost(model, 0, 0, cost_usd, purpose="image_generation", user_id=sender_id)`
7. Retourne le chemin fichier, le coût, et le prompt révisé

### Table de pricing image

Constante `IMAGE_COSTS` dans `openai_client.py` :

```python
IMAGE_COSTS = {
    "gpt-image-1.5": {
        ("low", "1024x1024"): 0.009,
        ("low", "1024x1536"): 0.013,
        ("low", "1536x1024"): 0.013,
        ("medium", "1024x1024"): 0.034,
        ("medium", "1024x1536"): 0.05,
        ("medium", "1536x1024"): 0.05,
        ("high", "1024x1024"): 0.133,
        ("high", "1024x1536"): 0.20,
        ("high", "1536x1024"): 0.20,
    },
    "gpt-image-1": {
        ("low", "1024x1024"): 0.011,
        ("low", "1024x1536"): 0.016,
        ("low", "1536x1024"): 0.016,
        ("medium", "1024x1024"): 0.042,
        ("medium", "1024x1536"): 0.063,
        ("medium", "1536x1024"): 0.063,
        ("high", "1024x1024"): 0.167,
        ("high", "1024x1536"): 0.25,
        ("high", "1536x1024"): 0.25,
    },
    "gpt-image-1-mini": {
        ("low", "1024x1024"): 0.005,
        ("low", "1024x1536"): 0.0075,
        ("low", "1536x1024"): 0.0075,
        ("medium", "1024x1024"): 0.019,
        ("medium", "1024x1536"): 0.0285,
        ("medium", "1536x1024"): 0.0285,
        ("high", "1024x1024"): 0.076,
        ("high", "1024x1536"): 0.114,
        ("high", "1536x1024"): 0.114,
    },
}
```

**Modèles supportés au lancement** : `gpt-image-1.5`, `gpt-image-1`, `gpt-image-1-mini`. DALL-E 2/3 exclus (API legacy, paramètres incompatibles).

Fallback pricing : si combinaison (model, quality, size) inconnue, utiliser le prix le plus élevé du modèle pour éviter de sous-estimer.

Méthode statique `estimate_image_cost(model, quality, size) -> float` pour le frontend.

### Config `ImageGenerationConfig`

Nouveau bloc dans `config.yaml` + dataclass dans `config.py` :

```yaml
image_generation:
  model: "gpt-image-1.5"
  quality: "medium"
  size: "1024x1024"
  background: "auto"
  format: "png"
  daily_limit: -1          # -1 = illimité
  per_user_limit: 5        # par jour, -1 = illimité
```

---

## 2. Base de données

### Table `gallery_images`

```sql
CREATE TABLE IF NOT EXISTS gallery_images (
    id TEXT PRIMARY KEY,
    title TEXT,
    prompt TEXT NOT NULL,
    revised_prompt TEXT,
    username TEXT NOT NULL,
    user_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    file_path TEXT NOT NULL,
    model TEXT NOT NULL,
    quality TEXT NOT NULL,
    size TEXT NOT NULL,
    cost_usd REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_gallery_created ON gallery_images(created_at DESC);
CREATE INDEX idx_gallery_user ON gallery_images(username);
```

### Table `gallery_votes`

```sql
CREATE TABLE IF NOT EXISTS gallery_votes (
    image_id TEXT NOT NULL REFERENCES gallery_images(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (image_id, user_id)
);
```

### Méthodes `Database`

- `insert_gallery_image(id, title, prompt, revised_prompt, username, user_id, platform, file_path, model, quality, size, cost_usd)`
- `delete_gallery_image(id)` — supprime entrée + votes (CASCADE)
- `get_gallery_images(search, sort_by, user_filter, limit, offset)` — pagination, tri par date ou votes
- `get_gallery_image(id)` — une image avec vote count
- `toggle_gallery_vote(image_id, user_id) -> bool` — True = voté, False = retiré
- `update_gallery_title(id, title)`
- `get_user_image_count_today(user_id) -> int`
- `get_total_image_count_today() -> int`
- `get_random_gallery_image(filter)` — filter: "all" (toutes), "top" (au moins 1 vote, pondéré par votes), "recent" (dernières 48h)
- `get_gallery_images_for_date(date)` — images d'une date donnée (pour le journal)

---

## 3. Galerie web (page publique)

### Routes API — `bot/dashboard/routes/gallery.py`

**Public :**
```
GET    /api/public/gallery                    → liste paginée (search, sort_by, user_filter, limit, offset)
GET    /api/public/gallery/{id}               → détail image
GET    /api/public/gallery/{id}/image         → FileResponse depuis DATA_GALLERY_DIR (voir sécurité ci-dessous)
POST   /api/public/gallery/{id}/vote          → toggle flamme (auth JWT)
PATCH  /api/public/gallery/{id}/title         → modifier titre (JWT, créateur uniquement)
GET    /api/public/gallery/random             → image aléatoire (filter: all|top|recent)
GET    /api/public/loading-gif                → GIF aléatoire depuis loading_gifs/
GET    /api/public/sse/overlay-image          → SSE stream overlay
GET    /api/public/gallery/estimate-cost      → estimation coût (query: model, quality, size)
```

**Admin :**
```
DELETE /api/admin/gallery/{id}                → supprimer image + fichier disque
```

### Frontend — Onglet "Galerie" dans `app.js`

Onglet public visible par tous :

- **Barre de recherche** : filtre sur prompt et username
- **Options de tri** : par date (défaut) ou par flammes
- **Filtre par utilisateur** : dropdown ou chips cliquables
- **Grille responsive** de cartes image :
  - Vignette de l'image
  - Username du créateur
  - Date/heure de génération
  - Prompt (tronqué, expandable)
  - Bouton flamme 🔥 avec compteur (toggle, flamme active en `#ff3333`)
- **Pagination** : infinite scroll ou "charger plus"
- **Lightbox** : clic sur image → modal plein écran avec tous les détails
- **Admin** : bouton 🗑️ suppression par image avec confirmation toast

**Style** : dark neobrutalism — bordures blanches 3px, ombres dures, fond cartes `#1a1a1a`.

### Sécurité du service d'images

La route `GET /api/public/gallery/{id}/image` :
- Récupère `file_path` depuis la DB par `id` (jamais depuis l'URL directement)
- Résout le chemin relatif par rapport à une constante `DATA_GALLERY_DIR = Path("data/gallery")`
- Vérifie que le chemin résolu est bien un enfant de `DATA_GALLERY_DIR` (protection path traversal)
- Vérifie que le fichier existe → 404 sinon
- Retourne `FileResponse` avec `media_type` déduit de l'extension et headers cache (`Cache-Control: public, max-age=86400`)

### Vote — authentification

`POST /api/public/gallery/{id}/vote` et `PATCH /api/public/gallery/{id}/title` sont des routes publiques mais nécessitent une authentification JWT. La validation JWT est faite **dans le handler** (pas dans le middleware Bearer qui ne couvre que `/api/admin`). Le `user_id` est extrait du token JWT décodé, même mécanisme que le WebSocket chat.

---

## 4. Slash commands web chat + autocomplétion

### Frontend

Quand l'utilisateur tape `/` dans le champ de saisie du chat :
- Popup d'autocomplétion au-dessus de l'input
- Commandes :
  - `/imagine <prompt>` — Générer une image (tout le monde)
  - `/scan <query>` — Recherche mémoire (admin uniquement, masqué sinon)
- Filtrage en temps réel, Tab/clic pour compléter, navigation clavier
- Style : popup dark neobrutalism (fond `#1a1a1a`, bordure blanche 3px, ombre dure)

### Backend — Détection dans WebSocket `chat.py`

```python
if message.startswith("/"):
    command, _, args = message.partition(" ")
    if command == "/imagine":
        # génération image
    elif command == "/scan":
        # vérification admin + scan existant
    else:
        # erreur "commande inconnue"
    return
```

### Flux `/imagine` — Embed interactif

**Étape 1 — Embed "en cours" :**
- Titre : "🎨 Génération en cours..."
- Contenu : le prompt
- Image : GIF aléatoire depuis `loading_gifs/` (via `/api/public/loading-gif`)

**Étape 2 — Génération serveur :**
1. Appel `generate_image(prompt, sender_id)`
2. Appel LLM secondary pour générer un titre court
3. Insert `gallery_images` (avec titre)
4. Souvenir mem0 : "{username} a généré une image : {titre}"

**Étape 3 — Mise à jour embed :**
- Titre : titre court LLM
- Image : l'image générée
- Prompt : en texte secondaire
- Footer : date et heure
- Bouton 🔥 : toggle vote flamme (tout le monde connecté)
- Bouton ✏️ : modifier titre (créateur uniquement)

### Flux `/scan`

Admin only. Réutilise la logique existante de `_handle_scan` dans `chat.py`.
- `/scan` sans arguments : comportement existant inchangé (scan complet)
- `/scan <query>` : passe `query` comme argument à la recherche existante
- Résultat non broadcast (message privé, envoyé uniquement à l'auteur)

**Refactoring requis** : le check actuel dans `chat.py` (`content.lower() == "/scan"`) doit être remplacé par le nouveau pattern `startswith("/")` + `partition(" ")`. La fonction `_handle_scan` reçoit un nouveau paramètre `query: str | None = None` — si `None`, scan complet (comportement actuel), sinon recherche ciblée.

### Messages WebSocket — Nouveaux types

L'embed `/imagine` dans le web chat utilise des messages WebSocket structurés :

```json
// Embed en cours de génération
{"type": "image_generating", "id": "msg_id", "prompt": "...", "loading_gif": "/api/public/loading-gif"}

// Embed final (remplace le message précédent par id)
{"type": "image_result", "id": "msg_id", "image_id": "gallery_uuid", "title": "...", "prompt": "...", "image_url": "/api/public/gallery/{id}/image", "username": "...", "created_at": "...", "votes": 0, "user_voted": false}

// Actions utilisateur
{"type": "vote", "image_id": "gallery_uuid"}
{"type": "edit_title", "image_id": "gallery_uuid", "title": "Nouveau titre"}
```

---

## 5. Overlay image (Twitch `!image`)

### Page overlay — `bot/dashboard/static/overlay_image.html`

Page HTML transparente pour OBS, séparée de l'overlay émotions.

**Comportement :**
1. Connecte SSE à `/api/public/sse/overlay-image`
2. Attend un événement SSE nommé `show_image` (format : `event: show_image\ndata: {json}\n\n`)
3. Affiche l'image avec animation d'entrée (Animate.css)
4. Reste affichée pendant la durée configurée
5. Animation de sortie puis disparaît
6. Revient transparent

### Animations — Animate.css

Bibliothèque CDN (~4KB gzip), 80+ animations. Entrée et sortie configurables dans l'admin.

### Commande Twitch `!image`

Dans `bot/twitch/handlers.py` :
- Détecte la commande configurable (défaut `!image`)
- Appelle `db.get_random_gallery_image(filter=config.overlay_image.random_filter)`
- Pousse événement SSE vers overlay via un mécanisme de broadcast dédié :
  - `AppState` reçoit un nouveau champ `overlay_image_queue: asyncio.Queue(maxsize=1)` (à ajouter dans `bot/dashboard/state.py`)
  - Le handler Twitch accède à la queue via `bot.dashboard_state.overlay_image_queue` (pattern existant, `dashboard_state` est déjà assigné avant le démarrage)
  - Le handler fait `queue.put_nowait(image_data)` (ignore si plein = image déjà en cours)
  - Le SSE endpoint lit depuis cette queue et pousse un événement nommé `show_image`
  - Payload SSE : `{"image_url": "/api/public/gallery/{id}/image", "title": "...", "username": "...", "display_duration": 15}`
- Si image déjà affichée (queue pleine), ignore silencieusement — cooldown implicite = `display_duration`

### Config `OverlayImageConfig`

```yaml
overlay_image:
  command: "!image"
  display_duration: 15
  animation_in: "fadeIn"
  animation_out: "fadeOut"
  animation_duration: 1.0
  random_filter: "all"
  enabled: true
```

### Onglet admin "Overlays"

Nouvel onglet regroupant les deux overlays :

**Section Overlay Émotions** (existant, déplacé ici) :
- Toggle on/off

**Section Overlay Image** :
- Toggle enabled
- Champ texte : commande Twitch
- Slider : durée d'affichage (5–60s)
- Select : animation d'entrée (liste Animate.css)
- Select : animation de sortie (liste Animate.css)
- Slider : durée animation (0.5–3s)
- Select : filtre images (all / top / recent)
- Bouton "Tester" : déclenche l'overlay avec image aléatoire

---

## 6. Commande Discord `/wally imagine`

### Slash command — `bot/discord/commands/imagine.py`

```
/wally imagine prompt:<texte>
```

**Flux :**
1. Vérifie limites (daily + per user) → erreur si dépassé
2. Embed "en cours" avec GIF aléatoire (via `attachment://` depuis `/api/public/loading-gif`)
3. `generate_image(prompt, sender_id)`
4. `complete_secondary()` pour titre court
5. Insert `gallery_images`
6. Souvenir mem0
7. Édite embed avec image finale

### Embed Discord — Résultat

- Titre : titre court LLM
- Image : `attachment://image.png` (fichier attaché au message)
- Description : prompt original en italique
- Footer : date et heure de génération
- Couleur : `#ffdd00` (joy)

### Boutons Discord (View persistante)

- **🔥 Flamme** (`custom_id: "gallery_vote:{image_id}"`) : toggle vote, label = compteur. Tout le monde.
- **✏️ Modifier titre** (`custom_id: "gallery_edit:{image_id}"`) : ouvre Modal, champ texte. Créateur uniquement (vérifie `interaction.user.id == user_id`).

Boutons enregistrés avec `timeout=None` pour persister après redémarrage. Les `custom_id` incluent l'`image_id` pour le routage après restart.

### Intégration journal

`bot/core/journal.py` inclut les images du jour :
- Récupère via `db.get_gallery_images_for_date(date)` (méthode dédiée avec filtre sur `created_at`)
- Format : "**Galerie du jour** : N images — {titres} par {usernames}"

---

## 7. Fichiers impactés

### Modifiés

| Fichier | Modifications |
|---|---|
| `bot/config.py` | + `ImageGenerationConfig` + `OverlayImageConfig` |
| `bot/core/openai_client.py` | + `generate_image()` + `estimate_image_cost()` + `IMAGE_COSTS` |
| `bot/db/database.py` | + tables + méthodes CRUD galerie/votes |
| `bot/dashboard/app.py` | + montage routes galerie + SSE overlay-image + static mounts |
| `bot/dashboard/routes/admin.py` | + config overlay |
| `bot/dashboard/static/app.js` | + onglet Galerie + onglet Overlays + slash commands + autocomplétion |
| `bot/dashboard/static/style.css` | + styles galerie, flamme, autocomplétion, lightbox |
| `bot/dashboard/static/index.html` | + entrées sidebar Galerie + Overlays |
| `bot/dashboard/state.py` | + champ `overlay_image_queue: asyncio.Queue` |
| `bot/dashboard/routes/chat.py` | refactoring détection commandes (`/scan` exact match → partition pattern) |
| `bot/discord/bot.py` | + cog imagine + boutons persistants |
| `bot/twitch/handlers.py` | + détection commande overlay configurable |
| `bot/core/journal.py` | + section galerie du jour |

### Nouveaux

| Fichier | Rôle |
|---|---|
| `bot/discord/commands/imagine.py` | Slash command + View persistante |
| `bot/dashboard/routes/gallery.py` | Routes API galerie |
| `bot/dashboard/static/overlay_image.html` | Overlay OBS image |
| `bot/dashboard/static/loading_gifs/` | Dossier GIFs chargement (vide — rempli par l'utilisateur) |
| `data/gallery/` | Stockage images (créé au runtime) |

---

## 8. Détails complémentaires

### Fallback GIF de chargement

Si le dossier `loading_gifs/` est vide, `/api/public/loading-gif` retourne un 204 No Content. Le frontend affiche alors un spinner CSS animé en fallback (texte "Génération en cours..." avec animation de points).

### Config persistence

`ImageGenerationConfig` et `OverlayImageConfig` doivent être intégrés dans :
- `Config` dataclass : nouveaux champs `image_generation` et `overlay_image`
- `Config.load()` : parsing avec `raw.get("image_generation", {})` + valeurs par défaut
- `Config.save()` : sérialisation avec `asdict(self.image_generation)` et `asdict(self.overlay_image)`

### Validation titre

`PATCH /api/public/gallery/{id}/title` : le titre est limité à **100 caractères**. Au-delà → 400 Bad Request. Le Modal Discord a la même limite via `max_length=100`.

### Route overlay_image.html

`bot/dashboard/app.py` ajoute une route dédiée pour servir `overlay_image.html` (comme la route existante pour `overlay.html`) avec headers no-cache :
```python
@app.get("/overlay-image")
async def overlay_image_page():
    return FileResponse("bot/dashboard/static/overlay_image.html", headers={"Cache-Control": "no-cache"})
```

### Réponse estimate-cost

`GET /api/public/gallery/estimate-cost?model=...&quality=...&size=...` retourne :
```json
{"cost_usd": 0.034, "model": "gpt-image-1.5", "quality": "medium", "size": "1024x1024"}
```

### Cooldown `/imagine` web chat

La commande `/imagine` **respecte le cooldown existant** du web chat (`config.web_chat.cooldown_seconds`). De plus, la limite `per_user_limit` (par jour) s'applique. Si un utilisateur spam `/imagine` rapidement, le cooldown bloque les requêtes suivantes. La génération d'image ne bypass pas le cooldown — elle le déclenche comme un message normal.

### Suppression d'image — fichier manquant

`DELETE /api/admin/gallery/{id}` : si le fichier sur disque est déjà absent (suppression manuelle), log un WARNING via loguru mais ne fait pas échouer l'opération. L'entrée DB + votes sont toujours supprimés.

### `get_random_gallery_image` — type de retour

Retourne le même format que `get_gallery_image(id)` : dict avec `id`, `title`, `prompt`, `username`, `file_path`, `created_at`, `votes` (int). Retourne `None` si la galerie est vide.
