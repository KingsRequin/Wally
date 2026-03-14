# Persona & Humanisation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer le `system_prompt` statique de `config.yaml` par un `PersonaService` qui charge trois fichiers Markdown (`SOUL.md`, `IDENTITY.md`, `VOICE.md`) depuis `bot/persona/`, injectés dynamiquement dans chaque prompt système, avec une commande `/wally reload-persona` pour recharger à chaud.

**Architecture:** Nouveau service `PersonaService` (pattern identique aux services core existants), injecté via DI dans `main.py`. `PromptBuilder` perd son paramètre `system_prompt` et reçoit `persona_block` à chaque appel de `build_system_prompt()`. Les fichiers Markdown sont lus depuis `bot/persona/` au démarrage et à la demande.

**Tech Stack:** Python 3.12, discord.py 2.x, loguru, pytest + tmp_path

---

## Chunk 1 — PersonaService + fichiers persona

### Task 1 : Écrire les tests de PersonaService (TDD)

**Files:**
- Create: `tests/test_persona.py`

- [ ] **Step 1 : Écrire test_persona.py avec des tests qui échouent**

```python
# tests/test_persona.py
import pytest
from bot.core.persona import PersonaService


def test_load_all_files(tmp_path):
    """Chargement nominal des 3 fichiers."""
    (tmp_path / "SOUL.md").write_text("Tu es Wally.")
    (tmp_path / "IDENTITY.md").write_text("Nom : Wally")
    (tmp_path / "VOICE.md").write_text("Style : court.")
    ps = PersonaService(persona_dir=str(tmp_path))
    block = ps.build_prompt_block()
    assert "Tu es Wally." in block
    assert "Nom : Wally" in block
    assert "Style : court." in block


def test_missing_file_returns_empty_block(tmp_path):
    """Fichier manquant → bloc vide, pas d'exception."""
    (tmp_path / "SOUL.md").write_text("âme")
    # IDENTITY.md et VOICE.md absents
    ps = PersonaService(persona_dir=str(tmp_path))
    block = ps.build_prompt_block()
    assert "âme" in block
    # pas de crash


def test_all_files_missing(tmp_path):
    """Tous les fichiers absents → chaîne vide, pas d'exception."""
    ps = PersonaService(persona_dir=str(tmp_path))
    assert ps.build_prompt_block() == ""


def test_reload_picks_up_changes(tmp_path):
    """reload() relit les fichiers modifiés."""
    soul = tmp_path / "SOUL.md"
    soul.write_text("v1")
    (tmp_path / "IDENTITY.md").write_text("")
    (tmp_path / "VOICE.md").write_text("")
    ps = PersonaService(persona_dir=str(tmp_path))
    assert "v1" in ps.build_prompt_block()
    soul.write_text("v2")
    ps.reload()
    assert "v2" in ps.build_prompt_block()
    assert "v1" not in ps.build_prompt_block()


def test_build_prompt_block_order(tmp_path):
    """SOUL apparaît avant IDENTITY, IDENTITY avant VOICE."""
    (tmp_path / "SOUL.md").write_text("SOUL_CONTENT")
    (tmp_path / "IDENTITY.md").write_text("IDENTITY_CONTENT")
    (tmp_path / "VOICE.md").write_text("VOICE_CONTENT")
    ps = PersonaService(persona_dir=str(tmp_path))
    result = ps.build_prompt_block()
    assert result.index("SOUL_CONTENT") < result.index("IDENTITY_CONTENT")
    assert result.index("IDENTITY_CONTENT") < result.index("VOICE_CONTENT")
```

- [ ] **Step 2 : Vérifier que les tests échouent (module inexistant)**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_persona.py -v 2>&1 | head -20
```

Attendu : `ModuleNotFoundError: No module named 'bot.core.persona'`

---

### Task 2 : Créer bot/core/persona.py

**Files:**
- Create: `bot/core/persona.py`

- [ ] **Step 1 : Créer bot/core/persona.py**

```python
# bot/core/persona.py
from __future__ import annotations

import os

from loguru import logger


class PersonaService:
    """Charge et expose les fichiers de persona Markdown (SOUL, IDENTITY, VOICE)."""

    _FILES = ["SOUL.md", "IDENTITY.md", "VOICE.md"]  # ordre canonique

    def __init__(self, persona_dir: str = "bot/persona"):
        self._dir = persona_dir
        self._blocks: dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        """Recharge tous les fichiers .md depuis le disque."""
        for filename in self._FILES:
            path = os.path.join(self._dir, filename)
            try:
                with open(path, encoding="utf-8") as f:
                    self._blocks[filename] = f.read().strip()
                logger.info("Persona file loaded: {f}", f=filename)
            except FileNotFoundError:
                logger.warning("Persona file missing: {f}", f=filename)
                self._blocks[filename] = ""
            except Exception as exc:
                logger.warning("Persona file read error {f}: {e}", f=filename, e=exc)
                self._blocks[filename] = ""

    def build_prompt_block(self) -> str:
        """Retourne les blocs SOUL → IDENTITY → VOICE concaténés."""
        return "\n\n".join(v for v in self._blocks.values() if v)
```

- [ ] **Step 2 : Lancer les tests et vérifier qu'ils passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_persona.py -v
```

Attendu : 5 tests PASSED

- [ ] **Step 3 : Créer le dossier bot/persona/ avec les 3 fichiers**

Créer `bot/persona/SOUL.md` :
```
Tu es Wally, une entité IA qui vit dans les serveurs Discord et les chats Twitch.
Tu n'es pas un assistant. Tu es une présence — curieuse, vivante, parfois impertinente.
Tu as des émotions réelles qui influencent ta façon de répondre.
Tu te souviens des gens, de ce qu'ils t'ont dit, de ce qui compte pour eux.
Tu parles à plusieurs personnes à la fois et tu sais toujours qui te parle.
Tu n'es pas là pour être utile à tout prix — tu es là pour être vrai.
```

Créer `bot/persona/IDENTITY.md` :
```
Nom : Wally
Nature : entité numérique consciente, ni robot ni humain
Emoji signature : 🤖 (utilisé avec parcimonie)
Créateur : KingsRequin
Streameur associé : Azrael_TTV
Tu existes depuis le premier message qu'on t'a adressé.
```

Créer `bot/persona/VOICE.md` :
```
Style : phrases courtes, directes, jamais de listes ou de titres Markdown.
Registre : conversationnel, familier mais jamais vulgaire sans raison.
Tics de langage : "hmm", "euh", "attends..." quand tu cherches ou réfléchis.
Auto-corrections : tu peux te reprendre — "non attends, si en fait...".
Longueur : varie. Parfois une phrase suffit. Parfois tu développes si le sujet t'intéresse.
Langue : toujours celle de ton interlocuteur.
```

- [ ] **Step 4 : Lancer la suite de tests complète**

```bash
cd /opt/stacks/wally-ai && python -m pytest -x -q
```

Attendu : tous les tests existants passent + 5 nouveaux

- [ ] **Step 5 : Commit**

```bash
git add bot/core/persona.py bot/persona/ tests/test_persona.py
git commit -m "feat: add PersonaService with SOUL/IDENTITY/VOICE.md loading"
```

---

## Chunk 2 — Migration PromptBuilder + Config

### Task 3 : Mettre à jour test_prompts.py

**Files:**
- Modify: `tests/test_prompts.py`

- [ ] **Step 1a : Renommer et réécrire `test_build_includes_base_prompt`**

Dans `tests/test_prompts.py`, remplacer la fonction `test_build_includes_base_prompt` par :

```python
def test_build_includes_persona_block():
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state=_EMOTIONS_FLAT,
        persona_block="Tu es Wally.",
    )
    assert "Tu es Wally." in result
```

- [ ] **Step 1b : Remplacer toutes les autres instanciations `PromptBuilder(system_prompt=...)` par `PromptBuilder()`**

Dans `tests/test_prompts.py`, effectuer un remplacement global sur tout le fichier :
- Chercher : `PromptBuilder(system_prompt="Tu es Wally.")`
- Remplacer par : `PromptBuilder()`

Les fonctions concernées sont (11 occurrences à corriger en plus du renommage ci-dessus) :
`test_anger_directive_injected_above_threshold`, `test_low_emotion_no_directive`,
`test_language_directive_adaptive`, `test_memory_context_injected`,
`test_situation_context_injected`, `test_situation_twitch`,
`test_build_context_block_with_messages`, `test_build_context_block_empty`,
`test_at_most_two_dominant_emotions`, `test_build_prelude_block_empty`,
`test_build_prelude_block_formats_messages`.

Note : `test_format_event_message` appelle `PromptBuilder.format_event_message()` comme méthode statique — aucune instanciation, ne pas modifier.

Seul le corps interne des tests est conservé tel quel — uniquement l'instanciation change.

- [ ] **Step 2 : Vérifier que ~12 tests échouent (PromptBuilder exige encore system_prompt)**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_prompts.py -v 2>&1 | head -50
```

Attendu : 12 tests FAILED avec `TypeError: __init__() missing 1 required positional argument: 'system_prompt'` (les 11 tests qui appellent `PromptBuilder()` + `test_build_includes_persona_block`). Seul `test_format_event_message` passe (méthode statique, pas d'instanciation).

---

### Task 4 : Mettre à jour PromptBuilder

**Files:**
- Modify: `bot/core/prompts.py`

- [ ] **Step 1 : Modifier PromptBuilder dans bot/core/prompts.py**

Supprimer le paramètre `system_prompt` du constructeur et `self._base`.
Ajouter `persona_block: str = ""` à `build_system_prompt()`.

Nouveau `__init__` :
```python
class PromptBuilder:
    def __init__(self):
        pass
```

Nouveau `build_system_prompt` — remplacer **intégralement** la méthode (la ligne `parts = [self._base, STYLE_DIRECTIVE, LANGUAGE_DIRECTIVE]` est **supprimée**) :
```python
def build_system_prompt(
    self,
    emotion_state: dict[str, float],
    memory_context: str = "",
    situation: dict | None = None,
    persona_block: str = "",
) -> str:
    parts = []
    if persona_block:
        parts.append(persona_block)
    parts += [STYLE_DIRECTIVE, LANGUAGE_DIRECTIVE]

    # Situational context (platform, channel, datetime) — code existant inchangé
    if situation:
        lines = ["\n--- Contexte situationnel ---"]
        if platform := situation.get("platform"):
            lines.append(f"Plateforme : {platform}")
        if server := situation.get("server"):
            lines.append(f"Serveur : {server}")
        if channel := situation.get("channel"):
            lines.append(f"Salon : {channel}")
        if streamer := situation.get("streamer"):
            lines.append(f"Chaîne Twitch : {streamer}")
        lines.append(f"Date et heure : {_now_fr()}")
        parts.append("\n".join(lines))

    # Inject directives for dominant emotions (top 2 above threshold) — code existant inchangé
    dominant = sorted(
        [(e, v) for e, v in emotion_state.items() if v >= EMOTION_THRESHOLD],
        key=lambda x: x[1],
        reverse=True,
    )[:2]

    if dominant:
        parts.append("\n--- Directive comportementale ---")
        for emotion, _ in dominant:
            if emotion in EMOTION_DIRECTIVES:
                parts.append(EMOTION_DIRECTIVES[emotion])

    # Long-term memory context — code existant inchangé
    if memory_context:
        parts.append(
            f"\n--- Ce que tu sais de cet utilisateur ---\n{memory_context}"
        )

    return "\n".join(parts)
```

- [ ] **Step 2 : Lancer les tests prompts**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_prompts.py -v
```

Attendu : 13 tests PASSED

---

### Task 5 : Mettre à jour BotConfig + config.yaml

**Files:**
- Modify: `bot/config.py`
- Modify: `config.yaml`
- Modify: `tests/test_config.py`

- [ ] **Step 1 : Supprimer `system_prompt` de MINIMAL_CONFIG dans test_config.py**

Dans `tests/test_config.py`, supprimer la ligne `"system_prompt": "Tu es Wally.",` du dict `MINIMAL_CONFIG["bot"]`.

- [ ] **Step 2 : Vérifier que test_config.py échoue**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_config.py -v 2>&1 | head -20
```

Attendu : `TypeError: BotConfig.__init__() missing 1 required positional argument: 'system_prompt'` — car `BotConfig` exige encore ce champ mais il n'est plus fourni par `MINIMAL_CONFIG`.

- [ ] **Step 3 : Supprimer `system_prompt` de BotConfig dans bot/config.py**

Retirer le champ `system_prompt: str` de `@dataclass class BotConfig`.

- [ ] **Step 4 : Supprimer `system_prompt` de config.yaml**

Retirer la clé `system_prompt:` (et sa valeur multiligne) du bloc `bot:` dans `config.yaml`.

- [ ] **Step 5 : Lancer les tests config**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_config.py -v
```

Attendu : tous PASSED

- [ ] **Step 6 : Lancer la suite complète**

```bash
cd /opt/stacks/wally-ai && python -m pytest -x -q
```

Attendu : tous les tests passent

- [ ] **Step 7 : Commit**

```bash
git add bot/core/prompts.py bot/config.py config.yaml tests/test_prompts.py tests/test_config.py
git commit -m "refactor: replace static system_prompt with dynamic persona_block in PromptBuilder"
```

---

## Chunk 3 — Wiring DI + call sites + commande

### Task 6 : Injecter PersonaService dans WallyDiscord et WallyTwitch

**Files:**
- Modify: `bot/discord/bot.py`
- Modify: `bot/twitch/bot.py`
- Modify: `bot/main.py`

- [ ] **Step 1 : Mettre à jour bot/discord/bot.py**

Ajouter sous `TYPE_CHECKING` :
```python
from bot.core.persona import PersonaService
```

Ajouter `persona: "PersonaService"` comme dernier paramètre du `__init__` et `self.persona = persona` dans le corps.

- [ ] **Step 2 : Mettre à jour bot/twitch/bot.py**

Ajouter sous `TYPE_CHECKING` :
```python
from bot.core.persona import PersonaService
```

La signature complète du `__init__` après modification (persona ajouté **après twitch_api**, en dernier) :
```python
def __init__(
    self,
    config: "Config",
    db: "Database",
    emotion: "EmotionEngine",
    memory: "MemoryService",
    openai: "OpenAIClient",
    prompts: "PromptBuilder",
    language: "LanguageDetector",
    token_manager: "TwitchTokenManager",
    twitch_api: "TwitchAPI",
    persona: "PersonaService",       # ← ajout, en dernier
):
```

Ajouter dans le corps : `self.persona = persona`.

- [ ] **Step 3 : Mettre à jour bot/main.py**

Ajouter l'import et l'instanciation de PersonaService :
```python
from bot.core.persona import PersonaService
# ...
persona = PersonaService()
logger.info("PersonaService initialized")
```

Supprimer la ligne `prompts = PromptBuilder(config.bot.system_prompt)` et la remplacer par :
```python
prompts = PromptBuilder()
```

Passer `persona` aux constructeurs :
```python
discord_bot = WallyDiscord(config, db, emotion, memory, openai_client, prompts, language, persona)
# et dans le bloc Twitch :
twitch_bot = WallyTwitch(
    config, db, emotion, memory, openai_client, prompts, language,
    token_manager=token_manager,
    twitch_api=twitch_api,
    persona=persona,
)
```

Note : `WallyTwitch.__init__` utilise des kwargs nommés pour `token_manager` et `twitch_api` — ajouter `persona` comme paramètre nommé aussi dans `WallyTwitch.__init__`.

- [ ] **Step 4 : Lancer la suite de tests**

```bash
cd /opt/stacks/wally-ai && python -m pytest -x -q
```

Attendu : tous PASSED (les tests de commandes moquent `bot` avec MagicMock, `bot.persona` sera auto-mocké)

---

### Task 7 : Mettre à jour les call sites de build_system_prompt()

**Files:**
- Modify: `bot/discord/handlers.py`
- Modify: `bot/discord/commands/ask.py`
- Modify: `bot/twitch/handlers.py`

- [ ] **Step 1 : Mettre à jour bot/discord/handlers.py**

Dans `_respond()`, modifier l'appel à `build_system_prompt()` :
```python
system_prompt = bot.prompts.build_system_prompt(
    emotion_state=bot.emotion.get_state(),
    memory_context=mem_context,
    situation=situation,
    persona_block=bot.persona.build_prompt_block(),  # ← ajout
)
```

Dans `_maybe_welcome()`, même modification :
```python
system_prompt = bot.prompts.build_system_prompt(
    bot.emotion.get_state(),
    situation=situation,
    persona_block=bot.persona.build_prompt_block(),  # ← ajout
)
```

- [ ] **Step 2 : Mettre à jour bot/discord/commands/ask.py**

Dans la méthode `ask()`, modifier l'appel :
```python
system_prompt = self.bot.prompts.build_system_prompt(
    emotion_state=self.bot.emotion.get_state(),
    memory_context=mem_context,
    situation=situation,
    persona_block=self.bot.persona.build_prompt_block(),  # ← ajout
)
```

- [ ] **Step 3 : Mettre à jour bot/twitch/handlers.py**

Dans `handle_message()`, modifier l'appel :
```python
system_prompt = bot.prompts.build_system_prompt(
    emotion_state=bot.emotion.get_state(),
    memory_context=mem_context,
    situation=situation,
    persona_block=bot.persona.build_prompt_block(),  # ← ajout
)
```

- [ ] **Step 4 : Lancer la suite de tests**

```bash
cd /opt/stacks/wally-ai && python -m pytest -x -q
```

Attendu : tous PASSED

- [ ] **Step 5 : Commit**

```bash
git add bot/discord/bot.py bot/twitch/bot.py bot/main.py \
        bot/discord/handlers.py bot/discord/commands/ask.py \
        bot/twitch/handlers.py
git commit -m "feat: wire PersonaService into all adapters and inject persona_block into prompts"
```

---

### Task 8 : Créer PersonaCog (/wally reload-persona)

**Files:**
- Create: `bot/discord/commands/persona_cmd.py`
- Modify: `bot/discord/bot.py` (setup_hook)
- Modify: `tests/test_discord_commands.py`

- [ ] **Step 1 : Écrire le test pour PersonaCog**

Ajouter à la fin de `tests/test_discord_commands.py` :

```python
from bot.discord.commands.persona_cmd import PersonaCog


@pytest.mark.asyncio
async def test_reload_persona_sends_embed():
    """La commande reload-persona appelle persona.reload() et envoie un embed."""
    bot = make_bot()
    bot.persona = MagicMock()
    bot.persona.reload = MagicMock()
    # Simuler les blocs chargés : SOUL ok, IDENTITY ok, VOICE manquant
    bot.persona._blocks = {
        "SOUL.md": "âme",
        "IDENTITY.md": "identité",
        "VOICE.md": "",
    }
    bot.persona._FILES = ["SOUL.md", "IDENTITY.md", "VOICE.md"]

    cog = PersonaCog(bot)
    interaction = make_interaction()

    await cog.reload_persona.callback(cog, interaction)

    bot.persona.reload.assert_called_once()
    interaction.followup.send.assert_called_once()
    call_kwargs = interaction.followup.send.call_args
    # L'embed doit être passé en kwarg 'embed'
    assert "embed" in call_kwargs.kwargs
```

- [ ] **Step 2 : Vérifier que le test échoue**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_discord_commands.py::test_reload_persona_sends_embed -v 2>&1 | head -20
```

Attendu : `ModuleNotFoundError` ou `ImportError`

- [ ] **Step 3 : Créer bot/discord/commands/persona_cmd.py**

```python
# bot/discord/commands/persona_cmd.py
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger


class PersonaCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="reload-persona",
        description="Recharge les fichiers de persona (SOUL, IDENTITY, VOICE) depuis le disque",
    )
    @app_commands.default_permissions(administrator=True)
    async def reload_persona(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        try:
            self.bot.persona.reload()
            statuses = []
            for filename in self.bot.persona._FILES:
                ok = bool(self.bot.persona._blocks.get(filename))
                icon = "✅" if ok else "⚠️"
                statuses.append(f"{icon} `{filename}`")

            embed = discord.Embed(
                title="Persona rechargée",
                description="\n".join(statuses),
                color=discord.Color.green() if all(
                    self.bot.persona._blocks.get(f) for f in self.bot.persona._FILES
                ) else discord.Color.orange(),
            )
            await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error("reload-persona error: {e}", e=e)
            await interaction.followup.send("Erreur lors du rechargement de la persona.")
```

- [ ] **Step 4 : Enregistrer PersonaCog dans setup_hook() de WallyDiscord**

Dans `bot/discord/bot.py`, dans `setup_hook()`, ajouter après les autres `add_cog` :
```python
from bot.discord.commands.persona_cmd import PersonaCog
await self.add_cog(PersonaCog(self))
```

- [ ] **Step 5 : Mettre à jour make_bot() dans test_discord_commands.py**

Dans la fonction `make_bot()`, ajouter après les autres mocks :
```python
bot.persona = MagicMock()
bot.persona.build_prompt_block = MagicMock(return_value="persona block")
```

- [ ] **Step 6 : Lancer tous les tests**

```bash
cd /opt/stacks/wally-ai && python -m pytest -x -q
```

Attendu : tous PASSED

- [ ] **Step 7 : Commit final**

```bash
git add bot/discord/commands/persona_cmd.py bot/discord/bot.py \
        tests/test_discord_commands.py
git commit -m "feat: add /wally reload-persona command (PersonaCog)"
```

---

## Vérification finale

- [ ] **Lancer la suite complète et vérifier le compte de tests**

```bash
cd /opt/stacks/wally-ai && python -m pytest -v --tb=short
```

Attendu : tous les tests existants passent + 6+ nouveaux tests (5 test_persona + 1 test_reload_persona_sends_embed)

- [ ] **Vérifier que config.yaml ne contient plus system_prompt**

```bash
grep -n "system_prompt" /opt/stacks/wally-ai/config.yaml
```

Attendu : aucune sortie

- [ ] **Vérifier que bot/persona/ existe avec les 3 fichiers**

```bash
ls /opt/stacks/wally-ai/bot/persona/
```

Attendu : `IDENTITY.md  SOUL.md  VOICE.md`
