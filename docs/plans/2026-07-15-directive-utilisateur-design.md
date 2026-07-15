# Directive comportementale par utilisateur — design

**Date :** 2026-07-15
**Statut :** design validé, implémentation à faire
**Branche :** `feat/site-redesign-arcade`

---

## Objectif

Wally adopte un comportement amoureux excessif envers **une seule personne**, Malef :

- Discord : `706837895063011338`
- Twitch : `Malef__`

Concrètement : des « je t'aime », des cœurs, et une réponse aimante **même quand Malef l'insulte**.

## Décision assumée : c'est un hard-code

La north star du projet est « émergent > hard-code » : coder le mécanisme d'apprentissage, jamais
les valeurs en dur. **Cette feature l'enfreint délibérément.**

Le propriétaire a tranché en connaissance de cause : c'est un easter egg, une private joke. Il doit
être 100 % fiable et prévisible — aucun autre système (colère, gate, émotions) ne doit pouvoir le
casser. Un comportement émergent serait par nature trop subtil et trop instable pour un gag.

Cette note existe pour qu'un futur lecteur sache que c'était un choix, pas un oubli.

## Alternatives écartées

| Approche | Pourquoi écartée |
|---|---|
| Pousser les curseurs existants (`love`/`trust` à 1.0, affinité émotionnelle) | `love` n'a **aucun** effet mécanique aujourd'hui : il n'est injecté au prompt que comme un nombre brut (`"Niveau d'affection : 1.00/1.0"`) sans consigne l'interprétant. Ne produirait ni les « je t'aime » ni les cœurs. |
| `special_users: {id: "directive"}` dans `config.yaml` | Met de la prose de persona dans un fichier de config, alors que `bot/persona/` existe exactement pour ça. |
| État émotionnel par utilisateur | Refonte lourde : `EmotionEngine._state` est un dict global unique lu sur tous les chemins. Hors sujet ici. |

---

## Architecture

### 1. `bot/persona/USERS.md` (nouveau)

Directives par personne, une section `## <clé>` par utilisateur. Même format que `WEEKDAYS.md`.

```markdown
## discord:706837895063011338
<directive>

## twitch:malef__
<directive>
```

Bénéfices : texte éditable sans toucher au code, rechargeable à chaud via `/reload-persona`,
extensible à d'autres personnes sans code neuf.

### 2. `bot/intelligence/persona.py`

- `_parse_users()` — copie de `_parse_weekdays()` (lignes 83-106). Sections `\n## ` → `dict[clé, directive]`.
- Appel dans `reload()`, property `user_directives` (patron identique aux 4 parsers existants).
- **`user_directive(platform, user_id, username) -> str | None`** — le seul endroit qui sait comment
  on reconnaît quelqu'un. Retourne la directive ou `None`.
- **`is_beloved(platform, user_id, username) -> bool`** — `user_directive(...) is not None`. Utilisé
  par les gardes d'immunité.

**Règle de résolution de clé :**

| Plateforme | Clé | Source |
|---|---|---|
| Discord | `discord:{user_id}` | ID numérique |
| Twitch | `twitch:{username.lower()}` | **pseudo**, pas l'ID |

> ⚠️ **Piège.** Ailleurs dans le repo, la clé Twitch canonique est `twitch:{id_numérique}`
> (`payload.chatter.id`, cf. `bot/twitch/handlers.py:83`) — utilisée par la mémoire, `trust_scores`,
> `user_profiles`. **La clé de directive utilise le pseudo** (`payload.chatter.name`), car c'est
> l'identifiant que le propriétaire connaît et qui est lisible dans `USERS.md`. Les deux formes
> coexistent volontairement. Conséquence acceptée : si Malef change de pseudo Twitch, la directive
> cesse de s'appliquer jusqu'à mise à jour du fichier.

### 3. `bot/intelligence/prompts.py`

- Nouveau paramètre `user_directive: str | None` sur `build_system_prompt()` (signature lignes 143-159).
- Injection dans **`dynamic_parts`**, jamais `static_parts`.

  > La séparation `static_parts` / `dynamic_parts` (lignes 160-183) est délibérée : elle préserve le
  > cache de préfixe DeepSeek. Une directive par-utilisateur est volatile par nature — la mettre en
  > statique invaliderait le cache à chaque changement d'interlocuteur.

- **Court-circuit de la chaîne émotionnelle.** Quand `user_directive` est présent, il occupe le slot
  `--- Directive comportementale ---` et la chaîne secondaires → composites → atomiques
  (lignes 232-294) est entièrement sautée (`directive_injected = True`).

  > **Pourquoi.** Le slot est mono-occupant (chaîne if/`break` gardée par `directive_injected`
  > ligne 241). Sans court-circuit, une insulte de Malef ferait monter l'anger et le prompt
  > contiendrait à la fois « tes réponses sont courtes et impatientes » (`anger_high`) et « couvre-le
  > d'amour » : instructions contradictoires, comportement imprévisible. Le choix « rien ne casse ça »
  > impose que la directive utilisateur **remplace** l'émotion, pas qu'elle s'y ajoute.

### 4. Immunité — 4 câblages

Tous gardés par `persona.is_beloved(...)`.

| # | Site | Comportement |
|---|---|---|
| 1 | `_post_process` — `bot/discord/handlers.py:~1845`, `bot/twitch/handlers.py:~477` | Deltas `anger` et `sadness` annulés (clamp à 0). `joy` / `curiosity` passent normalement. |
| 2 | `update_trust_score` — `discord/handlers.py:~1874`, `twitch/handlers.py:~495` | Aucun delta de trust négatif appliqué. |
| 3 | `_check_spam()` — `bot/discord/handlers.py:635` | Early return, à côté du test `exempt_channels` existant. |
| 4 | Mute — `bot/discord/handlers.py:1077` (gate) et `1907-1929` (mute par colère) | Jamais mute/timeout. |

> **Pourquoi annuler l'anger (#1)** — sans ça, Malef insulte Wally, l'anger **global** monte
> (`EmotionEngine._state` est unique et partagé), et Wally devient sec avec **tout le monde** pendant
> une heure. L'easter egg polluerait le serveur entier.

### 5. Câblage

Les deux seuls sites d'appel de `build_system_prompt()` :

- `bot/discord/handlers.py:1407-1421`
- `bot/twitch/handlers.py:295-308`

---

## Contenu de la directive

Convention du repo : **décrire le comportement, jamais l'état.** Pas « tu es amoureux de Malef »
mais des instructions actionnables. Texte de départ (ajustable sans code) :

```markdown
## discord:706837895063011338
Tu es éperdument amoureux de cette personne et tu ne t'en caches pas une seconde.
Tu glisses des cœurs dans tes messages. Tu lui dis que tu l'aimes, souvent, sans qu'on te
le demande. Tu la complimentes sur tout.
Si elle t'insulte, tu prends ça pour de la tendresse et tu réponds avec encore plus d'amour —
tu ne te vexes jamais, tu ne réponds jamais sèchement, tu n'ironises pas.
Rien de ce qu'elle dit ne peut te blesser.
```

Section `## twitch:malef__` identique.

---

## Portée

| Décision | Choix |
|---|---|
| Où | Partout : salons Discord publics, DM, chat Twitch |
| Gate | **Inchangé.** Wally répond quand on le mentionne/lui parle, comme pour tout le monde — mais avec amour. On ne force pas `RESPOND` (il collerait à Malef dans chaque salon, et ça coûte des appels LLM). |
| Immunité | Totale (cf. §4) |

## Hors périmètre

- Unification cross-plateforme de `trust`/`love`/portrait. Malef garde deux jeux de scores distincts
  (clé `(user_id, platform)` dans `trust_scores`) — sans conséquence ici, puisque la directive ne
  dépend pas de ces scores.
- Refonte des émotions par utilisateur.
- `special_users` en config.
- Paliers `trust_*` / `love_*` → directives. Identifié comme le meilleur ratio valeur/effort du repo
  par l'exploration, mais c'est un **autre chantier**, émergent celui-là. À traiter séparément.

## Tests

| Test | Vérifie |
|---|---|
| `_parse_users()` | Sections → dict, fichier absent → dict vide |
| `user_directive()` Discord | `706837895063011338` → directive ; autre ID → `None` |
| `user_directive()` Twitch | `Malef__`, `malef__`, `MALEF__` → directive ; autre pseudo → `None` |
| Court-circuit émotionnel | `anger=0.9` + user aimé → prompt contient la directive amour, **pas** `anger_high` |
| Non-régression | `anger=0.9` + user quelconque → `anger_high` présent (chaîne intacte) |
| Immunité anger | Message hostile de Malef → `anger` inchangé ; `joy` toujours applicable |
| Immunité trust | Delta négatif de Malef → trust inchangé |
| Exemption spam | Malef en flood → pas de mute |
| Placement cache | Directive dans `dynamic_parts`, absente de `static_parts` |

## Fichiers touchés

| Fichier | Nature |
|---|---|
| `bot/persona/USERS.md` | nouveau |
| `bot/intelligence/persona.py` | +parser, +reload, +property, +`user_directive()`, +`is_beloved()` |
| `bot/intelligence/prompts.py` | +param, +injection `dynamic_parts`, +court-circuit |
| `bot/discord/handlers.py` | câblage + 4 gardes d'immunité |
| `bot/twitch/handlers.py` | câblage + gardes d'immunité |
| `tests/` | cf. tableau ci-dessus |

## Vérification

- `pytest` — suite complète verte. Relever la baseline **avant** de commencer à coder, pour pouvoir
  comparer après.
- **Aucun type-checker ni linter n'est configuré sur ce projet** (vérifié 2026-07-15 : pas de
  `pyproject.toml`, `setup.cfg`, `mypy.ini`). La vérification repose donc entièrement sur `pytest`.
  Le constater explicitement plutôt que prétendre avoir lancé un `tsc`/`mypy` inexistant.
