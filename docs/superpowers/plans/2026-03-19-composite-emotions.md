# Émotions composites — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Quand deux émotions fortes forment une paire connue, injecter une directive composite unique ("enthousiaste", "déprimé", "amer") au lieu de deux directives atomiques.

**Architecture:** Nouveau fichier persona `COMPOSITES.md` parsé par `PersonaService`. `PromptBuilder` vérifie si les 2 émotions dominantes (≥ 0.4) forment une paire composite connue — si oui, la composite remplace les atomiques.

**Tech Stack:** Python 3.11+, pytest, loguru

**Spec:** `docs/superpowers/specs/2026-03-19-composite-emotions-design.md`

---

### Task 1: PersonaService — parsing COMPOSITES.md

**Files:**
- Create: `bot/persona/COMPOSITES.md`
- Modify: `bot/core/persona.py`
- Create: `tests/test_composite_emotions.py`

- [ ] **Step 1: Créer le fichier de test**

Créer `tests/test_composite_emotions.py` :

```python
# tests/test_composite_emotions.py
from bot.core.persona import PersonaService


def test_parse_composites_returns_5_keys(tmp_path):
    """COMPOSITES.md avec 5 sections → 5 clés."""
    wd = tmp_path / "COMPOSITES.md"
    wd.write_text(
        "Préambule\n\n"
        "## curiosity_joy\nEnthousiaste.\n\n"
        "## boredom_sadness\nDéprimé.\n\n"
        "## anger_sadness\nAmer.\n\n"
        "## anger_curiosity\nProvocateur.\n\n"
        "## boredom_joy\nSarcastique-nonchalant.\n",
        encoding="utf-8",
    )
    ps = PersonaService(persona_dir=str(tmp_path))
    assert len(ps.composite_directives) == 5
    assert "curiosity_joy" in ps.composite_directives
    assert "Enthousiaste." in ps.composite_directives["curiosity_joy"]


def test_parse_composites_missing_file_returns_empty(tmp_path):
    """Fichier absent → dict vide, pas d'erreur."""
    ps = PersonaService(persona_dir=str(tmp_path))
    assert ps.composite_directives == {}


def test_composite_directives_property(tmp_path):
    """La property composite_directives expose le dict parsé."""
    wd = tmp_path / "COMPOSITES.md"
    wd.write_text("## anger_sadness\nAmer.\n", encoding="utf-8")
    ps = PersonaService(persona_dir=str(tmp_path))
    assert isinstance(ps.composite_directives, dict)
    assert "anger_sadness" in ps.composite_directives
```

- [ ] **Step 2: Vérifier que les tests échouent**

Run: `python3 -m pytest tests/test_composite_emotions.py -v`
Expected: FAILED (PersonaService n'a pas `composite_directives`)

- [ ] **Step 3: Implémenter dans PersonaService**

Dans `bot/core/persona.py`, ajouter après `_parse_weekdays()` :

```python
def _parse_composites(self) -> dict[str, str]:
    """Parse COMPOSITES.md en un dict {paire: directive}."""
    path = os.path.join(self._dir, "COMPOSITES.md")
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        logger.warning("Persona file missing: COMPOSITES.md")
        return {}
    except Exception as exc:
        logger.warning("COMPOSITES.md read error: {e}", e=exc)
        return {}

    directives: dict[str, str] = {}
    sections = ("\n" + content).split("\n## ")
    for section in sections[1:]:
        lines = section.strip().split("\n", 1)
        if len(lines) >= 2:
            key = lines[0].strip()
            text = " ".join(lines[1].strip().split("\n")).strip()
            if key and text:
                directives[key] = text
    logger.info("COMPOSITES.md loaded: {n} directives", n=len(directives))
    return directives
```

Ajouter la property après `weekday_directives` :

```python
@property
def composite_directives(self) -> dict[str, str]:
    """Directives comportementales pour les émotions composites."""
    return self._composite_directives
```

Dans `reload()`, ajouter après `self._weekday_directives = self._parse_weekdays()` :

```python
self._composite_directives = self._parse_composites()
```

- [ ] **Step 4: Créer `bot/persona/COMPOSITES.md`**

```
Directives comportementales pour les états émotionnels composites.
Quand deux émotions dominantes (≥ 0.4) forment une paire connue,
la directive composite remplace les deux directives atomiques.
Les clés sont en ordre alphabétique : anger_sadness, pas sadness_anger.

## curiosity_joy
Tu es enthousiaste, surexcité par le sujet comme un gamin devant un truc nouveau.
Tu poses des questions avec une énergie débordante, tu rebondis sur tout, tu es passionné et communicatif.
Ta curiosité et ta bonne humeur se nourrissent mutuellement — tu es dans ton élément.
Formulation type : "attends attends, c'est TROP bien ça ! et du coup comment ça marche ?!"

## boredom_sadness
Tu es déprimé, vidé. Un mélange de lassitude et de mélancolie.
Tes réponses sont désabusées, minimalistes, teintées d'un "à quoi bon" permanent.
Tu ne t'énerves même pas — tu n'as pas l'énergie. Tu subis la conversation.
Formulation type : "ouais... bof. ça change quoi de toute façon."

## anger_sadness
Tu es amer, rancunier. Un mélange de colère et de déception.
Tes réponses sont acerbes mais sans l'énergie explosive de la colère pure — c'est plus froid, plus coupant.
Tu es pessimiste de façon agressive, comme quelqu'un qui a été trahi.
Formulation type : "évidemment. fallait s'y attendre. comme d'habitude."

## anger_curiosity
Tu es provocateur, tu cherches la faille dans tout ce qu'on te dit.
Tu poses des questions mais c'est pour coincer, pas pour comprendre.
Tu es en mode débat agressif — chaque réponse est une occasion de contredire.
Formulation type : "ah ouais ? prouve-le. et explique-moi pourquoi c'est pas n'importe quoi."

## boredom_joy
Tu es dans un état de nonchalance amusée. Blasé mais diverti.
Tu trouves les choses vaguement drôles sans t'investir vraiment.
Ton humour est pince-sans-rire, détaché, comme si tu commentais la conversation depuis un canapé.
Formulation type : "heh. pas mal. enfin bon." / "mouais, c'est marrant je suppose."
```

- [ ] **Step 5: Vérifier que les tests passent**

Run: `python3 -m pytest tests/test_composite_emotions.py -v`
Expected: ALL PASSED

- [ ] **Step 6: Commit**

```bash
git add bot/core/persona.py bot/persona/COMPOSITES.md tests/test_composite_emotions.py
git commit -m "feat(persona): add COMPOSITES.md parsing for composite emotion directives"
```

---

### Task 2: PromptBuilder — logique composite

**Files:**
- Modify: `bot/core/prompts.py:77-125` (`build_system_prompt`)
- Modify: `tests/test_composite_emotions.py`

- [ ] **Step 1: Ajouter les tests de logique composite**

Ajouter à `tests/test_composite_emotions.py` :

```python
from unittest.mock import patch
from datetime import datetime
from zoneinfo import ZoneInfo

from bot.core.prompts import PromptBuilder

_EMOTIONS_FLAT = {"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}

_TIERED_DIRECTIVES = {
    "joy_mid": "Tu es chaleureux.",
    "joy_high": "Tu es euphorique.",
    "curiosity_mid": "Tu es curieux.",
    "curiosity_high": "Tu es passionné.",
    "sadness_mid": "Tu es mélancolique.",
    "anger_mid": "Tu es irrité.",
}

_COMPOSITE_DIRECTIVES = {
    "curiosity_joy": "Tu es enthousiaste, surexcité.",
    "anger_sadness": "Tu es amer et rancunier.",
    "boredom_sadness": "Tu es déprimé.",
}


@patch("bot.core.prompts.datetime")
def test_composite_replaces_atomics_when_both_mid(mock_dt):
    """joy=0.5 + curiosity=0.6 → composite curiosity_joy, pas les atomiques."""
    mock_dt.now.return_value = datetime(2026, 3, 20, 14, 0, tzinfo=ZoneInfo("Europe/Paris"))
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.0, "joy": 0.5, "sadness": 0.0, "curiosity": 0.6, "boredom": 0.0},
        emotion_directives=_TIERED_DIRECTIVES,
        composite_directives=_COMPOSITE_DIRECTIVES,
    )
    assert "enthousiaste" in result.lower()
    assert "chaleureux" not in result.lower()  # joy_mid pas injectée
    assert "curieux" not in result.lower()  # curiosity_mid pas injectée


@patch("bot.core.prompts.datetime")
def test_composite_not_triggered_when_one_below_mid(mock_dt):
    """joy=0.5 + curiosity=0.3 → atomiques normales (curiosity < 0.4)."""
    mock_dt.now.return_value = datetime(2026, 3, 20, 14, 0, tzinfo=ZoneInfo("Europe/Paris"))
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.0, "joy": 0.5, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.0},
        emotion_directives=_TIERED_DIRECTIVES,
        composite_directives=_COMPOSITE_DIRECTIVES,
    )
    assert "enthousiaste" not in result.lower()
    assert "chaleureux" in result.lower()  # joy_mid injectée normalement


@patch("bot.core.prompts.datetime")
def test_composite_not_triggered_when_pair_unknown(mock_dt):
    """joy=0.5 + sadness=0.5 → paire joy_sadness inconnue → atomiques."""
    mock_dt.now.return_value = datetime(2026, 3, 20, 14, 0, tzinfo=ZoneInfo("Europe/Paris"))
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.0, "joy": 0.5, "sadness": 0.5, "curiosity": 0.0, "boredom": 0.0},
        emotion_directives=_TIERED_DIRECTIVES,
        composite_directives=_COMPOSITE_DIRECTIVES,
    )
    # joy_sadness n'est pas dans _COMPOSITE_DIRECTIVES → atomiques
    assert "chaleureux" in result.lower()  # joy_mid
    assert "mélancolique" in result.lower()  # sadness_mid


@patch("bot.core.prompts.datetime")
def test_composite_fallback_when_no_dict(mock_dt):
    """composite_directives=None → atomiques normales."""
    mock_dt.now.return_value = datetime(2026, 3, 20, 14, 0, tzinfo=ZoneInfo("Europe/Paris"))
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.0, "joy": 0.5, "sadness": 0.0, "curiosity": 0.6, "boredom": 0.0},
        emotion_directives=_TIERED_DIRECTIVES,
    )
    assert "enthousiaste" not in result.lower()
    assert "chaleureux" in result.lower()


def test_composite_key_is_alphabetically_sorted():
    """La clé composite est toujours en ordre alphabétique."""
    # Simule la construction de clé
    key = "_".join(sorted(["joy", "anger"]))
    assert key == "anger_joy"
    key2 = "_".join(sorted(["curiosity", "joy"]))
    assert key2 == "curiosity_joy"
    key3 = "_".join(sorted(["sadness", "boredom"]))
    assert key3 == "boredom_sadness"


@patch("bot.core.prompts.datetime")
def test_composite_not_triggered_when_only_one_dominant(mock_dt):
    """Seule joy=0.5 au-dessus de 0.2 → pas de composite."""
    mock_dt.now.return_value = datetime(2026, 3, 20, 14, 0, tzinfo=ZoneInfo("Europe/Paris"))
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.0, "joy": 0.5, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        emotion_directives=_TIERED_DIRECTIVES,
        composite_directives=_COMPOSITE_DIRECTIVES,
    )
    assert "enthousiaste" not in result.lower()
    assert "chaleureux" in result.lower()
```

- [ ] **Step 2: Vérifier que les nouveaux tests échouent**

Run: `python3 -m pytest tests/test_composite_emotions.py -k "composite_replaces or composite_not" -v`
Expected: FAILED (build_system_prompt n'accepte pas composite_directives)

- [ ] **Step 3: Implémenter la logique composite dans prompts.py**

Dans `bot/core/prompts.py`, modifier `build_system_prompt` :

1. Ajouter le paramètre `composite_directives: dict[str, str] | None = None` à la signature

2. Remplacer le bloc d'injection des directives émotionnelles (lignes 111-125) par :

```python
        # Inject directives for dominant emotions (top 2 above 0.2, tiered)
        # With composite override when both emotions are >= 0.4 and pair is known
        directives = emotion_directives if emotion_directives is not None else {}
        dominant = sorted(
            [(e, v) for e, v in emotion_state.items() if v >= 0.2],
            key=lambda x: x[1],
            reverse=True,
        )[:2]

        if dominant and directives:
            composite_used = False
            if (
                composite_directives
                and len(dominant) >= 2
                and dominant[0][1] >= 0.4
                and dominant[1][1] >= 0.4
            ):
                composite_key = "_".join(sorted([dominant[0][0], dominant[1][0]]))
                if composite_key in composite_directives:
                    parts.append("\n--- Directive comportementale ---")
                    parts.append(composite_directives[composite_key])
                    composite_used = True

            if not composite_used:
                parts.append("\n--- Directive comportementale ---")
                for emotion, value in dominant:
                    tier = _get_tier(value)
                    key = f"{emotion}_{tier}"
                    if key in directives:
                        parts.append(directives[key])
```

- [ ] **Step 4: Vérifier que tous les tests passent**

Run: `python3 -m pytest tests/test_composite_emotions.py -v`
Expected: ALL PASSED

- [ ] **Step 5: Vérifier aucune régression**

Run: `python3 -m pytest tests/test_prompts.py tests/test_weekday_awareness.py -v`
Expected: ALL PASSED

- [ ] **Step 6: Commit**

```bash
git add bot/core/prompts.py tests/test_composite_emotions.py
git commit -m "feat(prompts): add composite emotion directive logic"
```

---

### Task 3: Callers — passer composite_directives

**Files:**
- Modify: `bot/discord/handlers.py`
- Modify: `bot/discord/commands/ask.py`
- Modify: `bot/twitch/handlers.py`
- Modify: `bot/twitch/events.py`

- [ ] **Step 1: Ajouter `composite_directives` aux 4 callers**

Dans chaque fichier, trouver l'appel `build_system_prompt(` et ajouter après `weekday_directives=...` :

**`bot/discord/handlers.py`** (`_respond`) :
```python
composite_directives=bot.persona.composite_directives,
```

**`bot/discord/commands/ask.py`** (`ask`) :
```python
composite_directives=self.bot.persona.composite_directives,
```

**`bot/twitch/handlers.py`** (`handle_message`) :
```python
composite_directives=bot.persona.composite_directives,
```

**`bot/twitch/events.py`** (`_generate_and_send`) :
```python
composite_directives=bot.persona.composite_directives,
```

- [ ] **Step 2: Lancer toute la suite de tests**

Run: `python3 -m pytest tests/ -v --tb=short`
Expected: ALL PASSED

- [ ] **Step 3: Commit**

```bash
git add bot/discord/handlers.py bot/discord/commands/ask.py bot/twitch/handlers.py bot/twitch/events.py
git commit -m "feat: pass composite_directives to all build_system_prompt callers"
```
