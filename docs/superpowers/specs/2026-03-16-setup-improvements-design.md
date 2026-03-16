# Spec — /wally setup : couverture complète config + .env

**Date :** 2026-03-16
**Statut :** Approuvé

---

## Contexte

La commande `/wally setup` expose actuellement 5 onglets (Modèle IA, Humeur, Noms déclencheurs,
Événements Twitch, Mémoire). De nombreuses options du `config.yaml` (paramètres Discord, Twitch,
OpenAI, decay des émotions, paramètres bot) ne sont pas configurables sans éditer le fichier
manuellement. Le `.env` (tokens et clés API) est également hors de portée du setup Discord.

---

## Objectifs

1. Exposer **toutes** les options du `config.yaml` dans `/setup`.
2. Permettre la **configuration du `.env`** directement depuis Discord (écriture sur disque).
3. Détecter automatiquement les clés `.env` manquantes au lancement de `/setup`.
4. Ajouter un bouton de **redémarrage du bot** (avec confirmation).

---

## Architecture générale

```
/wally setup
  └── SetupView
       ├── LevelSelect      — Basique | Avancé
       └── RestartButton    — 🔄 Redémarrer le bot (avec confirmation)

Message d'accueil :
  ├── ⚠️ Warning si clés .env manquantes (liste des clés absentes)
  └── Suggestion automatique de l'onglet "Variables d'environnement"
```

### Niveau Basique — `BasicTabSelect`

| Onglet | Contenu |
|--------|---------|
| 🤖 Modèle IA | Sélection modèle principal / secondaire (existant) |
| 😊 Humeur | Contrôle manuel des émotions +/- / Edit / Reset (existant) |
| 📢 Noms déclencheurs | Ajout / suppression des trigger names (existant) |
| 🎮 Événements Twitch | Toggle actif/inactif + édition message (existant) |
| 🧠 Mémoire | Réinitialisation mémoire court/long terme (existant) |
| 🔑 Variables d'env | Configuration .env (badge ⚠️ si clés manquantes) |

### Niveau Avancé — `AdvancedTabSelect`

| Onglet | Contenu |
|--------|---------|
| ⚙️ Bot Général | language_default, context_window_size, context_token_threshold, journal_time, prelude_window_size, journal_channel_id |
| 💬 Discord | anger_trigger_threshold, timeout_minutes, channel_filter_mode (toggle), gestion whitelist/blacklist |
| 🎮 Twitch | channels (liste séparée par virgules), cooldown_seconds |
| 🤖 OpenAI (params) | temperature, max_tokens |
| 💭 Decay émotions | decay_lambda par émotion (anger, joy, sadness, curiosity, boredom) |

---

## Détail : Configuration `.env`

### Clés éditables (12)

Réparties en 4 groupes (contrainte Discord : max 5 champs par modal) :

| Bouton | Modal | Clés |
|--------|-------|------|
| OpenAI | Modal 1 | `OPENAI_API_KEY` |
| Discord | Modal 2 | `DISCORD_TOKEN`, `DISCORD_GUILD_ID` |
| Twitch — Identité | Modal 3 | `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`, `TWITCH_BROADCASTER_ID`, `TWITCH_BOT_ID`, `TWITCH_BOT_NICK` |
| Twitch — Tokens | Modal 4 | `BOT_ACCESS_TOKEN`, `BOT_REFRESH_TOKEN`, `STREAMER_ACCESS_TOKEN`, `STREAMER_REFRESH_TOKEN` |

### Clés non éditables (infrastructure Docker)
- `QDRANT_URL` — URL interne du réseau Docker
- `DB_PATH` — chemin du volume SQLite

### Flux de sauvegarde `.env`

1. Valeurs actuelles pré-remplies dans les champs des modals.
2. Soumission → parser le `.env` ligne par ligne → mettre à jour les valeurs existantes, ajouter les clés absentes.
3. Message de confirmation + bouton **"Redémarrer maintenant"**.

### Détection automatique

À chaque invocation de `/setup` :
- Lire le `.env` et vérifier que les 12 clés éditables sont présentes et non-vides.
- Si manquantes → afficher dans le message d'accueil : `⚠️ Clés manquantes : OPENAI_API_KEY, ...`
- Suggestion : "Configurez-les via l'onglet **🔑 Variables d'environnement** (Basique)."

---

## Détail : Nouveaux onglets Avancés

### ⚙️ Bot Général

- **Modal 1** (5 champs) : `language_default` (str), `context_window_size` (int),
  `context_token_threshold` (int), `journal_time` (str, format HH:MM), `prelude_window_size` (int)
- **Bouton séparé** "Définir channel journal" → Modal 1 champ : `journal_channel_id` (int Discord ID)

### 💬 Discord

- **Modal 1** (2 champs) : `anger_trigger_threshold` (int), `timeout_minutes` (int)
- **Bouton toggle** : `channel_filter_mode` → alterne entre `blacklist` et `whitelist`
- **Boutons** : "Gérer la blacklist" / "Gérer la whitelist" → modals pour ajouter/supprimer des IDs de channels

### 🎮 Twitch (config)

- **Modal 1** (2 champs) : `channels` (str, virgule-séparés), `cooldown_seconds` (int)

### 🤖 OpenAI (params)

- **Modal 1** (2 champs) : `temperature` (float 0.0–2.0), `max_tokens` (int)

### 💭 Decay émotions

- **Modal 1** (5 champs) : `decay_lambda` pour `anger`, `joy`, `sadness`, `curiosity`, `boredom`

---

## Redémarrage du bot

- **Bouton** `🔄 Redémarrer le bot` dans le `SetupView` principal.
- Clic → message de confirmation avec bouton **"Confirmer le redémarrage"** et bouton **"Annuler"**.
- Confirmation → message "Redémarrage en cours..." → `sys.exit(0)`.
- Docker (`restart: unless-stopped` ou `always`) relance automatiquement le processus.
- Le bouton est également proposé après toute sauvegarde du `.env`.

---

## Implémentation

### Fichiers modifiés

- `bot/discord/commands/setup.py` — réécriture partielle (ajout de classes View/Modal/Button)

### Nouvelles classes (estimé ~12)

| Classe | Rôle |
|--------|------|
| `LevelSelect` | Select principal Basique/Avancé |
| `RestartButton` | Bouton redémarrage (SetupView) |
| `ConfirmRestartView` | Confirmation + Annuler |
| `BasicTabSelect` | Onglets niveau Basique |
| `AdvancedTabSelect` | Onglets niveau Avancé |
| `EnvView` | Vue .env avec 4 boutons de groupes |
| `EnvGroupModal` | Modal générique pour un groupe .env |
| `BotGeneralModal` | Modal Bot Général (5 champs) |
| `JournalChannelModal` | Modal channel journal (1 champ) |
| `DiscordParamsModal` | Modal anger/timeout (2 champs) |
| `ChannelFilterView` | Toggle + gestion listes channels |
| `TwitchConfigModal` | Modal channels/cooldown Twitch |
| `OpenAIParamsModal` | Modal temperature/max_tokens |
| `DecayModal` | Modal decay_lambda 5 émotions |

### Parser `.env`

Fonction utilitaire `update_env_file(path, updates: dict[str, str])` :
- Lit le fichier ligne par ligne
- Met à jour les lignes `KEY=value` existantes
- Ajoute les clés absentes en fin de fichier
- Écrit le fichier en place

### Contraintes Discord respectées

- Max 5 `TextInput` par modal ✓
- Max 25 options par `Select` ✓
- Max 5 lignes de boutons (rows) par `View` ✓

---

## Tests

- Test unitaire `update_env_file` : mise à jour, ajout, clés manquantes, fichier vide
- Test `is_env_complete` : détection clés manquantes
- Tests modaux existants inchangés
