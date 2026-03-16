# /wally setup — Amélioration complète Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Étendre `/wally setup` pour couvrir toutes les options du `config.yaml`, permettre la configuration du `.env` via Discord, et ajouter un redémarrage du bot avec confirmation.

**Architecture:** Architecture à deux niveaux (Basique/Avancé). `SetupTabSelect` supprimé et remplacé par `LevelSelect` + `BasicTabSelect`. Fonctions utilitaires `.env` au niveau module dans `setup.py`. Nouvelles classes View/Modal pour chaque onglet avancé.

**Tech Stack:** discord.py 2.x, Python 3.10+, asyncio, loguru

**Spec:** `docs/superpowers/specs/2026-03-16-setup-improvements-design.md`

---

## Chunk 1 : Utilitaires .env

---

### Task 1 : Fonctions utilitaires .env (`read_env_values`, `update_env_file`, `is_env_complete`)

**Files:**
- Modify: `bot/discord/commands/setup.py` (ajout en tête de fichier — `import asyncio` et `import os` sont pré-ajoutés ici car requis dès Chunk 2)
- Create: `tests/test_setup_env_utils.py`

---

- [ ] **Step 1 : Écrire les tests unitaires**

Créer `tests/test_setup_env_utils.py` :

```python
# tests/test_setup_env_utils.py
import pytest
from pathlib import Path


def test_read_env_values_parses_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("FOO=bar\nBAZ=qux\n")
    from bot.discord.commands.setup import read_env_values
    assert read_env_values(str(env)) == {"FOO": "bar", "BAZ": "qux"}


def test_read_env_values_skips_comments(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# commentaire\nFOO=bar\n# autre\n")
    from bot.discord.commands.setup import read_env_values
    assert read_env_values(str(env)) == {"FOO": "bar"}


def test_read_env_values_empty_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("")
    from bot.discord.commands.setup import read_env_values
    assert read_env_values(str(env)) == {}


def test_read_env_values_missing_file():
    from bot.discord.commands.setup import read_env_values
    assert read_env_values("/nonexistent/.env") == {}


def test_read_env_values_ignores_malformed_lines(tmp_path):
    """Une ligne sans '=' est ignorée (pas de crash)."""
    env = tmp_path / ".env"
    env.write_text("export FOO\nBAR=baz\n")
    from bot.discord.commands.setup import read_env_values
    assert read_env_values(str(env)) == {"BAR": "baz"}


def test_update_env_file_updates_existing(tmp_path):
    env = tmp_path / ".env"
    env.write_text("FOO=old\nBAR=keep\n")
    from bot.discord.commands.setup import update_env_file
    update_env_file(str(env), {"FOO": "new"})
    content = env.read_text()
    assert "FOO=new" in content
    assert "BAR=keep" in content
    assert "FOO=old" not in content


def test_update_env_file_appends_missing(tmp_path):
    env = tmp_path / ".env"
    env.write_text("FOO=bar\n")
    from bot.discord.commands.setup import update_env_file
    update_env_file(str(env), {"NEW_KEY": "value"})
    assert "NEW_KEY=value" in env.read_text()


def test_update_env_file_empty_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("")
    from bot.discord.commands.setup import update_env_file
    update_env_file(str(env), {"KEY": "val"})
    assert "KEY=val" in env.read_text()


def test_update_env_file_preserves_comments(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# OpenAI\nOPENAI_API_KEY=old\n")
    from bot.discord.commands.setup import update_env_file
    update_env_file(str(env), {"OPENAI_API_KEY": "new"})
    content = env.read_text()
    assert "# OpenAI" in content
    assert "OPENAI_API_KEY=new" in content


def test_is_env_complete_all_present(tmp_path):
    from bot.discord.commands.setup import is_env_complete, EDITABLE_ENV_KEYS
    env = tmp_path / ".env"
    env.write_text("\n".join(f"{k}=value" for k in EDITABLE_ENV_KEYS))
    assert is_env_complete(str(env)) == []


def test_is_env_complete_missing_key(tmp_path):
    from bot.discord.commands.setup import is_env_complete
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=sk-xxx\n")
    missing = is_env_complete(str(env))
    assert "DISCORD_TOKEN" in missing
    assert "OPENAI_API_KEY" not in missing


def test_is_env_complete_empty_value(tmp_path):
    from bot.discord.commands.setup import is_env_complete
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=\n")
    assert "OPENAI_API_KEY" in is_env_complete(str(env))


def test_is_env_complete_file_absent():
    from bot.discord.commands.setup import is_env_complete, EDITABLE_ENV_KEYS
    missing = is_env_complete("/nonexistent/.env")
    assert set(missing) == set(EDITABLE_ENV_KEYS)


def test_is_env_complete_ignores_infrastructure_keys(tmp_path):
    """QDRANT_URL et DB_PATH ne doivent pas être vérifiés."""
    from bot.discord.commands.setup import is_env_complete, EDITABLE_ENV_KEYS
    env = tmp_path / ".env"
    env.write_text("\n".join(f"{k}=value" for k in EDITABLE_ENV_KEYS))
    # Même sans QDRANT_URL et DB_PATH, doit retourner []
    assert is_env_complete(str(env)) == []
```

- [ ] **Step 2 : Lancer les tests pour vérifier qu'ils échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_setup_env_utils.py -v 2>&1 | head -30
```

Expected: `ImportError` ou `AttributeError` sur `read_env_values`.

- [ ] **Step 3 : Implémenter les fonctions dans `setup.py`**

Ajouter en tête de `bot/discord/commands/setup.py`, juste après les imports existants :

```python
import asyncio
import os

# ── Clés .env éditables ───────────────────────────────────────────────────────

EDITABLE_ENV_KEYS: list[str] = [
    "OPENAI_API_KEY",
    "DISCORD_TOKEN",
    "DISCORD_GUILD_ID",
    "TWITCH_CLIENT_ID",
    "TWITCH_CLIENT_SECRET",
    "TWITCH_BROADCASTER_ID",
    "TWITCH_BOT_ID",
    "TWITCH_BOT_NICK",
    "BOT_ACCESS_TOKEN",
    "BOT_REFRESH_TOKEN",
    "STREAMER_ACCESS_TOKEN",
    "STREAMER_REFRESH_TOKEN",
]


# ── Utilitaires .env ──────────────────────────────────────────────────────────

def read_env_values(path: str = ".env") -> dict[str, str]:
    """Lit le .env et retourne toutes les paires KEY=value (hors commentaires)."""
    try:
        with open(path) as f:
            lines = f.readlines()
    except FileNotFoundError:
        return {}
    result: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            key, _, value = stripped.partition("=")
            result[key.strip()] = value.strip()
    return result


def update_env_file(path: str, updates: dict[str, str]) -> None:
    """Met à jour les clés dans .env, ajoute les clés manquantes en fin de fichier."""
    try:
        with open(path) as f:
            lines = f.readlines()
    except FileNotFoundError:
        lines = []

    updated_keys: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            key = stripped.partition("=")[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}\n")
                updated_keys.add(key)
                continue
        new_lines.append(line)

    for key, value in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}\n")

    with open(path, "w") as f:
        f.writelines(new_lines)


def is_env_complete(path: str = ".env") -> list[str]:
    """Retourne les clés éditables manquantes ou vides dans le .env."""
    values = read_env_values(path)
    return [k for k in EDITABLE_ENV_KEYS if not values.get(k)]
```

- [ ] **Step 4 : Lancer les tests pour vérifier qu'ils passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_setup_env_utils.py -v
```

Expected: `14 passed`.

- [ ] **Step 5 : S'assurer que les tests existants passent toujours**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: tous les tests passent (110+13).

- [ ] **Step 6 : Commit**

```bash
cd /opt/stacks/wally-ai && git add bot/discord/commands/setup.py tests/test_setup_env_utils.py
git commit -m "feat: add .env utility functions (read_env_values, update_env_file, is_env_complete)"
```

---

## Chunk 2 : Migration SetupView + BasicTabSelect + Restart

---

### Task 2 : Réécrire `SetupView` et créer `LevelSelect`, `BasicView`, `BasicTabSelect`, `RestartButton`, `ConfirmRestartView`

**Files:**
- Modify: `bot/discord/commands/setup.py`
- Modify: `tests/test_discord_commands.py`

**Contexte :** `SetupTabSelect` est supprimé. Sa logique (5 onglets) est migrée dans `BasicTabSelect`.
`SetupView` est réécrit avec `LevelSelect` (row=0) + `RestartButton` (row=1).

---

- [ ] **Step 1 : Mettre à jour les tests existants**

Dans `tests/test_discord_commands.py`, appliquer les changements suivants :

```python
# Ligne 14 — modifier l'import (ajouter BasicTabSelect)
from bot.discord.commands.setup import is_valid_model, SetupCog, SetupView, BasicTabSelect

# test_setup_view_has_select — changer l'assertion
def test_setup_view_has_select():
    bot = make_bot()
    view = SetupView(bot)
    assert len(view.children) == 2  # LevelSelect + RestartButton

# test_setup_mood_tab_displays_percentage — remplacer SetupTabSelect par BasicTabSelect
async def test_setup_mood_tab_displays_percentage():
    """L'onglet Humeur du /setup affiche les émotions en %."""
    from bot.discord.commands.setup import BasicTabSelect  # remplace SetupTabSelect
    from unittest.mock import AsyncMock, MagicMock

    bot = MagicMock()
    bot.emotion.get_state = MagicMock(
        return_value={"anger": 0.0, "joy": 0.65, "sadness": 0.0,
                      "curiosity": 0.0, "boredom": 0.0}
    )
    bot.config.bot.trigger_names = ["wally"]

    select = BasicTabSelect(bot)  # remplace SetupTabSelect(bot)
    select._values = ["mood"]
    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()

    await select.callback(interaction)

    call_args = interaction.response.send_message.call_args
    content = call_args.args[0] if call_args.args else call_args.kwargs.get("content", "")
    assert "65%" in content
    assert "0.65" not in content
```

- [ ] **Step 2 : Lancer les tests modifiés pour vérifier qu'ils échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_discord_commands.py::test_setup_view_has_select tests/test_discord_commands.py::test_setup_mood_tab_displays_percentage -v
```

Expected: `ImportError` sur `BasicTabSelect` (n'existe pas encore).

- [ ] **Step 3 : Remplacer `SetupTabSelect` et `SetupView` dans `setup.py`**

**Supprimer** la classe `SetupTabSelect` et la classe `SetupView` existantes.

**Ajouter** à la fin du fichier, avant `SetupCog` :

**Note discord.py :** avec `@discord.ui.button`, tous les paramètres (label, style, row, etc.) vont **dans le décorateur**, pas dans `super().__init__()`. Ex : `@discord.ui.button(label="OK", style=discord.ButtonStyle.danger, row=0)`.

```python
# ── Restart ───────────────────────────────────────────────────────────────────

class ConfirmRestartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=30)  # expire en 30s

    @discord.ui.button(label="✅ Confirmer", style=discord.ButtonStyle.danger, row=0)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🔄 Redémarrage en cours...", ephemeral=True)
        asyncio.get_running_loop().call_later(1.0, os._exit, 0)

    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.secondary, row=0)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Redémarrage annulé.", ephemeral=True)


# ── Navigation niveau Basique ─────────────────────────────────────────────────

class BasicTabSelect(discord.ui.Select):
    def __init__(self, bot: "WallyDiscord"):
        self.bot = bot
        options = [
            discord.SelectOption(label="Modele IA", value="model", emoji="🤖"),
            discord.SelectOption(label="Humeur", value="mood", emoji="😊"),
            discord.SelectOption(label="Evenements Twitch", value="twitch", emoji="🎮"),
            discord.SelectOption(label="Noms declencheurs", value="triggers", emoji="📢"),
            discord.SelectOption(label="Memoire", value="memory", emoji="🧠"),
            discord.SelectOption(label="Variables d'env", value="env", emoji="🔑"),
        ]
        super().__init__(placeholder="Choisir un onglet...", options=options)

    async def callback(self, interaction: discord.Interaction):
        tab = self.values[0]
        if tab == "mood":
            view = MoodView(self.bot)
            state = self.bot.emotion.get_state()
            lines = [f"**{e}** : {int(v * 100)}%" for e, v in state.items()]
            await interaction.response.send_message(
                "**Humeur actuelle :**\n" + "\n".join(lines),
                view=view,
                ephemeral=True,
            )
        elif tab == "twitch":
            view = TwitchEventsView(self.bot)
            lines = [
                f"{'✅' if cfg.active else '❌'} **{name}** : "
                f"{cfg.message[:50]}{'...' if len(cfg.message) > 50 else ''}"
                for name, cfg in self.bot.config.twitch_events.items()
            ]
            await interaction.response.send_message(
                "**Evenements Twitch :**\n" + "\n".join(lines),
                view=view,
                ephemeral=True,
            )
        elif tab == "triggers":
            view = TriggerNamesView(self.bot)
            names = ", ".join(self.bot.config.bot.trigger_names)
            await interaction.response.send_message(
                f"**Noms déclencheurs :** {names}",
                view=view,
                ephemeral=True,
            )
        elif tab == "memory":
            view = MemoryView(self.bot)
            await interaction.response.send_message(
                "**Mémoire de Wally**\n"
                "⚠️ Cette action efface le contexte de conversation et la mémoire long terme.",
                view=view,
                ephemeral=True,
            )
        elif tab == "model":
            await interaction.response.defer(ephemeral=True, thinking=True)
            await _send_model_tab(self.bot, interaction)
        elif tab == "env":
            await _send_env_tab(self.bot, interaction)


class BasicView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=120)
        self.add_item(BasicTabSelect(bot))


# ── Navigation niveau Avancé (défini dans Chunk 4) ───────────────────────────

# (AdvancedTabSelect et AdvancedView seront ajoutés en Task 4)


# ── Sélecteur de niveau + SetupView ──────────────────────────────────────────

class LevelSelect(discord.ui.Select):
    def __init__(self, bot: "WallyDiscord"):
        self.bot = bot
        options = [
            discord.SelectOption(label="Basique", value="basic", emoji="⚙️",
                                 description="Modèle, humeur, triggers, Twitch events, mémoire, .env"),
            discord.SelectOption(label="Avancé", value="advanced", emoji="🔧",
                                 description="Paramètres bot, Discord, Twitch, OpenAI, decay"),
        ]
        super().__init__(placeholder="Choisir un niveau...", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "basic":
            view = BasicView(self.bot)
            await interaction.response.send_message(
                "**Configuration — Niveau Basique**", view=view, ephemeral=True
            )
        else:
            # AdvancedView défini en Task 4 — placeholder temporaire
            await interaction.response.send_message(
                "**Configuration — Niveau Avancé** (à venir)", ephemeral=True
            )


class RestartButton(discord.ui.Button):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(
            label="🔄 Redémarrer le bot",
            style=discord.ButtonStyle.danger,
            row=1,
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        view = ConfirmRestartView()
        await interaction.response.send_message(
            "⚠️ Confirmer le redémarrage du bot ?",
            view=view,
            ephemeral=True,
        )


class SetupView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=180)
        self.add_item(LevelSelect(bot))
        self.add_item(RestartButton(bot))
```

**Note :** `_send_env_tab` et `AdvancedView` seront complétés en Tasks 3 et 4. Ajouter des stubs :

```python
async def _send_env_tab(bot: "WallyDiscord", interaction: discord.Interaction) -> None:
    """Placeholder — implémenté en Task 3. Utilise send_message (pas defer)."""
    missing = is_env_complete()
    msg = "**Variables d'environnement**"
    if missing:
        msg += f"\n⚠️ Clés manquantes : {', '.join(missing)}"
    await interaction.response.send_message(msg, ephemeral=True)


class AdvancedView(discord.ui.View):
    """Stub — remplacé en Task 4."""
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=120)
```

- [ ] **Step 4 : Lancer les tests pour vérifier qu'ils passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_discord_commands.py -v --tb=short
```

Expected: tous les tests de `test_discord_commands.py` passent.

- [ ] **Step 5 : Lancer la suite complète**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: tous les tests passent.

- [ ] **Step 6 : Commit**

```bash
cd /opt/stacks/wally-ai && git add bot/discord/commands/setup.py tests/test_discord_commands.py
git commit -m "feat: migrate SetupView to two-level navigation (Basique/Avancé) + restart button"
```

*(Fichiers stagés : `bot/discord/commands/setup.py` et `tests/test_discord_commands.py`)*

---

## Chunk 3 : Tab .env — `EnvView` + 4 modaux

---

### Task 3 : Implémenter le tab .env avec `EnvView` et les 4 modaux de configuration

**Files:**
- Modify: `bot/discord/commands/setup.py`

**Rappel Discord.py :** les `TextInput` doivent être déclarés comme **attributs de classe** (pas d'instance). Chaque groupe est donc une classe distincte.

---

- [ ] **Step 1 : Écrire les tests pour `_send_env_tab` et `EnvOpenAIModal.on_submit`**

Ajouter dans `tests/test_discord_commands.py` :

```python
@pytest.mark.asyncio
async def test_send_env_tab_includes_env_view(monkeypatch):
    """_send_env_tab envoie un message avec une EnvView (pas juste du texte)."""
    from bot.discord.commands.setup import _send_env_tab, EnvView
    import bot.discord.commands.setup as setup_module

    monkeypatch.setattr(setup_module, "is_env_complete",
                        lambda path=".env": ["OPENAI_API_KEY"])

    bot_obj = make_bot()
    interaction = make_interaction()

    await _send_env_tab(bot_obj, interaction)

    call_args = interaction.response.send_message.call_args
    msg = call_args.args[0] if call_args.args else call_args.kwargs.get("content", "")
    assert "OPENAI_API_KEY" in msg
    # La vraie implémentation doit passer une EnvView
    view = call_args.kwargs.get("view")
    assert view is not None
    assert isinstance(view, EnvView)


@pytest.mark.asyncio
async def test_env_openai_modal_saves_key(monkeypatch):
    """EnvOpenAIModal.on_submit appelle update_env_file avec OPENAI_API_KEY."""
    from bot.discord.commands.setup import EnvOpenAIModal
    import bot.discord.commands.setup as setup_module

    saved = {}
    monkeypatch.setattr(setup_module, "update_env_file",
                        lambda path, updates: saved.update(updates))

    modal = EnvOpenAIModal({})
    modal.openai_api_key._value = "sk-new-key"

    interaction = make_interaction()
    await modal.on_submit(interaction)

    assert saved.get("OPENAI_API_KEY") == "sk-new-key"
    interaction.response.send_message.assert_awaited_once()
```

- [ ] **Step 2 : Lancer les tests pour vérifier qu'ils échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_discord_commands.py::test_send_env_tab_includes_env_view tests/test_discord_commands.py::test_env_openai_modal_saves_key -v
```

Expected: `test_send_env_tab_includes_env_view` FAIL (le placeholder ne passe pas de view), `test_env_openai_modal_saves_key` FAIL (EnvOpenAIModal n'existe pas encore).

- [ ] **Step 3 : Implémenter `EnvView` et les 4 modaux dans `setup.py`**

Remplacer la fonction placeholder `_send_env_tab` par l'implémentation complète.

Ajouter **avant** `_send_env_tab` dans `setup.py` :

```python
# ── Tab .env ──────────────────────────────────────────────────────────────────

class EnvOpenAIModal(discord.ui.Modal, title="Variables OpenAI"):
    openai_api_key = discord.ui.TextInput(
        label="OPENAI_API_KEY",
        placeholder="sk-proj-...",
        max_length=200,
    )

    def __init__(self, values: dict[str, str]):
        super().__init__()
        self.openai_api_key.default = values.get("OPENAI_API_KEY", "")

    async def on_submit(self, interaction: discord.Interaction):
        update_env_file(".env", {"OPENAI_API_KEY": self.openai_api_key.value})
        view = ConfirmRestartView()
        await interaction.response.send_message(
            "✅ Sauvegardé. Les changements s'appliqueront au prochain démarrage.",
            view=view,
            ephemeral=True,
        )


class EnvDiscordModal(discord.ui.Modal, title="Variables Discord"):
    discord_token = discord.ui.TextInput(
        label="DISCORD_TOKEN",
        placeholder="MTxx...",
        max_length=100,
    )
    discord_guild_id = discord.ui.TextInput(
        label="DISCORD_GUILD_ID",
        placeholder="1063150486137606256",
        max_length=20,
    )

    def __init__(self, values: dict[str, str]):
        super().__init__()
        self.discord_token.default = values.get("DISCORD_TOKEN", "")
        self.discord_guild_id.default = values.get("DISCORD_GUILD_ID", "")

    async def on_submit(self, interaction: discord.Interaction):
        update_env_file(".env", {
            "DISCORD_TOKEN": self.discord_token.value,
            "DISCORD_GUILD_ID": self.discord_guild_id.value,
        })
        view = ConfirmRestartView()
        await interaction.response.send_message(
            "✅ Sauvegardé. Les changements s'appliqueront au prochain démarrage.",
            view=view,
            ephemeral=True,
        )


class EnvTwitchIdModal(discord.ui.Modal, title="Twitch — Identité"):
    twitch_client_id = discord.ui.TextInput(label="TWITCH_CLIENT_ID", max_length=50)
    twitch_client_secret = discord.ui.TextInput(label="TWITCH_CLIENT_SECRET", max_length=50)
    twitch_broadcaster_id = discord.ui.TextInput(label="TWITCH_BROADCASTER_ID", max_length=20)
    twitch_bot_id = discord.ui.TextInput(label="TWITCH_BOT_ID", max_length=20)
    twitch_bot_nick = discord.ui.TextInput(label="TWITCH_BOT_NICK", max_length=50)

    def __init__(self, values: dict[str, str]):
        super().__init__()
        self.twitch_client_id.default = values.get("TWITCH_CLIENT_ID", "")
        self.twitch_client_secret.default = values.get("TWITCH_CLIENT_SECRET", "")
        self.twitch_broadcaster_id.default = values.get("TWITCH_BROADCASTER_ID", "")
        self.twitch_bot_id.default = values.get("TWITCH_BOT_ID", "")
        self.twitch_bot_nick.default = values.get("TWITCH_BOT_NICK", "")

    async def on_submit(self, interaction: discord.Interaction):
        update_env_file(".env", {
            "TWITCH_CLIENT_ID": self.twitch_client_id.value,
            "TWITCH_CLIENT_SECRET": self.twitch_client_secret.value,
            "TWITCH_BROADCASTER_ID": self.twitch_broadcaster_id.value,
            "TWITCH_BOT_ID": self.twitch_bot_id.value,
            "TWITCH_BOT_NICK": self.twitch_bot_nick.value,
        })
        view = ConfirmRestartView()
        await interaction.response.send_message(
            "✅ Sauvegardé. Les changements s'appliqueront au prochain démarrage.",
            view=view,
            ephemeral=True,
        )


class EnvTwitchTokensModal(discord.ui.Modal, title="Twitch — Tokens"):
    bot_access_token = discord.ui.TextInput(label="BOT_ACCESS_TOKEN", max_length=50)
    bot_refresh_token = discord.ui.TextInput(label="BOT_REFRESH_TOKEN", max_length=60)
    streamer_access_token = discord.ui.TextInput(label="STREAMER_ACCESS_TOKEN", max_length=50)
    streamer_refresh_token = discord.ui.TextInput(label="STREAMER_REFRESH_TOKEN", max_length=60)

    def __init__(self, values: dict[str, str]):
        super().__init__()
        self.bot_access_token.default = values.get("BOT_ACCESS_TOKEN", "")
        self.bot_refresh_token.default = values.get("BOT_REFRESH_TOKEN", "")
        self.streamer_access_token.default = values.get("STREAMER_ACCESS_TOKEN", "")
        self.streamer_refresh_token.default = values.get("STREAMER_REFRESH_TOKEN", "")

    async def on_submit(self, interaction: discord.Interaction):
        update_env_file(".env", {
            "BOT_ACCESS_TOKEN": self.bot_access_token.value,
            "BOT_REFRESH_TOKEN": self.bot_refresh_token.value,
            "STREAMER_ACCESS_TOKEN": self.streamer_access_token.value,
            "STREAMER_REFRESH_TOKEN": self.streamer_refresh_token.value,
        })
        view = ConfirmRestartView()
        await interaction.response.send_message(
            "✅ Sauvegardé. Les changements s'appliqueront au prochain démarrage.",
            view=view,
            ephemeral=True,
        )


class EnvOpenAIButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="OpenAI", style=discord.ButtonStyle.primary, row=0)

    async def callback(self, interaction: discord.Interaction):
        values = read_env_values()
        await interaction.response.send_modal(EnvOpenAIModal(values))


class EnvDiscordButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Discord", style=discord.ButtonStyle.primary, row=1)

    async def callback(self, interaction: discord.Interaction):
        values = read_env_values()
        await interaction.response.send_modal(EnvDiscordModal(values))


class EnvTwitchIdButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Twitch — Identité", style=discord.ButtonStyle.primary, row=2)

    async def callback(self, interaction: discord.Interaction):
        values = read_env_values()
        await interaction.response.send_modal(EnvTwitchIdModal(values))


class EnvTwitchTokensButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Twitch — Tokens", style=discord.ButtonStyle.primary, row=3)

    async def callback(self, interaction: discord.Interaction):
        values = read_env_values()
        await interaction.response.send_modal(EnvTwitchTokensModal(values))


class EnvView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(EnvOpenAIButton())
        self.add_item(EnvDiscordButton())
        self.add_item(EnvTwitchIdButton())
        self.add_item(EnvTwitchTokensButton())
```

**Remplacer** le placeholder `_send_env_tab` par :

```python
async def _send_env_tab(bot: "WallyDiscord", interaction: discord.Interaction) -> None:
    missing = is_env_complete()
    lines = ["**Variables d'environnement** — Sélectionnez un groupe à modifier :"]
    if missing:
        lines.append(f"⚠️ Clés manquantes : {', '.join(missing)}")
    view = EnvView()
    await interaction.response.send_message("\n".join(lines), view=view, ephemeral=True)
```

- [ ] **Step 4 : Lancer tous les tests**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: tous les tests passent.

- [ ] **Step 5 : Commit**

```bash
cd /opt/stacks/wally-ai && git add bot/discord/commands/setup.py tests/test_discord_commands.py
git commit -m "feat: add .env configuration tab with 4 grouped modals"
```

---

## Chunk 4 : Niveau Avancé — Structure + Bot Général + Discord

---

### Task 4 : `AdvancedTabSelect`, `AdvancedView` et onglets Bot Général + Discord

**Files:**
- Modify: `bot/discord/commands/setup.py`
- Modify: `tests/test_discord_commands.py`

---

- [ ] **Step 1 : Écrire les tests pour Bot Général, Discord, JournalChannel et EditChannelList**

Ajouter dans `tests/test_discord_commands.py` :

```python
@pytest.mark.asyncio
async def test_advanced_tab_bot_sends_message():
    """L'onglet Bot Général envoie un message avec BotGeneralView."""
    from bot.discord.commands.setup import AdvancedTabSelect

    bot = make_bot()
    bot.config.bot.language_default = "fr"
    bot.config.bot.context_window_size = 20
    bot.config.bot.context_token_threshold = 3000
    bot.config.bot.journal_time = "21:00"
    bot.config.bot.prelude_window_size = 15
    bot.config.bot.journal_channel_id = None

    select = AdvancedTabSelect(bot)
    select._values = ["bot"]
    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()

    await select.callback(interaction)

    interaction.response.send_message.assert_awaited_once()
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


@pytest.mark.asyncio
async def test_bot_general_modal_saves_config(tmp_path, monkeypatch):
    """BotGeneralModal met à jour config et appelle config.save()."""
    from bot.discord.commands.setup import BotGeneralModal

    bot = make_bot()
    bot.config.bot.language_default = "fr"
    bot.config.bot.context_window_size = 20
    bot.config.bot.context_token_threshold = 3000
    bot.config.bot.journal_time = "21:00"
    bot.config.bot.prelude_window_size = 15
    bot.config.save = MagicMock()

    modal = BotGeneralModal(bot)
    modal.language_default._value = "en"
    modal.context_window_size._value = "25"
    modal.context_token_threshold._value = "4000"
    modal.journal_time._value = "20:00"
    modal.prelude_window_size._value = "10"

    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()

    await modal.on_submit(interaction)

    assert bot.config.bot.language_default == "en"
    assert bot.config.bot.context_window_size == 25
    bot.config.save.assert_called_once()


@pytest.mark.asyncio
async def test_bot_general_modal_rejects_invalid_int():
    """BotGeneralModal envoie une erreur si context_window_size n'est pas un int valide."""
    from bot.discord.commands.setup import BotGeneralModal

    bot = make_bot()
    bot.config.bot.language_default = "fr"
    bot.config.bot.context_window_size = 20
    bot.config.bot.context_token_threshold = 3000
    bot.config.bot.journal_time = "21:00"
    bot.config.bot.prelude_window_size = 15
    bot.config.save = MagicMock()

    modal = BotGeneralModal(bot)
    modal.language_default._value = "fr"
    modal.context_window_size._value = "abc"  # invalide
    modal.context_token_threshold._value = "3000"
    modal.journal_time._value = "21:00"
    modal.prelude_window_size._value = "15"

    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()

    await modal.on_submit(interaction)

    bot.config.save.assert_not_called()
    interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_discord_params_modal_saves_config():
    """DiscordParamsModal met à jour anger_trigger_threshold et timeout_minutes."""
    from bot.discord.commands.setup import DiscordParamsModal

    bot = make_bot()
    bot.config.discord.anger_trigger_threshold = 3
    bot.config.discord.timeout_minutes = 10
    bot.config.save = MagicMock()

    modal = DiscordParamsModal(bot)
    modal.anger_trigger_threshold._value = "5"
    modal.timeout_minutes._value = "15"

    interaction = make_interaction()
    await modal.on_submit(interaction)

    assert bot.config.discord.anger_trigger_threshold == 5
    assert bot.config.discord.timeout_minutes == 15
    bot.config.save.assert_called_once()


@pytest.mark.asyncio
async def test_journal_channel_modal_clears_on_empty():
    """JournalChannelModal avec input vide met journal_channel_id à None."""
    from bot.discord.commands.setup import JournalChannelModal

    bot = make_bot()
    bot.config.bot.journal_channel_id = 12345
    bot.config.save = MagicMock()

    modal = JournalChannelModal(bot)
    modal.channel_id._value = ""

    interaction = make_interaction()
    await modal.on_submit(interaction)

    assert bot.config.bot.journal_channel_id is None
    bot.config.save.assert_called_once()


@pytest.mark.asyncio
async def test_edit_channel_list_modal_parses_comma_sep_ints():
    """EditChannelListModal parse les IDs séparés par des virgules."""
    from bot.discord.commands.setup import EditChannelListModal

    bot = make_bot()
    bot.config.discord.channel_blacklist = []
    bot.config.save = MagicMock()

    modal = EditChannelListModal(bot, "blacklist")
    modal.channel_ids._value = "123456, 789012, 345678"

    interaction = make_interaction()
    await modal.on_submit(interaction)

    assert bot.config.discord.channel_blacklist == [123456, 789012, 345678]
    bot.config.save.assert_called_once()


@pytest.mark.asyncio
async def test_edit_channel_list_modal_rejects_invalid():
    """EditChannelListModal rejette les IDs non entiers."""
    from bot.discord.commands.setup import EditChannelListModal

    bot = make_bot()
    bot.config.discord.channel_blacklist = []
    bot.config.save = MagicMock()

    modal = EditChannelListModal(bot, "blacklist")
    modal.channel_ids._value = "abc, 123"

    interaction = make_interaction()
    await modal.on_submit(interaction)

    bot.config.save.assert_not_called()
```

- [ ] **Step 2 : Lancer les tests pour vérifier qu'ils échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_discord_commands.py::test_advanced_tab_bot_sends_message tests/test_discord_commands.py::test_bot_general_modal_saves_config tests/test_discord_commands.py::test_discord_params_modal_saves_config tests/test_discord_commands.py::test_journal_channel_modal_clears_on_empty tests/test_discord_commands.py::test_edit_channel_list_modal_parses_comma_sep_ints -v
```

Expected: `ImportError` sur `AdvancedTabSelect`, `BotGeneralModal`, `DiscordParamsModal`, `JournalChannelModal`, `EditChannelListModal`.

- [ ] **Step 3 : Implémenter les classes dans `setup.py`**

Ajouter **avant** `LevelSelect` dans `setup.py` :

```python
# ── Tab Avancé : Bot Général ──────────────────────────────────────────────────

class BotGeneralModal(discord.ui.Modal, title="Paramètres généraux du bot"):
    language_default = discord.ui.TextInput(
        label="Langue par défaut (ex: fr, en)", max_length=5
    )
    context_window_size = discord.ui.TextInput(
        label="Taille contexte (nb messages, ≥1)", max_length=5
    )
    context_token_threshold = discord.ui.TextInput(
        label="Seuil tokens contexte (≥1)", max_length=6
    )
    journal_time = discord.ui.TextInput(
        label="Heure journal (HH:MM)", max_length=5
    )
    prelude_window_size = discord.ui.TextInput(
        label="Taille prélude (≥1)", max_length=5
    )

    def __init__(self, bot: "WallyDiscord"):
        super().__init__()
        self.bot = bot
        cfg = bot.config.bot
        self.language_default.default = cfg.language_default
        self.context_window_size.default = str(cfg.context_window_size)
        self.context_token_threshold.default = str(cfg.context_token_threshold)
        self.journal_time.default = cfg.journal_time
        self.prelude_window_size.default = str(cfg.prelude_window_size)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            cws = int(self.context_window_size.value)
            ctt = int(self.context_token_threshold.value)
            pws = int(self.prelude_window_size.value)
            if cws < 1 or ctt < 1 or pws < 1:
                raise ValueError("Valeur trop petite")
        except ValueError:
            await interaction.response.send_message(
                "❌ Valeurs invalides. Les champs numériques doivent être des entiers ≥ 1.",
                ephemeral=True,
            )
            return
        cfg = self.bot.config.bot
        cfg.language_default = self.language_default.value
        cfg.context_window_size = cws
        cfg.context_token_threshold = ctt
        cfg.journal_time = self.journal_time.value
        cfg.prelude_window_size = pws
        self.bot.config.save()
        await interaction.response.send_message("✅ Paramètres généraux mis à jour.", ephemeral=True)


class JournalChannelModal(discord.ui.Modal, title="Channel du journal"):
    channel_id = discord.ui.TextInput(
        label="ID du channel Discord (vide pour désactiver)",
        required=False,
        max_length=20,
    )

    def __init__(self, bot: "WallyDiscord"):
        super().__init__()
        self.bot = bot
        current = bot.config.bot.journal_channel_id
        self.channel_id.default = str(current) if current else ""

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.channel_id.value.strip()
        if raw == "":
            self.bot.config.bot.journal_channel_id = None
            self.bot.config.save()
            await interaction.response.send_message("✅ Channel journal désactivé.", ephemeral=True)
            return
        try:
            cid = int(raw)
            if cid <= 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ ID invalide. Entrez un entier > 0 ou laissez vide.", ephemeral=True
            )
            return
        self.bot.config.bot.journal_channel_id = cid
        self.bot.config.save()
        await interaction.response.send_message(f"✅ Channel journal : {cid}", ephemeral=True)


class BotGeneralView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=120)
        self.bot = bot

    @discord.ui.button(label="Modifier paramètres généraux", style=discord.ButtonStyle.primary, row=0)
    async def edit_general(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BotGeneralModal(self.bot))

    @discord.ui.button(label="Définir channel journal", style=discord.ButtonStyle.secondary, row=1)
    async def edit_journal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(JournalChannelModal(self.bot))


# ── Tab Avancé : Discord ──────────────────────────────────────────────────────

class DiscordParamsModal(discord.ui.Modal, title="Paramètres Discord"):
    anger_trigger_threshold = discord.ui.TextInput(
        label="Seuil déclencheur colère (≥1)", max_length=3
    )
    timeout_minutes = discord.ui.TextInput(
        label="Durée timeout en minutes (≥1)", max_length=4
    )

    def __init__(self, bot: "WallyDiscord"):
        super().__init__()
        self.bot = bot
        self.anger_trigger_threshold.default = str(bot.config.discord.anger_trigger_threshold)
        self.timeout_minutes.default = str(bot.config.discord.timeout_minutes)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            att = int(self.anger_trigger_threshold.value)
            tm = int(self.timeout_minutes.value)
            if att < 1 or tm < 1:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ Valeurs invalides. Les deux champs doivent être des entiers ≥ 1.",
                ephemeral=True,
            )
            return
        self.bot.config.discord.anger_trigger_threshold = att
        self.bot.config.discord.timeout_minutes = tm
        self.bot.config.save()
        await interaction.response.send_message(
            f"✅ Seuil colère : {att}, timeout : {tm} min.", ephemeral=True
        )


class EditChannelListModal(discord.ui.Modal, title="Modifier la liste de channels"):
    channel_ids = discord.ui.TextInput(
        label="IDs des channels (séparés par des virgules)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    def __init__(self, bot: "WallyDiscord", list_type: str):
        # IMPORTANT : appeler super().__init__() EN PREMIER
        # super() fait un deepcopy des TextInputs de classe vers l'instance.
        # self.channel_ids.default = ... doit venir APRÈS super().
        super().__init__()
        self.bot = bot
        self.list_type = list_type
        current: list[int] = (
            bot.config.discord.channel_blacklist
            if list_type == "blacklist"
            else bot.config.discord.channel_whitelist
        )
        self.channel_ids.default = ", ".join(str(c) for c in current)

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.channel_ids.value.strip()
        if not raw:
            ids: list[int] = []
        else:
            try:
                ids = [int(x.strip()) for x in raw.split(",") if x.strip()]
                if any(i <= 0 for i in ids):
                    raise ValueError
            except ValueError:
                await interaction.response.send_message(
                    "❌ IDs invalides. Entrez des entiers > 0 séparés par des virgules.",
                    ephemeral=True,
                )
                return
        if self.list_type == "blacklist":
            self.bot.config.discord.channel_blacklist = ids
        else:
            self.bot.config.discord.channel_whitelist = ids
        self.bot.config.save()
        await interaction.response.send_message(
            f"✅ {self.list_type.capitalize()} mise à jour ({len(ids)} channel(s)).",
            ephemeral=True,
        )


class DiscordView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=120)
        self.bot = bot
        mode = bot.config.discord.channel_filter_mode

        # Row 0: bouton params
        # Row 1: toggle filter mode
        # Row 2: blacklist
        # Row 3: whitelist
        # Les boutons avec row sont ajoutés via add_item

    @discord.ui.button(label="Colère & timeout", style=discord.ButtonStyle.primary, row=0)
    async def edit_params(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DiscordParamsModal(self.bot))

    @discord.ui.button(label="Mode filtre : ...", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_filter(self, interaction: discord.Interaction, button: discord.ui.Button):
        current = self.bot.config.discord.channel_filter_mode
        new_mode = "whitelist" if current == "blacklist" else "blacklist"
        self.bot.config.discord.channel_filter_mode = new_mode
        self.bot.config.save()
        await interaction.response.send_message(
            f"✅ Mode filtre : **{new_mode}**", ephemeral=True
        )

    @discord.ui.button(label="Modifier la blacklist", style=discord.ButtonStyle.secondary, row=2)
    async def edit_blacklist(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditChannelListModal(self.bot, "blacklist"))

    @discord.ui.button(label="Modifier la whitelist", style=discord.ButtonStyle.secondary, row=3)
    async def edit_whitelist(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditChannelListModal(self.bot, "whitelist"))
```

**Ajouter `AdvancedTabSelect` et `AdvancedView`**, puis mettre à jour le placeholder dans `LevelSelect.callback` :

```python
# ── Navigation niveau Avancé ──────────────────────────────────────────────────

class AdvancedTabSelect(discord.ui.Select):
    def __init__(self, bot: "WallyDiscord"):
        self.bot = bot
        options = [
            discord.SelectOption(label="Bot Général", value="bot", emoji="⚙️"),
            discord.SelectOption(label="Discord", value="discord", emoji="💬"),
            discord.SelectOption(label="Twitch Config", value="twitch_cfg", emoji="🟣"),
            discord.SelectOption(label="OpenAI (params)", value="openai", emoji="🤖"),
            discord.SelectOption(label="Decay émotions", value="decay", emoji="💭"),
        ]
        super().__init__(placeholder="Choisir un onglet avancé...", options=options)

    async def callback(self, interaction: discord.Interaction):
        tab = self.values[0]
        if tab == "bot":
            cfg = self.bot.config.bot
            lines = [
                f"**Bot Général**",
                f"Langue : {cfg.language_default}",
                f"Contexte : {cfg.context_window_size} messages / {cfg.context_token_threshold} tokens",
                f"Journal : {cfg.journal_time} — channel : {cfg.journal_channel_id or 'non défini'}",
                f"Prélude : {cfg.prelude_window_size}",
            ]
            view = BotGeneralView(self.bot)
            await interaction.response.send_message("\n".join(lines), view=view, ephemeral=True)
        elif tab == "discord":
            cfg = self.bot.config.discord
            lines = [
                f"**Paramètres Discord**",
                f"Seuil colère : {cfg.anger_trigger_threshold} — Timeout : {cfg.timeout_minutes} min",
                f"Mode filtre : **{cfg.channel_filter_mode}**",
                f"Blacklist : {len(cfg.channel_blacklist)} channel(s)",
                f"Whitelist : {len(cfg.channel_whitelist)} channel(s)",
            ]
            view = DiscordView(self.bot)
            await interaction.response.send_message("\n".join(lines), view=view, ephemeral=True)
        elif tab == "twitch_cfg":
            await _send_twitch_config_tab(self.bot, interaction)
        elif tab == "openai":
            await _send_openai_params_tab(self.bot, interaction)
        elif tab == "decay":
            await _send_decay_tab(self.bot, interaction)


class AdvancedView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=120)
        self.add_item(AdvancedTabSelect(bot))
```

**Mettre à jour `LevelSelect.callback`** — remplacer le commentaire placeholder :

```python
    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "basic":
            view = BasicView(self.bot)
            await interaction.response.send_message(
                "**Configuration — Niveau Basique**", view=view, ephemeral=True
            )
        else:
            view = AdvancedView(self.bot)
            await interaction.response.send_message(
                "**Configuration — Niveau Avancé**", view=view, ephemeral=True
            )
```

**Ajouter les placeholders** pour les fonctions qui seront définies en Task 5 :

```python
async def _send_twitch_config_tab(bot: "WallyDiscord", interaction: discord.Interaction) -> None:
    """Placeholder — implémenté en Task 5."""
    await interaction.response.send_message("Twitch Config — à venir", ephemeral=True)

async def _send_openai_params_tab(bot: "WallyDiscord", interaction: discord.Interaction) -> None:
    """Placeholder — implémenté en Task 5."""
    await interaction.response.send_message("OpenAI params — à venir", ephemeral=True)

async def _send_decay_tab(bot: "WallyDiscord", interaction: discord.Interaction) -> None:
    """Placeholder — implémenté en Task 5."""
    await interaction.response.send_message("Decay — à venir", ephemeral=True)
```

- [ ] **Step 4 : Lancer les tests**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/ -v --tb=short 2>&1 | tail -25
```

Expected: tous les tests passent.

- [ ] **Step 5 : Commit**

```bash
cd /opt/stacks/wally-ai && git add bot/discord/commands/setup.py tests/test_discord_commands.py
git commit -m "feat: add AdvancedTabSelect + BotGeneralView + DiscordView (advanced tabs)"
```

---

## Chunk 5 : Niveau Avancé — Twitch Config + OpenAI + Decay

---

### Task 5 : `TwitchConfigView`, `OpenAIParamsView`, `DecayView` et leurs modaux

**Files:**
- Modify: `bot/discord/commands/setup.py`
- Modify: `tests/test_discord_commands.py`

---

- [ ] **Step 1 : Écrire les tests**

Ajouter dans `tests/test_discord_commands.py` :

```python
@pytest.mark.asyncio
async def test_twitch_config_modal_saves_config():
    """TwitchConfigModal met à jour channels et cooldown_seconds."""
    from bot.discord.commands.setup import TwitchConfigModal

    bot = make_bot()
    bot.config.twitch.channels = ["Azrael_TTV"]
    bot.config.twitch.cooldown_seconds = 10
    bot.config.save = MagicMock()

    modal = TwitchConfigModal(bot)
    modal.channels._value = "Azrael_TTV, OtherStreamer"
    modal.cooldown_seconds._value = "15"

    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()

    await modal.on_submit(interaction)

    assert bot.config.twitch.channels == ["Azrael_TTV", "OtherStreamer"]
    assert bot.config.twitch.cooldown_seconds == 15
    bot.config.save.assert_called_once()


@pytest.mark.asyncio
async def test_openai_params_modal_rejects_invalid_temperature():
    """OpenAIParamsModal rejette une température hors de [0.0, 2.0]."""
    from bot.discord.commands.setup import OpenAIParamsModal

    bot = make_bot()
    bot.config.openai.temperature = 0.8
    bot.config.openai.max_tokens = 1000
    bot.config.save = MagicMock()

    modal = OpenAIParamsModal(bot)
    modal.temperature._value = "3.5"  # hors plage
    modal.max_tokens._value = "1000"

    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()

    await modal.on_submit(interaction)

    bot.config.save.assert_not_called()


@pytest.mark.asyncio
async def test_decay_modal_saves_all_lambdas():
    """DecayModal met à jour decay_lambda pour chaque émotion."""
    from bot.discord.commands.setup import DecayModal
    from bot.config import EmotionDecayConfig

    bot = make_bot()
    bot.config.emotions = {
        "anger": EmotionDecayConfig(decay_lambda=0.01),
        "joy": EmotionDecayConfig(decay_lambda=0.005),
        "sadness": EmotionDecayConfig(decay_lambda=0.008),
        "curiosity": EmotionDecayConfig(decay_lambda=0.01),
        "boredom": EmotionDecayConfig(decay_lambda=0.015),
    }
    bot.config.save = MagicMock()

    modal = DecayModal(bot)
    modal.anger._value = "0.02"
    modal.joy._value = "0.01"
    modal.sadness._value = "0.015"
    modal.curiosity._value = "0.012"
    modal.boredom._value = "0.02"

    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()

    await modal.on_submit(interaction)

    assert bot.config.emotions["anger"].decay_lambda == pytest.approx(0.02)
    assert bot.config.emotions["joy"].decay_lambda == pytest.approx(0.01)
    bot.config.save.assert_called_once()


@pytest.mark.asyncio
async def test_decay_modal_rejects_out_of_range():
    """DecayModal rejette decay_lambda hors de (0.0, 1.0)."""
    from bot.discord.commands.setup import DecayModal
    from bot.config import EmotionDecayConfig

    bot = make_bot()
    bot.config.emotions = {
        e: EmotionDecayConfig(decay_lambda=0.01)
        for e in ["anger", "joy", "sadness", "curiosity", "boredom"]
    }
    bot.config.save = MagicMock()

    modal = DecayModal(bot)
    modal.anger._value = "1.5"  # hors plage
    modal.joy._value = "0.01"
    modal.sadness._value = "0.008"
    modal.curiosity._value = "0.01"
    modal.boredom._value = "0.015"

    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()

    await modal.on_submit(interaction)

    bot.config.save.assert_not_called()
```

- [ ] **Step 2 : Lancer les tests pour vérifier qu'ils échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_discord_commands.py::test_twitch_config_modal_saves_config tests/test_discord_commands.py::test_openai_params_modal_rejects_invalid_temperature tests/test_discord_commands.py::test_decay_modal_saves_all_lambdas -v
```

Expected: `ImportError` sur `TwitchConfigModal`, `OpenAIParamsModal`, `DecayModal`.

- [ ] **Step 3 : Implémenter les classes dans `setup.py`**

Ajouter avant les placeholders `_send_twitch_config_tab` etc. :

```python
# ── Tab Avancé : Twitch Config ────────────────────────────────────────────────

class TwitchConfigModal(discord.ui.Modal, title="Configuration Twitch"):
    channels = discord.ui.TextInput(
        label="Channels Twitch (séparés par des virgules)",
        max_length=200,
    )
    cooldown_seconds = discord.ui.TextInput(
        label="Cooldown par utilisateur (secondes, ≥0)",
        max_length=5,
    )

    def __init__(self, bot: "WallyDiscord"):
        super().__init__()
        self.bot = bot
        self.channels.default = ", ".join(bot.config.twitch.channels)
        self.cooldown_seconds.default = str(bot.config.twitch.cooldown_seconds)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            cs = int(self.cooldown_seconds.value)
            if cs < 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ Cooldown invalide. Entrez un entier ≥ 0.", ephemeral=True
            )
            return
        self.bot.config.twitch.channels = [
            c.strip() for c in self.channels.value.split(",") if c.strip()
        ]
        self.bot.config.twitch.cooldown_seconds = cs
        self.bot.config.save()
        await interaction.response.send_message("✅ Config Twitch mise à jour.", ephemeral=True)


class TwitchConfigView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=120)
        self.bot = bot

    @discord.ui.button(label="Modifier config Twitch", style=discord.ButtonStyle.primary, row=0)
    async def edit_twitch(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TwitchConfigModal(self.bot))


# ── Tab Avancé : OpenAI params ────────────────────────────────────────────────

class OpenAIParamsModal(discord.ui.Modal, title="Paramètres OpenAI"):
    temperature = discord.ui.TextInput(
        label="Temperature (0.0 – 2.0)", max_length=5
    )
    max_tokens = discord.ui.TextInput(
        label="Max tokens (≥1)", max_length=6
    )

    def __init__(self, bot: "WallyDiscord"):
        super().__init__()
        self.bot = bot
        self.temperature.default = str(bot.config.openai.temperature)
        self.max_tokens.default = str(bot.config.openai.max_tokens)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            temp = float(self.temperature.value)
            mt = int(self.max_tokens.value)
            if not (0.0 <= temp <= 2.0) or mt < 1:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ Valeurs invalides. Temperature : 0.0–2.0, max_tokens : entier ≥ 1.",
                ephemeral=True,
            )
            return
        self.bot.config.openai.temperature = temp
        self.bot.config.openai.max_tokens = mt
        self.bot.config.save()
        await interaction.response.send_message(
            f"✅ Temperature : {temp}, max_tokens : {mt}.", ephemeral=True
        )


class OpenAIParamsView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=120)
        self.bot = bot

    @discord.ui.button(label="Modifier paramètres OpenAI", style=discord.ButtonStyle.primary, row=0)
    async def edit_openai(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(OpenAIParamsModal(self.bot))


# ── Tab Avancé : Decay émotions ───────────────────────────────────────────────

class DecayModal(discord.ui.Modal, title="Decay des émotions (λ)"):
    anger = discord.ui.TextInput(label="anger decay_lambda (0 < x < 1)", max_length=6)
    joy = discord.ui.TextInput(label="joy decay_lambda (0 < x < 1)", max_length=6)
    sadness = discord.ui.TextInput(label="sadness decay_lambda (0 < x < 1)", max_length=6)
    curiosity = discord.ui.TextInput(label="curiosity decay_lambda (0 < x < 1)", max_length=6)
    boredom = discord.ui.TextInput(label="boredom decay_lambda (0 < x < 1)", max_length=6)

    def __init__(self, bot: "WallyDiscord"):
        super().__init__()
        self.bot = bot
        emotions = bot.config.emotions
        self.anger.default = str(emotions["anger"].decay_lambda)
        self.joy.default = str(emotions["joy"].decay_lambda)
        self.sadness.default = str(emotions["sadness"].decay_lambda)
        self.curiosity.default = str(emotions["curiosity"].decay_lambda)
        self.boredom.default = str(emotions["boredom"].decay_lambda)

    async def on_submit(self, interaction: discord.Interaction):
        raw = {
            "anger": self.anger.value,
            "joy": self.joy.value,
            "sadness": self.sadness.value,
            "curiosity": self.curiosity.value,
            "boredom": self.boredom.value,
        }
        try:
            parsed = {k: float(v) for k, v in raw.items()}
            if any(not (0.0 < v < 1.0) for v in parsed.values()):
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ Valeurs invalides. Chaque λ doit être un float entre 0.0 et 1.0 (exclus).",
                ephemeral=True,
            )
            return
        for emotion, value in parsed.items():
            self.bot.config.emotions[emotion].decay_lambda = value
        self.bot.config.save()
        await interaction.response.send_message("✅ Decay des émotions mis à jour.", ephemeral=True)


class DecayView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=120)
        self.bot = bot

    @discord.ui.button(label="Modifier decay", style=discord.ButtonStyle.primary, row=0)
    async def edit_decay(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DecayModal(self.bot))
```

**Remplacer les 3 placeholders** par les implémentations finales :

```python
async def _send_twitch_config_tab(bot: "WallyDiscord", interaction: discord.Interaction) -> None:
    cfg = bot.config.twitch
    lines = [
        "**Twitch Config**",
        f"Channels : {', '.join(cfg.channels)}",
        f"Cooldown : {cfg.cooldown_seconds}s",
    ]
    view = TwitchConfigView(bot)
    await interaction.response.send_message("\n".join(lines), view=view, ephemeral=True)


async def _send_openai_params_tab(bot: "WallyDiscord", interaction: discord.Interaction) -> None:
    cfg = bot.config.openai
    lines = [
        "**Paramètres OpenAI**",
        f"Temperature : {cfg.temperature}",
        f"Max tokens : {cfg.max_tokens}",
    ]
    view = OpenAIParamsView(bot)
    await interaction.response.send_message("\n".join(lines), view=view, ephemeral=True)


async def _send_decay_tab(bot: "WallyDiscord", interaction: discord.Interaction) -> None:
    emotions = bot.config.emotions
    lines = ["**Decay des émotions (λ)**"] + [
        f"**{e}** : {cfg.decay_lambda}" for e, cfg in emotions.items()
    ]
    view = DecayView(bot)
    await interaction.response.send_message("\n".join(lines), view=view, ephemeral=True)
```

- [ ] **Step 4 : Lancer tous les tests**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/ -v --tb=short 2>&1 | tail -25
```

Expected: tous les tests passent (≥ 124 passed).

- [ ] **Step 5 : Vérifier que le message d'accueil du /setup affiche le warning .env**

Ajouter dans `tests/test_discord_commands.py` :

```python
@pytest.mark.asyncio
async def test_setup_command_warns_if_env_incomplete(monkeypatch):
    """Le message d'accueil de /setup liste les clés .env manquantes."""
    import bot.discord.commands.setup as setup_module
    monkeypatch.setattr(setup_module, "is_env_complete", lambda path=".env": ["OPENAI_API_KEY"])

    bot_obj = make_bot()
    cog = SetupCog(bot_obj)
    interaction = make_interaction()

    await cog.setup.callback(cog, interaction)

    call_args = interaction.response.send_message.call_args
    content = call_args.args[0] if call_args.args else call_args.kwargs.get("content", "")
    assert "OPENAI_API_KEY" in content
```

Mettre à jour `SetupCog.setup` pour inclure le warning. Le format exact de la ligne de warning
est `f"⚠️ Clés `.env` manquantes : {', '.join(missing)}"` — les noms de clés sont inclus
explicitement (ex: `OPENAI_API_KEY`), ce qui permet à `test_setup_command_warns_if_env_incomplete`
d'asserter `"OPENAI_API_KEY" in content`.

```python
@app_commands.command(
    name="setup", description="Panneau de configuration de Wally (admin)"
)
@app_commands.default_permissions(administrator=True)
async def setup(self, interaction: discord.Interaction):
    missing = is_env_complete()
    if missing:
        content = (
            "**Configuration de Wally** — Sélectionnez un niveau :\n"
            f"⚠️ Clés `.env` manquantes : {', '.join(missing)}"
        )
    else:
        content = "**Configuration de Wally** — Sélectionnez un niveau :"
    view = SetupView(self.bot)
    await interaction.response.send_message(content, view=view, ephemeral=True)
```

- [ ] **Step 6 : Lancer tous les tests en final**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: tous les tests passent.

- [ ] **Step 7 : Commit final**

```bash
cd /opt/stacks/wally-ai && git add bot/discord/commands/setup.py tests/test_discord_commands.py
git commit -m "feat: add Twitch config, OpenAI params, decay tabs + .env warning in /setup"
```
