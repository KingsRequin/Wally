# Emotion Coherence Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Empêcher que Wally soit simultanément heureux et en colère en introduisant une suppression partielle des émotions incompatibles dans `apply_delta()` et `set_emotion()`.

**Architecture:** Constante déclarative `SUPPRESSION_RULES` + helper privé `_apply_suppression()` appelé par les deux méthodes d'écriture d'état. Bidirectionnel (joy↔anger, joy↔sadness), coefficient 0.5, delta positifs uniquement.

**Tech Stack:** Python 3.11+, pytest, unittest.mock

**Spec:** `docs/superpowers/specs/2026-03-16-emotion-coherence-design.md`

---

## Chunk 1: Tests et implémentation

### Task 1: Écrire les tests de suppression (TDD — red phase)

**Files:**
- Create: `tests/test_emotion_suppression.py`

- [ ] **Step 1: Créer le fichier de tests**

```python
# tests/test_emotion_suppression.py
import pytest
from unittest.mock import MagicMock
from bot.core.emotion import EmotionEngine


def make_config():
    config = MagicMock()
    config.emotions = {
        e: MagicMock(decay_lambda=0.1)
        for e in ["anger", "joy", "sadness", "curiosity", "boredom"]
    }
    return config


# ── apply_delta : suppressions ────────────────────────────────────────────────

def test_joy_suppresses_anger():
    engine = EmotionEngine(make_config())
    engine._state["anger"] = 0.8
    engine.apply_delta("joy", 0.2)
    assert engine.get_state()["joy"] == pytest.approx(0.2, abs=0.001)
    assert engine.get_state()["anger"] == pytest.approx(0.7, abs=0.001)


def test_joy_suppresses_sadness():
    engine = EmotionEngine(make_config())
    engine._state["sadness"] = 0.6
    engine.apply_delta("joy", 0.4)
    assert engine.get_state()["joy"] == pytest.approx(0.4, abs=0.001)
    assert engine.get_state()["sadness"] == pytest.approx(0.4, abs=0.001)


def test_anger_suppresses_joy():
    engine = EmotionEngine(make_config())
    engine._state["joy"] = 0.8
    engine.apply_delta("anger", 0.3)
    assert engine.get_state()["anger"] == pytest.approx(0.3, abs=0.001)
    assert engine.get_state()["joy"] == pytest.approx(0.65, abs=0.001)


def test_sadness_suppresses_joy():
    engine = EmotionEngine(make_config())
    engine._state["joy"] = 0.8
    engine.apply_delta("sadness", 0.3)
    assert engine.get_state()["sadness"] == pytest.approx(0.3, abs=0.001)
    assert engine.get_state()["joy"] == pytest.approx(0.65, abs=0.001)


def test_anger_does_not_suppress_sadness():
    engine = EmotionEngine(make_config())
    engine._state["sadness"] = 0.5
    engine.apply_delta("anger", 0.3)
    assert engine.get_state()["sadness"] == pytest.approx(0.5, abs=0.001)


def test_curiosity_does_not_suppress_joy():
    engine = EmotionEngine(make_config())
    engine._state["joy"] = 0.8
    engine.apply_delta("curiosity", 0.3)
    assert engine.get_state()["joy"] == pytest.approx(0.8, abs=0.001)


def test_boredom_does_not_suppress_joy():
    engine = EmotionEngine(make_config())
    engine._state["joy"] = 0.8
    engine.apply_delta("boredom", 0.3)
    assert engine.get_state()["joy"] == pytest.approx(0.8, abs=0.001)


# ── apply_delta : edge cases ──────────────────────────────────────────────────

def test_negative_delta_no_suppression():
    """Un delta négatif (émotion qui baisse) ne recharge pas son opposée."""
    engine = EmotionEngine(make_config())
    engine._state["anger"] = 0.5
    engine.apply_delta("joy", -0.1)
    assert engine.get_state()["anger"] == pytest.approx(0.5, abs=0.001)


def test_zero_delta_no_suppression():
    engine = EmotionEngine(make_config())
    engine._state["anger"] = 0.5
    engine.apply_delta("joy", 0.0)
    assert engine.get_state()["anger"] == pytest.approx(0.5, abs=0.001)


def test_suppression_floored_at_zero():
    """La suppression ne peut pas rendre une émotion négative."""
    engine = EmotionEngine(make_config())
    engine._state["anger"] = 0.05
    engine.apply_delta("joy", 0.8)  # suppression = 0.8*0.5 = 0.4 > 0.05
    assert engine.get_state()["anger"] == pytest.approx(0.0, abs=0.001)


def test_double_suppression_llm_order():
    """Simule l'ordre d'appel LLM : anger d'abord, puis joy.
    anger=0.5, joy=0.8 initiaux.
    1. apply_delta("anger", 0.1) → anger=0.6, joy=0.8-0.05=0.75
    2. apply_delta("joy", 0.2)  → joy=0.95, anger=0.6-0.1=0.5
    """
    engine = EmotionEngine(make_config())
    engine._state["anger"] = 0.5
    engine._state["joy"] = 0.8
    engine.apply_delta("anger", 0.1)
    engine.apply_delta("joy", 0.2)
    assert engine.get_state()["anger"] == pytest.approx(0.5, abs=0.001)
    assert engine.get_state()["joy"] == pytest.approx(0.95, abs=0.001)


# ── set_emotion : suppressions ────────────────────────────────────────────────

def test_set_emotion_joy_suppresses_anger():
    """set_emotion("joy", 0.9) depuis 0 : delta_effectif=0.9, anger -= 0.9*0.5=0.45."""
    engine = EmotionEngine(make_config())
    engine._state["anger"] = 0.8
    engine.set_emotion("joy", 0.9)
    assert engine.get_state()["joy"] == pytest.approx(0.9, abs=0.001)
    assert engine.get_state()["anger"] == pytest.approx(0.35, abs=0.001)


def test_set_emotion_negative_effective_delta_no_suppression():
    """Si set_emotion baisse la valeur (delta_effectif < 0), pas de suppression."""
    engine = EmotionEngine(make_config())
    engine._state["joy"] = 0.5
    engine._state["anger"] = 0.8
    engine.set_emotion("joy", 0.1)  # delta_effectif = 0.1 - 0.5 = -0.4
    assert engine.get_state()["anger"] == pytest.approx(0.8, abs=0.001)
```

- [ ] **Step 2: Vérifier que les tests échouent (red)**

```bash
cd /opt/stacks/wally-ai
pytest tests/test_emotion_suppression.py -v
```

Résultat attendu : la plupart des tests ÉCHOUENT. Les tests de delta négatif / zéro peuvent passer car la logique actuelle ne supprime rien du tout.

---

### Task 2: Implémenter la suppression dans emotion.py

**Files:**
- Modify: `bot/core/emotion.py`

- [ ] **Step 3: Ajouter la constante `SUPPRESSION_RULES` après `MAX_DELTA_PER_MESSAGE` (ligne 29)**

Trouver :
```python
# Max delta applied per message per emotion
MAX_DELTA_PER_MESSAGE = 0.3
```

Remplacer par :
```python
# Max delta applied per message per emotion
MAX_DELTA_PER_MESSAGE = 0.3

# Paires d'émotions incompatibles : (source, cible, coefficient de suppression)
# Bidirectionnel et symétrique : même coefficient dans les deux sens.
# Quand source monte, cible descend de delta×coeff, et vice-versa.
SUPPRESSION_RULES: list[tuple[str, str, float]] = [
    ("joy", "anger",   0.5),
    ("joy", "sadness", 0.5),
]
```

- [ ] **Step 4: Ajouter le helper `_apply_suppression` dans la classe `EmotionEngine`**

Trouver la méthode `apply_delta` :
```python
    def apply_delta(self, emotion: str, delta: float) -> None:
```

Insérer juste AVANT cette méthode :
```python
    def _apply_suppression(self, emotion: str, delta: float) -> None:
        """Supprime partiellement les émotions incompatibles si delta > 0."""
        if delta <= 0:
            return
        for src, tgt, coeff in SUPPRESSION_RULES:
            if emotion == src:
                self._state[tgt] = max(0.0, self._state[tgt] - delta * coeff)
            elif emotion == tgt:
                self._state[src] = max(0.0, self._state[src] - delta * coeff)

```

- [ ] **Step 5: Modifier `apply_delta` pour appeler `_apply_suppression`**

Trouver :
```python
    def apply_delta(self, emotion: str, delta: float) -> None:
        if emotion not in self._state:
            return
        self._state[emotion] = max(0.0, min(1.0, self._state[emotion] + delta))
        self._dirty = True
        self._schedule_save()
```

Remplacer par :
```python
    def apply_delta(self, emotion: str, delta: float) -> None:
        if emotion not in self._state:
            return
        self._state[emotion] = max(0.0, min(1.0, self._state[emotion] + delta))
        self._apply_suppression(emotion, delta)
        self._dirty = True
        self._schedule_save()
```

- [ ] **Step 6: Modifier `set_emotion` pour appeler `_apply_suppression`**

Trouver :
```python
    def set_emotion(self, emotion: str, value: float) -> None:
        if emotion in self._state:
            self._state[emotion] = max(0.0, min(1.0, value))
            self._dirty = True
            self._schedule_save()
```

Remplacer par :
```python
    def set_emotion(self, emotion: str, value: float) -> None:
        if emotion in self._state:
            effective_delta = value - self._state[emotion]
            self._state[emotion] = max(0.0, min(1.0, value))
            self._apply_suppression(emotion, effective_delta)
            self._dirty = True
            self._schedule_save()
```

---

### Task 3: Vérification et commit

**Files:** aucun nouveau fichier

- [ ] **Step 7: Vérifier que les nouveaux tests passent**

```bash
cd /opt/stacks/wally-ai
pytest tests/test_emotion_suppression.py -v
```

Résultat attendu : **tous les tests PASSENT**.

- [ ] **Step 8: Vérifier que les tests existants passent toujours**

```bash
cd /opt/stacks/wally-ai
pytest tests/test_emotion.py -v
```

Résultat attendu : **tous les tests PASSENT** (les tests existants partent tous d'un état à zéro, donc la suppression n'a pas d'effet sur les tests d'accumulation simple).

- [ ] **Step 9: Lancer la suite complète**

```bash
cd /opt/stacks/wally-ai
pytest --tb=short -q
```

Résultat attendu : **tous les tests passent** (110+ tests).

- [ ] **Step 10: Commit**

```bash
cd /opt/stacks/wally-ai
git add bot/core/emotion.py tests/test_emotion_suppression.py
git commit -m "feat: add emotion suppression rules (joy↔anger, joy↔sadness)"
```
