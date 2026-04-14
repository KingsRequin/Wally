# Setup Command Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scinder `bot/discord/commands/setup.py` (1218 lignes) en un sous-dossier `setup/` composé de 5 fichiers focalisés, sans aucun changement de comportement.

**Architecture:** `setup/utils.py` (env + ConfirmRestartView) → `setup/env.py` (onglet .env) → `setup/basic.py` (onglets basiques) → `setup/advanced.py` (onglets avancés) → `setup/__init__.py` (SetupCog, exports). Les imports de `env.py` depuis `basic.py` se font en lazy import dans la méthode callback pour éviter le risque de cycle.

**Tech Stack:** Python, discord.py

---

## File Map

| Fichier | Action |
|---|---|
| `bot/discord/commands/setup/utils.py` | Créer — constantes env, utilitaires .env, ConfirmRestartView |
| `bot/discord/commands/setup/env.py` | Créer — onglet Variables d'env |
| `bot/discord/commands/setup/basic.py` | Créer — onglets basiques (humeur, Twitch events, triggers, modèle, mémoire) |
| `bot/discord/commands/setup/advanced.py` | Créer — onglets avancés (bot général, Discord, Twitch, OpenAI, decay) |
| `bot/discord/commands/setup/__init__.py` | Créer — LevelSelect, RestartButton, SetupView, SetupCog |
| `bot/discord/commands/setup.py` | Supprimer après vérification |

---

### Task 1 : Créer `setup/utils.py`

**Files:**
- Create: `bot/discord/commands/setup/utils.py`

Contient : `EDITABLE_ENV_KEYS`, `read_env_values`, `update_env_file`, `is_env_complete`, `is_valid_model`, `ConfirmRestartView`.

Source : lignes 17–97 + 438–450 de `bot/discord/commands/setup.py`.

- [ ] **Step 1 : Lire les lignes source**

```bash
sed -n '1,97p' /opt/stacks/wally-ai/bot/discord/commands/setup.py
sed -n '436,450p' /opt/stacks/wally-ai/bot/discord/commands/setup.py
```

- [ ] **Step 2 : Créer le dossier et utils.py**

```bash
mkdir -p /opt/stacks/wally-ai/bot/discord/commands/setup
```

```python
# bot/discord/commands/setup/utils.py
from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

import discord

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


def is_valid_model(model_id: str) -> bool:
    excluded = ["realtime", "preview", "audio", "vision"]
    included = ["gpt", "chatgpt", "o1", "o3", "o4"]
    mid = model_id.lower()
    if any(ex in mid for ex in excluded):
        return False
    return any(inc in mid for inc in included)


# ── Restart confirmation ──────────────────────────────────────────────────────

class ConfirmRestartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=30)

    @discord.ui.button(label="✅ Confirmer", style=discord.ButtonStyle.danger, row=0)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🔄 Redémarrage en cours...", ephemeral=True)
        asyncio.get_running_loop().call_later(1.0, os._exit, 0)

    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.secondary, row=0)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Redémarrage annulé.", ephemeral=True)
```

- [ ] **Step 3 : Vérifier l'import**

```bash
cd /opt/stacks/wally-ai && python3 -c "from bot.discord.commands.setup.utils import read_env_values, is_valid_model, ConfirmRestartView; print('OK')"
```

Attendu : `OK`

---

### Task 2 : Créer `setup/env.py`

**Files:**
- Create: `bot/discord/commands/setup/env.py`

Contient tout l'onglet `.env` : `EnvOpenAIModal`, `EnvDiscordModal`, `EnvTwitchIdModal`, `EnvTwitchTokensModal`, `EnvOpenAIButton`, `EnvDiscordButton`, `EnvTwitchIdButton`, `EnvTwitchTokensButton`, `EnvView`, `_send_env_tab`.

Source : lignes 983–1147 de `setup.py`.

- [ ] **Step 1 : Lire les lignes source**

```bash
sed -n '983,1147p' /opt/stacks/wally-ai/bot/discord/commands/setup.py
```

- [ ] **Step 2 : Créer env.py**

Copier le contenu exact des lignes 983–1147 avec ces imports en tête :

```python
# bot/discord/commands/setup/env.py
from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from bot.discord.commands.setup.utils import (
    ConfirmRestartView,
    read_env_values,
    update_env_file,
    is_env_complete,
)

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord
```

Puis coller le code des classes et de `_send_env_tab` (les lignes 985–1147), en supprimant les lignes qui redéfinissent les imports ou les constantes déjà dans utils.py.

- [ ] **Step 3 : Vérifier l'import**

```bash
cd /opt/stacks/wally-ai && python3 -c "from bot.discord.commands.setup.env import _send_env_tab, EnvView; print('OK')"
```

Attendu : `OK`

---

### Task 3 : Créer `setup/basic.py`

**Files:**
- Create: `bot/discord/commands/setup/basic.py`

Contient : `_EMOTIONS`, onglet Humeur (EditEmotionModal, EmotionMinusButton, EmotionPlusButton, EmotionEditButton, ResetMoodButton, MoodView), onglet Twitch Events (EditEventMessageModal, ToggleEventButton, EditEventButton, TwitchEventsView), onglet Trigger Names (AddTriggerModal, AddTriggerButton, RemoveTriggerButton, TriggerNamesView), onglet Modèle (PrimaryModelSelect, SecondaryModelSelect, ModelSelectView, _send_model_tab), onglet Mémoire (ResetMemoryButton, MemoryView), `BasicTabSelect`, `BasicView`.

Source : lignes 99–517 de `setup.py`.

- [ ] **Step 1 : Lire les lignes source**

```bash
sed -n '99,517p' /opt/stacks/wally-ai/bot/discord/commands/setup.py
```

- [ ] **Step 2 : Créer basic.py**

```python
# bot/discord/commands/setup/basic.py
from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from loguru import logger

from bot.discord.commands.setup.utils import is_valid_model

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord
```

Puis coller le code exact des lignes 99–517.

Dans `BasicTabSelect.callback()`, remplacer l'appel à `_send_env_tab` (ligne 510) par un lazy import :

```python
        elif tab == "env":
            from bot.discord.commands.setup.env import _send_env_tab
            await _send_env_tab(self.bot, interaction)
```

- [ ] **Step 3 : Vérifier l'import**

```bash
cd /opt/stacks/wally-ai && python3 -c "from bot.discord.commands.setup.basic import BasicView, MoodView; print('OK')"
```

Attendu : `OK`

---

### Task 4 : Créer `setup/advanced.py`

**Files:**
- Create: `bot/discord/commands/setup/advanced.py`

Contient : `_REASONING_EFFORTS`, `_TEXT_VERBOSITIES`, tous les composants avancés (BotGeneralModal, JournalChannelModal, BotGeneralView, DiscordParamsModal, EditChannelListModal, DiscordView, TwitchConfigModal, TwitchConfigView, OpenAIParamsModal, OpenAIParamsView, DecayModal, DecayView, _send_twitch_config_tab, _send_openai_params_tab, _send_decay_tab, AdvancedTabSelect, AdvancedView).

Source : lignes 519–981 de `setup.py`.

- [ ] **Step 1 : Lire les lignes source**

```bash
sed -n '519,981p' /opt/stacks/wally-ai/bot/discord/commands/setup.py
```

- [ ] **Step 2 : Créer advanced.py**

```python
# bot/discord/commands/setup/advanced.py
from __future__ import annotations

import re
from typing import TYPE_CHECKING

import discord
from loguru import logger

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord
```

Puis coller le code exact des lignes 519–981.

- [ ] **Step 3 : Vérifier l'import**

```bash
cd /opt/stacks/wally-ai && python3 -c "from bot.discord.commands.setup.advanced import AdvancedView, DecayModal; print('OK')"
```

Attendu : `OK`

---

### Task 5 : Créer `setup/__init__.py` et supprimer l'ancien setup.py

**Files:**
- Create: `bot/discord/commands/setup/__init__.py`
- Delete: `bot/discord/commands/setup.py`

`__init__.py` contient : `LevelSelect`, `RestartButton`, `SetupView`, `SetupCog`. Expose aussi `SetupCog` comme export principal du package.

Source : lignes 1149–1219 de `setup.py`.

- [ ] **Step 1 : Lire les lignes source**

```bash
sed -n '1149,1219p' /opt/stacks/wally-ai/bot/discord/commands/setup.py
```

- [ ] **Step 2 : Créer `__init__.py`**

```python
# bot/discord/commands/setup/__init__.py
from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from bot.discord.commands.setup.utils import is_env_complete, ConfirmRestartView
from bot.discord.commands.setup.basic import BasicView
from bot.discord.commands.setup.advanced import AdvancedView

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord
```

Puis coller le code exact des lignes 1149–1219 (`LevelSelect`, `RestartButton`, `SetupView`, `SetupCog`).

- [ ] **Step 3 : Vérifier que le package s'importe correctement**

```bash
cd /opt/stacks/wally-ai && python3 -c "from bot.discord.commands.setup import SetupCog; print('OK')"
```

Attendu : `OK`

- [ ] **Step 4 : Vérifier que l'import existant dans bot.py fonctionne**

```bash
grep -n "setup" /opt/stacks/wally-ai/bot/discord/bot.py
```

Si `bot.py` importe depuis `bot.discord.commands.setup` (chemin du module), l'import reste valide car `bot/discord/commands/setup/__init__.py` exporte `SetupCog`. Si l'import est `from bot.discord.commands import setup as setup_module` suivi de `setup_module.SetupCog`, ça marche aussi.

- [ ] **Step 5 : Supprimer l'ancien setup.py**

```bash
rm /opt/stacks/wally-ai/bot/discord/commands/setup.py
```

- [ ] **Step 6 : Import final et tests**

```bash
cd /opt/stacks/wally-ai && python3 -c "from bot.discord.commands.setup import SetupCog; print('OK')"
cd /opt/stacks/wally-ai && python3 -m pytest tests/ -x -q --ignore=tests/test_dashboard_costs.py 2>&1 | tail -5
```

Attendu : `OK` puis tous verts.

- [ ] **Step 7 : Commit**

```bash
cd /opt/stacks/wally-ai
git add bot/discord/commands/setup/
git rm bot/discord/commands/setup.py
git commit -m "refactor(discord): split setup.py into setup/ subfolder (utils, basic, advanced, env)"
```
