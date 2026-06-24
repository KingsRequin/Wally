# Wally — Bot IA Discord & Twitch

Wally est un bot IA pour Discord et Twitch doté d'une **personnalité cohérente**, d'un **état émotionnel persistant**, d'une **mémoire long-terme** par utilisateur, d'une **boucle cognitive autonome** (il pense, décide et intervient de lui-même) et d'un **dashboard web** d'administration.

---

## ⚠️ À lire avant tout

**Wally a été codé entièrement avec [Claude Code](https://claude.com/claude-code)** (l'agent CLI d'Anthropic). Du premier commit jusqu'aux dernières fonctionnalités, l'intégralité du code a été écrite par l'IA, sous ma direction.

Le projet est **fourni tel quel (« as-is »)**, sans garantie ni engagement de support :

- C'est un projet **personnel**, mis en public au cas où il intéresserait quelqu'un.
- Je **corrige les bugs au fur et à mesure** que je les rencontre, sur mon temps libre. Il n'y a pas de roadmap ni de SLA.
- Il peut contenir des bugs, des approximations ou des choix d'architecture discutables.
- Aucune assistance n'est garantie. Les *issues* et *PR* sont les bienvenues mais peuvent rester sans réponse.

Si tu reprends ce code, fais-le en connaissance de cause : lis-le, teste-le, adapte-le à ton besoin.

---

## Fonctionnalités

### 🧠 Autonomie & boucle cognitive

Wally ne se contente pas de répondre quand on lui parle. Il tourne une **boucle cognitive** en continu :

- **Cycle ATTN → THINK → DECIDE → SPEAK → ACT** : il évalue l'attention que mérite ce qui se passe, réfléchit, décide d'agir ou non, puis parle ou exécute une action.
- **Perception multi-salons** : il perçoit **tous les salons publics** (capture passive, comme sur Twitch) et peut intervenir spontanément quand c'est pertinent, sans qu'on le mentionne.
- **Fil de pensée intérieur** (*inner monologue*) et **récit de soi** : il maintient une narration interne cohérente de qui il est et de ce qu'il vit.
- **Buts** (*goals*) : il peut se fixer des objectifs, les poursuivre et les clôturer.
- **Drive émotionnel & déclencheurs spontanés** : ses émotions et ses « passions » le poussent à initier des conversations.
- **Droit au silence** : un *gate* décide s'il vaut mieux ne rien dire — il n'est pas obligé de répondre.
- **Anti-rumination** : il ne re-réfléchit pas en boucle au même contexte tant qu'il n'y a pas de nouvelle activité.

### 🔧 Auto-modification de code (self-upgrade via Claude Code)

Wally peut **modifier son propre code**. Quand il décide qu'un correctif ou une amélioration est nécessaire, il émet une intention `[ACT code_fix {but}]`. Le créateur reçoit alors une demande d'autorisation en DM (✅/❌, but verbatim) ; une fois approuvée, **Claude Code s'exécute sur l'hôte** pour réaliser la modification. L'outil d'auto-modification est réservé au créateur.

Concrètement, **Wally commite lui-même** ses changements dans ce dépôt git : ses auto-modifications apparaissent dans l'historique sous l'auteur **`Wally (self-upgrade)`**, distinct des commits humains. Une partie de l'historique de ce repo a donc littéralement été écrite par le bot lui-même.

### 💾 Mémoire long-terme

- **Faits S-P-O** (Sujet-Prédicat-Objet) stockés en **SQLite (FTS5)**, avec un **vocabulaire fermé** de prédicats.
- **Déduplication live** à l'ajout + **réconciliation en 2 étages** (`MemoryIngest`).
- **Retrieval type *Generative Agents*** (pertinence + récence + importance).
- **Origine (lieu)** et **péremption (TTL/`expires_at`)** des faits : Wally sait où il a appris quelque chose et oublie ce qui devient obsolète.
- **Rappel spontané** : il évoque de lui-même un souvenir pertinent en cours de conversation.
- **Relations** : scores de confiance (*trust*) et d'affection (*love*) par utilisateur.
- **Extraction automatique** de faits mémorables depuis les conversations et en fin de session.
- **Mémoire d'images** : chaque image envoyée est décrite en une phrase et mémorisée.

### ❤️ État émotionnel

- **5 émotions** (colère, joie, tristesse, curiosité, ennui), chacune un flottant 0–1.
- **Décroissance exponentielle** par émotion, **suppression** des émotions incompatibles, **compétition** entre émotions coexistantes.
- **Rythme circadien**, **fatigue**, **habituation**, **humeur** (mood) lissée.
- **Émotions secondaires** (anxiété, mépris, frustration, nostalgie, fierté, émerveillement) et **composites** dérivées de combinaisons.
- L'émotion dominante module le comportement via des **directives injectées dans le prompt** (jamais « tu es en colère », mais « tes réponses sont courtes et impatientes »).
- **Timeout/mute** : trop de colère → Wally passe en mode réactions uniquement.

### 🎭 Personnalité

- Persona composée de fichiers Markdown (`SOUL`, `IDENTITY`, `VOICE`, `EXEMPLES`), directives par émotion, par jour de la semaine, et composites.
- Rechargeable à chaud via `/reload-persona`.

### 🛠️ Capacités

- **Génération d'images** via l'API OpenAI Images, **galerie publique** avec votes.
- **Actions planifiées** : rappels one-shot et récurrents via *tool calling* LLM.
- **Notes persistantes** créées par Wally.
- **Recherche web** (Tavily).
- **Détection de spam** : tracking par canal, mute automatique, avertissement généré par le LLM.
- **Journal quotidien** : résumé automatique de la journée publié sur Discord.
- **Sessions** : suivi des conversations par canal, extraction de faits durables à la fin.

### 📺 Twitch

- **Stream awareness** : Wally sait quand le live est en cours.
- **Suivi des visites** sur les chaînes invitées, résumé LLM injecté dans le journal.
- **Événements** : follow / sub / resub / gift sub / bits / raid (messages configurables).
- Cooldowns par utilisateur, filtre anti-bots.

### 🖥️ Dashboard & site public

- **Site public arcade** : status temps réel, chat web, galerie, journal, et un **flux cognitif live** (SSE) qui montre le « cerveau » de Wally penser en direct.
- **Dashboard admin** : configuration LLM/émotions/images, logs temps réel, gestion mémoire, coûts API, actions planifiées, prompts, système.
- **Auth** : Bearer token (admin) + Discord OAuth2 (JWT pour le chat web).

### ⚙️ Technique

- **Multi-provider LLM** (DeepSeek en principal, couche d'abstraction `bot/core/llm/`), *prompt caching* côté Claude.
- **Hot-reload** de la configuration sans redémarrage.
- **Suivi des coûts** API par modèle/période.
- **Auto-update** via GHCR (un bouton apparaît dans l'admin quand une nouvelle image est dispo).

---

## Prérequis

| Outil | Version | Pourquoi |
|---|---|---|
| Docker + Docker Compose | >= 24 | Faire tourner le bot |
| Clé API DeepSeek | — | Réponses (texte) — provider LLM principal |
| Clé API OpenAI | — | Génération d'images |
| Application Discord | — | Token bot + intents |
| Application Twitch | _(optionnel)_ | Token OAuth bot + client ID |
| Clé API Tavily | _(optionnel)_ | Recherche web |
| Qdrant | _(optionnel)_ | Moteur vectoriel (la mémoire de base fonctionne sans, en SQLite) |

### Créer l'application Discord

1. Aller sur <https://discord.com/developers/applications> → **New Application**
2. **Bot** → activer **Message Content Intent** et **Server Members Intent**
3. **OAuth2 → URL Generator** : scopes `bot` + `applications.commands`, permissions `Send Messages`, `Add Reactions`, `Read Message History`
4. Copier le **Token** → `DISCORD_TOKEN` dans `.env`

### Créer l'application Twitch (optionnel)

1. Aller sur <https://dev.twitch.tv/console> → **Register Your Application**
2. Catégorie : **Chat Bot**, OAuth Redirect URL : `http://localhost`
3. Copier **Client ID** → `TWITCH_CLIENT_ID` et générer un **Client Secret** → `TWITCH_CLIENT_SECRET`
4. Générer un token OAuth pour le compte bot → `BOT_ACCESS_TOKEN` dans `.env`

---

## Installation

```bash
# 1. Cloner le dépôt
git clone https://github.com/KingsRequin/Wally.git wally
cd wally

# 2. Créer le fichier d'environnement
cp .env.example .env
# Éditer .env et remplir les valeurs requises (clés API, tokens…)

# 3. Créer la configuration (token admin + IDs Discord)
cp config.example.yaml config.yaml
# Éditer config.yaml : changer dashboard_token, renseigner les IDs de salons éventuels

# 4. Créer l'annuaire des canaux Discord (où Wally a le droit d'écrire)
cp bot/intelligence/persona/CHANNELS.example.md bot/intelligence/persona/CHANNELS.md
# Éditer CHANNELS.md avec tes propres IDs de salons (optionnel : Wally fonctionne sans)

# 5. Créer les dossiers de données
mkdir -p data logs

# 6. Lancer
docker compose up -d

# 7. Vérifier que tout tourne
docker compose ps
docker compose logs -f wally
```

Chercher dans les logs :
```
Wally starting...
Discord bot ready
Dashboard server added to gather on port 8080
```

> `config.yaml` et `.env` sont ignorés par git : ils contiennent ton token admin et tes secrets. Pars toujours des fichiers `*.example`.

---

## Configuration — `config.yaml`

Toutes les valeurs sont modifiables **à chaud** via `/wally setup` (Discord) ou le dashboard web. Les changements sont écrits dans `config.yaml` immédiatement, sans redémarrage. Voir `config.example.yaml` pour la liste complète et commentée.

### Section `llm`

```yaml
llm:
  primary:
    provider: "deepseek"        # seul provider texte supporté
    model: "deepseek-v4-pro"
    temperature: 0.8
    max_tokens: 8192
    thinking_type: "disabled"   # disabled / enabled
  secondary:
    provider: "deepseek"
    model: "deepseek-v4-flash"
    temperature: 0.8
    max_tokens: 1000
```

> OpenAI n'est pas un provider texte — il est construit séparément (hors `llm:`) pour la génération d'images.

### Quelques clés `bot`

| Clé | Défaut | Description |
|---|---|---|
| `trigger_names` | `["wally"]` | Mots qui déclenchent Wally dans un message |
| `language_default` | `fr` | Langue de fallback si la détection échoue |
| `context_window_size` | `20` | Nb de messages gardés par salon dans la fenêtre glissante |
| `journal_time` | `"21:00"` | Heure de génération du journal quotidien |
| `journal_channel_id` | `null` | ID du salon Discord où publier le journal |
| `dashboard_token` | `changeme` | **Mot de passe d'accès admin du dashboard — à changer** |
| `update_image` | `""` | Image GHCR pour l'auto-update (ex : `ghcr.io/user/wally-ai:latest`) |

### Section `emotions`

Chaque émotion a un `decay_lambda` (vitesse de décroissance). On y configure aussi le circadien, la fatigue, l'habituation, les émotions secondaires et les événements spontanés.

---

## Commandes Discord `/wally`

| Commande | Description | Permissions |
|---|---|---|
| `/ask <question>` | Poser une question directement à Wally | Tout le monde |
| `/mood` | Voir l'état émotionnel actuel (5 barres) | Tout le monde |
| `/status` | Uptime, modèle actif, humeur, coûts | Tout le monde |
| `/imagine <prompt>` | Générer une image IA | Tout le monde |
| `/memory <user>` | Voir la mémoire long-terme d'un utilisateur | Administrateur |
| `/journal [date]` | Déclencher un journal (backfill optionnel) | Administrateur |
| `/reload-persona` | Recharger les fichiers persona sans redémarrage | Administrateur |
| `/setup` | Panneau de configuration interactif | Administrateur |

---

## Architecture

Monolithe modulaire — un seul processus asyncio, deux adaptateurs (Discord, Twitch) partageant des services injectés.

```
bot/
├── main.py              # Point d'entrée, DI wiring, asyncio.gather()
├── bootstrap.py         # Construction des services, injection DI
├── config.py            # Config dataclass, hot-reload, config.save()
├── core/                # Primitives sans LLM
│   ├── llm/             # Abstraction LLM (base, deepseek, openai images, factory)
│   ├── emotion.py       # État émotionnel, décroissance, NRCLex
│   ├── language.py      # Détection de langue (langdetect)
│   ├── web_search.py    # Recherche web (Tavily)
│   ├── update_checker.py
│   └── ...
├── intelligence/        # Tout ce qui raisonne via LLM
│   ├── memory/          # Mémoire sémantique (FTS5/SQLite) — faits S-P-O
│   ├── actions/         # Actions planifiées via tool calling
│   ├── cognitive_loop.py   # Boucle cognitive (ATTN/THINK/DECIDE/SPEAK)
│   ├── cognitive_feed.py   # Fan-out SSE du flux cognitif
│   ├── reasoning_agent.py  # Génération de réponses
│   ├── attention_agent.py  # Scoring d'attention
│   ├── gate.py             # Décision de répondre (droit au silence)
│   ├── persona.py          # Chargement de la persona
│   ├── fact_extractor.py   # Extraction de faits mémorables
│   ├── journal.py          # Journal quotidien
│   ├── self_upgrade.py     # Auto-modification de code via Claude Code
│   ├── inner_monologue.py  # Fil de pensée intérieur
│   └── ...
├── discord/             # Bot Discord, handlers, commandes /wally
├── twitch/              # Bot Twitch, handlers, events
├── persona/             # Fichiers persona Markdown + prompts/
├── dashboard/           # FastAPI + SPA (admin + site public arcade)
└── db/                  # aiosqlite : schéma, mixins, requêtes
```

---

## Docker

Services : `init-perms` (permissions), `wally` (bot + dashboard, port 8080) et `cloudflared` (tunnel, optionnel). Le socket Docker est monté dans le container pour permettre le restart et l'auto-update depuis le dashboard.

`config.yaml`, `.env` et `data/` sont montés en volumes — pense à les créer avant le premier lancement.

### Mise à jour automatique

Renseigne `bot.update_image` dans `config.yaml` avec la référence GHCR de l'image. Le bot vérifie chaque heure ; quand une nouvelle image existe, un bouton « Mise à jour disponible » apparaît dans l'admin et déclenche `docker compose pull && docker compose up -d --force-recreate`. Laisser vide pour désactiver.

---

## Dépannage

### Wally ne répond pas sur Discord
1. Vérifier que **Message Content Intent** est activé dans le portail Discord Developers
2. Vérifier que `DISCORD_TOKEN` dans `.env` est correct
3. Vérifier les permissions du bot dans le salon

### Wally ne répond pas sur Twitch
1. Vérifier `BOT_ACCESS_TOKEN` dans `.env`
2. Vérifier les chaînes (en minuscules) dans la config Twitch

### Coûts élevés
Utiliser `/wally status` ou l'onglet **Coûts** du dashboard. Réduire `max_tokens` ou changer de modèle via `/wally setup`.

---

## Licence & usage

Projet personnel fourni tel quel, sans garantie. Codé avec Claude Code. Utilise-le, modifie-le, apprends-en ce que tu veux — à tes risques.
