# Twitch Visit Awareness — Design Spec

**Date:** 2026-03-29
**Status:** Approved

## Objectif

Wally doit être conscient de ses visites sur les chaînes Twitch invitées. Chaque visite est
enregistrée, résumée en langage naturel, puis injectée dans le journal quotidien sous forme
d'un "petit voyage" — style carnet de bord, à la première personne.

---

## Base de données

Nouvelle table `twitch_visits` dans SQLite, créée via migration automatique dans
`Database._migrate()` :

```sql
CREATE TABLE IF NOT EXISTS twitch_visits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    channel     TEXT    NOT NULL,
    joined_at   REAL    NOT NULL,
    left_at     REAL,
    duration_s  INTEGER,
    msg_count   INTEGER DEFAULT 0,
    summary     TEXT
);
```

Trois nouvelles méthodes dans `bot/db/database.py` :

- `start_twitch_visit(channel: str) → int` — insère la ligne avec `joined_at=now()`, retourne l'id
- `end_twitch_visit(visit_id: int, left_at: float, msg_count: int, summary: str)` — complète la ligne
- `get_twitch_visits_for_date(date_str: str) → list[dict]` — retourne les visites dont `joined_at`
  tombe dans la journée (Europe/Paris), pour le journal

---

## Capture de la visite

### `WallyTwitch` (`bot/twitch/bot.py`)

Nouvel attribut : `_active_visits: dict[str, dict]` — map `channel_name → {visit_id, msg_count, joined_at}`.

**`add_guest_channel(name)`** — après le join IRC réussi :
```python
joined_at = time.time()
visit_id = await self.db.start_twitch_visit(name)
self._active_visits[name] = {"visit_id": visit_id, "msg_count": 0, "joined_at": joined_at}
```

**`remove_guest_channel(name)`** — avant la suppression de config :
```python
info = self._active_visits.pop(name, None)
if info:
    self._fire(self._finalize_visit(name, info["visit_id"], info["joined_at"], info["msg_count"]))
```

**`_finalize_visit(channel, visit_id, joined_at, msg_count)`** — méthode async fire-and-forget :
1. `left_at = time.time()` ; `duration_s = int(left_at - joined_at)`
2. Récupère les messages du canal depuis la fenêtre contextuelle mémoire :
   `self.memory.get_context(f"twitch:{channel}")`
3. Appelle `llm_secondary.complete()` avec le prompt `twitch_visit_summary.md` et les messages
4. Appelle `db.end_twitch_visit(visit_id, left_at, msg_count, summary)`

### Comptage des messages (`bot/twitch/bot.py`)

`_active_visits` stocke `dict[str, dict]` avec `{"visit_id": int, "msg_count": int, "joined_at": float}`.
Dans `handle_message()`, pour les canaux invités (`channel_name != bot.config.twitch.channel`),
incrémenter `bot._active_visits[channel_name]["msg_count"]` à chaque message reçu.

---

## Prompt de résumé (`bot/persona/prompts/twitch_visit_summary.md`)

Prompt système court : demande au LLM de rédiger 3-5 lignes à la première personne, style
"carnet de voyage". Doit mentionner : le nom du streamer, la durée, l'ambiance générale,
les moments notables (subs, raids, messages marquants). Ton cohérent avec la personnalité de Wally.

---

## Intégration dans le journal

Dans `DailyJournal.generate_and_send()` (`bot/core/journal.py`), nouveau bloc `twitch_visits_block`
ajouté après `gallery_block` :

```python
twitch_visits_block = ""
if self._db is not None:
    try:
        visits = await self._db.get_twitch_visits_for_date(effective_date.isoformat())
        if visits:
            lines = [f"**Visites Twitch du jour** : {len(visits)} chaîne(s)"]
            for v in visits:
                dur = f"{v['duration_s'] // 60} min" if v.get('duration_s') else "durée inconnue"
                lines.append(f"- {v['channel']} ({dur}) : {v.get('summary') or '...'}")
            twitch_visits_block = "\n".join(lines)
    except Exception as exc:
        logger.warning("Failed to get twitch visits for journal: {e}", e=exc)
```

Ce bloc est ajouté aux `sections` du prompt utilisateur. Le LLM du journal reçoit les résumés
déjà rédigés et peut les tisser naturellement dans l'entrée de journal.

---

## Fichiers à modifier / créer

| Fichier | Action |
|---|---|
| `bot/db/database.py` | Nouvelle table, 3 nouvelles méthodes |
| `bot/twitch/bot.py` | `_active_visits`, `add_guest_channel`, `remove_guest_channel`, `_finalize_visit` |
| `bot/core/journal.py` | Nouveau bloc `twitch_visits_block` |
| `bot/persona/prompts/twitch_visit_summary.md` | Nouveau prompt |

---

## Cas limites

- **Wally redémarre pendant une visite** : `left_at` reste NULL, `summary` NULL. Le journal
  affiche "durée inconnue" et pas de résumé. Acceptable.
- **Chaîne déjà dans `guest_channels` au démarrage** : `event_ready` rejoint les canaux IRC
  mais ne démarre pas de visite (pas d'`add_guest_channel`). Ces visites persistantes ne sont
  pas tracées — seules les visites déclenchées par l'ActionService le sont.
- **Appel LLM `_finalize_visit` qui échoue** : `end_twitch_visit` est quand même appelé avec
  `summary=None` — la visite est enregistrée sans résumé, le journal affiche `...`.
- **Visites très courtes (< 1 min)** : enregistrées normalement, le résumé peut juste dire
  "passage éclair".
