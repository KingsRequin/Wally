# Wally Observability — flux cognitif riche, but courant, mémoire admin

**Date** : 2026-06-27
**Branche** : `feat/site-redesign-arcade`
**But** : « voir vraiment ce qui se passe dans la tête de Wally » — rendre lisible et complet ce qu'il fait (site public) et exposer sa mémoire (admin).

## Problème

L'« activité en direct » du site ne montre, en pratique, que ses pensées :
- la plupart des events SONT déjà émis (THINK, SPEAK, ACT, DM, DECIDE, EVOLVE) mais le **rendu front est pauvre** (libellés indistincts, REACT noyé dans « ACT ») ;
- les **self-fix** n'émettent que la *demande*, jamais l'issue (accepté / refusé / déployé) ;
- les textes sont **tronqués à l'émission** (`goal[:60]`, `ACT[:300]`, `ATTN[:160]`) sans moyen de voir la suite ;
- le **buffer est en RAM (30 events)** → pas d'historique durable ;
- **aucune UI pour le but courant** ;
- l'admin mémoire affiche un **stub** (« mémoire en refonte ») et n'expose jamais les faits S-P-O V2.

## Décisions

- **Historique persistant léger** : table `cognitive_events` avec rotation (cap 1000 lignes), le live SSE et le buffer RAM restent inchangés. **ATTN n'est PAS persisté** (trop fréquent/transitoire) — il reste visible en live mais hors historique ; on persiste ce que Wally *fait/pense* (THINK, SPEAK, ACT, REACT, DM, self-fix, EVOLVE, DECIDE).
- **Anti-troncature par dépliage** : chaque event porte `snippet` (court) + `full` (complet, borné ~2000) ; le front déplie au clic.
- **REACT** = type d'event distinct.
- **Mémoire admin** : faits S-P-O par utilisateur **et** mémoire interne de Wally (`wally:self`).
- **Popup but** : sur le site public.

---

## Volet 1 — Activité en direct complète

### Backend

**`bot/intelligence/cognitive_feed.py`**
- `publish(event)` : en plus du buffer RAM + fan-out SSE, **persiste** l'event via un `event_store` injecté (best-effort, jamais bloquant) — **sauf `type == "ATTN"`** (exclu de l'historique).
- Normalisation : chaque event conserve ses champs existants ; on ajoute `full` optionnel (texte complet) là où un `snippet`/`detail` est tronqué.

**Nouveau `CognitiveEventStore`** (table `cognitive_events`)
- Schéma : `id INTEGER PK`, `ts REAL` (epoch mur), `type TEXT`, `payload TEXT` (JSON de l'event complet).
- `append(event)` : INSERT + rotation (supprime `id <= max_id - CAP`, CAP=1000) — trim cheap à chaque insert.
- `recent(limit, before_id=None)` : pagination décroissante pour l'historique.
- DDL idempotent dans `schema_v2.py` (`CREATE TABLE IF NOT EXISTS`).

**Émissions enrichies**
- `action_dispatcher._react` (≈l.421) : publier `{"type":"REACT","emoji","channel","detail"}` au lieu de `ACT detail "react …"`.
- `self_fix.py` (≈l.276-303) : publier l'issue sur le feed à chaque transition — `{"type":"ACT","detail":"auto-modif acceptée/refusée/déployée : <goal>"}` (réutilise le feed déjà injecté, sinon best-effort).
- `action_dispatcher` code_fix (≈l.591) : `goal[:60]→[:200]` + champ `full=goal`.
- Là où `detail[:300]` coupe : garder `detail` (snippet) **et** ajouter `full` = texte entier (borné 2000).

**Route** `bot/dashboard/routes/cognitive.py`
- `GET /api/public/cognitive/history?limit=50&before=<id>` → `{"events":[…], "next_before":<id|null>}`.

### Front — `bot/dashboard/static/public-starter/tabs/status.js`
- `feedText`/rendu : un libellé + icône par type, REACT/DM/self-fix inclus. Couleurs réutilisées.
- **Clic sur une ligne** → déplie `full` (toggle), sinon affiche `snippet`.
- Scroll en bas de la liste → fetch `/cognitive/history?before=…`, append (historique défilable).
- Miroir requis vers `public-ui/` (cf. process projet).

### Tests
- `CognitiveEventStore` : append + rotation (cap respecté) + `recent` pagination (vraie DB SQLite, comme `test_fts.py`).
- `cognitive_feed.publish` persiste via le store injecté + reste best-effort si le store lève.
- Émission REACT distincte (test action_dispatcher).
- Route history (test dashboard).

---

## Volet 2 — Popup « but actuel »

### Backend — `routes/cognitive.py`
- `GET /api/public/cognitive/goal` → `{"goals":[…GOAL actifs…], "preoccupation": <focus|null>, "desires":[…]}`. Lit `fact_store.search_by_category(GOAL/DESIRE, ACTIVE)` + `get_latest_by_source("wally:self","focus")`.

### Front — `status.js`
- Bouton « 🎯 Son but » → popup (modale arcade) : but(s) courant(s), préoccupation du moment, désirs actifs. Vide → message « il vagabonde, aucun but fixé ».

### Tests
- Route goal : structure de réponse (fact_store mocké).

---

## Volet 3 — Mémoire dans l'admin

### Backend — `routes/memory.py`
- `GET /api/admin/memory/users/{user_id}/facts` → faits S-P-O actifs du user (remplace le stub l.249-254). Utilise `fact_store.get_by_user(user_id)`.
- `GET /api/admin/memory/self` → mémoire interne : `{"goals":[],"desires":[],"thoughts":[],"relationships":[],"focus":…}` via `search_by_category` + `get_by_user("wally:self",[REL])` + `get_latest_by_source(focus)`.

### Front — `bot/dashboard/static/app.js`
- Détail user : remplacer le stub par la liste des faits (S-P-O ou contenu, catégorie, confiance, origine, date).
- Nouvelle section « Dans la tête de Wally » (sous l'onglet Mémoire) : buts, désirs, pensées récentes, affinités, focus.

### Tests
- Routes `/users/{id}/facts` et `/self` : structure (fact_store mocké), auth admin requise.

---

## Phasage (chaque phase ≤5 fichiers cœur, TDD Python)

- **Phase A — Backend feed** : `CognitiveEventStore` + DDL + persistance dans `publish` + REACT distinct + self-fix issue + anti-troncature (`full`) + route history.
- **Phase B — Front public** : rendu enrichi + clic-déplier + scroll historique + popup but (+ route goal).
- **Phase C — Admin mémoire** : routes facts/self + UI détail user + section « tête de Wally ».

## Risques / non-buts

- **Rotation** : cap par count (1000) ; pas de rétention temporelle fine (YAGNI).
- **Twitch** : non concerné (le feed est cognitif, pas par plateforme).
- **Front non couvert par tests auto** : vérifié au navigateur (chromium headless, cf. process projet).
- Déploiement backend = rebuild image (non bind-mount).
