# Vie mentale progressive — Phase 5 (nettoyage one-shot de la dette)

Plan: docs/superpowers/plans/2026-06-27-vie-mentale-phase5-dedupe.md
Spec: docs/superpowers/specs/2026-06-26-vie-mentale-progressive-design.md (§ Phase 5)
Base: fda1c6c (HEAD, Phase 1 livrée)
Note: utiliser `python3 -m pytest` (pas `python`).

## Décisions issues des données réelles (lues le 2026-06-27)

1. **Clustering = déterministe pondéré IDF, pas de LLM.** Opération réversible
   (archive) + dry-run + revue humaine → déterminisme/reproductibilité > rappel
   LLM. 1444 pensées rendent le LLM impraticable. Les vrais doublons partagent
   des tokens rares (jubeii, polylrose, mks_zedd, downloads, Cluth) que l'IDF
   capte. La revue humaine du dry-run EST le filet sémantique.
2. **Pseudo-souvenirs : PAS de marquage par mot-clé.** polylrose/jubeii1979/
   mks_zedd sont de vrais users avec ~80 faits légitimes. Marquage limité à une
   **liste curée d'IDs confirmés faux** (#484 jubeii plays Apex, #575 polylrose
   dislikes Six seven). Le reste relève du futur outil live `doubt_memory`
   (Phase 3).
3. **Pensées : near-duplicate strict, pas thématique.** jubeii apparaît dans 403
   pensées légitimes ; élaguer par thème détruirait le monologue. On élague des
   grappes de quasi-doublons (option agressive = seuil plus bas), en gardant le
   représentant le plus récent. Réversible (archive).

## Périmètre (cible `wally:self`)

- DESIRE actifs (71) : fusion des grappes quasi-identiques → garde le plus
  récent, cumule `support_count`, archive les autres.
- THOUGHT actifs (1444) : élague les grappes de quasi-doublons → garde le plus
  récent par grappe, archive les autres.
- Pseudo-souvenirs : liste curée d'IDs → `needs_review` + confidence ≤ 0.3.
- Idempotent (2ᵉ run = 0 changement, car on ne charge que les `active`).
- Dry-run par défaut ; `--apply` exécute.

## Architecture — `scripts/dedupe_mental_state.py`

Fonctions pures (testables, sans DB) :
- `_tokens(text) -> set[str]` : lower, retrait ponctuation, split, drop stopwords
  + tokens < 3 car. Réutilise la logique de `facts._normalize`.
- `_idf(docs: list[set[str]]) -> dict[str, float]` : `log(N / (1 + df(t)))`.
- `_weighted_jaccard(a, b, idf) -> float` : `Σ idf[t∈a∩b] / Σ idf[t∈a∪b]`.
- `cluster(items, threshold, idf) -> list[list[int]]` : union-find sur paires
  dont la similarité pondérée ≥ seuil. `items` = liste d'index→tokens.
- `plan_merges(facts, threshold) -> list[Cluster]` : Cluster = {survivor, losers,
  merged_support}. Survivor = `max(last_seen_at, id)`. merged_support = Σ support.

DB (sqlite3 sync, modèle `purge_expired_facts.py`) :
- `load_facts(conn, category, user_id, status)`.
- `apply_merges(conn, clusters)` : survivor `support_count = merged`, losers
  `status='archived'`.
- `apply_pseudo(conn, ids)` : `status='needs_review'`, `confidence=MIN(conf,0.3)`.
- `print_report(...)` : grappes + IDs + extraits + survivant choisi + compteurs.

CLI : `--db` (def `DB_PATH`/`data/wally.db`), `--apply`, `--desire-threshold`
(def 0.5), `--thought-threshold` (def 0.45, agressif), `--skip-desires`,
`--skip-thoughts`, `--skip-pseudo`, `--user` (def `wally:self`).

## Tasks
- [x] Task 1: Fonctions pures (_tokens, _idf, _weighted_jaccard, cluster,
      plan_merges) + tests unitaires (paraphrases groupées, choix survivant,
      support cumulé, idempotence d'un set déjà dédupliqué).
- [x] Task 2: Couche DB + CLI (load/apply/report, dry-run vs --apply) + tests
      sur DB SQLite en mémoire/tmp (fixture avec doublons connus ; dry-run
      n'écrit rien ; --apply archive + cumule ; 2ᵉ run = 0 changement).
- [x] Task 3: Dry-run sur la vraie base, calibrage des seuils, revue des grappes.

## Vérification
- `python3 -m pytest tests/scripts/test_dedupe_mental_state.py -q` vert.
- `python3 -m pytest tests/intelligence -q` = 293 (pas de régression).
- Dry-run lisible sur `data/wally.db` ; grappes cohérentes après calibrage.

## Log
Tâches 1-3 complètes. 10 tests script verts + 293 intelligence (303 total, 0
régression). Calibrage dry-run sur `data/wally.db` (= base LIVE, bind-mount
`./data:/app/data`, bot actif) :
- DESIRE seuil 0.30 → 9 grappes, 24/71 archivés (jubeii ×9, mks_zedd ×6,
  Cluth-Silver ×4, downloads ×3, animés ×3, réactions emoji ×2, polylrose ×2,
  Cluth-Motorfest ×2, animés-aime ×2). Aucune fusion abusive constatée.
- THOUGHT seuil 0.25 → 65 grappes, 104/1444 archivés (test-emoji ×10,
  « on m'aurait menti » ×6, auto-modification ×4…). Quelques grappes regroupées
  surtout sur le cadre stéréotypé (vagabondage/ennui) — réversible.
- PSEUDO : #484, #575 → needs_review + confidence ≤ 0.3.
RESTE (Task d'exploitation, hors code) : `--apply` réel = base LIVE → backup +
idéalement coupler au déploiement Phase 1 (sinon ré-accumulation, anti-rumination
encore dormante). Décision timing/backup à valider avec le créateur.
