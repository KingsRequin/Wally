# Self-model dérivé — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Empêcher le self-model de Wally d'affirmer une capacité technique contraire à l'état réel (cas réel : « vocal désactivé » alors qu'il fonctionne), en dérivant la capacité vocal de `config.voice.enabled` au lieu de l'écrire en dur dans `CAPABILITIES.md`.

**Architecture:** Un module pur `self_model.py` expose `build_self_model(static_text, config)` qui appende au narratif statique une section dérivée d'un registre déclaratif de capacités à bascule. Les deux consommateurs du self-model (cognition idle via `bot.py`, réactif via `PersonaService`) appliquent cette même fonction. La ligne vocal fossilisée est retirée de `CAPABILITIES.md`.

**Tech Stack:** Python 3, pytest, dataclasses de config (`bot/config.py`).

## Global Constraints

- Logging : `loguru` uniquement, jamais `print()` ni `import logging`.
- `build_self_model` doit être une **fonction pure** : aucune I/O, aucune dépendance aux objets services montés (sensibles à l'ordre de boot). Elle lit uniquement la `config`.
- Rétrocompat : `PersonaService(persona_dir=...)` sans `config` doit continuer de fonctionner (fallback au texte statique). Les tests existants de `tests/test_persona.py` doivent rester verts.
- Le narratif stable de `CAPABILITIES.md` (« pas de corps », garde anti-hallucination, etc.) est conservé tel quel. On ne retire QUE la ligne vocal.
- Spec de référence : `docs/superpowers/specs/2026-06-28-self-model-derive-design.md`.

---

### Task 1: Module pur `self_model.py` + registre vocal

**Files:**
- Create: `bot/intelligence/self_model.py`
- Test: `tests/intelligence/test_self_model.py`

**Interfaces:**
- Consumes: rien (brique de base).
- Produces: `build_self_model(static_text: str, config) -> str` — appende au texte statique une section `## Mes capacités techniques actuelles` dont chaque ligne reflète l'état réel des capacités à bascule (vocal via `config.voice.enabled`). Tolère un `config` malformé (capacité réputée inactive plutôt que crash).

- [ ] **Step 1: Write the failing test**

Create `tests/intelligence/test_self_model.py`:

```python
from types import SimpleNamespace

from bot.intelligence.self_model import build_self_model


def _cfg(voice_enabled: bool):
    return SimpleNamespace(voice=SimpleNamespace(enabled=voice_enabled))


def test_voice_enabled_states_capability_active():
    out = build_self_model("Je suis Wally.", _cfg(True))
    assert "parler en vocal" in out
    # Aucune trace de l'ancienne affirmation fossilisée :
    assert "désactivé" not in out
    assert "pas branché" not in out
    assert "pas activé" not in out


def test_voice_disabled_states_capability_inactive():
    out = build_self_model("Je suis Wally.", _cfg(False))
    assert "n'est pas activé" in out
    assert "parler en vocal" not in out


def test_static_text_is_preserved():
    static = "Je n'ai pas de corps. Je ne prétends jamais me souvenir d'un moment vécu."
    out = build_self_model(static, _cfg(True))
    assert "Je n'ai pas de corps." in out
    assert "Je ne prétends jamais me souvenir d'un moment vécu." in out


def test_derived_section_has_title():
    out = build_self_model("X", _cfg(True))
    assert "## Mes capacités techniques actuelles" in out


def test_malformed_config_falls_back_to_inactive():
    out = build_self_model("X", SimpleNamespace())  # pas d'attribut voice
    assert "n'est pas activé" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/intelligence/test_self_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.intelligence.self_model'`

- [ ] **Step 3: Write minimal implementation**

Create `bot/intelligence/self_model.py`:

```python
from __future__ import annotations

# Registre déclaratif des capacités « à bascule » : (condition, phrase_active,
# phrase_inactive). Chaque condition lit l'état RÉEL depuis la config (source de
# vérité déclarative), jamais une valeur écrite à la main dans CAPABILITIES.md —
# c'est ce qui évite la fossilisation du self-model. Ajouter une capacité future =
# une entrée ici.
_TOGGLE_CAPABILITIES = [
    (
        lambda c: bool(getattr(getattr(c, "voice", None), "enabled", False)),
        "Je peux entendre et parler en vocal dans les salons audio.",
        "Le vocal existe dans mon code mais il n'est pas activé pour l'instant.",
    ),
]

_SECTION_TITLE = "## Mes capacités techniques actuelles"


def build_self_model(static_text: str, config) -> str:
    """Assemble le self-model : narratif statique + capacités dérivées de l'état réel.

    `static_text` = CAPABILITIES.md nettoyé (vérités de personnage stables).
    `config` = la config runtime ; chaque capacité à bascule est évaluée contre elle.

    Fonction pure : aucune I/O, aucune dépendance aux objets services montés
    (donc insensible à l'ordre de montage au boot). Un `config` malformé fait
    juste tomber la capacité en « inactive », jamais une exception.
    """
    lines = []
    for condition, on_text, off_text in _TOGGLE_CAPABILITIES:
        try:
            active = bool(condition(config))
        except Exception:
            active = False
        lines.append(f"- {on_text if active else off_text}")
    derived = _SECTION_TITLE + "\n" + "\n".join(lines)

    static = (static_text or "").rstrip()
    return f"{static}\n\n{derived}\n" if static else f"{derived}\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/intelligence/test_self_model.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add bot/intelligence/self_model.py tests/intelligence/test_self_model.py
git commit -m "feat(self-model): module pur build_self_model + registre vocal dérivé"
```

---

### Task 2: Brancher le réactif (PersonaService) + nettoyer CAPABILITIES.md

**Files:**
- Modify: `bot/intelligence/persona.py` (`_FILES`, `__init__`, `reload`, `build_prompt_block`)
- Modify: `bot/bootstrap.py:153` (passer `config` à `PersonaService`)
- Modify: `bot/persona/CAPABILITIES.md` (retrait de la ligne vocal)
- Test: `tests/test_persona_self_model.py`

**Interfaces:**
- Consumes: `build_self_model(static_text, config)` (Task 1).
- Produces: `PersonaService(persona_dir=..., config=...)` ; `build_prompt_block()` appende le self-model dérivé quand `config` est fourni, sinon le texte statique brut.

- [ ] **Step 1: Write the failing test**

Create `tests/test_persona_self_model.py`:

```python
from types import SimpleNamespace

from bot.intelligence.persona import PersonaService


def _persona_dir(tmp_path, caps_text="Je n'ai pas de corps."):
    (tmp_path / "SOUL.md").write_text("âme", encoding="utf-8")
    (tmp_path / "IDENTITY.md").write_text("Nom : Wally", encoding="utf-8")
    (tmp_path / "VOICE.md").write_text("Style : court.", encoding="utf-8")
    (tmp_path / "CAPABILITIES.md").write_text(caps_text, encoding="utf-8")
    return str(tmp_path)


def test_block_reflects_voice_enabled(tmp_path):
    cfg = SimpleNamespace(voice=SimpleNamespace(enabled=True))
    ps = PersonaService(persona_dir=_persona_dir(tmp_path), config=cfg)
    block = ps.build_prompt_block()
    assert "parler en vocal" in block
    assert "Je n'ai pas de corps." in block  # narratif statique préservé


def test_block_reflects_voice_disabled(tmp_path):
    cfg = SimpleNamespace(voice=SimpleNamespace(enabled=False))
    ps = PersonaService(persona_dir=_persona_dir(tmp_path), config=cfg)
    block = ps.build_prompt_block()
    assert "n'est pas activé" in block


def test_block_without_config_uses_static_only(tmp_path):
    ps = PersonaService(persona_dir=_persona_dir(tmp_path))  # config=None
    block = ps.build_prompt_block()
    assert "Je n'ai pas de corps." in block
    assert "Mes capacités techniques actuelles" not in block


def test_real_capabilities_md_has_no_fossilised_voice_line():
    # Le fichier réel ne doit plus affirmer que le vocal est désactivé/pas branché.
    with open("bot/persona/CAPABILITIES.md", encoding="utf-8") as f:
        content = f.read()
    assert "pas branché" not in content
    assert "elle est désactivée" not in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_persona_self_model.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'config'` (et l'assert sur le fichier réel échoue tant que la ligne n'est pas retirée).

- [ ] **Step 3a: Modifier `bot/intelligence/persona.py`**

Remplacer la déclaration de classe + `__init__` (lignes 9-18) :

```python
class PersonaService:
    """Charge et expose les fichiers de persona Markdown (SOUL, IDENTITY, VOICE, EMOTIONS)."""

    _FILES = ["SOUL.md", "IDENTITY.md", "VOICE.md", "EXEMPLES.md"]  # ordre canonique ; CAPABILITIES dérivé à part
    _CAPS_FILE = "CAPABILITIES.md"

    def __init__(self, persona_dir: str = "bot/persona", config=None):
        self._dir = persona_dir
        self._config = config
        self._blocks: dict[str, str] = {}
        self._caps_static: str = ""
        self._emotion_directives: dict[str, str] = {}
        self.reload()
```

Dans `reload()`, juste après la boucle `for filename in self._FILES:` (avant `self._emotion_directives = self._parse_emotions()`), insérer le chargement séparé du self-model statique :

```python
        # Self-model : la partie narrative stable est chargée à part ; les capacités
        # « à bascule » (vocal…) sont dérivées de la config dans build_prompt_block,
        # pour ne plus fossiliser (cf. self_model.build_self_model).
        caps_path = os.path.join(self._dir, self._CAPS_FILE)
        try:
            with open(caps_path, encoding="utf-8") as f:
                self._caps_static = f.read().strip()
        except FileNotFoundError:
            logger.warning("Persona file missing: {f}", f=self._CAPS_FILE)
            self._caps_static = ""
        except Exception as exc:
            logger.warning("Persona file read error {f}: {e}", f=self._CAPS_FILE, e=exc)
            self._caps_static = ""
```

Remplacer `build_prompt_block()` (lignes 161-166) :

```python
    def build_prompt_block(self) -> str:
        """Retourne SOUL → IDENTITY → VOICE → EXEMPLES + le self-model dérivé."""
        from datetime import datetime

        from bot.intelligence.self_model import build_self_model

        today = datetime.now().strftime("%A %d %B %Y")
        blocks = [v.replace("{current_date}", today) for v in self._blocks.values() if v]
        self_model = (
            build_self_model(self._caps_static, self._config)
            if self._config is not None
            else self._caps_static
        )
        if self_model:
            blocks.append(self_model.replace("{current_date}", today))
        return "\n\n".join(blocks)
```

- [ ] **Step 3b: Câbler la config dans le wiring DI — `bot/bootstrap.py:153`**

Remplacer :

```python
    persona = PersonaService()
```

par :

```python
    persona = PersonaService(config=config)
```

- [ ] **Step 3c: Nettoyer `bot/persona/CAPABILITIES.md`**

Supprimer entièrement la ligne suivante (ligne 22) :

```
- Pour l'instant je n'utilise pas le vocal : la capacité d'entendre et de parler en vocal existe dans mon code mais elle est désactivée (pas branchée). Inutile que je la redemande — elle est déjà construite, elle attend juste d'être activée.
```

Ne pas toucher aux autres lignes (notamment la ligne 21 sur le web, qui est correcte et conservée).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_persona_self_model.py tests/test_persona.py -v`
Expected: PASS — les 4 nouveaux tests + tous les tests existants de `test_persona.py` (non-régression : `test_capabilities_loaded_in_block`, `test_capabilities_loaded_from_real_persona_dir`, `test_build_prompt_block_order`).

- [ ] **Step 5: Commit**

```bash
git add bot/intelligence/persona.py bot/bootstrap.py bot/persona/CAPABILITIES.md tests/test_persona_self_model.py
git commit -m "feat(self-model): réactif dérive le vocal de config + retrait ligne fossilisée"
```

---

### Task 3: Brancher la cognition idle (bot.py)

**Files:**
- Modify: `bot/discord/bot.py:217` (appliquer `build_self_model` au texte injecté dans `ReasoningAgent`)

**Interfaces:**
- Consumes: `build_self_model(static_text, config)` (Task 1) ; `self.config` (déjà disponible dans `setup_hook`).
- Produces: rien de nouveau ; `ReasoningAgent` reçoit désormais le self-model dérivé au lieu du `.md` brut.

> Note : `setup_hook` (client Discord réel) n'est pas testable unitairement ici. La vérification repose sur un import sanity + la suite complète (non-régression). Le comportement de `build_self_model` est déjà couvert par Task 1.

- [ ] **Step 1: Modifier `bot/discord/bot.py`**

Le bloc actuel (lignes 216-217) :

```python
            _caps_path = Path(__file__).parent.parent / "persona" / "CAPABILITIES.md"
            _caps_text = _caps_path.read_text(encoding="utf-8") if _caps_path.exists() else ""
```

devient :

```python
            from bot.intelligence.self_model import build_self_model
            _caps_path = Path(__file__).parent.parent / "persona" / "CAPABILITIES.md"
            _caps_static = _caps_path.read_text(encoding="utf-8") if _caps_path.exists() else ""
            _caps_text = build_self_model(_caps_static, self.config)
```

Le log existant juste après (`if _caps_text: logger.info("CAPABILITIES.md chargé ...")`) et le passage `capabilities_text=_caps_text` à `ReasoningAgent` restent inchangés.

- [ ] **Step 2: Vérifier l'import (sanity)**

Run: `python -c "import bot.discord.bot"`
Expected: aucune erreur (exit 0).

- [ ] **Step 3: Non-régression — suite complète**

Run: `python -m pytest -q`
Expected: pas de NOUVEL échec par rapport à la baseline. (Baseline projet connue : 2 échecs préexistants `spam` + `cost`, non liés à ce travail — ne pas les compter comme régressions.)

- [ ] **Step 4: Commit**

```bash
git add bot/discord/bot.py
git commit -m "feat(self-model): cognition idle dérive le vocal de config (build_self_model)"
```

---

## Self-Review

**Spec coverage :**
- Module pur `self_model.py` + registre → Task 1. ✅
- Capacité vocal dérivée de `config.voice.enabled`, web exclu du registre initial → Task 1 (registre = vocal seul). ✅
- Nettoyage de `CAPABILITIES.md` (ligne 22 retirée, ligne 21 conservée) → Task 2, Step 3c. ✅
- Branchement réactif (`PersonaService` + wiring `config`) → Task 2. ✅
- Branchement cognition idle (`bot.py`) → Task 3. ✅
- Fallback `config=None` au texte statique → Task 2, `build_prompt_block` + `test_block_without_config_uses_static_only`. ✅
- Dérivation depuis `config` (pas les objets services), justifiée par l'ordre de boot → respectée (fonction lit `self.config` / `config`). ✅
- Tests de la limite/narratif stable → Task 1 (`test_static_text_is_preserved`), Task 2. ✅

**Type consistency :** `build_self_model(static_text: str, config) -> str` est défini en Task 1 et consommé à l'identique en Task 2 (`build_self_model(self._caps_static, self._config)`) et Task 3 (`build_self_model(_caps_static, self.config)`). Cohérent. ✅

**Placeholder scan :** aucun TBD/TODO ; chaque step de code montre le code complet ; chaque commande a sa sortie attendue. ✅
