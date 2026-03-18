# Emotion Coherence Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Éliminer les états émotionnels incohérents (anger=0.65 + joy=0.33 simultanément) en renforçant les coefficients de suppression et en ajoutant une compétition continue entre émotions incompatibles lors du decay.

**Architecture:** Deux changements dans `emotion.py` : (1) coefficients SUPPRESSION_RULES 0.5→0.8, (2) nouvelle méthode `_apply_competition()` appelée à la fin de `_apply_decay()` qui érode mutuellement les émotions incompatibles proportionnellement au produit de leurs valeurs.

**Tech Stack:** Python, pytest — aucune nouvelle dépendance.

---

## File Map

| Fichier | Action | Description |
|---|---|---|
| `bot/core/emotion.py` | Modifier | SUPPRESSION_RULES coeff 0.5→0.8, COMPETITION_K=0.05, `_apply_competition()`, appel dans `_apply_decay()` |
| `tests/test_emotion_suppression.py` | Modifier | Mettre à jour les valeurs attendues pour le nouveau coeff 0.8 |
| `tests/test_emotion_competition.py` | Créer | Tests pour la compétition continue pendant le decay |

---

### Task 1 : Mettre à jour les tests de suppression pour le nouveau coeff 0.8

Les tests existants utilisent le coeff 0.5. Mettre à jour les expected values au coeff 0.8 **avant** de modifier le code — ces tests passeront en rouge dès que le coeff change.

**Files:**
- Modify: `tests/test_emotion_suppression.py`

- [ ] **Step 1 : Mettre à jour les expected values dans test_emotion_suppression.py**

Remplacer les assertions qui dépendent du coeff 0.5 par les nouvelles valeurs (coeff 0.8) :

```python
# test_joy_suppresses_anger
# anger=0.8, apply_delta("joy", 0.2) → suppression = 0.2*0.8 = 0.16
assert engine.get_state()["anger"] == pytest.approx(0.64, abs=0.001)

# test_joy_suppresses_sadness
# sadness=0.6, apply_delta("joy", 0.4) → suppression = 0.4*0.8 = 0.32
assert engine.get_state()["sadness"] == pytest.approx(0.28, abs=0.001)

# test_anger_suppresses_joy
# joy=0.8, apply_delta("anger", 0.3) → suppression = 0.3*0.8 = 0.24
assert engine.get_state()["joy"] == pytest.approx(0.56, abs=0.001)

# test_sadness_suppresses_joy
# joy=0.8, apply_delta("sadness", 0.3) → suppression = 0.3*0.8 = 0.24
assert engine.get_state()["joy"] == pytest.approx(0.56, abs=0.001)

# test_double_suppression_llm_order (anger=0.5, joy=0.8 initiaux)
# 1. apply_delta("anger", 0.1) → anger=0.6, joy=0.8-0.1*0.8=0.72
# 2. apply_delta("joy", 0.2)  → joy=0.92, anger=0.6-0.2*0.8=0.44
assert engine.get_state()["anger"] == pytest.approx(0.44, abs=0.001)
assert engine.get_state()["joy"]   == pytest.approx(0.92, abs=0.001)

# test_set_emotion_joy_suppresses_anger
# anger=0.8, set_emotion("joy", 0.9) → delta_effectif=0.9, anger -= 0.9*0.8=0.72
assert engine.get_state()["anger"] == pytest.approx(0.08, abs=0.001)

# test_suppression_uses_effective_delta_when_clamped
# anger=0.9 near cap, apply_delta(0.5) → effective=0.1, joy = 0.8 - 0.1*0.8=0.72
assert engine.get_state()["joy"] == pytest.approx(0.72, abs=0.001)
```

`test_suppression_floored_at_zero` reste valide (résultat clampé à 0.0 dans les deux cas).

- [ ] **Step 2 : Vérifier que les tests échouent avec le code actuel**

```bash
cd /opt/stacks/wally-ai
pytest tests/test_emotion_suppression.py -v 2>&1 | head -60
```

Attendu : 6–7 tests FAILED (ceux qui ont des nouvelles expected values). Les tests non modifiés doivent rester verts.

- [ ] **Step 3 : Commit des tests mis à jour**

```bash
git add tests/test_emotion_suppression.py
git commit -m "test(emotion): update suppression expected values for coeff 0.8"
```

---

### Task 2 : Implémenter le nouveau coeff 0.8 dans SUPPRESSION_RULES

**Files:**
- Modify: `bot/core/emotion.py:34-37`

- [ ] **Step 1 : Mettre à jour SUPPRESSION_RULES**

Dans `bot/core/emotion.py`, remplacer :

```python
SUPPRESSION_RULES: list[tuple[str, str, float]] = [
    ("joy", "anger",   0.5),
    ("joy", "sadness", 0.5),
]
```

Par :

```python
# Coefficient de suppression lors d'un apply_delta : la valeur montante érode la valeur adverse.
# Bidirectionnel : si joy monte, anger baisse ; si anger monte, joy baisse.
# ("sadness", "joy") est explicite pour que sadness montante supprime joy directement.
# anger↔boredom intentionnellement absent (coexistence plausible).
SUPPRESSION_RULES: list[tuple[str, str, float]] = [
    ("joy",     "anger",   0.8),
    ("joy",     "sadness", 0.8),
    ("sadness", "joy",     0.8),  # explicite : sadness montante supprime joy
]
```

- [ ] **Step 2 : Vérifier que les tests passent**

```bash
pytest tests/test_emotion_suppression.py -v
```

Attendu : tous verts.

- [ ] **Step 3 : Commit**

```bash
git add bot/core/emotion.py
git commit -m "fix(emotion): renforcer coefficients suppression joy/anger et joy/sadness 0.5→0.8"
```

---

### Task 3 : Écrire les tests de compétition continue

**Files:**
- Create: `tests/test_emotion_competition.py`

- [ ] **Step 1 : Créer le fichier de tests**

```python
# tests/test_emotion_competition.py
"""Tests pour la compétition continue pendant le decay.

_apply_competition() est appelée à la fin de _apply_decay().
Elle érode mutuellement les émotions incompatibles :
    extra = state[src] * state[tgt] * COMPETITION_K
    state[src] -= extra
    state[tgt] -= extra

COMPETITION_K = 0.05. Une seule itération de _apply_decay simule 1 tick (60s).
"""
import time
import pytest
from unittest.mock import MagicMock, patch
from bot.core.emotion import EmotionEngine, COMPETITION_K


def make_config(decay_lambda=0.0):
    """decay_lambda=0.0 neutralise le decay exponentiel pour isoler la compétition."""
    config = MagicMock()
    config.emotions = {
        e: MagicMock(decay_lambda=decay_lambda)
        for e in ["anger", "joy", "sadness", "curiosity", "boredom"]
    }
    return config


def test_competition_reduces_anger_when_joy_high():
    """anger=0.65, joy=0.33 — après 1 tick de decay, les deux baissent."""
    engine = EmotionEngine(make_config())
    engine._state["anger"] = 0.65
    engine._state["joy"] = 0.33

    # Figer _last_decay pour que _apply_decay fasse exactement 1 tick simulé
    engine._last_decay = time.time() - 60
    engine._apply_decay()

    assert engine._state["anger"] < 0.65, "anger doit baisser"
    assert engine._state["joy"] < 0.33,   "joy doit baisser"


def test_competition_symmetric():
    """La compétition est symétrique : même réduction pour src et tgt."""
    engine = EmotionEngine(make_config())
    engine._state["anger"] = 0.5
    engine._state["joy"] = 0.5

    engine._last_decay = time.time() - 60
    engine._apply_decay()

    # extra = 0.5 * 0.5 * 0.05 = 0.0125
    expected = 0.5 - (0.5 * 0.5 * COMPETITION_K)
    assert engine._state["anger"] == pytest.approx(expected, abs=0.001)
    assert engine._state["joy"]   == pytest.approx(expected, abs=0.001)


def test_competition_converges_in_10_minutes():
    """Scénario réel : anger=0.65, joy=0.33. Après 10 ticks (10min), incohérence résolue."""
    engine = EmotionEngine(make_config())
    engine._state["anger"] = 0.65
    engine._state["joy"] = 0.33

    for _ in range(10):
        engine._last_decay = time.time() - 60
        engine._apply_decay()

    # L'une ou l'autre (ou les deux) doit avoir baissé significativement
    anger = engine._state["anger"]
    joy   = engine._state["joy"]
    assert anger < 0.60 or joy < 0.25, (
        f"Après 10 ticks : anger={anger:.3f}, joy={joy:.3f} — toujours incohérent"
    )


def test_competition_no_effect_when_one_is_zero():
    """Si l'une des émotions est à 0, pas de compétition (produit = 0)."""
    engine = EmotionEngine(make_config())
    engine._state["anger"] = 0.8
    engine._state["joy"] = 0.0

    engine._last_decay = time.time() - 60
    engine._apply_decay()

    assert engine._state["anger"] == pytest.approx(0.8, abs=0.001)


def test_competition_does_not_go_below_zero():
    """Résultat clampé à 0.0 même avec des valeurs très hautes."""
    engine = EmotionEngine(make_config())
    engine._state["anger"] = 1.0
    engine._state["joy"] = 1.0

    for _ in range(1000):
        engine._last_decay = time.time() - 60
        engine._apply_decay()

    assert engine._state["anger"] >= 0.0
    assert engine._state["joy"]   >= 0.0


def test_sadness_joy_competition():
    """sadness et joy sont également en compétition."""
    engine = EmotionEngine(make_config())
    engine._state["sadness"] = 0.6
    engine._state["joy"] = 0.6

    engine._last_decay = time.time() - 60
    engine._apply_decay()

    assert engine._state["sadness"] < 0.6
    assert engine._state["joy"]     < 0.6


def test_curiosity_joy_no_competition():
    """curiosity et joy ne sont PAS en compétition."""
    engine = EmotionEngine(make_config())
    engine._state["curiosity"] = 0.8
    engine._state["joy"] = 0.8

    engine._last_decay = time.time() - 60
    engine._apply_decay()

    assert engine._state["curiosity"] == pytest.approx(0.8, abs=0.001)
    assert engine._state["joy"]       == pytest.approx(0.8, abs=0.001)
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```bash
pytest tests/test_emotion_competition.py -v 2>&1 | head -40
```

Attendu : plusieurs FAILED (COMPETITION_K n'existe pas encore, `_apply_competition` n'existe pas).

- [ ] **Step 3 : Commit des tests**

```bash
git add tests/test_emotion_competition.py
git commit -m "test(emotion): tests compétition continue pendant decay"
```

---

### Task 4 : Implémenter `_apply_competition()` et l'appeler dans `_apply_decay()`

**Files:**
- Modify: `bot/core/emotion.py`

- [ ] **Step 1 : Ajouter COMPETITION_K et `_apply_competition()`**

Ajouter après `SUPPRESSION_RULES` dans `bot/core/emotion.py` :

```python
# Coefficient de compétition continue pendant le decay (par tick de 60s).
# extra = state[src] * state[tgt] * COMPETITION_K est soustrait des deux émotions.
# Avec K=0.05 : anger=0.65 + joy=0.33 → extra≈0.011/tick → convergence en ~10min.
COMPETITION_K: float = 0.05
```

Ajouter la méthode dans `EmotionEngine`, après `_apply_suppression` :

```python
def _apply_competition(self) -> None:
    """Érode mutuellement les émotions incompatibles (appelée après chaque decay tick).

    Pour chaque paire (src, tgt) dans SUPPRESSION_RULES :
        extra = state[src] * state[tgt] * COMPETITION_K
    Les deux valeurs baissent de `extra`, clampées à 0.0.
    """
    for src, tgt, _ in SUPPRESSION_RULES:
        extra = self._state[src] * self._state[tgt] * COMPETITION_K
        if extra <= 0:
            continue
        self._state[src] = max(0.0, self._state[src] - extra)
        self._state[tgt] = max(0.0, self._state[tgt] - extra)
```

- [ ] **Step 2 : Appeler `_apply_competition()` à la fin de `_apply_decay()`**

Dans `_apply_decay()`, ajouter l'appel après la boucle de decay exponentiel :

```python
def _apply_decay(self) -> None:
    now = time.time()
    delta_t = now - self._last_decay
    if delta_t <= 0:
        return
    for emotion in EMOTIONS:
        cfg = self._config.emotions.get(emotion)
        if not cfg or self._state[emotion] <= 0:
            continue
        lam = cfg.decay_lambda
        decayed = self._state[emotion] * math.exp(-lam * (delta_t / 60.0))
        self._state[emotion] = 0.0 if decayed < DECAY_FLOOR else decayed
    self._last_decay = now
    self._apply_competition()  # ← ajout
```

- [ ] **Step 3 : Vérifier que tous les tests passent**

```bash
pytest tests/test_emotion_competition.py tests/test_emotion_suppression.py tests/test_emotion.py -v
```

Attendu : tous verts.

- [ ] **Step 4 : Lancer la suite de tests complète**

```bash
pytest --tb=short -q
```

Attendu : 0 erreurs.

- [ ] **Step 5 : Commit**

```bash
git add bot/core/emotion.py
git commit -m "fix(emotion): compétition continue pendant decay — résout incohérence anger+joy"
```
