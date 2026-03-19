# Opinions évolutives

**Date :** 2026-03-19
**Scope :** `bot/db/database.py`, `bot/core/journal.py`, `bot/discord/handlers.py`, `bot/twitch/handlers.py`, `bot/persona/SOUL.md`

---

## Problème

Wally n'a pas d'opinions sur les sujets récurrents de la communauté. Il traite chaque conversation comme si c'était la première fois qu'il entendait parler de Valorant ou du chat d'Alice. Un membre de communauté forme des avis avec le temps — Wally devrait aussi.

---

## Solution : Opinions formées par le journal quotidien

### Table `opinions`

```sql
CREATE TABLE IF NOT EXISTS opinions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL UNIQUE,
    opinion TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
```

`topic` est UNIQUE — un sujet = une opinion, mise à jour si le sujet revient.

### `bot/db/database.py` — Nouvelles méthodes

```python
async def upsert_opinion(self, topic: str, opinion: str) -> None:
```
INSERT OR REPLACE — met à jour `opinion` et `updated_at` si le topic existe déjà.

```python
async def get_opinions(self, limit: int = 10) -> list[dict]:
```
Retourne les `limit` opinions les plus récemment mises à jour. Chaque dict : `{"topic": str, "opinion": str}`.

```python
async def cleanup_opinions(self, max_age_days: int = 30, max_count: int = 10) -> None:
```
1. Supprimer les opinions avec `updated_at` > 30 jours
2. Si le total dépasse `max_count`, garder les 10 plus récentes

### `bot/core/journal.py` — Formation des opinions

Après la génération du journal quotidien (après l'envoi dans le canal), un appel LLM secondaire analyse les conversations du jour pour former des opinions.

**Prompt :**

```
Tu es Wally. Voici le résumé des conversations d'aujourd'hui.
Identifie les sujets qui reviennent régulièrement ou qui ont provoqué
des réactions fortes. Pour chaque sujet (max 3), formule une opinion
courte que Wally pourrait avoir, cohérente avec sa personnalité
(aigri, sarcastique, mais avec des avis tranchés et parfois
surprenants).

Retourne un JSON valide uniquement :
[{"topic": "nom du sujet", "opinion": "opinion courte de Wally"}]

Si aucun sujet ne mérite une opinion, retourne [].
```

Le user message contient le résumé des conversations (le même qui a servi au journal).

**Parsing :** JSON → liste de `{topic, opinion}` → `db.upsert_opinion()` pour chacun → `db.cleanup_opinions()`.

**Timing :** cet appel se fait APRÈS le journal, de façon fire-and-forget. Si ça échoue, on log un warning et on continue — les opinions ne sont pas critiques.

### Injection dans le prompt

Dans `_respond()` (Discord) et `handle_message()` (Twitch), après le mem_context (après les jokes), récupérer les opinions :

```python
opinions = await bot.db.get_opinions(limit=10)
if opinions:
    opinions_block = "\n--- Tes opinions sur les sujets de la communauté ---"
    for o in opinions:
        opinions_block += f'\n- {o["topic"]} : "{o["opinion"]}"'
    mem_context = (mem_context + opinions_block) if mem_context else opinions_block.strip()
```

### Directive SOUL.md

```
Tu as des opinions sur les sujets qui reviennent souvent dans la
communauté (dans "Tes opinions sur les sujets de la communauté").
Ce sont TES avis — assume-les, défends-les, réfère-toi y quand
le sujet revient. Tes opinions évoluent avec le temps. Ne les
récite pas — intègre-les naturellement dans tes réponses.
```

---

## Tests

- `test_upsert_opinion_creates` — insère une opinion, vérifie qu'elle est en DB
- `test_upsert_opinion_updates_existing` — insère puis met à jour la même topic → opinion modifiée
- `test_get_opinions_returns_latest` — insère 12 opinions, get(limit=10) retourne 10
- `test_cleanup_removes_old` — opinion > 30 jours → supprimée
- `test_cleanup_keeps_max_count` — 15 opinions récentes → 10 gardées
- `test_get_opinions_empty` — pas d'opinions → liste vide

---

## Fichiers

| Fichier | Changement |
|---------|-----------|
| `bot/db/database.py` | Table `opinions`, `upsert_opinion()`, `get_opinions()`, `cleanup_opinions()` |
| `bot/core/journal.py` | Appel LLM post-journal pour former opinions |
| `bot/discord/handlers.py` | Injecter opinions dans prompt |
| `bot/twitch/handlers.py` | Idem |
| `bot/persona/SOUL.md` | Directive opinions |
| Tests | DB methods + cleanup |
