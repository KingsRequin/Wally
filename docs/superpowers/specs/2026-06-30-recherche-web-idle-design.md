# Spec — Recherche web pendant les pensées cognitives (chantier B du self-model)

**Date :** 2026-06-30
**Branche :** `feat/site-redesign-arcade`
**Statut :** design validé, prêt pour plan d'implémentation
**Chantier :** TODO #1 — « Self-model chantier B : recherche web en pensée idle »

## Contexte

Le self-model dérivé (livré 2026-06-28) rend les capacités de Wally cohérentes avec
son état réel (ex. le vocal dérivé de `config.voice.enabled`). Le **web** avait été
exclu : il reste nié en dur dans `bot/persona/CAPABILITIES.md:21` (« Je ne navigue pas
sur le web librement — seulement via un outil précis quand on m'en donne un »).

Aujourd'hui, `WebSearchService` (`bot/core/web_search.py`) n'est appelé que dans le
**chemin réactif** (Discord/Twitch texte via `complete_with_tools`, et vocal « à voix
haute » via `bot/discord/voice/tools.py::_search_aloud`). **Aucun appelant dans le
chemin cognitif/idle.** Le tick cognitif n'utilise pas de tool-calling natif : les
actions passent par des tags texte `[ACT nom {json}]` parsés depuis la pensée
(`bot/intelligence/meta_agent.py`), dispatchés par `ActionDispatcher._act`.

**But :** donner à Wally la capacité de chercher sur le web **de sa propre initiative**
pendant ses pensées (vagabondage mental), de façon émergente — il décide, on ne le
force pas. Aligné North Star « émergent > hard-code, autonomie #1 ».

## Décisions de design (validées avec l'owner)

1. **Déclenchement : émergent.** Wally décide seul en écrivant
   `[ACT web_search {"query": "…"}]` dans sa pensée. Aucune amorce ne le pousse.
   La capacité est dérivée dynamiquement dans le self-model pour qu'il **sache** qu'il
   peut (sinon il ne l'utilisera jamais).
2. **Résultat : seconde passe immédiate.** Dans le même tick : il pense → s'il émet
   `web_search`, on exécute la recherche → on réinjecte le résultat → il **re-pense**
   avec l'info. La 2ᵉ pensée suit le flux normal (judge → décisions).
3. **Garde-fou : cooldown léger configurable + quota Tavily.** Délai minimal entre deux
   recherches cognitives, en plus du quota mensuel Tavily déjà existant.
4. **Périmètre : tous les ticks cognitifs** (idle ET actif sans nouvelle activité
   externe), pas seulement `is_idle`. C'est la curiosité de Wally qui décide ; le
   cooldown gère l'abus. Le chemin **réactif** est hors périmètre (web déjà branché là).

## Architecture / flux

Dans `bot/intelligence/cognitive_loop.py::_tick`, après
`result = await self._reasoning.reason(context)` (≈ ligne 356) et **avant** le
`ThoughtProgressJudge` :

```
1. Chercher dans result.decisions une décision act_name == "web_search".
2. Si présente ET gardes OK (capacité dispo + sous quota + cooldown écoulé):
   a. extraire query depuis act_args ;
   b. résultat = await web_search.search(query, platform="discord") ;
   c. armer le cooldown (_web_search_cooldown_ts = time.monotonic()) ;
   d. émettre un event ACT au cognitive_feed (observabilité site) ;
   e. reconstruire le contexte avec web_finding = "query → résultat" ;
   f. result = await self._reasoning.reason(context2)  # 2e passe
3. La pensée (1re sans tag, ou 2e après recherche) continue le flux normal:
   ThoughtProgressJudge → THINK → DECIDE → routage des décisions.
```

**Garde anti-boucle : une seule recherche par tick.** Si la 2ᵉ pensée re-émet
`web_search`, on l'ignore (elle suit le routage normal des décisions, où `web_search`
n'est PAS un act_name dispatché — voir ci-dessous).

**`web_search` n'est PAS un `act_name` d'`ActionDispatcher`.** Il est intercepté
uniquement dans `_tick` (avant le dispatch). S'il atteint la boucle de dispatch normale
(cas de la 2ᵉ passe), `_act` ne le connaît pas → no-op silencieux (log debug). Pas de
nouvelle branche dans `action_dispatcher.py`.

## Composants touchés

| Fichier | Changement |
|---|---|
| `bot/intelligence/attention_agent.py` | Champ `web_finding: str \| None` sur `AttentionContext` ; param `web_finding=None` sur `build_context()` (passé tel quel, pas recalculé). |
| `bot/intelligence/reasoning_agent.py` | `_format_context` rend un bloc « Tu viens de chercher sur le web : *query* → *résultat* » quand `web_finding` est présent. |
| `bot/intelligence/cognitive_loop.py` | Interception `web_search` + 2ᵉ passe + état `_web_search_cooldown_ts` + gardes. Injection DI : `web_search` (déjà sur le bot), `cognitive_feed` (déjà présent pour les events). |
| `bot/intelligence/persona/prompts/reasoning_system.md` | Ajouter `[ACT web_search {"query": "…"}]` à la liste des actions offertes (lignes ≈ 80-90, à la suite des autres `[ACT …]`), avec une consigne d'usage (curiosité réelle, pas à chaque pensée). |
| `bot/intelligence/self_model.py` | Étendre la signature `build_self_model(static_text, config, *, web_available)` et ajouter une capacité « web » dérivée de `web_available` → phrase active/inactive. **Voir note dispo ci-dessous.** |
| `bot/persona/CAPABILITIES.md` | Retirer/corriger la ligne 21 qui nie la navigation web (deviendrait fausse). |
| `bot/config.py` | Champ `cognitive_cooldown_minutes: int = 45` sur `TavilyConfig` (déjà existante, n'a que `monthly_limit`). |

### Note disponibilité web pour le self-model
`build_self_model(static_text, config)` est **pure sur `config`**, mais la dispo web
réelle dépend de `TAVILY_API_KEY` (env, lu dans `web_search.py:83`), PAS de la config —
`TavilyConfig` n'a que `monthly_limit`. On ne peut donc pas la dériver fidèlement depuis
`config` seul. **Décision : étendre la signature** en
`build_self_model(static_text, config, *, web_available: bool = False)`. Le flag est
calculé au câblage (`bot/discord/bot.py` et `bot/intelligence/persona.py`) à partir de
`bot.web_search.available` (et idéalement `not await is_quota_exceeded()`, sinon
`available` seul suffit pour le self-model — le quota est revérifié au moment du tick).
Mettre à jour les deux appelants existants de `build_self_model`.

## Garde-fous & config

- Capacité offerte au LLM (documentée dans le prompt + self-model) **seulement si**
  `web_search.available and not await web_search.is_quota_exceeded()` — même garde qu'en
  vocal (`bot/discord/voice/tools.py:39-41`).
- Cooldown : `config.tavily.cognitive_cooldown_minutes` (défaut 45 min). Stocké
  via `time.monotonic()` sur l'instance du `CognitiveLoop` (`_web_search_cooldown_ts`).
- Une seule recherche par tick (anti-boucle).

## Tests (TDD)

1. Pensée sans tag `web_search` → aucune recherche, aucune 2ᵉ passe.
2. Pensée avec `[ACT web_search {"query": "x"}]`, gardes OK → `web_search.search` appelé
   une fois avec « x » → 2ᵉ passe `reason()` reçoit un contexte avec `web_finding`.
3. Cooldown actif (recherche récente) → tag ignoré, pas de recherche.
4. Quota dépassé OU Tavily indisponible → capacité non offerte / recherche non exécutée.
5. Une seule recherche par tick : 2ᵉ pensée re-émet `web_search` → ignorée.
6. `web_finding` présent → `reasoning_agent._format_context` rend le bloc attendu.
7. `self_model` : web dispo → phrase active ; indispo → phrase inactive.

Cible : aucune régression sur la suite existante (`tests/intelligence/`).

## Hors périmètre

- Recherche web dans le chemin **réactif** (déjà branché).
- Recherche d'**images** (`IMAGE_SEARCH_TOOL`), scraping Firecrawl (stack séparée).
- Amorce de curiosité « web » dans `_build_idle_seed` (déclenchement émergent uniquement).
- Refonte de l'extraction mémoire S-P-O.
