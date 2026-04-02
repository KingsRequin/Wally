# Wally — AI Discord & Twitch Bot

Wally est un bot IA pour Discord et Twitch avec une personnalite coherente, un etat emotionnel persistant, une memoire long-terme par utilisateur, et un dashboard web d'administration.

## Fonctionnalites principales

- **Multi-provider LLM** : OpenAI (GPT, O-series) et Anthropic Claude en parallele, configurable par role (primary/secondary)
- **Etat emotionnel** : 5 emotions (anger, joy, sadness, curiosity, boredom) avec decroissance exponentielle, influence les reponses
- **Memoire long-terme** : Qdrant (vecteurs) pour stocker faits, preferences, relations par utilisateur et plateforme
- **Generation d'images** : via OpenAI Images API, galerie publique avec votes
- **Actions planifiees** : rappels one-shot et recurrents via tool calling LLM
- **Detection de spam** : tracking par canal, mute automatique, avertissement LLM
- **Journal quotidien** : resume automatique de la journee publie sur Discord
- **Dashboard web** : administration, monitoring emotions, logs, gestion memoire, galerie, chat web
- **Interventions spontanees** : Wally reagit naturellement aux conversations selon ses passions et emotions
- **Sessions** : suivi des conversations par canal, extraction de faits a la fin

---

## Prerequis

| Outil | Version | Pourquoi |
|---|---|---|
| Docker + Docker Compose | >= 24 | Faire tourner le bot et Qdrant |
| Cle API OpenAI | — | Reponses, images, embeddings |
| Cle API Anthropic | _(optionnel)_ | Utiliser Claude comme provider LLM |
| Application Discord | — | Token bot + intents |
| Application Twitch | _(optionnel)_ | Token OAuth bot + client ID |

### Creer l'application Discord

1. Aller sur <https://discord.com/developers/applications> -> **New Application**
2. **Bot** -> Activer **Message Content Intent** et **Server Members Intent**
3. **OAuth2 -> URL Generator** : scopes `bot` + `applications.commands`, permissions `Send Messages`, `Add Reactions`, `Read Message History`
4. Copier le **Token** -> `DISCORD_TOKEN` dans `.env`

### Creer l'application Twitch (optionnel)

1. Aller sur <https://dev.twitch.tv/console> -> **Register Your Application**
2. Categorie : **Chat Bot**, OAuth Redirect URL : `http://localhost`
3. Copier **Client ID** -> `TWITCH_CLIENT_ID` et generer un **Client Secret** -> `TWITCH_CLIENT_SECRET`
4. Generer un token OAuth pour le compte bot -> `BOT_ACCESS_TOKEN` dans `.env`

---

## Installation

```bash
# 1. Cloner le depot
git clone <url-du-repo> wally-ai
cd wally-ai

# 2. Creer le fichier d'environnement
cp .env.example .env
# Editer .env et remplir les valeurs requises

# 3. Creer les dossiers de donnees
mkdir -p data logs

# 4. Lancer
docker compose up -d

# 5. Verifier que tout tourne
docker compose ps
docker compose logs -f wally
```

Qdrant devient healthy en ~10s, puis Wally demarre. Chercher dans les logs :
```
Wally starting...
Discord bot ready
Twitch adapter configured
Dashboard server added to gather on port 8080
```

---

## Configuration — `config.yaml`

Toutes les valeurs peuvent etre modifiees a chaud via `/wally setup` (Discord) ou le dashboard web. Les changements sont ecrits dans `config.yaml` immediatement sans redemarrage.

### Section `llm`

```yaml
llm:
  primary:
    provider: "claude"        # ou "openai"
    model: "claude-sonnet-4-6-20260301"
    temperature: 1.0
    max_tokens: 1000
    thinking_type: "adaptive" # Claude: disabled/enabled/adaptive
    thinking_effort: "medium" # Claude adaptive: low/medium/high
  secondary:
    provider: "openai"
    model: "gpt-5.1-mini"
    temperature: 0.8
    max_tokens: 1000
    reasoning_effort: "medium" # OpenAI-specific
```

### Section `bot`

| Cle | Defaut | Description |
|---|---|---|
| `trigger_names` | `["wally"]` | Mots qui declenchent Wally dans un message |
| `language_default` | `fr` | Langue de fallback si detection echoue |
| `context_window_size` | `20` | Nb de messages gardes par salon dans la fenetre glissante |
| `journal_time` | `"03:00"` | Heure de generation du journal quotidien |
| `journal_channel_id` | `null` | ID du salon Discord ou publier le journal |
| `memory_search_min_score` | `0.5` | Score Qdrant minimum pour les reponses normales |
| `memory_context_max_tokens` | `800` | Budget tokens pour le bloc memoire dans le prompt |
| `spontaneous_memory_probability` | `0.2` | Chance de rappel spontane sur souvenir pertinent |
| `update_image` | `""` | Référence image GHCR pour la détection auto de mise à jour (ex: `ghcr.io/user/wally-ai:latest`) |

### Section `discord`

| Cle | Defaut | Description |
|---|---|---|
| `allowed_channels` | `[]` | Salons ou Wally repond (vide = tous) |
| `anger_trigger_threshold` | `3` | Nb de declenchements sous colere avant mute |
| `timeout_minutes` | `10` | Duree du mute en minutes |
| `spam_detection.enabled` | `true` | Detection de spam automatique |
| `spam_detection.max_messages` | `10` | Seuil de messages dans la fenetre |
| `spam_detection.window_seconds` | `120` | Fenetre de temps pour le spam |

### Section `twitch`

| Cle | Defaut | Description |
|---|---|---|
| `channels` | `[]` | Chaines Twitch a rejoindre |
| `cooldown_seconds` | `10` | Delai minimal entre deux reponses au meme utilisateur |

### Section `emotions`

Chaque emotion (`anger`, `joy`, `sadness`, `curiosity`, `boredom`) a un `decay_lambda` (vitesse de decroissance exponentielle).

### Section `image_generation`

| Cle | Defaut | Description |
|---|---|---|
| `model` | `gpt-image-1` | Modele OpenAI pour la generation d'images |
| `daily_limit` | `20` | Limite quotidienne d'images |
| `per_user_limit` | `5` | Limite par utilisateur par jour |

---

## Commandes Discord `/wally`

| Commande | Description | Permissions |
|---|---|---|
| `/ask <question>` | Poser une question directement a Wally | Tout le monde |
| `/mood` | Voir l'etat emotionnel actuel (5 barres) | Tout le monde |
| `/status` | Uptime, modele actif, humeur, couts | Tout le monde |
| `/imagine <prompt>` | Generer une image IA | Tout le monde |
| `/memory <user>` | Voir la memoire long-terme d'un utilisateur | Administrateur |
| `/journal [date]` | Declencher un journal (backfill optionnel) | Administrateur |
| `/reload-persona` | Recharger les fichiers persona sans redemarrage | Administrateur |
| `/setup` | Panneau de configuration interactif | Administrateur |

---

## Dashboard Web

Accessible sur le port `8080`. Deux modes :

### Mode public (sans authentification)
- **Status** : uptime, connectivite, compteurs de messages
- **Chat** : chat web avec Wally via WebSocket
- **Galerie** : images generees, recherche, votes
- **Journal** : historique des journaux quotidiens

### Mode admin (Bearer token)
- **Config** : modeles LLM, provider, temperature, parametres bot
- **Logs** : logs temps reel via SSE
- **Memoire** : gestion utilisateurs, memoires, aliases, questions pendantes, memoire globale
- **Overlay** : controle overlay OBS pour images
- **Couts** : graphes de couts API par modele/periode
- **Actions** : taches planifiees, permissions par role
- **Barre de controle** : statut Discord/Twitch, boutons stop/start, bouton "Mise à jour disponible" (amber, auto-détecté via GHCR)

---

## Architecture

Monolithe modulaire — un seul processus asyncio, modules communiquant via injection de dependances.

```
bot/
├── main.py                # Point d'entree, DI wiring, asyncio.gather()
├── config.py              # Config dataclass, hot-reload, config.save()
├── core/
│   ├── emotion.py         # EmotionEngine : etat, decroissance, NRCLex
│   ├── memory.py          # MemoryService : fenetre glissante, search, consolidation
│   ├── memory_store.py    # QdrantMemoryStore : acces direct Qdrant, embeddings, CRUD
│   ├── prompts.py         # PromptBuilder, load_prompt(), directives emotionnelles
│   ├── language.py        # Detection de langue (langdetect)
│   ├── journal.py         # Journal quotidien (apscheduler)
│   ├── sessions.py        # SessionManager : suivi sessions, analyse LLM
│   ├── persona.py         # PersonaService : chargement fichiers persona
│   ├── llm/               # Abstraction multi-provider LLM
│   │   ├── base.py        # ABC BaseLLMClient
│   │   ├── openai_client.py # OpenAI Chat Completions + Responses API
│   │   ├── claude_client.py # Anthropic Claude, prompt caching, extended thinking
│   │   └── factory.py     # Factory create_llm_client()
│   └── actions/           # Taches planifiees via tool calling
│       ├── registry.py    # Catalogue actions + ACL par role
│       ├── scheduler.py   # Persistence SQLite + apscheduler
│       ├── executor.py    # Routing + livraison messages
│       └── service.py     # Facade LLM, tool definitions
├── discord/
│   ├── bot.py             # WallyDiscord
│   ├── handlers.py        # Pipeline message complet, spam, spontane
│   └── commands/          # ask, status, mood, memory, setup, imagine, journal, persona
├── twitch/
│   ├── bot.py             # WallyTwitch, cooldowns
│   ├── handlers.py        # Pipeline message Twitch
│   └── events.py          # follow/sub/resub/bits/raid
├── persona/
│   ├── SOUL.md / IDENTITY.md / VOICE.md / EMOTIONS.md
│   └── prompts/           # Templates systeme charges via load_prompt()
├── dashboard/
│   ├── app.py             # FastAPI app, middleware auth
│   ├── state.py           # AppState dataclass
│   ├── routes/            # admin, memory, status, gallery, chat, sse, actions
│   └── static/            # SPA vanilla JS + CSS glassmorphism
└── db/
    └── database.py        # aiosqlite : cost_log, trust_scores, gallery, actions, etc.
```

---

## Docker

Deux services : `wally` (bot principal) et `qdrant` (base vectorielle). `cloudflared` peut être ajouté optionnellement pour un tunnel.

Le socket Docker est monte dans le container Wally pour permettre le restart et la mise à jour depuis le dashboard.

---

## Mise à jour

Configurer `bot.update_image` dans `config.yaml` avec la référence de l'image GHCR :

```yaml
bot:
  update_image: "ghcr.io/ton-user/wally-ai:latest"
```

Le bot vérifie toutes les heures si une nouvelle image est disponible. Quand c'est le cas, un bouton amber "Mise à jour disponible" apparaît dans le panel admin. Un clic déclenche `docker compose pull && docker compose up -d --force-recreate` — le container se recrée avec la nouvelle image.

Laisser `update_image` vide pour désactiver le polling.

---

## Depannage

### Qdrant n'est pas healthy

```bash
ss -tlnp | grep 6333
docker compose down && docker compose up -d
```

### Wally ne repond pas sur Discord

1. Verifier que **Message Content Intent** est active dans le portail Discord Developers
2. Verifier que `DISCORD_TOKEN` dans `.env` est correct
3. Verifier les permissions du bot dans le salon

### Wally ne repond pas sur Twitch

1. Verifier `BOT_ACCESS_TOKEN` dans `.env`
2. Verifier les chaines dans `config.yaml > twitch > channels` (en minuscules)

### Memoire (Qdrant)

Si Qdrant est indisponible, Wally fonctionne sans memoire long-terme (mode degrade, log WARNING). Les donnees sont stockees dans `./data/qdrant/` sur l'hote.

### Couts eleves

Utiliser `/wally status` ou l'onglet Couts du dashboard. Reduire `max_tokens` ou changer de modele via `/wally setup` ou le dashboard.
