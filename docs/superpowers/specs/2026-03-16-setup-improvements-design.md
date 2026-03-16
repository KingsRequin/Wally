# Spec — /wally setup : couverture complète config + .env

**Date :** 2026-03-16
**Statut :** Approuvé

---

## Contexte

La commande `/wally setup` expose actuellement 5 onglets via `SetupTabSelect` directement dans
`SetupView`. De nombreuses options du `config.yaml` et du `.env` ne sont pas configurables sans
éditer les fichiers manuellement.

---

## Objectifs

1. Exposer **toutes** les options du `config.yaml` dans `/setup`.
2. Permettre la **configuration du `.env`** directement depuis Discord (écriture sur disque).
3. Détecter automatiquement les clés `.env` manquantes au lancement de `/setup`.
4. Ajouter un bouton de **redémarrage du bot** (avec confirmation).

---

## Migration de l'existant

`SetupTabSelect` est **supprimé** de `SetupView`. Sa logique (5 onglets existants) est migrée dans
`BasicTabSelect`. `SetupView` est réécrit pour contenir `LevelSelect` + `RestartButton`.

**Tests à mettre à jour :**
- `tests/test_discord_commands.py` — `test_setup_view_has_select` : assertion `len(view.children) == 1`
  → passer à `== 2` (LevelSelect + RestartButton)
- `tests/test_discord_commands.py` — `test_setup_mood_tab_displays_percentage` : import et
  instanciation directe de `SetupTabSelect` → remplacer par `BasicTabSelect`
- Import `SetupView` depuis `bot.discord.commands.setup` → inchangé (classe conservée, réécrite)

---

## Architecture générale

```
/wally setup
  └── SetupView (timeout=180)
       ├── LevelSelect (row=0)   — Basique | Avancé
       └── RestartButton (row=1) — 🔄 Redémarrer le bot
```

### Modèle de navigation (3 niveaux de messages ephemerals)

- **Message A** : `SetupView` — sélecteur de niveau + bouton restart
  - Si clés `.env` manquantes → affiche : `⚠️ Clés manquantes : KEY1, KEY2`
- **Message B** : sélection dans `LevelSelect` → `interaction.response.send_message()` envoie un
  nouveau message ephemeral avec `BasicView` ou `AdvancedView`
- **Message C** : sélection d'un onglet dans B → nouveau message ephemeral avec la View de l'onglet

Règle : chaque `Select.callback()` ou `Button.callback()` appelle `interaction.response.send_message()`
exactement une fois. Pas d'`edit_message`. L'accumulation de messages ephemerals est intentionnelle
(ils ne sont visibles que de l'admin, disparaissent en fermeture de session ou au dismiss).

### Nouvelles Views conteneurs de niveau

- **`BasicView`** (timeout=120) : contient uniquement `BasicTabSelect`
- **`AdvancedView`** (timeout=120) : contient uniquement `AdvancedTabSelect`

---

## Niveau Basique — `BasicTabSelect`

*(migré depuis l'existant `SetupTabSelect` + ajout de l'onglet .env)*

| Option | Valeur | Contenu |
|--------|--------|---------|
| 🤖 Modèle IA | `model` | Sélection modèle principal / secondaire (inchangé) |
| 😊 Humeur | `mood` | Contrôle manuel des émotions +/- / Edit / Reset (inchangé) |
| 📢 Noms déclencheurs | `triggers` | Ajout / suppression des trigger names (inchangé) |
| 🎮 Twitch Events | `twitch` | Toggle actif/inactif + édition message (inchangé) |
| 🧠 Mémoire | `memory` | Réinitialisation mémoire court/long terme (inchangé) |
| 🔑 Variables d'env | `env` | Configuration .env (badge ⚠️ si clés manquantes) |

---

## Niveau Avancé — `AdvancedTabSelect`

| Option | Valeur | Contenu |
|--------|--------|---------|
| ⚙️ Bot Général | `bot` | Paramètres généraux + channel journal |
| 💬 Discord | `discord` | Colère/timeout + gestion filtres channels |
| 🟣 Twitch Config | `twitch_cfg` | channels, cooldown_seconds |
| 🤖 OpenAI (params) | `openai` | temperature, max_tokens |
| 💭 Decay émotions | `decay` | decay_lambda par émotion |

*"🎮 Twitch Events" (Basique) = messages d'événements. "🟣 Twitch Config" (Avancé) = connexion et
cooldown. `trigger_names` est dans Basique → 📢 Noms déclencheurs, non dupliqué dans Bot Général.*

---

## Détail : Configuration `.env`

### Inventaire des clés `.env`

| Statut | Clés |
|--------|------|
| **Éditables** (12) | `OPENAI_API_KEY`, `DISCORD_TOKEN`, `DISCORD_GUILD_ID`, `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`, `TWITCH_BROADCASTER_ID`, `TWITCH_BOT_ID`, `TWITCH_BOT_NICK`, `BOT_ACCESS_TOKEN`, `BOT_REFRESH_TOKEN`, `STREAMER_ACCESS_TOKEN`, `STREAMER_REFRESH_TOKEN` |
| **Non éditables** | `QDRANT_URL` (URL Docker interne), `DB_PATH` (chemin volume SQLite) |

### Modaux `.env` — 4 classes distinctes

Discord.py exige que les `TextInput` soient déclarés en attributs de classe. Chaque groupe est
donc une **classe modale distincte** (pas de modal générique paramétré) :

| Classe | Bouton (EnvView row) | Champs TextInput |
|--------|----------------------|------------------|
| `EnvOpenAIModal` | row=0 | `OPENAI_API_KEY` |
| `EnvDiscordModal` | row=1 | `DISCORD_TOKEN`, `DISCORD_GUILD_ID` |
| `EnvTwitchIdModal` | row=2 | `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`, `TWITCH_BROADCASTER_ID`, `TWITCH_BOT_ID`, `TWITCH_BOT_NICK` |
| `EnvTwitchTokensModal` | row=3 | `BOT_ACCESS_TOKEN`, `BOT_REFRESH_TOKEN`, `STREAMER_ACCESS_TOKEN`, `STREAMER_REFRESH_TOKEN` |

**`EnvView`** (timeout=120) : 4 boutons, rows 0–3, aucun autre composant.

### Pré-remplissage des modaux `.env`

Avant d'ouvrir le modal, lire toutes les valeurs avec `read_env_values(".env")` → `dict[str, str]`.
Pré-remplir chaque `TextInput` via `default=values.get(KEY, "")`.

### Flux de sauvegarde `.env`

1. Valeurs actuelles pré-remplies (`default=`) via `read_env_values`.
2. Soumission → `update_env_file(".env", updates)` → mise à jour sur disque.
3. **Important :** l'écriture sur disque ne met pas à jour `os.environ` en mémoire.
   Message de confirmation : "✅ Sauvegardé. Les changements s'appliqueront au prochain démarrage."
4. Bouton **"Redémarrer maintenant"** (`ConfirmRestartView`) proposé dans le même message.

### Détection automatique des clés manquantes — `is_env_complete(path=".env")`

- Vérifie uniquement les **12 clés éditables** (pas `QDRANT_URL` ni `DB_PATH`).
- Si le fichier n'existe pas (`FileNotFoundError`) → retourne les 12 clés comme manquantes.
- Sinon, utilise `read_env_values` et considère manquante toute clé absente ou dont la valeur est vide.
- Retourne `list[str]` des clés manquantes/vides.

### Fonctions utilitaires `.env`

```
read_env_values(path: str) -> dict[str, str]
```
Lit le fichier `.env` (chemin relatif au CWD), retourne un dict de toutes les paires `KEY=value`.
Les lignes commençant par `#` (commentaires) et les lignes vides sont ignorées.
Retourne un dict vide si le fichier n'existe pas (`FileNotFoundError`).

```
update_env_file(path: str, updates: dict[str, str]) -> None
```
- Lit ligne par ligne. Pour chaque `KEY=value` : si `KEY ∈ updates`, remplace la valeur.
- Ajoute en fin de fichier les clés de `updates` absentes.
- Écrit en place (overwrite synchrone).
- *Limitation acceptée :* pas de verrou fichier. Usage admin-only, conteneur unique.

```
is_env_complete(path: str = ".env") -> list[str]
```
Voir ci-dessus.

### Chemin `.env`

Chemin relatif `".env"` = relatif au répertoire de travail du process (CWD = `/app` en Docker,
identique à l'emplacement de `config.yaml`). Ne pas résoudre via `__file__`.

---

## Détail : Nouveaux onglets Avancés

### ⚙️ Bot Général — `BotGeneralView` (timeout=120)

| Row | Composant |
|-----|-----------|
| 0 | Bouton "Modifier paramètres généraux" → `BotGeneralModal` |
| 1 | Bouton "Définir channel journal" → `JournalChannelModal` |

**`BotGeneralModal`** (5 champs) : `language_default` (str), `context_window_size` (int ≥ 1),
`context_token_threshold` (int ≥ 1), `journal_time` (str HH:MM), `prelude_window_size` (int ≥ 1)

**`JournalChannelModal`** (1 champ) : `journal_channel_id` (int > 0, Discord channel ID)
Input vide → `config.bot.journal_channel_id = None` (efface le channel configuré).

*`dashboard_token` non exposé — dashboard non implémenté (cf. CLAUDE.md).*

### 💬 Discord — `DiscordView` (timeout=120)

Un seul View contient tous les composants Discord (pas de View imbriquée) :

| Row | Composant |
|-----|-----------|
| 0 | Bouton "Colère & timeout" → `DiscordParamsModal` |
| 1 | Bouton toggle `channel_filter_mode` (blacklist ↔ whitelist) — label dynamique |
| 2 | Bouton "Modifier la blacklist" → `EditChannelListModal(list_type="blacklist")` |
| 3 | Bouton "Modifier la whitelist" → `EditChannelListModal(list_type="whitelist")` |

**`DiscordParamsModal`** (2 champs) : `anger_trigger_threshold` (int ≥ 1), `timeout_minutes` (int ≥ 1)

**`EditChannelListModal`** (1 champ) : `TextInput` label "IDs des channels (séparés par des virgules)",
valeur par défaut = liste actuelle jointe par `,`. Sur soumission :
```python
ids = [int(x.strip()) for x in raw.split(",") if x.strip()]
# Valider que chaque valeur est un int > 0 ; si erreur → message d'erreur, no save
if list_type == "blacklist":
    config.discord.channel_blacklist = ids
else:
    config.discord.channel_whitelist = ids
config.save()
```
*Remplace l'intégralité de la liste à chaque soumission.* C'est le même pattern que le `TwitchConfigModal`
pour `channels`.

### 🟣 Twitch Config — `TwitchConfigView` (timeout=120)

| Row | Composant |
|-----|-----------|
| 0 | Bouton "Modifier config Twitch" → `TwitchConfigModal` |

**`TwitchConfigModal`** (2 champs) :
- `channels` (str, virgule-séparés) — round-trip :
  `config.twitch.channels = [c.strip() for c in raw.split(",") if c.strip()]`
- `cooldown_seconds` (int ≥ 0)

### 🤖 OpenAI (params) — `OpenAIParamsView` (timeout=120)

| Row | Composant |
|-----|-----------|
| 0 | Bouton "Modifier paramètres OpenAI" → `OpenAIParamsModal` |

**`OpenAIParamsModal`** (2 champs) : `temperature` (float 0.0–2.0), `max_tokens` (int ≥ 1)

### 💭 Decay émotions — `DecayView` (timeout=120)

| Row | Composant |
|-----|-----------|
| 0 | Bouton "Modifier decay" → `DecayModal` |

**`DecayModal`** (5 champs) : `decay_lambda` pour `anger`, `joy`, `sadness`, `curiosity`, `boredom`
(float, 0.0 < x < 1.0)

---

## Validation des champs numériques

Stratégie uniforme : valeur invalide → message ephemeral d'erreur, pas de `config.save()`.

| Champ | Type | Contrainte |
|-------|------|------------|
| `context_window_size` | int | ≥ 1 |
| `context_token_threshold` | int | ≥ 1 |
| `prelude_window_size` | int | ≥ 1 |
| `anger_trigger_threshold` | int | ≥ 1 |
| `timeout_minutes` | int | ≥ 1 |
| `cooldown_seconds` | int | ≥ 0 |
| `max_tokens` | int | ≥ 1 |
| `temperature` | float | 0.0 ≤ x ≤ 2.0 |
| `decay_lambda` | float | 0.0 < x < 1.0 |
| `journal_channel_id` | int | > 0 |
| channel IDs (whitelist/blacklist) | int | > 0, chaque ID |

---

## Redémarrage du bot

- **`RestartButton`** dans `SetupView` (row=1).
- Clic → `ConfirmRestartView` (timeout=30s) envoyé en nouveau message ephemeral :
  - Bouton "✅ Confirmer" (danger, row=0), Bouton "❌ Annuler" (secondary, row=0)
- **Séquence de confirmation :**
  ```python
  import os, asyncio
  await interaction.response.send_message("🔄 Redémarrage en cours...", ephemeral=True)
  asyncio.get_running_loop().call_later(1.0, os._exit, 0)
  ```
  `os._exit(0)` termine le process sans propager `SystemExit` dans asyncio.
  `call_later(1.0, ...)` laisse 1 seconde pour que Discord reçoive la réponse HTTP.
  `get_running_loop()` (Python 3.10+) remplace le deprecated `get_event_loop()`.
- **`ConfirmRestartView.on_timeout`** : non défini — expiration silencieuse, les boutons deviennent
  inactifs naturellement. Acceptable car l'admin voit les boutons griser.
- Annulation → message "Redémarrage annulé." ephemeral.
- *Imports requis dans `setup.py` :* `import asyncio`, `import os` (`sys` non nécessaire)

*Le bouton restart est également proposé après toute sauvegarde du `.env`.*

---

## Timeouts des Views

| View | Timeout | Comportement on_timeout |
|------|---------|-------------------------|
| `SetupView` | 180s | (non défini, expiration silencieuse) |
| `ConfirmRestartView` | 30s | (non défini, expiration silencieuse) |
| `BasicView`, `AdvancedView` | 120s | (non défini) |
| `EnvView` | 120s | (non défini) |
| Toutes autres nouvelles Views | 120s | (non défini) |
| Views existantes | inchangés | inchangés |

---

## Implémentation — Fichiers modifiés

### `bot/discord/commands/setup.py`

- `SetupTabSelect` supprimé
- `SetupView` réécrit (LevelSelect + RestartButton)
- Nouvelles classes ajoutées (voir table ci-dessous)

### `tests/test_discord_commands.py`

- `test_setup_view_has_select` : `assert len(view.children) == 2`
- `test_setup_mood_tab_displays_percentage` : remplacer `SetupTabSelect` par `BasicTabSelect`
  dans l'import et l'instanciation. `BasicTabSelect.__init__` reçoit `bot` mais n'accède pas à
  `bot.config.twitch_events` à la construction (seul le callback du tab "twitch" crée `TwitchEventsView`).
- Import : ajouter `BasicTabSelect` à l'import depuis `bot.discord.commands.setup`

### Nouvelles classes

| Classe | Type | Rôle |
|--------|------|------|
| `LevelSelect` | Select | Basique / Avancé dans SetupView |
| `RestartButton` | Button | Redémarrage dans SetupView |
| `ConfirmRestartView` | View | Confirmation redémarrage (timeout=30s) |
| `BasicView` | View | Conteneur de BasicTabSelect |
| `BasicTabSelect` | Select | 6 onglets niveau Basique |
| `AdvancedView` | View | Conteneur de AdvancedTabSelect |
| `AdvancedTabSelect` | Select | 5 onglets niveau Avancé |
| `EnvView` | View | 4 boutons groupes .env |
| `EnvOpenAIModal` | Modal | 1 champ OPENAI_API_KEY |
| `EnvDiscordModal` | Modal | 2 champs Discord |
| `EnvTwitchIdModal` | Modal | 5 champs identité Twitch |
| `EnvTwitchTokensModal` | Modal | 4 champs tokens Twitch |
| `BotGeneralView` | View | Boutons Bot Général |
| `BotGeneralModal` | Modal | 5 champs paramètres bot |
| `JournalChannelModal` | Modal | 1 champ journal_channel_id |
| `DiscordView` | View | 4 composants Discord |
| `DiscordParamsModal` | Modal | anger + timeout |
| `EditChannelListModal` | Modal | 1 champ liste IDs (blacklist ou whitelist) |
| `TwitchConfigView` | View | Bouton config Twitch |
| `TwitchConfigModal` | Modal | channels + cooldown |
| `OpenAIParamsView` | View | Bouton params OpenAI |
| `OpenAIParamsModal` | Modal | temperature + max_tokens |
| `DecayView` | View | Bouton decay émotions |
| `DecayModal` | Modal | 5 decay_lambda |

### Fonctions utilitaires (module-level dans setup.py)

- `read_env_values(path: str = ".env") -> dict[str, str]`
- `update_env_file(path: str, updates: dict[str, str]) -> None`
- `is_env_complete(path: str = ".env") -> list[str]`

### Contraintes Discord respectées

- Max 5 `TextInput` par modal ✓
- Max 25 options par `Select` ✓
- Max 5 lignes (rows) par `View` ✓
- `interaction.response` appelé une seule fois par interaction ✓
- `TextInput` déclarés en attributs de classe (pas dynamiques) ✓

---

## Tests

**Nouveaux tests :**
- `read_env_values` : fichier complet, fichier vide, fichier absent, lignes commentées
- `update_env_file` : mise à jour valeur existante, ajout clé absente, fichier vide
- `is_env_complete` : toutes présentes, clés manquantes, valeurs vides, fichier absent

**Tests à mettre à jour :**
- `test_setup_view_has_select` : `len(view.children) == 2`
- `test_setup_mood_tab_displays_percentage` : `BasicTabSelect` au lieu de `SetupTabSelect`
