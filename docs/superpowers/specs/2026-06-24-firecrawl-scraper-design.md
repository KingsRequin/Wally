# Design — Scraper Firecrawl pour Wally

**Date** : 2026-06-24
**Branche** : `feat/site-redesign-arcade`
**Statut** : design validé, prêt pour plan d'implémentation

## Problème / Objectif

Wally sait *chercher* sur le web (Tavily, `bot/core/web_search.py`, exposé au LLM via
tool calling), mais ne sait pas *lire une page précise en entier*. Tavily renvoie des
snippets courts (~300 caractères) de 5 sources ; il ne donne jamais le contenu complet
d'un article, de patch notes, d'une doc ou d'un lien que quelqu'un colle dans le chat.

Objectif : ajouter une capacité de **scraping** complémentaire (pas un remplacement de
Tavily) via **Firecrawl auto-hébergé**, pour que Wally puisse extraire le contenu
principal d'une URL en markdown propre et l'utiliser dans sa réponse. Cohérent avec la
North Star « autonomie maximale » : Wally décide lui-même quand approfondir une source.

## Décisions tranchées (brainstorming)

| Sujet | Décision |
|---|---|
| Provider | Firecrawl **self-host**, stack complète (api + playwright + redis + rabbitmq + nuq-postgres + foundationdb), pinné sur un **tag stable** (pas `main`). |
| Déclenchement | **Les deux** : (A) tool LLM `scrape_url`, (B) auto sur lien collé. |
| Anti-abus auto | **1 seul lien par message**, pages web uniquement (médias/CDN exclus), **cooldown par canal** (défaut 30 s). |
| Budget contenu | **Hybride** : injecté tel quel si ≤ ~2000 tokens, sinon résumé via `llm_secondary`. Seuil réglable. |
| Logging / quota | Log léger (URL + date) + **plafond quotidien de sécurité** (défaut 200/jour) pour protéger CT100. Pas de coût $ (self-host). |
| RAM | CT100 porté à 14 Go (10.4 Go libres) — marge confortable pour la stack complète. |

## Architecture

### 1. Infrastructure Docker

La stack Firecrawl est **ajoutée au `docker-compose.yml` de Wally** (`/opt/stacks/wally-ai/`)
pour partager automatiquement le réseau Docker (pas de réseau externe à câbler).

Services (images/tag stable pinné) :
- `firecrawl-api` — API principale, port interne 3002 (non exposé publiquement)
- `firecrawl-playwright` — rendu JS / navigateur headless (poste RAM le plus variable)
- `redis` — file / rate limiting
- `rabbitmq` — file de jobs
- `nuq-postgres` — backend de file
- `foundationdb` (+ container init one-shot) — persistance

Garde-fous Firecrawl (env) : `MAX_RAM=0.8`, `MAX_CPU=0.8` → rejette de nouveaux jobs si
CT100 sature. Wally joint l'API via `FIRECRAWL_API_URL=http://firecrawl-api:3002`.

`wally` reçoit un `depends_on` **non bloquant** (sans `condition: service_healthy`) :
Wally doit démarrer même si Firecrawl boote lentement ou est en panne.

### 2. `ScrapeService` — `bot/core/scrape.py` (nouveau)

Calqué sur `WebSearchService`. Responsabilité unique : scraper une URL via l'API Firecrawl
et renvoyer du texte prêt à injecter dans le contexte LLM.

- `__init__(config, db)` : lit `FIRECRAWL_API_URL`, prépare un client httpx async.
- `available` (property) : vrai si l'URL Firecrawl est configurée.
- `async scrape(url: str) -> str` : POST `/v1/scrape` avec
  `{"formats": ["markdown"], "onlyMainContent": true}` ; applique le budget contenu (§5) ;
  log + vérif quota (§7). Renvoie un message dégradé en français en cas d'échec.
- `SCRAPE_TOOL` : définition tool au format OpenAI Chat Completions (`scrape_url(url)`).
- `get_tool_definitions() -> list[dict]` : `[SCRAPE_TOOL]`.
- `_is_scrapable_url(url: str) -> bool` : filtre partagé — rejette images, vidéos, CDN
  Discord (`cdn.discordapp.com`, `media.discordapp.net`), fichiers binaires. Utilisé par
  les deux déclencheurs.

### 3. Déclenchement A — tool LLM `scrape_url`

Dans `bot/discord/handlers.py` (~ligne 1141) et `bot/twitch/handlers.py` :
- si `scrape_service.available` : `tools.extend(scrape_service.get_tool_definitions())` ;
- dispatch (~ligne 1174) : `elif name == "scrape_url": return await scrape_service.scrape(args["url"])`.

Le LLM appelle `scrape_url` quand il juge utile de lire une page complète (ex. Tavily a
renvoyé une URL intéressante, ou l'utilisateur demande de détailler un lien).

### 4. Déclenchement B — auto sur lien collé

Hook tôt dans `on_message` (avant construction du contexte), avec la politique anti-abus :
- extraction du **1er** lien web du message (regex URL) ;
- `_is_scrapable_url` doit l'accepter (sinon ignoré) ;
- **cooldown par canal** : `_scrape_cooldowns: dict[channel_id, float]` (défaut 30 s),
  même pattern que `_memory_check_cooldowns` dans `handlers.py` ;
- si OK → scrape en **background** (`asyncio.create_task`), résultat injecté dans le
  contexte / prélude du message courant sous un bloc `--- Page web ---`.

Le filtre média garantit qu'on ne scrape jamais une image ou un lien CDN.

### 5. Budget contenu (hybride)

Dans `ScrapeService.scrape`, après récupération du markdown nettoyé par Firecrawl
(`onlyMainContent` retire déjà nav / pub / footer) :
- estimation grossière des tokens (`len(text) // 4`) ;
- si `≤ firecrawl.inline_max_tokens` (défaut 2000) → injecté **tel quel** (info complète,
  aucun coût LLM, aucune latence) ;
- sinon → **résumé** via `llm_secondary.complete()` avec un prompt dédié
  `bot/persona/prompts/scrape_summary.md`, en conservant titre + URL.

Pattern déjà utilisé ailleurs dans Wally (`llm_secondary` pour descriptions d'images,
résumés de session, résumés de visites Twitch). Seuil réglable dans `config.yaml`.

### 6. Config & variables d'environnement

- `.env` : `FIRECRAWL_API_URL` (+ entrée dans `.env.example`). Pas de clé API (self-host).
- `config.yaml` → nouveau bloc `firecrawl:` :
  ```yaml
  firecrawl:
    enabled: true
    inline_max_tokens: 2000
    auto_scrape_links: true
    auto_scrape_cooldown_s: 30
    daily_limit: 200
  ```
- `bot/config.py` : dataclass `FirecrawlConfig` (pattern `SpamDetectionConfig` / `tavily`),
  construite dans `Config.load()`.

### 7. Logging & quota

Réutilise le pattern Tavily (`log_web_search` / `count_web_searches_this_month`) :
- `Database.log_scrape(url)` — enregistre URL + date ;
- `Database.count_scrapes_today()` — pour le plafond quotidien ;
- `scrape()` renvoie un message clair si `daily_limit` est dépassé.

Pas de coût monétaire (self-host) : le plafond protège uniquement le CPU/RAM de CT100
contre une boucle ou un abus.

### 8. Gestion d'erreurs

- Firecrawl indisponible / timeout → log WARNING, `scrape()` renvoie un message dégradé en
  français, Wally continue (jamais de crash).
- `depends_on` **sans** `condition: service_healthy` → Wally démarre même si Firecrawl est
  lent à booter ou down.
- httpx : timeout explicite (≈ 30 s) ; erreurs réseau catchées comme dans `web_search.py`.

### 9. Tests

- `ScrapeService` (client httpx mocké) : scrape OK, page courte (inline, pas d'appel LLM),
  page longue (résumé `llm_secondary` appelé), URL média rejetée, quota dépassé,
  Firecrawl down → message dégradé.
- Auto-scrape : cooldown respecté, lien média ignoré, un seul lien scrapé par message.
- Réutiliser le pattern de mock des tests Tavily existants.

## Empreinte

1 nouveau fichier (`bot/core/scrape.py`), 1 prompt (`scrape_summary.md`), +~15 lignes dans
chaque handler (Discord + Twitch), 1 bloc config + dataclass, 2 méthodes DB, ajout au
`docker-compose.yml`. **Aucun refacto du code existant.**

## Hors scope (YAGNI)

- Crawl multi-pages (Firecrawl `/crawl`) — on ne fait que du `/scrape` mono-URL.
- Cache de pages scrapées — non demandé.
- Dashboard dédié au scraping — le log léger suffit ; UI plus tard si besoin.
- Scraping de plusieurs liens par message — explicitement écarté (1 lien/message).
