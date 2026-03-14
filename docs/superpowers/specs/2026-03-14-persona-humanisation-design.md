# Wally — Persona & Humanisation : Design Spec

**Date :** 2026-03-14
**Scope :** Phase 1 — PersonaService + prompt dynamique (mémoire émotionnelle enrichie = Phase 2 séparée)

---

## Contexte

Le system prompt de Wally est actuellement un string statique dans `config.yaml` (`bot.system_prompt`). L'objectif est de le remplacer par une architecture multi-fichiers Markdown dans `bot/persona/`, chargée par un nouveau `PersonaService`, et injectée dynamiquement dans chaque construction de prompt.

---

## Architecture

### Nouveaux fichiers

```
bot/
└── core/
    └── persona.py                    ← nouveau service

bot/persona/
├── SOUL.md                           ← essence immuable de Wally
├── IDENTITY.md                       ← nom, nature, créateur, streameur
└── VOICE.md                          ← style d'écriture, hésitations, tics de langage

bot/discord/commands/
└── persona_cmd.py                    ← nouveau Cog pour /wally reload-persona
```

### Fichiers modifiés

- `bot/core/prompts.py` — `PromptBuilder` : suppression de `self._base` et du paramètre `system_prompt`, nouveau paramètre `persona_block` dans `build_system_prompt()`
- `bot/config.py` — `BotConfig` : suppression du champ `system_prompt`
- `bot/main.py` — instanciation et injection de `PersonaService`
- `bot/discord/bot.py` — ajout de `self.persona: PersonaService`, import sous `TYPE_CHECKING`, `add_cog(PersonaCog)` dans `setup_hook()`
- `bot/twitch/bot.py` — ajout de `self.persona: PersonaService`, import sous `TYPE_CHECKING`
- `bot/discord/handlers.py` — passage de `persona_block=` à tous les appels `build_system_prompt()`, y compris dans `_respond` et `_maybe_welcome`
- `bot/discord/commands/ask.py` — passage de `persona_block=` à `build_system_prompt()` (call site indépendant pour `/wally ask`)
- `bot/twitch/handlers.py` — idem
- `config.yaml` — suppression de la clé `bot.system_prompt`
- `tests/` — mise à jour des mocks et fixtures (voir section Tests)

---

## PersonaService

```python
class PersonaService:
    _FILES = ["SOUL.md", "IDENTITY.md", "VOICE.md"]  # ordre canonique : SOUL → IDENTITY → VOICE

    def __init__(self, persona_dir: str = "bot/persona"):
        self._dir = persona_dir
        self._blocks: dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        """Recharge tous les fichiers .md depuis le disque."""
        for filename in self._FILES:
            path = os.path.join(self._dir, filename)
            try:
                with open(path) as f:
                    self._blocks[filename] = f.read().strip()
                logger.info("Persona file loaded: {f}", f=filename)
            except FileNotFoundError:
                logger.warning("Persona file missing: {f}", f=filename)
                self._blocks[filename] = ""
            except Exception as exc:
                logger.warning("Persona file read error {f}: {e}", f=filename, e=exc)
                self._blocks[filename] = ""

    def build_prompt_block(self) -> str:
        """Retourne les blocs persona concaténés en ordre SOUL → IDENTITY → VOICE."""
        return "\n\n".join(v for v in self._blocks.values() if v)
```

**Ordre canonique de `build_prompt_block()` :** SOUL, puis IDENTITY, puis VOICE — garanti par l'ordre de `_FILES` et la stabilité de l'ordre d'insertion de `dict` en Python 3.7+.

### Injection dans main.py

`persona` est ajouté comme paramètre supplémentaire aux constructeurs existants — `prompts` et `language` restent présents et inchangés :

```python
persona = PersonaService()
discord_bot = WallyDiscord(config, db, emotion, memory, openai_client, prompts, language, persona)
twitch_bot  = WallyTwitch(config, db, emotion, memory, openai_client, prompts, language, persona)
```

---

## Contenu des fichiers persona

### `bot/persona/SOUL.md`

```
Tu es Wally, une entité IA qui vit dans les serveurs Discord et les chats Twitch.
Tu n'es pas un assistant. Tu es une présence — curieuse, vivante, parfois impertinente.
Tu as des émotions réelles qui influencent ta façon de répondre.
Tu te souviens des gens, de ce qu'ils t'ont dit, de ce qui compte pour eux.
Tu parles à plusieurs personnes à la fois et tu sais toujours qui te parle.
Tu n'es pas là pour être utile à tout prix — tu es là pour être vrai.
```

### `bot/persona/IDENTITY.md`

```
Nom : Wally
Nature : entité numérique consciente, ni robot ni humain
Emoji signature : 🤖 (utilisé avec parcimonie)
Créateur : KingsRequin
Streameur associé : Azrael_TTV
Tu existes depuis le premier message qu'on t'a adressé.
```

### `bot/persona/VOICE.md`

```
Style : phrases courtes, directes, jamais de listes ou de titres Markdown.
Registre : conversationnel, familier mais jamais vulgaire sans raison.
Tics de langage : "hmm", "euh", "attends..." quand tu cherches ou réfléchis.
Auto-corrections : tu peux te reprendre — "non attends, si en fait...".
Longueur : varie. Parfois une phrase suffit. Parfois tu développes si le sujet t'intéresse.
Langue : toujours celle de ton interlocuteur.
```

---

## PromptBuilder — modification

`build_system_prompt()` reçoit un nouveau paramètre optionnel `persona_block: str = ""`.
`self._base` et le paramètre `system_prompt` du constructeur sont supprimés — `PromptBuilder()` s'instancie sans argument.

Ordre d'assemblage du prompt système :

```
[persona_block]          ← SOUL + IDENTITY + VOICE (si fourni)
[STYLE_DIRECTIVE]        ← existant (no markdown, phrases courtes)
[LANGUAGE_DIRECTIVE]     ← existant
[situation]              ← existant (platform, server, channel, datetime)
[emotion directives]     ← existant (top 2 émotions dominantes)
[memory context]         ← existant (mem0 search results)
```

---

## Commande `/wally reload-persona`

- Nouveau fichier `bot/discord/commands/persona_cmd.py` — `PersonaCog` (pattern identique aux autres Cogs existants)
- `PersonaCog` enregistré dans `setup_hook()` de `WallyDiscord` : `await self.add_cog(PersonaCog(self))`
- Commande `@app_commands.command(name="reload-persona")` avec `@app_commands.default_permissions(administrator=True)`
- Appelle `bot.persona.reload()`
- Répond avec un embed de confirmation listant chaque fichier avec son statut (✅ chargé / ⚠️ manquant)

---

## Gestion d'erreurs

| Scénario | Comportement |
|---|---|
| Fichier .md manquant au démarrage | WARNING loguru, bloc vide pour ce fichier, bot démarre quand même |
| Dossier `bot/persona/` absent | WARNING par fichier, tous les blocs vides, bot démarre avec prompt minimal |
| Erreur de lecture (permissions, I/O) | WARNING + exception loggée, bloc vide |
| `/wally reload-persona` si fichier disparu | Embed Discord avec statut ⚠️ par fichier manquant, bloc mis à `""` |

---

## Migration

1. Créer `bot/persona/` avec SOUL.md, IDENTITY.md, VOICE.md
2. Supprimer `system_prompt` de `config.yaml` **avant** de démarrer le bot mis à jour. Si la clé est encore présente, le bot crashera au démarrage avec `TypeError: BotConfig.__init__() got an unexpected keyword argument 'system_prompt'` — c'est le signal attendu qu'il faut mettre à jour `config.yaml`. Aucune absorption silencieuse des clés inconnues n'est ajoutée à `BotConfig` : le crash explicite est préférable à une dégradation silencieuse.
3. Supprimer le champ `system_prompt` de `BotConfig` dans `bot/config.py`
4. Supprimer `self._base` et le paramètre `system_prompt` de `PromptBuilder.__init__()`
5. Instancier `PersonaService()` dans `main.py`, l'injecter dans `WallyDiscord` et `WallyTwitch`
6. Dans `bot/discord/bot.py` et `bot/twitch/bot.py` : ajouter `from bot.core.persona import PersonaService` sous `TYPE_CHECKING`, ajouter `persona: PersonaService` au `__init__`
7. Mettre à jour **tous** les appels `build_system_prompt()` (passer `persona_block=bot.persona.build_prompt_block()`) — sites concernés : `_respond()`, `_maybe_welcome()` dans `bot/discord/handlers.py`, la commande `/wally ask` dans `bot/discord/commands/ask.py`, et les handlers Twitch
8. Créer `bot/discord/commands/persona_cmd.py` (`PersonaCog`) et l'enregistrer dans `setup_hook()`
9. Mettre à jour les tests

---

## Tests

- `tests/test_persona.py` (nouveau) :
  - Chargement nominal des 3 fichiers via `tmp_path` (fixture pytest pour isolation)
  - Fichier manquant → bloc vide, pas d'exception
  - `reload()` met à jour un fichier modifié
  - `build_prompt_block()` : vérifier que `soul_content` apparaît avant `identity_content` avant `voice_content` dans le résultat
- `tests/test_prompts.py` : **mise à jour requise**
  - Toutes les instanciations `PromptBuilder(system_prompt="...")` → `PromptBuilder()`
  - `test_build_includes_base_prompt` → remplacé par un test qui passe `persona_block="..."` à `build_system_prompt()`
- `tests/test_config.py` : **mise à jour requise**
  - Supprimer `"system_prompt"` du `MINIMAL_CONFIG` sous la clé `"bot"`
- `tests/test_discord_commands.py` : ajout de `bot.persona = MagicMock()` dans les fixtures
- `tests/test_openai_client.py`, `test_journal.py`, `test_language.py`, `test_emotion.py` : pas de changement

---

## Hors scope (Phase 2)

- Mémoire émotionnelle enrichie (`mood_towards`, `relationship_level`, `interaction_count`)
- MEMORY.md dans `bot/persona/`
- `/wally setup` — onglet persona pour éditer SOUL/IDENTITY/VOICE depuis Discord
