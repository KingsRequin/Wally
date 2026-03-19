# Émotions composites

**Date :** 2026-03-19
**Scope :** `bot/persona/COMPOSITES.md`, `bot/core/persona.py`, `bot/core/prompts.py`, 4 callers

---

## Problème

Quand deux émotions sont dominantes simultanément, le système injecte deux directives atomiques indépendantes (ex: `joy_high` + `curiosity_mid`). Le LLM doit les "superposer" lui-même, ce qui donne des résultats incohérents. Un état composite comme "enthousiaste" (joy+curiosity) a une qualité distincte qui n'est pas la somme de "joyeux" + "curieux".

---

## Solution : Directives composites conditionnelles

### Principe

Quand les 2 émotions dominantes sont **toutes les deux ≥ 0.4** (palier mid ou plus) et forment une paire composite connue, une directive composite unique **remplace** les deux directives atomiques. Sinon, le système tiered actuel s'applique normalement.

### Clés composites

Les clés sont construites en triant les deux noms d'émotion par ordre alphabétique, séparés par `_`. Cela évite les doublons (`joy_curiosity` et `curiosity_joy` → toujours `curiosity_joy`).

### 5 paires définies

| Clé | État | Description |
|-----|------|-------------|
| `curiosity_joy` | enthousiaste | surexcité par un sujet, gamin passionné |
| `boredom_sadness` | déprimé | vide, désabusé, "à quoi bon" |
| `anger_sadness` | amer | rancunier, déçu-énervé, pessimiste agressif |
| `anger_curiosity` | provocateur | cherche la faille, débat agressif, "prouve-le" |
| `boredom_joy` | sarcastique-nonchalant | blasé mais amusé, humour pince-sans-rire |

### `bot/persona/COMPOSITES.md`

Nouveau fichier avec 5 sections `## clé_composite`. Format identique à EMOTIONS.md : préambule + sections `##`.

### `bot/core/persona.py`

Ajouter `_parse_composites()` — utilise le pattern `_parse_weekdays()` (avec `("\n" + content).split("\n## ")` pour gérer les fichiers commençant directement par `##`). Property `composite_directives` exposée.

Dans `reload()`, ajouter après `self._weekday_directives = self._parse_weekdays()` :
```python
self._composite_directives = self._parse_composites()
```

Note : un dict vide `{}` (fichier absent) et `None` (param non passé) ont le même effet — aucune composite n'est injectée, fallback atomique.

### `bot/core/prompts.py`

Modifier `build_system_prompt` :

1. Nouveau paramètre : `composite_directives: dict[str, str] | None = None`
2. Après avoir déterminé les 2 émotions dominantes (top 2 ≥ 0.2), avant d'injecter les directives :
   - Si les 2 sont ≥ 0.4 et `composite_directives` est fourni :
     - Construire la clé : `"_".join(sorted([emotion1, emotion2]))`
     - Si la clé existe dans `composite_directives` → injecter cette directive seule
     - Sinon → fallback : injecter les 2 directives atomiques tiered normalement
   - Si une des deux est < 0.4 → directives atomiques normalement
   - Si `len(dominant) < 2` (une seule émotion dominante) → skip composite, atomique directement

Le bloc `--- Directive comportementale ---` est toujours utilisé, que ce soit pour une composite ou des atomiques.

### Callers

Les 4 sites d'appel de `build_system_prompt` doivent passer `composite_directives=bot.persona.composite_directives` :

- `bot/discord/handlers.py` — `_respond()`
- `bot/discord/commands/ask.py` — `ask()`
- `bot/twitch/handlers.py` — `handle_message()`
- `bot/twitch/events.py` — `_generate_and_send()`

---

## Tests

### Tests persona parsing

- `test_parse_composites_returns_5_keys` — vérifie que les 5 paires sont parsées
- `test_parse_composites_missing_file_returns_empty` — fichier absent → dict vide
- `test_composite_directives_property` — la property expose le dict

### Tests logique composite dans prompts

- `test_composite_replaces_atomics_when_both_mid` — joy=0.5, curiosity=0.6 → directive composite `curiosity_joy` injectée, pas les atomiques
- `test_composite_not_triggered_when_one_below_mid` — joy=0.5, curiosity=0.3 → atomiques normales (curiosity < 0.4)
- `test_composite_not_triggered_when_pair_unknown` — joy=0.5, sadness=0.5 (paire `joy_sadness` non définie) → atomiques normales
- `test_composite_fallback_when_no_dict` — `composite_directives=None` → atomiques normales
- `test_composite_key_is_alphabetically_sorted` — vérifie que la clé est construite en triant alphabétiquement (test unitaire de la construction de clé)
- `test_composite_not_triggered_when_only_one_dominant` — seule joy=0.5 au-dessus de 0.2 → pas de composite, atomique seule

### Tests existants

Aucune régression — le nouveau paramètre est optionnel avec défaut `None`.

---

## Résumé des fichiers

| Fichier | Changement |
|---------|-----------|
| `bot/persona/COMPOSITES.md` | Nouveau — 5 directives composites |
| `bot/core/persona.py` | `_parse_composites()`, property `composite_directives`, appel dans `reload()` |
| `bot/core/prompts.py` | Nouveau param `composite_directives`, logique composite avant fallback atomique |
| `bot/discord/handlers.py` | Passer `composite_directives` |
| `bot/discord/commands/ask.py` | Passer `composite_directives` |
| `bot/twitch/handlers.py` | Passer `composite_directives` |
| `bot/twitch/events.py` | Passer `composite_directives` |
| Tests | Parsing + logique composite + fallback |
