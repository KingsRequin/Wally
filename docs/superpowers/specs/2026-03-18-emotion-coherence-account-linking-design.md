# Design Spec — Cohérence émotionnelle & Liaison de comptes Twitch/Discord

**Date :** 2026-03-18
**Statut :** Approuvé

---

## 1. Bug — Cohérence émotionnelle

### Problème

L'état émotionnel peut contenir des combinaisons incohérentes (ex. anger=0.65 et joy=0.33 simultanément). Les règles de suppression existent (`SUPPRESSION_RULES`) mais n'agissent qu'au moment où une émotion monte via `apply_delta`, pas en continu. Si anger accumule sur plusieurs messages puis que joy monte indépendamment, l'incohérence persiste.

### Solution : Compétition continue (Approche B + extension des paires)

#### 1.1 Renforcement des SUPPRESSION_RULES

```python
SUPPRESSION_RULES: list[tuple[str, str, float]] = [
    ("joy",     "anger",   0.8),  # 0.5 → 0.8
    ("joy",     "sadness", 0.8),  # 0.5 → 0.8
    ("sadness", "joy",     0.8),  # nouveau (symétrique explicite)
]
```

`anger ↔ boredom` intentionnellement absent : être énervé et s'ennuyer est plausible.

#### 1.2 Compétition continue dans `_apply_decay()`

Après le decay exponentiel normal, pour chaque paire incompatible :

```python
COMPETITION_K = 0.05  # coefficient de compétition par tick (60s)

def _apply_competition(self) -> None:
    for src, tgt, _ in SUPPRESSION_RULES:
        extra = self._state[src] * self._state[tgt] * COMPETITION_K
        if extra > 0:
            self._state[src] = max(0.0, self._state[src] - extra)
            self._state[tgt] = max(0.0, self._state[tgt] - extra)
```

`_apply_competition()` est appelé à la fin de `_apply_decay()`.

**Effet :** Si anger=0.65 et joy=0.33, extra ≈ 0.011 par tick. En ~10min les deux convergent naturellement sans saut brutal.

#### 1.3 Fichiers modifiés

- `bot/core/emotion.py` : `SUPPRESSION_RULES`, `COMPETITION_K`, `_apply_competition()`, `_apply_decay()`

---

## 2. Feature — Liaison de comptes Twitch/Discord

### Vue d'ensemble

Permet de lier manuellement un compte Twitch et un compte Discord appartenant à la même personne réelle. Après fusion, toutes les nouvelles interactions (Twitch ou Discord) alimentent un profil mémoire unique. La fusion est toujours manuelle — jamais automatique. L'analyse de similarité de pseudo est on-demand (bouton dashboard) et automatique à l'arrivée d'un nouveau compte.

---

### 2.1 Schéma DB — Table `user_links`

```sql
CREATE TABLE IF NOT EXISTS user_links (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_id  TEXT NOT NULL,   -- ex. discord:394823019482
    alias_id      TEXT NOT NULL,   -- ex. twitch:kingsrequin_ttv
    confidence    REAL NOT NULL,   -- score Jaro-Winkler normalisé 0.0–1.0
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending | accepted | rejected
    created_at    REAL NOT NULL,
    resolved_at   REAL,
    UNIQUE(canonical_id, alias_id)
);
```

**Règle canonique :** l'identité Discord est toujours canonique (ID numérique stable). L'identité Twitch est toujours l'alias.

**Méthodes DB ajoutées dans `database.py` :**

| Méthode | Description |
|---|---|
| `upsert_link_proposal(canonical_id, alias_id, confidence)` | Insert si absent ; met à jour `confidence` si le score a changé ; no-op si déjà accepted/rejected |
| `list_link_proposals(status=None)` | Liste filtrée par statut, triée par confidence DESC |
| `accept_link(id)` | `status='accepted'`, `resolved_at=now()` |
| `reject_link(id)` | `status='rejected'`, `resolved_at=now()` |
| `get_alias_map()` | `dict[alias_id → canonical_id]` pour tous les liens acceptés |

Migration : ajout de la table dans `Database.create()` via `executescript` + migration `ALTER TABLE` en no-op si déjà présente.

---

### 2.2 MemoryService — Résolution d'alias au runtime

`MemoryService` maintient un cache en mémoire :

```python
self._alias_cache: dict[str, str] = {}  # alias_id → canonical_id
```

**Chargement :** `await memory.load_aliases(db)` appelé dans `main.py` après `Database.create()`.

**Résolution :**

```python
def _user_id(self, platform: str, user_id: str) -> str:
    raw = f"{platform}:{user_id}"
    return self._alias_cache.get(raw, raw)
```

Toutes les méthodes existantes (`add`, `search`, `get_all`) passent par `_user_id` → transparence totale.

**Mise à jour du cache :** la route `/api/admin/links/{id}/accept` met à jour `_alias_cache` en mémoire après acceptation, sans redémarrage.

---

### 2.3 Module `bot/core/account_linker.py`

Responsabilité unique : calcul des scores de similarité et persistance des propositions.

#### Normalisation des pseudos

```python
def _normalize(name: str) -> str:
    name = name.lower()
    name = re.sub(r'_?ttv$', '', name)   # strip _TTV / TTV
    name = re.sub(r'[_\-\.]', '', name)  # strip séparateurs
    name = re.sub(r'\d+$', '', name)     # strip chiffres finaux
    return name.strip()
```

#### Scoring

Jaro-Winkler via `jellyfish` (pure Python, légère). Seuil configurable `link_min_confidence` dans `config.yaml` (défaut : `0.75`).

#### Points d'entrée

```python
async def analyze_all(db: Database) -> int:
    """Compare tous les comptes Discord vs tous les Twitch dans memory_users.
    Insère les propositions dont le score >= link_min_confidence.
    Retourne le nombre de propositions créées/mises à jour."""

async def analyze_new_user(db: Database, new_user_id: str) -> None:
    """Compare un seul nouvel arrivant contre tous les comptes de l'autre plateforme.
    Appelé en fire-and-forget depuis upsert_memory_user."""
```

`analyze_new_user` est appelé dans `MemoryService.add()` après `db.upsert_memory_user()` via `self._fire(...)`.

#### Dépendance

`jellyfish` ajouté à `requirements.txt`.

---

### 2.4 Routes dashboard — `/api/admin/links`

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/api/admin/links` | Liste des propositions. Paramètre optionnel `?status=pending\|accepted\|rejected` |
| `POST` | `/api/admin/links/analyze` | Déclenche `analyze_all` en tâche background. Réponse immédiate `{"status": "started"}` |
| `POST` | `/api/admin/links/{id}/accept` | Merge mémoires + update cache + `accept_link()` |
| `POST` | `/api/admin/links/{id}/reject` | `reject_link()` |

**Séquence d'acceptation (`accept`) :**

1. `mem0.get_all(alias_id)` → liste des mémoires
2. Pour chaque mémoire : `mem0.add(memory_text, user_id=canonical_id)`
3. `mem0.delete_all(alias_id)`
4. `db.execute("DELETE FROM memory_users WHERE user_id=?", alias_id)`
5. `db.accept_link(id)`
6. `memory._alias_cache[alias_id] = canonical_id`

Erreurs mem0 : loggées, non bloquantes. Le lien est accepté même si la copie mémoire échoue partiellement (les nouvelles interactions iront vers canonical_id dès l'étape 6).

Fichier : `bot/dashboard/routes/links.py` — router inclus dans `app.py` sous `/api/admin`.

---

### 2.5 Config — Nouveau champ

```yaml
bot:
  link_min_confidence: 0.75  # seuil Jaro-Winkler pour les propositions de liaison
```

Champ `link_min_confidence: float = 0.75` ajouté au dataclass `BotConfig` dans `config.py`.

---

### 2.6 Dashboard UI — Section "Liaisons de comptes"

Ajoutée dans la page admin, après la section mémoire.

**Structure :**

- Header : titre + bouton "⟳ ANALYSER" (déclenche `POST /analyze`, désactivé pendant l'analyse)
- Onglets : EN ATTENTE / ACCEPTÉS / REJETÉS (avec badge de count)
- Liste de cartes, une par proposition :
  - Côté Discord : label plateforme + username + user_id
  - Flèche centrale ⟷
  - Côté Twitch : label plateforme + username + user_id + lien cliquable `twitch.tv/username` (icône Twitch, ouvre dans nouvel onglet)
  - Score de confiance : pourcentage + barre de progression colorée (vert ≥90%, jaune 75–89%, orange <75%)
  - Boutons : ✓ FUSIONNER (jaune) / ✕ REJETER (rouge)
- Style : dark neobrutalism strict, conforme au cahier des charges existant

**Comportement après action :**
- Accepter : toast "Comptes fusionnés", carte déplacée vers onglet ACCEPTÉS
- Rejeter : toast "Proposition rejetée", carte déplacée vers onglet REJETÉS
- Analyser : badge "ANALYSE EN COURS..." pendant la durée, toast "X proposition(s) trouvée(s)" à la fin

---

### 2.7 Fichiers créés / modifiés

| Fichier | Type | Description |
|---|---|---|
| `bot/core/emotion.py` | modifié | SUPPRESSION_RULES renforcées, COMPETITION_K, `_apply_competition()` |
| `bot/db/database.py` | modifié | Table `user_links`, 4 nouvelles méthodes, migration |
| `bot/core/memory.py` | modifié | `_alias_cache`, `load_aliases()`, `_user_id()` résolution |
| `bot/core/account_linker.py` | créé | Analyse similarité Jaro-Winkler, `analyze_all`, `analyze_new_user` |
| `bot/config.py` | modifié | Champ `link_min_confidence` dans `BotConfig` |
| `bot/dashboard/routes/links.py` | créé | 4 routes admin |
| `bot/dashboard/app.py` | modifié | Include router links |
| `bot/dashboard/static/app.js` | modifié | Section UI liaisons de comptes |
| `bot/dashboard/static/index.html` | modifié | Onglet/section liaisons dans l'admin |
| `requirements.txt` | modifié | Ajout `jellyfish` |

---

### 2.8 Tests

- `tests/test_emotion_coherence.py` : vérifier que anger=0.65 + joy=0.33 convergent après N ticks de decay
- `tests/test_account_linker.py` : normalisation + scoring Jaro-Winkler + seuil
- `tests/test_dashboard_links.py` : routes GET/POST (mock DB + mock mem0)
- `tests/test_memory_alias.py` : `_user_id()` retourne canonical_id quand alias présent
