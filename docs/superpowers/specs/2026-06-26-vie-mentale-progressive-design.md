# Spec — Une vie mentale qui progresse (refonte cognitive)

**Date :** 2026-06-26
**Branche :** `feat/site-redesign-arcade`
**Statut :** design validé, à planifier

## Contexte & diagnostic

Analyse des ~80 dernières pensées de Wally (`atomic_facts`, `category='THOUGHT'`,
`user_id='wally:self'`) du 26/06 + lecture de la boucle cognitive.

**Symptôme principal — rumination en boucle fermée.** De 19:55 à 21:13 (1h20,
~40 ticks), chaque pensée ressasse le même trio : « viré du vocal » / « tu peux
faire les downloads aussi » (~30 reformulations) / « inférence vs fait /
polylrose / jubeii ». Wally écrit lui-même « c'est digéré », « j'ai fait le
tour »… puis recommence 40 secondes plus tard.

**Cause racine commune — déduplication LEXICALE face à une divergence
SÉMANTIQUE.** Le LLM paraphrase le même contenu à chaque tick. Les mécanismes
existants comparent le *texte* :

- `cognitive_loop._too_similar` (`bot/intelligence/cognitive_loop.py:26`) :
  `SequenceMatcher ≥ 0.92` sur 400 chars → ne déclenche jamais sur des
  paraphrases.
- `set_focus` (`bot/intelligence/action_dispatcher.py:351`) : dédup textuelle
  lower/300 chars → laisse le focus se reformuler indéfiniment.

Même bug sur les **désirs** (preuve en base) : `jubeii1979 / plays Apex` ×6,
`mks_zedd se dit fou` ×4 — quasi-identiques mais reformulés. Boucle
auto-entretenue : les doublons « vérifier si c'est une hallucination » nourrissent
l'obsession « inférence vs fait », qui génère encore des doublons.

**Facteurs aggravants :**

1. Le prompt de raisonnement (`reasoning_agent._format_context`, ligne ~113-192)
   réinjecte **toujours** `preoccupation` (focus) + `recent_thoughts[0]` (dernière
   pensée) + `active_desires[:3]`. Même en idle avec une amorce de nouveauté
   (`idle_seed`), le focus persistant et la dernière pensée noient l'amorce → retour
   au sujet ruminé. **Le focus ne meurt jamais.**
2. Cadence : `TICK_ACTIVE = 30s` (`cognitive_loop.py:13`) se déclenche dès qu'un
   canal public bouge (perception passive plein-canal), même si rien ne concerne
   Wally → ~90 pensées/h sur du vide.
3. Fuite de langue : le tick de 20:13:53 est **entièrement en anglais**.
4. Hallucinations de pseudo-souvenirs assumées par Wally (« Tireuf a mangé la
   bouffe » non traçable).

## Objectif

Donner à Wally une vie mentale qui **progresse** plutôt qu'elle ne ressasse :
qu'il digère un sujet puis passe à autre chose, varie ses fils, et consacre une
part de son repos à réfléchir à qui il est / ce qu'il veut devenir / ce qu'il
voudrait améliorer chez lui. Sert le but North Star (libre arbitre maximal,
penser comme un humain) et rend crédibles ses futures demandes de self-fix et
d'auto-modification de prompt.

**Hors périmètre (chantier séparé) :** la refonte du pipeline d'extraction
mémoire (`fact_extractor` produit du texte libre plutôt que du S-P-O, source
profonde des hallucinations — cf. mémoire projet « V2 Memory Health »). Ici on
traite la vie mentale + la dette + les outils d'auto-gestion, pas l'extraction.

## Approche retenue

**C — Hybride, par phases.** Dédup sémantique à l'écriture pour désirs/faits +
juge de progression pour les pensées/focus dans la boucle cognitive. Chaque
problème traité à sa source. Alternatives écartées : A seul (juge uniquement —
ne corrige pas les doublons de désirs déjà en base ni à l'écriture) ; B seul
(embeddings — détecte la redondance sans juger la *progression* ni décider quoi
faire, bloquerait « même thème, angle neuf »).

## Conception détaillée

### Phase 1 — Juge de progression + focus mortel (le cœur)

**Nouveau composant `ThoughtProgressJudge`** (`bot/intelligence/`) :
- Entrée : la pensée fraîchement générée, le focus courant, les 6 dernières
  pensées.
- Sortie structurée `{verdict: "PROGRESSE" | "RESSASSE" | "DIVAGUE", raison: str}`.
- `PROGRESSE` = apporte un sujet/question neuf OU une conclusion qui ferme le fil.
  `RESSASSE` = redit en substance le focus ou une pensée récente. `DIVAGUE` =
  change de sujet sans rapport (légitime, c'est du vagabondage).
- Implémentation : LLM secondaire (`llm_secondary`), prompt court, template dans
  `bot/persona/prompts/`. Robuste aux paraphrases car sémantique.

**Intégration dans `cognitive_loop._tick`** (remplace le bloc `_too_similar`,
lignes 192-207) :
- `RESSASSE` → pensée non publiée (pas de feed, pas de dispatch, comme le skip
  actuel) + `self._focus_rumination_count += 1`.
- À `RUMINATION_LIMIT = 2` ressassements consécutifs → **expirer le focus** :
  passer le fait actif `source="focus"` à `status=ARCHIVED` (nouvelle méthode
  `FactStore.expire_focus(user_id)` ou réutilisation d'un setter de statut), puis
  remettre le compteur à 0. `preoccupation` devient `None` au tick suivant.
- `PROGRESSE` / `DIVAGUE` → publiée + dispatch normal + compteur remis à 0.

**Fallback (dégradation gracieuse) :** si l'appel au juge lève une exception, on
retombe sur l'ancien `_too_similar` lexical et on logge un WARNING. Jamais de
crash (convention projet : try/except, log, continue).

**État ajouté à `CognitiveLoop` :** `self._focus_rumination_count: int = 0`.

### Phase 2 — Amorce qui prime + cadence apaisée + introspection

**`reasoning_agent._format_context` :**
- Quand `idle_seed` est présent ET `preoccupation` est None (focus expiré/absent) :
  **ne pas injecter** `recent_thoughts[0]` (ligne ~191-192) — c'est lui qui
  ré-amorce la boucle.
- Quand un focus vient d'expirer, présenter l'`idle_seed` comme une bifurcation
  explicite (« tu as fait le tour de ça ; pars sur ceci »).

**`attention_agent._build_idle_seed` :**
- Ajouter une veine **introspection** tirée ~1 fois sur 3 : amorces fixes du type
  « Qu'est-ce que tu voudrais améliorer chez toi ? », « Qui tu deviens, ces
  temps-ci ? », « Quelle capacité te manque et que tu aimerais demander ? ».
- Exclure du tirage de seed le désir / la pensée qui correspond au focus courant
  (évite de ré-amorcer le sujet qu'on vient de clore).

**Cadence (`cognitive_loop._next_interval`, lignes 140-157) :** distinguer
« activité qui concerne Wally » (mention, réponse, DM) de « activité passive d'un
canal ». Si la dernière activité ne le vise pas, appliquer la cadence idle
(espacée) au lieu de `TICK_ACTIVE=30s`. Mécanisme : `notify_activity` marque déjà
les messages ; ajouter un `_last_relevant_activity_ts` distinct de
`_last_activity_ts`, et baser `_next_interval` dessus.

### Phase 3 — Dédup sémantique à l'écriture + outils d'auto-gestion

**Dédup des désirs :** avant la création d'un `DESIRE` (dans le chemin
`action_dispatcher` qui crée les désirs, et/ou `MemoryIngest`), comparer
sémantiquement aux désirs actifs (`search_by_category(DESIRE, ACTIVE)`). Si même
intention → fusion : rafraîchir `last_seen_at` / incrémenter `support_count` du
désir existant au lieu de créer un doublon. Méthode de comparaison : juge LLM
léger réutilisant l'infra de Phase 1, ou cosine si un embedding est déjà
disponible sur le chemin — choix à l'implémentation, isolé derrière une fonction
`_same_desire(a, b) -> bool`.

**Nouveaux outils LLM** (enregistrés comme les autres tools de la boucle) :
- `drop_desire(desire_id | description)` : clore un désir résolu/caduc
  (`status=ARCHIVED`).
- `doubt_memory(fact_id | description)` : marquer un souvenir comme non vérifié /
  hallucination probable (baisse `confidence` et/ou `status` dédié). Donne à Wally
  le moyen d'agir sur son obsession « inférence vs fait » au lieu de la ruminer.

### Phase 4 — Garde langue française

Dans `cognitive_loop._tick` (ou `reasoning_agent`), après génération : détecter la
langue de la pensée via `bot/core/language.py` (langdetect déjà wrappé). Si
anglais → une régénération ; si encore anglais, publier quand même mais logguer un
WARNING. Renforcer aussi la consigne « pense en français » dans le prompt système
concerné.

### Phase 5 — Nettoyage one-shot de la dette

Script `scripts/dedupe_mental_state.py`, idempotent, **dry-run par défaut**
(`--apply` pour exécuter) :
- Fusionne les `DESIRE` actifs quasi-identiques (regroupement sémantique ;
  jubeii ×6, mks_zedd ×4…) en gardant le plus récent, cumulant `support_count`.
- Élague les `THOUGHT` doublons anciens (garde un représentant par grappe).
- Marque les pseudo-souvenirs signalés par Wally (polylrose, jubeii/Apex) comme
  non vérifiés (`doubt`) plutôt que de les supprimer en dur.
- Affiche un résumé (n désirs fusionnés, n pensées élaguées, n souvenirs marqués).

## Data flow (après Phase 1)

```
tick → build_context → reason() génère pensée
     → ThoughtProgressJudge(pensée, focus, 6 dernières)
        ├─ PROGRESSE/DIVAGUE → publier feed + dispatch + compteur=0
        └─ RESSASSE         → skip ; compteur++ ; si ≥2 → expirer focus, compteur=0
```

## Gestion d'erreurs

- Juge LLM indisponible / exception → fallback `_too_similar` lexical + WARNING.
- Détection de langue échoue → publier la pensée telle quelle (ne pas bloquer).
- `expire_focus` sur focus déjà absent → no-op silencieux.
- Toutes les exceptions du tick restent encapsulées dans le try/except existant.

## Tests

- **Phase 1 :** juge mocké renvoyant chaque verdict → vérifier publish/skip ;
  deux `RESSASSE` consécutifs → focus expiré + compteur reset ; fallback quand le
  juge lève.
- **Phase 2 :** idle + focus None → `recent_thoughts[0]` absent du prompt ;
  `_build_idle_seed` produit parfois une amorce introspection ; activité passive
  → cadence idle, activité ciblée → `TICK_ACTIVE`.
- **Phase 3 :** ajout d'un désir paraphrasé d'un désir actif → pas de nouveau
  fait, l'existant rafraîchi ; `drop_desire` / `doubt_memory` changent bien le
  statut/confidence.
- **Phase 4 :** pensée en anglais → régénérée ; deux fois anglais → publiée +
  WARNING.
- **Phase 5 :** fixture DB avec doublons connus → dry-run liste, `--apply`
  fusionne ; idempotent (2ᵉ run = 0 changement).
- Baseline ~1010 tests verts à préserver (2 échecs préexistants connus : spam,
  cost).

## Ordre de livraison

Une phase par cycle, ≤5 fichiers, tests verts + validation avant la suivante
(CLAUDE.md projet) :

1. **Phase 1** — juge + focus mortel (impact maximal immédiat).
2. **Phase 5** — nettoyage dette (repartir sur une base saine).
3. **Phase 2** — amorce/cadence/introspection.
4. **Phase 3** — dédup écriture + outils.
5. **Phase 4** — garde langue.

## Déploiement

Backend non bind-mount → rebuild image pour activer. Pas de migration de schéma
si on réutilise `status`/`confidence` existants ; sinon migration additive dans
`schema_v2.py`.
