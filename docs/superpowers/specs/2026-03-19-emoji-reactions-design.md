# Réactions emoji contextuelles

**Date :** 2026-03-19
**Scope :** `bot/discord/handlers.py`, `bot/persona/SOUL.md`, `bot/config.py`, `config.yaml`

---

## Problème

Wally ne réagit qu'avec du texte. Un humain dans un chat Discord réagit souvent avec un simple emoji sans rien dire — un 😂 sur un truc drôle, un 🔥 sur un beau play. Cette absence rend Wally moins "présent" dans le chat.

---

## Solution : Deux mécanismes de réaction emoji

### 1. Réaction passive (messages non-trigger)

Dans `handle_message`, quand Wally n'est **pas** mentionné, il a une probabilité faible (configurable, défaut 5%) de réagir avec un emoji basé sur des règles simples.

**Règles de détection :**

| Signal dans le message | Emoji candidats |
|------------------------|----------------|
| Mots rire : `mdr`, `lol`, `ptdr`, `xd`, `haha`, `😂`, `🤣` | 😂, 💀 |
| Mots positifs : `gg`, `bravo`, `trop bien`, `bien joué`, `incroyable` | 🔥, 👏 |
| Mots négatifs/jurons : `merde`, `putain`, `nul`, `chier` | 😤, 💀 |
| Question + émotion curiosity ≥ 0.4 : message contient `?` | 🤔 |

**Logique :**
1. Message non-trigger, canal autorisé, auteur pas un bot
2. Scanner le message pour les signaux ci-dessus
3. Si un signal matche → `random.random() < emoji_reaction_probability`
4. Si oui → choisir un emoji random parmi les candidats, `message.add_reaction(emoji)`
5. Un seul emoji par message, première catégorie qui matche gagne
6. Si aucun signal → skip silencieusement

**Pas d'appel LLM.** C'est du keyword matching + random.

### 2. Réaction complémentaire (quand Wally répond)

Quand Wally répond texte à un trigger, le LLM peut optionnellement suggérer une réaction emoji.

**Instruction dans SOUL.md :**

```
Si le message auquel tu réponds mérite une réaction emoji en plus
de ta réponse, commence ta réponse par [react:emoji] (un seul emoji).
Utilise-le quand c'est naturel — un truc drôle, un truc impressionnant,
une connerie monumentale. Ne le mets pas systématiquement, seulement
quand ça ajoute quelque chose. Si tu n'as pas de réaction, commence
directement ta réponse sans tag.
```

**Parsing dans `_respond` :**
- Regex sur la réponse du LLM : `^\[react:(.+?)\]\s*`
- Si match → extraire l'emoji, retirer le tag du texte, `message.add_reaction(emoji)` avant d'envoyer le texte
- Si pas de match → comportement normal (texte seul)
- Discord uniquement — sur Twitch, le tag est juste strippé sans réaction

### Config

Nouveau champ dans `DiscordConfig` :

```python
emoji_reaction_probability: float = 0.05
```

Ajouté dans `config.yaml` sous `discord:`.

---

## Fichiers modifiés

| Fichier | Changement |
|---------|-----------|
| `bot/persona/SOUL.md` | Instruction `[react:emoji]` pour réaction complémentaire |
| `bot/discord/handlers.py` | Réaction passive dans `handle_message`, parsing `[react:]` dans `_respond` |
| `bot/twitch/handlers.py` | Stripping du tag `[react:]` dans la réponse (pas de réaction Twitch) |
| `bot/config.py` | `emoji_reaction_probability: float = 0.05` dans `DiscordConfig` |
| `config.yaml` | `emoji_reaction_probability: 0.05` sous `discord:` |
| Tests | Parsing react tag, règles passives, probabilité |

---

## Tests

### Tests parsing react tag

- `test_parse_react_tag_extracts_emoji` — `"[react:😂] c'est drôle"` → emoji=`😂`, texte=`"c'est drôle"`
- `test_parse_react_tag_no_tag` — `"texte normal"` → emoji=`None`, texte=`"texte normal"`
- `test_parse_react_tag_strips_whitespace` — `"[react:🔥]  texte"` → emoji=`🔥`, texte=`"texte"`

### Tests réaction passive

- `test_passive_reaction_matches_laugh_keywords` — message avec "mdr" → retourne un emoji candidat parmi 😂, 💀
- `test_passive_reaction_no_signal_returns_none` — message sans signal → retourne None
- `test_passive_reaction_respects_probability` — avec probability=0.0 → jamais de réaction

### Tests existants

Aucune régression — les changements dans `handle_message` sont dans le path non-trigger (early return), et le parsing react tag est additif dans `_respond`.
