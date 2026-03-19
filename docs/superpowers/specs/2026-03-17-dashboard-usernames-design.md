# Design — Noms d'utilisateurs dans le dashboard mémoire

**Date :** 2026-03-17
**Statut :** Approuvé

---

## Contexte

Le dashboard affiche les utilisateurs de la mémoire long-terme (mem0/Qdrant) avec leur `user_id` brut (ex : `discord:123456789`). Ce n'est pas lisible. De plus, les utilisateurs dont les souvenirs ont été créés avant l'ajout de la table `memory_users` n'apparaissent pas du tout dans le dashboard.

Les utilisateurs Discord et Twitch sont indépendants pour l'instant. Un futur feature permettra de les lier manuellement via le dashboard (hors scope de ce document).

---

## Objectifs

1. Afficher le **pseudo** (Discord username ou Twitch username) à la place de l'ID numérique dans le dashboard.
2. Synchroniser les utilisateurs existants dans mem0/Qdrant vers `memory_users` au démarrage et via un bouton manuel.

---

## Section 1 — Base de données

### Migration de schéma

Ajouter la colonne `username TEXT` à la table `memory_users` au démarrage, après `executescript(SCHEMA)` :

```python
try:
    await conn.execute("ALTER TABLE memory_users ADD COLUMN username TEXT")
    await conn.commit()
except Exception:
    pass  # colonne déjà présente
```

### `upsert_memory_user(user_id, platform, username="")`

- Signature mise à jour avec `username: str = ""` (optionnel, pas de valeur par défaut obligatoire).
- SQL : `ON CONFLICT(user_id) DO UPDATE SET last_updated=..., username=COALESCE(excluded.username, memory_users.username)`.
- Si `username` est vide, la valeur existante est **préservée** — un `upsert` sans nom ne supprime pas un nom déjà connu.
- Retourne `None` (pas de changement de signature de retour).

### `list_memory_users(q=None)`

- Retourne désormais le champ `username` (peut être `None`) dans chaque entrée dict.
- Le filtre `q` s'applique sur **`m.user_id` et `m.username`** : `WHERE (m.user_id LIKE ? OR m.username LIKE ?)`.

### `sync_memory_users_from_qdrant()`

Nouvelle méthode publique sur `Database`, prend en paramètre l'URL Qdrant :

```python
async def sync_memory_users_from_qdrant(self, qdrant_url: str) -> int:
```

1. Importe `QdrantClient` depuis `qdrant_client`.
2. Instancie le client avec `url=qdrant_url`.
3. Scroll la collection `"wally_memory"` par pages de 100 points avec `with_payload=True`.
4. Extrait le champ `user_id` de chaque point (clé `"user_id"` dans le payload).
5. Déduplique les `user_id` trouvés.
6. Pour chaque `user_id` unique, décompose en `platform:raw_id` → appelle `upsert_memory_user(user_id, platform, username="")` (préserve les usernames existants).
7. Retourne le nombre de **nouvelles** entrées insérées (compteur incrémenté quand `upsert` crée une ligne).
8. Si Qdrant indisponible ou collection absente : log `WARNING`, retourne `0`, ne lève pas d'exception.

---

## Section 2 — Couche mémoire et sessions

### `MemoryService.add()`

Signature étendue :

```python
async def add(self, platform: str, user_id: str, content: str,
              username: str = "", emotion_context: str = "") -> None:
```

Passe `username` à `db.upsert_memory_user(uid, platform, username)`.

### `sessions.py` — `_analyze_session()`

C'est **ici** que `memory.add()` est appelé (pas dans les handlers). Le `display_name` est déjà disponible dans `session.participants` :

```python
for user_id, display_name in session.participants.items():
    ...
    await self._memory.add(
        session.platform,
        user_id,
        user_facts,
        username=display_name,  # ← ajout
    )
```

Aucun changement dans `discord/handlers.py` ni `twitch/handlers.py` pour le username — ils passent déjà `display_name` à `session_manager.record_message()`.

### `main.py` — boot sync

Après l'initialisation de tous les services, avant `asyncio.gather()` :

```python
qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
await db.sync_memory_users_from_qdrant(qdrant_url)
```

Si Qdrant est indisponible, log WARNING et continue.

---

## Section 3 — Dashboard

### API : `POST /memory/sync` (dans `bot/dashboard/routes/memory.py`)

Route admin protégée par le middleware Bearer token existant. Ajoutée dans `memory.py` :

```python
@router.post("/memory/sync")
async def sync_memory_users(request: Request):
    state = request.app.state.wally
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    n = await state.db.sync_memory_users_from_qdrant(qdrant_url)
    return {"synced": n}
```

Exposée via le préfixe admin existant → `POST /api/admin/memory/sync`.

### `app.js` — liste des utilisateurs

- Affiche `username` si disponible (non null/vide), sinon l'ID numérique extrait (comportement actuel : `u.user_id.split(':').slice(1).join(':')`).
- Format inchangé : nom en ligne principale, `platform · date` en sous-texte.
- La recherche par nom fonctionne via l'API (qui inclut désormais `username` dans le `WHERE LIKE`).

### `app.js` — header vue mémoire (`renderMemories`)

- Si `username` connu : `OlafMC (discord:123456789) — 3 souvenir(s)`
- Sinon : `discord:123456789 — 3 souvenir(s)` (comportement actuel)

### `app.js` — bouton Sync

Bouton `↻ SYNC` dans la barre de l'onglet mémoire (à côté du champ de recherche). Appelle `POST /api/admin/memory/sync` et affiche un toast : `"N utilisateur(s) importés"`. Recharge la liste après le sync.

### `app.js` — résultats de recherche globale (`searchMemories`)

Remplace l'affichage du `user_id` brut par `username (user_id)` si `username` est connu dans les résultats (à noter : les résultats de recherche ne retournent pas `username` actuellement — la route `/memory/search` doit aussi retourner `username` pour chaque résultat).

### Route `/memory/search` — mise à jour

Dans `search_memories()`, enrichir chaque résultat avec le `username` issu de `db.list_memory_users()` (chargé en dict `user_id → username` avant la boucle).

---

## Hors scope

- Lien Discord ↔ Twitch (future feature).
- Résolution de nom via API Discord/Twitch en temps réel.
- Backfill des usernames pour anciens utilisateurs sans interaction récente (apparaissent avec leur ID jusqu'à leur prochaine interaction).

---

## Fichiers modifiés

| Fichier | Changement |
|---|---|
| `bot/db/database.py` | Migration `username`, `upsert_memory_user()`, `list_memory_users()`, `sync_memory_users_from_qdrant()` |
| `bot/core/memory.py` | `add()` accepte `username` |
| `bot/core/sessions.py` | `_analyze_session()` passe `username=display_name` |
| `bot/main.py` | Boot sync au démarrage |
| `bot/dashboard/routes/memory.py` | Route `POST /memory/sync` + enrichir `/memory/search` avec username |
| `bot/dashboard/static/app.js` | Affichage username, bouton Sync, résultats de recherche |
