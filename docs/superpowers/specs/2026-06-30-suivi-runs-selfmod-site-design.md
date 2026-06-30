# Spec — Suivi live des runs de self-modification sur le site (niveau léger)

**Date :** 2026-06-30
**Branche :** `feat/site-redesign-arcade`
**Statut :** design validé, prêt pour plan d'implémentation
**Chantier :** TODO #2 — « Suivi en direct des runs de self-modification (Claude Code) sur le site »

## Contexte

Quand Wally émet `[ACT code_fix {goal}]`, `SelfFix` (`bot/intelligence/self_fix.py`)
demande l'autorisation du créateur en DM (✅/❌), lance Claude Code via le daemon hôte
(`scripts/host_bridge_daemon.py`, `claude -p --output-format json`), édite un message DM
de progression au fil de l'eau, puis commit + rebuild. **Ce suivi DM existe déjà.**

Sur le **site** (dashboard arcade public), en revanche, un run de self-modification est
quasi invisible : `cognitive_feed` ne reçoit un event (`type:"ACT"`) qu'aux **états
terminaux** (`_set_status` → DELIVERED/DECLINED/ABANDONED, `self_fix.py:60-83`). Rien
n'est publié pour la demande, l'acceptation, le démarrage du run, ni la progression.

**But :** rendre les runs self-mod visibles en direct sur le site, via le
`cognitive_feed` SSE déjà en place, **sans toucher au daemon hôte** (infra critique,
déployée à la main hors conteneur). Niveau léger : étapes + % estimé.

## Limite assumée (hors périmètre)

Le daemon lance `claude -p --output-format json`, qui ne renvoie qu'un **résultat final**
(`host_bridge_daemon.py:189-190`). Le « % » est donc une **estimation temporelle**
(`_PROGRESS_EST_SECONDS = 300`, `self_fix.py:16`), pas une progression réelle. Afficher
la **vraie activité** de Claude (fichiers lus/édités, tests) exigerait `--output-format
stream-json` + parsing incrémental côté daemon/bridge → **chantier futur séparé**, hors
de ce spec.

## Décisions de design (validées avec l'owner)

1. **Niveau léger** : republier les étapes dans le `cognitive_feed` SSE existant. Aucun
   changement au daemon hôte ni au protocole bridge.
2. **Type d'event dédié `CODEFIX`** (icône 🔧, « se répare »), distinct du `ACT` générique
   — les runs self-mod sont reconnaissables d'un coup d'œil.
3. **Granularité = jalons + seuils 25/50/75 %** (≤ ~7 events/run, pas de spam du buffer
   de 30).
4. **Jalon « proposée » publié AVANT validation** du créateur (transparence : on voit
   l'intention de Wally, même si elle est ensuite refusée).

## Architecture / flux

### Backend — `bot/intelligence/self_fix.py`

Helper centralisé (factorise la forme canonique déjà présente `self_fix.py:66-77`) :

```python
def _publish_feed(self, detail: str, full: str | None = None) -> None:
    """Publie un jalon de self-modification dans le cognitive_feed (best-effort)."""
    feed = getattr(self._bot, "cognitive_feed", None)
    if feed is None:
        return
    try:
        evt = {"type": "CODEFIX", "detail": detail}
        if full:
            evt["full"] = full
        feed.publish(evt)
    except Exception as e:  # noqa: BLE001 — jamais bloquant
        logger.debug("cognitive_feed CODEFIX publish échec: {}", e)
```

Points d'émission (tous dans `self_fix.py`) :

| Jalon | Emplacement | `detail` |
|---|---|---|
| Proposée | `request_upgrade`, après `self._active_goal = goal` (l.135) | `f"Wally veut se modifier : {goal[:200]}"` (`full=goal`) |
| Démarre | après `claude_run` (l.204) | `"validé par le créateur — Claude Code démarre"` |
| 25/50/75 % | dans `_progress(elapsed)` (l.209-214), au franchissement | `f"auto-modif en cours — avancement estimé ~{pct} %"` |
| Application | autour de `claude_commit`/`docker_rebuild` (l.249-253) | `"Claude a fini — application + rebuild en cours"` |
| Terminal | `_set_status` (l.66-77, déjà émis) | bascule `type:"ACT"` → `type:"CODEFIX"` |

Logique de seuils (état + fonction pure testable) :

```python
# constante module
_FEED_THRESHOLDS = (25, 50, 75)

# fonction pure (testable isolément)
def _next_threshold_crossed(pct: int, last: int) -> int | None:
    """Renvoie le plus haut seuil de _FEED_THRESHOLDS franchi par `pct` et non
    encore publié (> last), ou None. Garantit un seul event par palier."""
    crossed = [t for t in _FEED_THRESHOLDS if last < t <= pct]
    return max(crossed) if crossed else None
```

État sur l'instance : `self._last_feed_pct: int = 0` (réinitialisé au début de chaque
`_run_upgrade`). Dans `_progress`, après le calcul de `pct` : si
`_next_threshold_crossed(pct, self._last_feed_pct)` renvoie un seuil `t`, publier le
jalon et faire `self._last_feed_pct = t`.

### Front — `public-ui/tabs/status.js` + miroir `bot/dashboard/static/public-starter/tabs/status.js`

Les deux fichiers doivent rester **identiques** (cf. CLAUDE.md : source de vérité =
`public-starter/`, miroir = `public-ui/`).

- Ajouter à la table `FEED_META` (≈ l.23-34) :
  ```js
  CODEFIX: { color: '#e879f9', icon: '🔧', label: 'se répare' },
  ```
- Ajouter à `feedText(e)` (≈ l.48-59) une branche : `CODEFIX → e.detail` (avec dépliage
  `full` si présent, comme `ACT`).

Aucun autre changement front : `connectCognitiveSSE` / `pushFeedEvent` / `renderFeed`
traitent déjà n'importe quel `type` de façon générique.

## Persistance & cohérence

- `CODEFIX` est persisté par `cognitive_feed.publish` (seul `ATTN` est exclu,
  `cognitive_feed.py:47-55`) → apparaît dans `/cognitive/history` (rejoué au chargement
  via `seedFeed`). Cohérent avec `ACT`.
- L'anti-rumination du feed (drop si identique au dernier, `cognitive_feed.py:34`) ne
  gêne pas : chaque jalon a un `detail` différent.
- Libellés toujours « estimé » → pas de fausse précision.

## Tests (TDD)

Backend (`tests/intelligence/`) :
1. `_next_threshold_crossed` : `(10, 0)→None` ; `(30, 0)→25` ; `(60, 25)→50` ;
   `(80, 50)→75` ; `(80, 75)→None` ; `(100, 0)→75` (plus haut franchi).
2. `_publish_feed` : publie un event `type:"CODEFIX"` avec `detail` (et `full` si fourni)
   sur un feed mock ; `feed=None` → no-op ; feed qui lève → exception avalée.
3. (Si praticable sans trop de mocks) `_progress` : appels successifs avec `elapsed`
   croissant publient un jalon par palier et mettent à jour `_last_feed_pct`.

Front : pas de framework de test JS dans le projet → **vérification navigateur**
(chromium headless ou manuel) : un event `CODEFIX` injecté s'affiche avec l'icône 🔧 et
la couleur magenta. À faire au moment du déploiement.

## Déploiement

- Front bind-monté (`public-ui`) mais le backend embarque `public-starter` → **rebuild
  image** nécessaire (pour le helper backend + le miroir embarqué). Les deux fichiers
  front restent identiques.

## Hors périmètre

- `stream-json` / vraie activité de Claude (chantier futur séparé).
- `self_upgrade.py` (MAJ image GHCR — pas un run Claude).
- Toute modification du daemon hôte ou du protocole bridge.
