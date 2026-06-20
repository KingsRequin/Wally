# Refonte site public — thème Arcade, câblé backend

**Statut :** approuvé (design)
**Date :** 2026-06-20
**Design source :** `docs/design/Wally.dc.html` (importé depuis claude.ai/design projet "Refonte du site Wally")

## Objectif

Remplacer le thème visuel de `public-ui/` (glassmorphism actuel) par le **thème arcade/rétro** du mockup (VT323 + Press Start 2P, fond violet CRT #120a26, scanlines, canvas animé, néons, sprites flamme pixel), en **conservant l'architecture SPA** et en **câblant chaque section au vrai backend**. Ajout d'un **flux cognitif live** (le "cerveau" de Wally) pour le bloc ACTIVITÉ EN DIRECT.

## Architecture conservée

`public-ui/` reste une SPA : `index.html` (shell) + `app.js` (router hash + SSE émotions) + `tabs/*.js` (un module par section) + `style.css`. Le design arcade est un single-page à 6 sections scrollables ; on l'adapte au router hash existant (6 onglets). Servie via `SPAStaticFiles` par `bot/dashboard/app.py`. **Aucun changement backend de montage.**

## Mapping sections ↔ onglets ↔ endpoints (tous existants sauf marqués NEW)

| Section design | Onglet | Données réelles | Endpoint |
|---|---|---|---|
| **STATUT** | status.js | messages traités, uptime, services on/off | `GET /api/public/status` |
| | | émotions live (barres PERSONNALITÉ) | `GET /api/public/emotions` + `GET /api/public/sse/emotions` |
| | | viewers en mémoire | `GET /api/public/twitch/stream` |
| | | temps de réponse | **NEW** `GET /api/public/status` enrichi (avg latency) |
| | | **ACTIVITÉ EN DIRECT** (flux cerveau) | **NEW** `GET /api/public/sse/cognitive` |
| **CHAT** | chat.js | chat live Discord OAuth | existant : `/ws/chat`, `/api/chat/auth/*`, `/api/public/memory/me` |
| **GALERIE** | gallery.js | images + votes | existant : `/api/public/gallery*` |
| **JOURNAL** | journal.js | entrées journal + charts | existant : `/api/public/journal*` |
| **COMMUNAUTÉ** | community.js | classement viewers par affinité | **NEW** `GET /api/public/community/ranking` + graphe existant `/api/public/social-graph/data` |
| **À PROPOS** | about.js | contenu statique (corrigé) | aucun |

## Nouveau backend (3 ajouts)

### 1. Flux cognitif — le "cerveau" live (priorité — bloc ACTIVITÉ EN DIRECT)
La `CognitiveLoop` V2 (`bot/v2/core/cognitive_loop.py`) et ses agents (InnerMonologue, MetaAgent, ActionDispatcher) ne loguent qu'en debug aujourd'hui. On ajoute un **broadcaster cognitif** :

- **`bot/v2/core/cognitive_feed.py` (NEW)** : `CognitiveFeed` — file fan-out (même pattern que `sse.py` actions/logs). Méthode `publish(event: dict)`. Buffer circulaire des N derniers events (ex. 30) pour le snapshot initial.
- **Points d'émission** (injecter `feed.publish(...)` sans changer la logique) :
  - InnerMonologue : après génération → `{type:"THINK", text: monologue, ts}`
  - MetaAgent/ActionDispatcher : par décision → `{type:"SPEAK"|"ACT"|"EVOLVE"|"SLEEP", detail, channel?, ts}`
  - AttentionAgent / loop : interaction traitée → `{type:"ATTN", target: author, content_snippet, ts}`
- **`GET /api/public/sse/cognitive`** (public, dans `bot/dashboard/routes/`) : stream SSE `data: {event}\n\n`. Réutilise le pattern fan-out de `sse.py`.
- **`GET /api/public/cognitive/state`** (public) : snapshot des N derniers events (buffer) pour amorcer l'affichage avant le SSE.
- Câblage : `CognitiveFeed` instancié dans bootstrap/bot wiring, injecté dans la CognitiveLoop + exposé via AppState pour les routes. Satisfait les tâches #14 (observabilité cognitive) et amorce #15.
- **Confidentialité** : DÉCIDÉ (user 2026-06-20) — flux **PUBLIC et NON anonymisé**. Contenu complet (vrais noms/auteurs, monologue intégral, détails des décisions). Pas de troncature ni de masquage d'ID requis.

### 2. Classement communauté
- **`GET /api/public/community/ranking`** (NEW) : top viewers par score d'affinité. Source : `trust_scores`/`love_scores` (DB) agrégés, ou poids du graphe social (Neo4j). Réponse : `{ranking: [{name, trait, score}]}`. Azrael = épinglé "intouchable/MAX" (règle métier du design).

### 3. Temps de réponse
- Enrichir `GET /api/public/status` avec `avg_response_ms` (moyenne glissante). Source : instrumenter le pipeline de réponse (timing déjà loggé) → compteur en RAM dans AppState. Dégrade en "—" si indisponible.

## Assets design (extraits du .dc.html)

- **Fonts** : Google Fonts VT323 + Press Start 2P (preconnect + link).
- **Palette** : fond `#120a26` / `#2a1556` radial ; texte `#ffe8c2` ; accents jaune `#ffd400`, rose `#ff3b6b`, violet `#7c4dff`, cyan `#43e0ff`, vert `#7CFC52`.
- **Fond animé** : `<canvas>` plein écran avec 5 effets sélectionnables (grille, constellation, aimant, vortex, onde) — code dans le `DCLogic` du mockup, à porter en JS vanilla. Préférence sauvegardée `localStorage("wally_mfx")`. + scanlines CSS + vignette CSS.
- **Sprites flamme** : `drawFlame(id, scale)` (pixel art canvas) pour le logo nav + héros + about. À porter.
- **Effets** : `@keyframes blink/bob/bounce`, reveal au scroll (IntersectionObserver), nav active au scroll.
- **NE PAS** importer le format `.dc.html` (templating `{{}}`, `<sc-for>`, support.js, image-slot.js) — ré-écrire en HTML/CSS/JS réel intégré au SPA existant.

## Corrections de contenu (le mockup ment)

Le mockup affiche des données/tech fausses → corriger lors du câblage :
- "GPT-5" / "Node.js" / "Sequelize" / "better-sqlite3" → **DeepSeek (deepseek-v4-pro/flash)**, **Python/asyncio**, **aiosqlite**, **Qdrant**, **discord.py / twitchio**.
- Stats fictives (48 920 messages, 2 380 viewers, classement zed/gaby...) → vraies données API.
- Le JOURNAL du mockup est un changelog "patch notes" ; le vrai journal = entrées quotidiennes générées. Adapter le rendu carte aux entrées réelles (date, contenu markdown, chart). Garder l'esthétique carte arcade.
- Footer mockup : `github.com/KingsRequin/wallyAi` → `github.com/KingsRequin/wally-ai`.

## Gestion d'erreur

- Chaque section dégrade proprement si son endpoint échoue (placeholder arcade "—" / "hors ligne", pas de page blanche).
- SSE cognitif/émotions : reconnect auto (EventSource le fait), fallback snapshot REST.
- Pas de régression du chat (WebSocket OAuth) : réutiliser le module chat existant, re-skinné.

## Critères de succès

1. Les 6 sections rendues au thème arcade (fonts, fond animé, néons) — fidèle au mockup visuellement.
2. STATUT affiche vraies stats + barres émotions live (SSE) + **flux cerveau live** dans ACTIVITÉ EN DIRECT.
3. CHAT fonctionne (login Discord, WS, mémoire) — re-skinné, zéro régression.
4. GALERIE/JOURNAL/COMMUNAUTÉ affichent vraies données.
5. Nouveau backend : `/api/public/sse/cognitive`, `/api/public/cognitive/state`, `/api/public/community/ranking`, `avg_response_ms` — testés.
6. CognitiveLoop émet des events sans changement de comportement (tests V2 restent verts).
7. Responsive (mobile) préservé.
8. Démarrage bot propre, site servi, aucune régression backend.

## Hors scope

- Refonte de l'admin panel (`/admin`, static/) — inchangé.
- Tâches #14 (tab dashboard cognitive admin) / #15 (AtomicFacts admin) : le flux cognitif public couvre une partie de #14 ; le reste admin reste séparé.

## Découpe suggérée (sous-projets, à planifier)

- **R1 — Backend cognitive feed** : CognitiveFeed + émissions + SSE/state routes + tests. (socle du bloc phare)
- **R2 — Backend ranking + response-time** : 2 endpoints + tests.
- **R3 — Shell arcade + assets** : index.html re-skin, style.css arcade, canvas bg effects + flame sprites portés, router conservé.
- **R4 — Sections câblées** : porter les 6 tabs au thème arcade en réutilisant les fetch existants + nouveaux endpoints. (le plus gros — peut se sous-diviser par onglet)
- **R5 — Intégration** : rebuild, démarrage, vérif chaque section live, responsive.
