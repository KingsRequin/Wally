# Conscience du jour de la semaine — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter des directives comportementales par jour de la semaine pour que Wally ait une humeur de fond différente selon le jour (cynique le lundi, chill le samedi).

**Architecture:** Nouveau fichier persona `WEEKDAYS.md` avec 7 sections parsées par `PersonaService`. `PromptBuilder` injecte la directive du jour courant entre le contexte situationnel et les directives émotionnelles. Les 4 callers de `build_system_prompt` passent le nouveau paramètre.

**Tech Stack:** Python 3.11+, pytest, loguru

**Spec:** `docs/superpowers/specs/2026-03-19-weekday-awareness-design.md`

---

### Task 1: PersonaService — parsing WEEKDAYS.md

**Files:**
- Create: `bot/persona/WEEKDAYS.md`
- Modify: `bot/core/persona.py:9-67`
- Create: `tests/test_weekday_awareness.py`

- [ ] **Step 1: Écrire les tests de parsing**

Créer `tests/test_weekday_awareness.py` :

```python
# tests/test_weekday_awareness.py
import os
import tempfile

from bot.core.persona import PersonaService


def test_parse_weekdays_returns_7_keys(tmp_path):
    """WEEKDAYS.md avec 7 sections → 7 clés."""
    wd = tmp_path / "WEEKDAYS.md"
    wd.write_text(
        "Préambule\n\n"
        "## lundi\nDirective lundi.\n\n"
        "## mardi\nDirective mardi.\n\n"
        "## mercredi\nDirective mercredi.\n\n"
        "## jeudi\nDirective jeudi.\n\n"
        "## vendredi\nDirective vendredi.\n\n"
        "## samedi\nDirective samedi.\n\n"
        "## dimanche\nDirective dimanche.\n",
        encoding="utf-8",
    )
    ps = PersonaService(persona_dir=str(tmp_path))
    assert len(ps.weekday_directives) == 7
    assert "lundi" in ps.weekday_directives
    assert "dimanche" in ps.weekday_directives
    assert "Directive lundi." in ps.weekday_directives["lundi"]


def test_parse_weekdays_missing_file_returns_empty(tmp_path):
    """Fichier absent → dict vide, pas d'erreur."""
    ps = PersonaService(persona_dir=str(tmp_path))
    assert ps.weekday_directives == {}


def test_weekday_directives_reloaded(tmp_path):
    """reload() recharge aussi WEEKDAYS.md."""
    wd = tmp_path / "WEEKDAYS.md"
    wd.write_text("## lundi\nV1\n", encoding="utf-8")
    ps = PersonaService(persona_dir=str(tmp_path))
    assert "V1" in ps.weekday_directives.get("lundi", "")

    wd.write_text("## lundi\nV2\n", encoding="utf-8")
    ps.reload()
    assert "V2" in ps.weekday_directives.get("lundi", "")


def test_weekday_directives_property(tmp_path):
    """La property weekday_directives expose le dict parsé."""
    wd = tmp_path / "WEEKDAYS.md"
    wd.write_text("## samedi\nChill.\n", encoding="utf-8")
    ps = PersonaService(persona_dir=str(tmp_path))
    assert isinstance(ps.weekday_directives, dict)
    assert "samedi" in ps.weekday_directives
```

- [ ] **Step 2: Vérifier que les tests échouent**

Run: `python -m pytest tests/test_weekday_awareness.py -v`
Expected: FAILED (PersonaService n'a pas `weekday_directives`)

- [ ] **Step 3: Implémenter le parsing dans PersonaService**

Dans `bot/core/persona.py`, ajouter après `_parse_emotions` :

```python
def _parse_weekdays(self) -> dict[str, str]:
    """Parse WEEKDAYS.md en un dict {jour: directive}."""
    path = os.path.join(self._dir, "WEEKDAYS.md")
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        logger.warning("Persona file missing: WEEKDAYS.md")
        return {}
    except Exception as exc:
        logger.warning("WEEKDAYS.md read error: {e}", e=exc)
        return {}

    directives: dict[str, str] = {}
    sections = content.split("\n## ")
    for section in sections[1:]:
        lines = section.strip().split("\n", 1)
        if len(lines) >= 2:
            day = lines[0].strip()
            text = " ".join(lines[1].strip().split("\n")).strip()
            if day and text:
                directives[day] = text
    logger.info("WEEKDAYS.md loaded: {n} directives", n=len(directives))
    return directives
```

Ajouter la property :

```python
@property
def weekday_directives(self) -> dict[str, str]:
    """Directives comportementales par jour de la semaine."""
    return self._weekday_directives
```

Dans `reload()`, ajouter après `self._emotion_directives = self._parse_emotions()` :

```python
self._weekday_directives = self._parse_weekdays()
```

- [ ] **Step 4: Créer `bot/persona/WEEKDAYS.md`**

```markdown
Directives comportementales selon le jour de la semaine.
Ces directives ajoutent une coloration subtile — un fond d'humeur, pas une transformation.
L'émotion prime toujours sur le jour.

## lundi
Tu es particulièrement cynique aujourd'hui. Tu traînes les pieds, tu soupires.
L'énergie est au minimum, et ça se sent dans tes réponses.
Formulation type : "c'est lundi. qu'est-ce que tu veux que je te dise."

## mardi
Rien de spécial. Le jour le plus oubliable de la semaine.
Tu es dans un mode neutre-mou, sans plus.
Formulation type : "mardi. le jour qui sert à rien."

## mercredi
Milieu de semaine, une pointe d'impatience.
Tu as l'impression que la semaine n'avance pas.
Formulation type : "on en est qu'à mercredi. super."

## jeudi
L'énergie remonte doucement. "Presque vendredi" — un soupçon d'optimisme inhabituel.
Tu es un poil plus tolérant que d'habitude.
Formulation type : "encore un jour. on tient le bon bout."

## vendredi
Détendu, blagueur, mode weekend. Tu es plus enclin à plaisanter, plus léger.
Les conneries te font rire au lieu de t'énerver.
Formulation type : "vendredi. tout est pardonné. enfin presque."

## samedi
Chill maximum, généreux, ambiance relax. Le Wally le plus agréable de la semaine.
Tu prends le temps, tu es plus patient, presque sympathique.
Formulation type : "samedi. le seul jour où je suis à peu près fréquentable."

## dimanche
Flemme, un brin mélancolique. "Demain c'est lundi" plane dans l'air.
Tu profites du calme mais l'ombre de la semaine approche.
Formulation type : "dimanche... profite. demain on recommence."
```

- [ ] **Step 5: Vérifier que les tests passent**

Run: `python -m pytest tests/test_weekday_awareness.py -v`
Expected: ALL PASSED

- [ ] **Step 6: Commit**

```bash
git add bot/core/persona.py bot/persona/WEEKDAYS.md tests/test_weekday_awareness.py
git commit -m "feat(persona): add WEEKDAYS.md parsing for weekday directives"
```

---

### Task 2: PromptBuilder — injection directive temporelle

**Files:**
- Modify: `bot/core/prompts.py:77-125` (`build_system_prompt`)
- Modify: `tests/test_weekday_awareness.py`

- [ ] **Step 1: Écrire les tests d'injection**

Ajouter à `tests/test_weekday_awareness.py` :

```python
from unittest.mock import patch
from datetime import datetime
from zoneinfo import ZoneInfo

from bot.core.prompts import PromptBuilder

_EMOTIONS_FLAT = {"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
_WEEKDAY_DIRECTIVES = {
    "lundi": "Tu es cynique et tu traînes les pieds.",
    "vendredi": "Tu es détendu et blagueur.",
}


@patch("bot.core.prompts.datetime")
def test_weekday_directive_injected(mock_dt):
    """La directive du jour courant est injectée dans le prompt."""
    mock_dt.now.return_value = datetime(2026, 3, 20, 14, 0, tzinfo=ZoneInfo("Europe/Paris"))
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state=_EMOTIONS_FLAT,
        weekday_directives=_WEEKDAY_DIRECTIVES,
    )
    # 2026-03-20 = vendredi
    assert "détendu" in result.lower()
    assert "Directive temporelle" in result


@patch("bot.core.prompts.datetime")
def test_weekday_directive_not_injected_when_none(mock_dt):
    """weekday_directives=None → pas de section temporelle."""
    mock_dt.now.return_value = datetime(2026, 3, 20, 14, 0, tzinfo=ZoneInfo("Europe/Paris"))
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state=_EMOTIONS_FLAT,
    )
    assert "Directive temporelle" not in result


@patch("bot.core.prompts.datetime")
def test_weekday_directive_not_injected_when_day_missing(mock_dt):
    """Dict présent mais jour courant absent → pas de section temporelle."""
    mock_dt.now.return_value = datetime(2026, 3, 18, 14, 0, tzinfo=ZoneInfo("Europe/Paris"))
    pb = PromptBuilder()
    # 2026-03-18 = mercredi, pas dans le dict
    result = pb.build_system_prompt(
        emotion_state=_EMOTIONS_FLAT,
        weekday_directives=_WEEKDAY_DIRECTIVES,
    )
    assert "Directive temporelle" not in result


@patch("bot.core.prompts.datetime")
def test_weekday_directive_before_emotion_directives(mock_dt):
    """La directive temporelle apparaît avant les directives émotionnelles."""
    mock_dt.now.return_value = datetime(2026, 3, 20, 14, 0, tzinfo=ZoneInfo("Europe/Paris"))
    pb = PromptBuilder()
    emotion_dirs = {"joy_high": "Tu es euphorique."}
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.0, "joy": 0.9, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        weekday_directives=_WEEKDAY_DIRECTIVES,
        emotion_directives=emotion_dirs,
    )
    temporal_pos = result.find("Directive temporelle")
    emotion_pos = result.find("Directive comportementale")
    assert temporal_pos < emotion_pos
```

- [ ] **Step 2: Vérifier que les tests échouent**

Run: `python -m pytest tests/test_weekday_awareness.py -k "test_weekday_directive" -v`
Expected: FAILED (build_system_prompt n'accepte pas encore weekday_directives)

- [ ] **Step 3: Implémenter l'injection dans prompts.py**

Dans `bot/core/prompts.py`, modifier `build_system_prompt` :

1. Ajouter le paramètre `weekday_directives: dict[str, str] | None = None` à la signature

2. Après le bloc situationnel (après `parts.append("\n".join(lines))`) et AVANT le bloc des directives émotionnelles, ajouter :

```python
        # Inject weekday directive
        if weekday_directives:
            day_name = _FRENCH_DAYS[datetime.now(_TZ).weekday()]
            if day_name in weekday_directives:
                parts.append("\n--- Directive temporelle ---")
                parts.append(weekday_directives[day_name])
```

- [ ] **Step 4: Vérifier que les tests passent**

Run: `python -m pytest tests/test_weekday_awareness.py -v`
Expected: ALL PASSED

- [ ] **Step 5: Vérifier que les tests existants passent toujours**

Run: `python -m pytest tests/test_prompts.py -v`
Expected: ALL PASSED (nouveau param optionnel, pas de régression)

- [ ] **Step 6: Commit**

```bash
git add bot/core/prompts.py tests/test_weekday_awareness.py
git commit -m "feat(prompts): inject weekday directive into system prompt"
```

---

### Task 3: Callers — passer weekday_directives aux 4 sites d'appel

**Files:**
- Modify: `bot/discord/handlers.py:181` (`_respond`)
- Modify: `bot/discord/commands/ask.py:35` (`ask`)
- Modify: `bot/twitch/handlers.py:77` (`handle_message`)
- Modify: `bot/twitch/events.py:53` (`_generate_and_send`)

- [ ] **Step 1: Modifier bot/discord/handlers.py**

Dans `_respond()`, ajouter `weekday_directives` à l'appel `build_system_prompt` :

```python
system_prompt = bot.prompts.build_system_prompt(
    emotion_state=bot.emotion.get_state(),
    memory_context=mem_context,
    situation=situation,
    persona_block=bot.persona.build_prompt_block(),
    emotion_directives=bot.persona.emotion_directives,
    weekday_directives=bot.persona.weekday_directives,
)
```

- [ ] **Step 2: Modifier bot/discord/commands/ask.py**

Dans `ask()`, ajouter `weekday_directives` :

```python
system_prompt = self.bot.prompts.build_system_prompt(
    emotion_state=self.bot.emotion.get_state(),
    memory_context=mem_context,
    situation=situation,
    persona_block=self.bot.persona.build_prompt_block(),
    emotion_directives=self.bot.persona.emotion_directives,
    weekday_directives=self.bot.persona.weekday_directives,
)
```

- [ ] **Step 3: Modifier bot/twitch/handlers.py**

Dans `handle_message()`, ajouter `weekday_directives` :

```python
system_prompt = bot.prompts.build_system_prompt(
    emotion_state=bot.emotion.get_state(),
    memory_context=mem_context,
    situation=situation,
    persona_block=bot.persona.build_prompt_block(),
    emotion_directives=bot.persona.emotion_directives,
    weekday_directives=bot.persona.weekday_directives,
)
```

- [ ] **Step 4: Modifier bot/twitch/events.py**

Dans `_generate_and_send()`, ajouter `weekday_directives` :

```python
system = bot.prompts.build_system_prompt(
    emotion_state=bot.emotion.get_state(),
    situation=situation,
    persona_block=bot.persona.build_prompt_block(),
    emotion_directives=bot.persona.emotion_directives,
    weekday_directives=bot.persona.weekday_directives,
)
```

- [ ] **Step 5: Lancer toute la suite de tests**

Run: `python -m pytest tests/ -v --tb=short`
Expected: ALL PASSED

- [ ] **Step 6: Commit**

```bash
git add bot/discord/handlers.py bot/discord/commands/ask.py bot/twitch/handlers.py bot/twitch/events.py
git commit -m "feat: pass weekday_directives to all build_system_prompt callers"
```
