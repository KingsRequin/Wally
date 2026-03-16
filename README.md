# Wally — AI Discord & Twitch Bot

Wally est un bot IA pour Discord et Twitch avec une personnalité cohérente, un état émotionnel persistant et une mémoire long-terme par utilisateur.

---

## Prérequis

| Outil | Version | Pourquoi |
|---|---|---|
| Docker + Docker Compose | ≥ 24 | Faire tourner le bot et Qdrant |
| Clé API OpenAI | — | Génération de réponses |
| Application Discord | — | Token bot + intents |
| Application Twitch | — | Token OAuth bot + client ID |

### Créer l'application Discord

1. Aller sur <https://discord.com/developers/applications> → **New Application**
2. **Bot** → Activer **Message Content Intent** et **Server Members Intent**
3. **OAuth2 → URL Generator** : scopes `bot` + `applications.commands`, permissions `Send Messages`, `Add Reactions`, `Read Message History`
4. Copier le **Token** → `DISCORD_TOKEN` dans `.env`

### Créer l'application Twitch

1. Aller sur <https://dev.twitch.tv/console> → **Register Your Application**
2. Catégorie : **Chat Bot**, OAuth Redirect URL : `http://localhost`
3. Copier **Client ID** → `TWITCH_CLIENT_ID` et générer un **Client Secret** → `TWITCH_CLIENT_SECRET`
4. Générer un token OAuth pour le compte bot : <https://twitchapps.com/tmi/> → `TWITCH_BOT_TOKEN` (format `oauth:xxxx`)

---

## Installation

```bash
# 1. Cloner le dépôt
git clone <url-du-repo> wally-ai
cd wally-ai

# 2. Créer le fichier d'environnement
cp .env.example .env
# Éditer .env et remplir toutes les valeurs

# 3. Créer les dossiers de données
mkdir -p data logs

# 4. Lancer
docker compose up -d

# 5. Vérifier que tout tourne
docker compose ps
docker compose logs -f wally
```

Qdrant devient healthy en ~10s, puis Wally démarre. Chercher dans les logs :
```
Wally starting...
Config loaded — primary model: gpt-4o
Discord bot ready as Wally#1234
Twitch bot ready as wallybot
```

---

## Configuration — `config.yaml`

Toutes les valeurs peuvent être modifiées à chaud via `/wally setup` (Discord) — les changements sont écrits dans `config.yaml` immédiatement sans redémarrage.

### Section `bot`

| Clé | Défaut | Description |
|---|---|---|
| `trigger_names` | `["wally"]` | Mots qui déclenchent Wally dans un message |
| `language_default` | `fr` | Langue de fallback si détection échoue |
| `context_window_size` | `20` | Nb de messages gardés par salon dans la fenêtre glissante |
| `context_token_threshold` | `3000` | Seuil (tokens estimés) déclenchant la résumation automatique |
| `journal_time` | `"03:00"` | Heure de génération du journal quotidien (HH:MM, heure locale container) |
| `journal_channel_id` | `null` | ID du salon Discord où publier le journal (null = désactivé) |
| `system_prompt` | _(voir fichier)_ | Prompt système de base injecté dans toutes les requêtes |

### Section `openai`

| Clé | Défaut | Description |
|---|---|---|
| `primary_model` | `gpt-4o` | Modèle pour les réponses conversationnelles |
| `secondary_model` | `gpt-4o-mini` | Modèle pour résumés, journal, analyse |
| `temperature` | `0.8` | Créativité (0.0 = déterministe, 2.0 = très créatif) |
| `max_tokens` | `1000` | Longueur max d'une réponse |

### Section `discord`

| Clé | Défaut | Description |
|---|---|---|
| `allowed_channels` | `[]` | Salons où Wally répond (vide = tous) |
| `anger_trigger_threshold` | `3` | Nb de déclenchements sous colère avant mute |
| `timeout_minutes` | `10` | Durée du mute en minutes |

### Section `twitch`

| Clé | Défaut | Description |
|---|---|---|
| `channels` | `[]` | Chaînes Twitch à rejoindre (ex: `["nomdelachain"]`) |
| `cooldown_seconds` | `10` | Délai minimal entre deux réponses au même utilisateur |

### Section `emotions`

Chaque émotion (`anger`, `joy`, `sadness`, `curiosity`, `boredom`) a :

| Clé | Description |
|---|---|
| `decay_lambda` | Vitesse de décroissance exponentielle (plus élevé = décroissance plus rapide) |

### Section `twitch_events`

Chaque événement (`follow`, `sub`, `resub`, `bits`, `raid`) a :

| Clé | Description |
|---|---|
| `active` | `true`/`false` — activer ou non la réaction automatique |
| `message` | Template du message (variables : `{username}`, `{amount}`, `{months}`, `{raiders_count}`) |

---

## Commandes Discord `/wally`

| Commande | Description | Permissions |
|---|---|---|
| `/ask <question>` | Poser une question directement à Wally | Tout le monde |
| `/mood` | Voir l'état émotionnel actuel (5 barres de progression) | Tout le monde |
| `/status` | Uptime, modèle actif, humeur dominante, coûts OpenAI | Tout le monde |
| `/memory <user>` | Voir la mémoire long-terme de Wally pour un utilisateur | Administrateur |
| `/setup` | Panneau de configuration interactif à 4 onglets | Administrateur |

### Guide `/wally setup`

Le panneau `/setup` comporte 4 onglets accessibles via un menu déroulant :

**🤖 Modèle IA** — Sélectionner le modèle principal et secondaire parmi la liste des modèles OpenAI compatibles (filtrés : GPT, ChatGPT, O1, O3, O4 ; exclus : realtime, preview, audio, vision).

**😊 Humeur** — Ajuster les 5 émotions de Wally manuellement : boutons `+`/`-` par pas de 0.1, bouton `Edit` pour entrer une valeur précise, bouton `Reset` pour tout remettre à 0.

**🎮 Événements Twitch** — Activer/désactiver chaque événement (follow, sub, resub, bits, raid) et modifier les messages de réaction.

**📢 Noms déclencheurs** — Ajouter ou supprimer les mots qui font réagir Wally dans le chat.

Tous les changements sont sauvegardés immédiatement dans `config.yaml`.

---

## Dépannage

### Qdrant n'est pas healthy

```
wally-qdrant | Error: listen tcp :6333...
```

Vérifier que le port 6333 n'est pas déjà utilisé :
```bash
ss -tlnp | grep 6333
docker compose down && docker compose up -d
```

### Wally ne répond pas sur Discord

1. Vérifier que **Message Content Intent** est activé dans le portail Discord Developers
2. Vérifier que `DISCORD_TOKEN` dans `.env` est correct et n'a pas expiré
3. Vérifier que le bot a les permissions dans le salon

### Wally ne répond pas sur Twitch

1. Vérifier que `TWITCH_BOT_TOKEN` commence bien par `oauth:`
2. Vérifier que les chaînes dans `config.yaml > twitch > channels` sont correctes (en minuscules)
3. Le token OAuth Twitch expire — régénérer via <https://twitchapps.com/tmi/>

### Modèle non trouvé dans `/wally setup`

Vérifier que `OPENAI_API_KEY` est valide. La liste de modèles est récupérée en live depuis l'API OpenAI.

### Coûts élevés

Utiliser `/wally status` pour voir les coûts du jour et du mois. Réduire `max_tokens` ou passer à `gpt-4o-mini` comme modèle principal via `/wally setup`.

### Mémoire (Qdrant / mem0)

Si Qdrant est indisponible, Wally fonctionne sans mémoire long-terme (mode dégradé, log WARNING). Les données sont stockées dans `./data/qdrant/` sur l'hôte.

---

## Structure du projet

```
bot/
├── main.py              # Point d'entrée, injection de dépendances
├── config.py            # Config dataclass, Config.load(), config.save()
├── core/
│   ├── emotion.py       # EmotionEngine : état, décroissance, NRCLex
│   ├── memory.py        # MemoryService : mem0 + fenêtre glissante
│   ├── openai_client.py # Completions, retry, suivi des coûts
│   ├── prompts.py       # Templates de prompts, directives émotionnelles
│   ├── language.py      # Détection de langue (langdetect)
│   └── journal.py       # Journal quotidien (apscheduler)
├── discord/
│   ├── bot.py           # WallyDiscord
│   ├── handlers.py      # on_message, welcome, pipeline complet
│   └── commands/        # ask, status, mood, memory, setup
├── twitch/
│   ├── bot.py           # WallyTwitch, cooldowns par utilisateur
│   ├── handlers.py      # Pipeline message Twitch
│   └── events.py        # follow/sub/resub/bits/raid
└── db/
    └── database.py      # aiosqlite : cost_log, timeout_log, welcomed, trust_scores
```
