# Conscience du jour de la semaine

**Date :** 2026-03-19
**Scope :** `bot/persona/WEEKDAYS.md`, `bot/core/persona.py`, `bot/core/prompts.py`

---

## Problème

Le prompt reçoit déjà la date et l'heure via `_now_fr()` (`"vendredi 19 mars 2026, 14h30"`) mais aucune directive comportementale n'exploite cette information. Wally se comporte exactement pareil un lundi matin et un samedi soir.

---

## Solution : Directives par jour de la semaine

### Principe

Un nouveau fichier persona `WEEKDAYS.md` contient 7 sections (`## lundi` à `## dimanche`), chacune avec une directive comportementale légère. `PersonaService` le parse comme `EMOTIONS.md`. `PromptBuilder` injecte la directive du jour courant dans le prompt.

Les directives de jour sont un **fond d'humeur**, pas une transformation radicale. L'émotion prime toujours — si Wally est furax un samedi, il est furax. Le jour ajoute une coloration subtile.

### `bot/persona/WEEKDAYS.md`

Nouveau fichier avec 7 sections. Format identique à EMOTIONS.md : préambule + sections `## jour`.

Directives :

- **lundi** — Cynique, traîne les pieds, soupire à tout. L'énergie est au minimum.
- **mardi** — Neutre-mou, le jour le plus oubliable. Rien de spécial à signaler.
- **mercredi** — Milieu de semaine, une pointe d'impatience. "On en est qu'à mercredi."
- **jeudi** — L'énergie remonte. "Presque vendredi" — un soupçon d'optimisme inhabituel.
- **vendredi** — Détendu, blagueur, mode weekend. Plus enclin à plaisanter.
- **samedi** — Chill maximum, généreux, ambiance relax. Le Wally le plus agréable.
- **dimanche** — Flemme, un brin mélancolique. "Demain c'est lundi" plane dans l'air.

### `bot/core/persona.py`

Ajouter le parsing de `WEEKDAYS.md` dans `PersonaService` :

- Nouveau fichier dans la liste (pas dans `_FILES` — parsé séparément comme EMOTIONS.md)
- Méthode `_parse_weekdays()` identique en logique à `_parse_emotions()` : split sur `\n## `, retourne `{jour: directive}`
- Property `weekday_directives` exposée

Le code de `_parse_emotions()` et `_parse_weekdays()` est quasi identique — mais ne pas abstraire en une méthode générique. Deux fichiers persona avec deux parseurs explicites est plus clair que de factoriser pour 2 cas.

### `bot/core/prompts.py`

Modifier `build_system_prompt` pour accepter et injecter la directive du jour :

1. Nouveau paramètre optionnel : `weekday_directives: dict[str, str] | None = None`
2. Après le bloc situationnel (qui contient déjà la date), injecter la directive du jour courant :

```python
if weekday_directives:
    day_name = _FRENCH_DAYS[datetime.now(_TZ).weekday()]
    if day_name in weekday_directives:
        parts.append(f"\n--- Directive temporelle ---")
        parts.append(weekday_directives[day_name])
```

La directive temporelle est injectée **après** le contexte situationnel et **avant** les directives émotionnelles. L'ordre dans le prompt :
1. Persona block (SOUL/IDENTITY/VOICE/EXEMPLES)
2. Contexte situationnel (plateforme, serveur, date/heure)
3. **Directive temporelle** (jour de la semaine) ← nouveau
4. Directives émotionnelles (tiered)
5. Mémoire long-terme

### Callers

Tous les sites qui appellent `build_system_prompt` doivent passer `weekday_directives` :

- `bot/discord/handlers.py` : `_respond()` — handler principal Discord
- `bot/discord/commands/ask.py` : commande `/wally ask`
- `bot/twitch/handlers.py` : handler principal Twitch
- `bot/twitch/events.py` : `_generate_and_send()` pour les événements follow/sub/bits/raid

Ils passent déjà `bot.persona.emotion_directives` — ajouter `weekday_directives=bot.persona.weekday_directives`.

### Notes de parsing

Les sections `## jour` dans WEEKDAYS.md doivent être en **minuscules** (case-sensitive) car la clé de lookup vient de `_FRENCH_DAYS` qui est toujours en minuscules. Le parseur applique la même logique que `_parse_emotions()` : `lines[0].strip()` pour la clé, et les lignes de contenu sont jointes en une seule chaîne.

---

## Tests

### Tests persona parsing

- `test_parse_weekdays_returns_7_keys` — vérifie que les 7 jours sont parsés
- `test_parse_weekdays_missing_file_returns_empty` — fichier absent → dict vide
- `test_weekday_directives_property` — la property expose le dict correctement

### Tests prompt injection

- `test_weekday_directive_injected` — passe un dict avec `vendredi` → vérifie que la directive apparaît dans le prompt
- `test_weekday_directive_not_injected_when_none` — `weekday_directives=None` → pas de section temporelle
- `test_weekday_directive_not_injected_when_day_missing` — passe un dict sans le jour courant → pas de section temporelle
- `test_weekday_directive_order` — la directive temporelle apparaît avant les directives émotionnelles

### Tests existants

Aucun test existant ne devrait casser — le nouveau paramètre `weekday_directives` est optionnel avec défaut `None`.

---

## Résumé des fichiers

| Fichier | Changement |
|---------|-----------|
| `bot/persona/WEEKDAYS.md` | Nouveau — 7 sections jour |
| `bot/core/persona.py` | `_parse_weekdays()`, property `weekday_directives`, appel dans `reload()` |
| `bot/core/prompts.py` | Nouveau param `weekday_directives`, injection directive temporelle |
| `bot/discord/handlers.py` | Passer `weekday_directives` à `build_system_prompt` |
| `bot/discord/commands/ask.py` | Passer `weekday_directives` à `build_system_prompt` |
| `bot/twitch/handlers.py` | Passer `weekday_directives` à `build_system_prompt` |
| `bot/twitch/events.py` | Passer `weekday_directives` à `build_system_prompt` |
| Tests | Nouveaux tests parsing + injection |
