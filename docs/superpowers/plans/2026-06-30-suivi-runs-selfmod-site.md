# Suivi live des runs self-mod sur le site — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendre les runs de self-modification de Wally visibles en direct sur le site en republiant leurs jalons dans le cognitive_feed SSE via un type d'event dédié `CODEFIX`.

**Architecture:** Émission backend dans `self_fix.py` (helper `_publish_feed` + jalons proposée/démarre/seuils 25-50-75%/application/terminal) ; rendu front via une entrée `FEED_META.CODEFIX` + branche `feedText` dans les deux fichiers `status.js` miroir. Aucun changement au daemon hôte ni au protocole bridge.

**Tech Stack:** Python 3.11, asyncio, pytest ; front vanilla JS (EventSource SSE).

## Global Constraints

- Logging : `loguru` exclusivement (`from loguru import logger`), jamais `print`/`logging`.
- Émission feed = **best-effort** : ne jamais propager d'exception (le flux self-fix ne doit pas casser).
- Type d'event dédié `CODEFIX` (pas de réutilisation de `ACT` pour les jalons self-mod). Le terminal (`_set_status`) bascule de `ACT` → `CODEFIX`.
- Granularité : jalons + seuils **25/50/75 %** uniquement (≤ ~7 events/run ; ne pas spammer le buffer de 30).
- Jalon « proposée » publié AVANT validation du créateur (à `request_upgrade`, après les gardes).
- Libellés de progression toujours « estimé » (le % est temporel, pas réel).
- Les **deux** fichiers front doivent rester **identiques** : `bot/dashboard/static/public-starter/tabs/status.js` (source de vérité) et `public-ui/tabs/status.js` (miroir).
- Baseline tests : suite verte (échecs préexistants connus à ignorer : `tests/test_web_search.py::test_complete_with_tools_logs_cost`, `tests/test_dashboard_costs.py`).

---

## File Structure

| Fichier | Responsabilité / changement |
|---|---|
| `bot/intelligence/self_fix.py` | Constante `_FEED_THRESHOLDS` + fonction pure `_next_threshold_crossed` ; `__init__` état `_last_feed_pct` ; méthodes `_publish_feed` / `_maybe_publish_progress` ; jalons insérés dans `request_upgrade` + `_run_upgrade` ; `_set_status` bascule `ACT`→`CODEFIX`. |
| `bot/dashboard/static/public-starter/tabs/status.js` | `FEED_META.CODEFIX` + branche `feedText` (source de vérité). |
| `public-ui/tabs/status.js` | Idem, miroir identique. |
| `tests/intelligence/test_self_fix_feed.py` | (créé) Tests `_next_threshold_crossed`, `_publish_feed`, `_maybe_publish_progress`. |

---

## Task 1 : Backend — émission des jalons self-mod dans le feed

**Files:**
- Modify: `bot/intelligence/self_fix.py`
- Test: `tests/intelligence/test_self_fix_feed.py` (créé)

**Interfaces:**
- Consumes: `self._bot.cognitive_feed` (objet avec `.publish(dict)`), déjà posé sur le bot.
- Produces:
  - module-level `_next_threshold_crossed(pct: int, last: int) -> int | None`
  - `SelfFix._publish_feed(self, detail: str, full: str | None = None) -> None`
  - `SelfFix._maybe_publish_progress(self, pct: int) -> None` (met à jour `self._last_feed_pct`)
  - état `SelfFix._last_feed_pct: int`

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `tests/intelligence/test_self_fix_feed.py` :

```python
from unittest.mock import MagicMock

from bot.intelligence.self_fix import SelfFix, _next_threshold_crossed


def _selffix(feed):
    bot = MagicMock()
    bot.cognitive_feed = feed
    return SelfFix(MagicMock(), bot)


# --- _next_threshold_crossed (fonction pure) ---

def test_threshold_none_below_first():
    assert _next_threshold_crossed(10, 0) is None


def test_threshold_first_crossed():
    assert _next_threshold_crossed(30, 0) == 25


def test_threshold_second_crossed():
    assert _next_threshold_crossed(60, 25) == 50


def test_threshold_third_crossed():
    assert _next_threshold_crossed(80, 50) == 75


def test_threshold_same_palier_not_republished():
    assert _next_threshold_crossed(80, 75) is None


def test_threshold_highest_crossed_returned():
    assert _next_threshold_crossed(100, 0) == 75


# --- _publish_feed (best-effort) ---

def test_publish_feed_emits_codefix():
    feed = MagicMock()
    sf = _selffix(feed)
    sf._publish_feed("test detail", full="le goal")
    feed.publish.assert_called_once()
    evt = feed.publish.call_args.args[0]
    assert evt["type"] == "CODEFIX"
    assert evt["detail"] == "test detail"
    assert evt["full"] == "le goal"


def test_publish_feed_no_full_key_when_absent():
    feed = MagicMock()
    sf = _selffix(feed)
    sf._publish_feed("sans full")
    evt = feed.publish.call_args.args[0]
    assert "full" not in evt


def test_publish_feed_no_feed_is_noop():
    bot = MagicMock()
    bot.cognitive_feed = None
    sf = SelfFix(MagicMock(), bot)
    sf._publish_feed("x")  # ne doit pas lever


def test_publish_feed_swallows_exception():
    feed = MagicMock()
    feed.publish.side_effect = Exception("boom")
    sf = _selffix(feed)
    sf._publish_feed("x")  # ne doit pas lever


# --- _maybe_publish_progress (seuils + état) ---

def test_progress_crosses_first_threshold():
    feed = MagicMock()
    sf = _selffix(feed)
    sf._maybe_publish_progress(30)
    assert sf._last_feed_pct == 25
    feed.publish.assert_called_once()
    assert "25" in feed.publish.call_args.args[0]["detail"]


def test_progress_no_double_publish_same_palier():
    feed = MagicMock()
    sf = _selffix(feed)
    sf._maybe_publish_progress(30)   # franchit 25
    feed.publish.reset_mock()
    sf._maybe_publish_progress(45)   # toujours dans le palier 25 (< 50)
    feed.publish.assert_not_called()
    assert sf._last_feed_pct == 25


def test_progress_below_first_threshold_silent():
    feed = MagicMock()
    sf = _selffix(feed)
    sf._maybe_publish_progress(10)
    feed.publish.assert_not_called()
    assert sf._last_feed_pct == 0
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `python3 -m pytest tests/intelligence/test_self_fix_feed.py -v`
Expected: FAIL (`ImportError: cannot import name '_next_threshold_crossed'`, puis `AttributeError` sur `_publish_feed`/`_maybe_publish_progress`).

- [ ] **Step 3 : Constante + fonction pure**

Dans `bot/intelligence/self_fix.py`, après `_PROGRESS_EST_SECONDS = 300.0` (l.16) :

```python
# Seuils d'avancement (%) republiés dans le cognitive_feed pendant un run self-mod.
# Un seul event par palier franchi → le run reste visible sur le site sans noyer
# le feed (buffer de 30 events).
_FEED_THRESHOLDS = (25, 50, 75)


def _next_threshold_crossed(pct: int, last: int) -> int | None:
    """Plus haut seuil de _FEED_THRESHOLDS franchi par `pct` et pas encore publié
    (strictement > last), ou None. Garantit un event par palier."""
    crossed = [t for t in _FEED_THRESHOLDS if last < t <= pct]
    return max(crossed) if crossed else None
```

- [ ] **Step 4 : État `_last_feed_pct` dans `__init__`**

Dans `SelfFix.__init__`, après `self._active_goal: str | None = None` (l.58) :

```python
        # Dernier palier d'avancement publié sur le feed pour le run en cours
        # (réinitialisé à chaque nouvelle demande). Évite de republier le même palier.
        self._last_feed_pct: int = 0
```

- [ ] **Step 5 : Méthodes `_publish_feed` et `_maybe_publish_progress`**

Ajouter ces deux méthodes dans la classe `SelfFix` (par ex. juste après `_set_status`) :

```python
    def _publish_feed(self, detail: str, full: str | None = None) -> None:
        """Publie un jalon de self-modification dans le cognitive_feed (type CODEFIX).
        Best-effort : ne propage jamais (le feed ne doit pas casser le flux self-fix)."""
        feed = getattr(self._bot, "cognitive_feed", None)
        if feed is None:
            return
        try:
            evt = {"type": "CODEFIX", "detail": detail}
            if full:
                evt["full"] = full
            feed.publish(evt)
        except Exception as e:  # noqa: BLE001 — le feed ne doit jamais casser le flux
            logger.debug("self-fix CODEFIX publish échoué: {}", e)

    def _maybe_publish_progress(self, pct: int) -> None:
        """Publie un jalon de progression au franchissement d'un palier (25/50/75 %)."""
        t = _next_threshold_crossed(pct, self._last_feed_pct)
        if t is not None:
            self._last_feed_pct = t
            self._publish_feed(f"auto-modif en cours — avancement estimé ~{t} %")
```

- [ ] **Step 6 : Lancer, vérifier le succès des tests de briques**

Run: `python3 -m pytest tests/intelligence/test_self_fix_feed.py -v`
Expected: PASS (12 tests).

- [ ] **Step 7 : Insérer les jalons dans le flux**

(a) `request_upgrade` — après `self._active_goal = goal` (l.135), ajouter le reset + le jalon « proposée » :

```python
        self._active_goal = goal   # suivi de l'issue sur le feed (#observability A4)
        self._last_feed_pct = 0
        self._publish_feed(f"Wally veut se modifier : {goal[:200]}", full=goal)
```

(b) `_run_upgrade` — après `job_id = await self._bridge.claude_run(...)` (l.204), ajouter :

```python
        self._publish_feed("validé par le créateur — Claude Code démarre")
```

(c) Dans la closure `_progress(elapsed)` (l.209-214), après le bloc `try/except` qui édite `prog_msg`, ajouter :

```python
            self._maybe_publish_progress(pct)
```

(d) Phase finale — juste avant `await self._bridge.claude_commit(job_id)` (l.252), ajouter :

```python
        self._publish_feed("Claude a fini — application + rebuild en cours")
```

- [ ] **Step 8 : Basculer le terminal `ACT` → `CODEFIX`**

Dans `_set_status` (l.71-75), changer le `type` de l'event publié :

```python
            try:
                feed.publish({
                    "type": "CODEFIX",
                    "detail": f"auto-modif {label} : {goal[:200]}",
                    "full": goal,
                })
            except Exception as e:  # noqa: BLE001 — le feed ne doit jamais casser le flux
                logger.warning("self-fix feed.publish échoué: {}", e)
```

- [ ] **Step 9 : Suite complète (non-régression)**

Run: `python3 -m pytest tests/intelligence/test_self_fix_feed.py -v && python3 -m pytest -q`
Expected: les 12 nouveaux tests PASS ; suite globale sans nouvel échec (seuls les échecs costs préexistants tolérés).

- [ ] **Step 10 : Commit**

```bash
git add bot/intelligence/self_fix.py tests/intelligence/test_self_fix_feed.py
git commit -m "feat(self-fix): republie les jalons self-mod dans le cognitive_feed (type CODEFIX, seuils 25/50/75%)"
```

---

## Task 2 : Front — type `CODEFIX` dans le feed du site

**Files:**
- Modify: `bot/dashboard/static/public-starter/tabs/status.js` (FEED_META ≈ l.23-34 ; feedText ≈ l.48-59)
- Modify: `public-ui/tabs/status.js` (mêmes emplacements — miroir identique)

**Interfaces:**
- Consumes: events `{type:"CODEFIX", detail, full?}` produits par Task 1.
- Produces: rendu visuel (icône 🔧, couleur magenta, label « se répare »).

> Pas de framework de test JS dans le projet → vérification au navigateur (étape finale). Les deux fichiers DOIVENT rester identiques.

- [ ] **Step 1 : Ajouter `FEED_META.CODEFIX` (source de vérité)**

Dans `bot/dashboard/static/public-starter/tabs/status.js`, dans la table `FEED_META`, après la ligne `SLEEP: {...},` (l.33) :

```js
  CODEFIX: { color: '#e879f9', icon: '🔧', label: 'se répare' },
```

- [ ] **Step 2 : Ajouter la branche `feedText` (source de vérité)**

Dans le même fichier, dans `feedText(e)`, après la ligne `if (e.type === 'EVOLVE') ...` (l.57) :

```js
  if (e.type === 'CODEFIX') return e.detail || '';
```

- [ ] **Step 3 : Répliquer à l'identique dans le miroir**

Appliquer EXACTEMENT les deux mêmes ajouts (Steps 1 et 2) dans `public-ui/tabs/status.js`.

- [ ] **Step 4 : Vérifier l'identité des deux fichiers**

Run: `diff bot/dashboard/static/public-starter/tabs/status.js public-ui/tabs/status.js`
Expected: aucune différence (sortie vide, exit 0).

- [ ] **Step 5 : Commit**

```bash
git add bot/dashboard/static/public-starter/tabs/status.js public-ui/tabs/status.js
git commit -m "feat(site): type CODEFIX dans le feed cognitif (🔧 se répare) — runs self-mod visibles"
```

---

## Task 3 : Vérification d'intégration

**Files:** aucun (vérification seule).

- [ ] **Step 1 : Suite backend ciblée + globale**

Run: `python3 -m pytest tests/intelligence/test_self_fix_feed.py -q && python3 -m pytest -q`
Expected: nouveaux tests verts ; aucun nouvel échec global.

- [ ] **Step 2 : Import smoke**

Run: `python3 -c "import bot.intelligence.self_fix"`
Expected: aucune exception.

- [ ] **Step 3 : Identité des deux fichiers front**

Run: `diff bot/dashboard/static/public-starter/tabs/status.js public-ui/tabs/status.js && echo IDENTIQUES`
Expected: `IDENTIQUES`.

- [ ] **Step 4 : Vérification navigateur (au déploiement)**

Après rebuild image : ouvrir le site, onglet Status. Injecter (ou attendre) un event `CODEFIX` et confirmer le rendu : icône 🔧, couleur magenta `#e879f9`, label « se répare », texte = `detail`. À faire au moment du déploiement (chromium headless ou manuel). Noter le résultat.

---

## Self-Review (rempli à la rédaction)

- **Couverture spec :** type CODEFIX (Task 1 backend + Task 2 front) ✓ ; jalon proposée avant validation (Step 7a) ✓ ; démarre (7b) ✓ ; seuils 25/50/75 via `_maybe_publish_progress` (7c) ✓ ; application (7d) ✓ ; terminal basculé ACT→CODEFIX (Step 8) ✓ ; best-effort partout (`_publish_feed` try/except, tests dédiés) ✓ ; 2 fichiers miroir identiques (Task 2 Step 4 + Task 3 Step 3) ✓ ; daemon hôte non touché (aucune modif de `host_bridge_daemon.py`) ✓.
- **Placeholders :** aucun — chaque step porte le code réel et l'emplacement exact.
- **Type consistency :** `_next_threshold_crossed(pct, last)` défini (Step 3) et consommé par `_maybe_publish_progress` (Step 5) et les tests ; `_publish_feed(detail, full=None)` signature identique partout ; `_last_feed_pct` initialisé (Step 4), reset (Step 7a), muté (Step 5) ; event toujours `{"type":"CODEFIX", "detail", "full"?}` côté backend et lu via `e.detail`/`e.full` côté front.
- **Note :** le `full` du dépliage front est déjà géré génériquement par `feedFull(e)` (status.js:61-64) pour tout type → rien à ajouter pour CODEFIX.
