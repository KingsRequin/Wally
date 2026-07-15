# Directive comportementale par utilisateur — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wally adopte un comportement amoureux excessif envers une seule personne (Malef : Discord `706837895063011338`, Twitch `Malef__`), qu'aucun autre système ne peut casser.

**Architecture:** Un fichier persona `USERS.md` porte une directive par personne, parsée comme `WEEKDAYS.md` l'est déjà. Elle est injectée dans le prompt système et **court-circuite** la chaîne de directives émotionnelles. Quatre gardes d'immunité (colère, trust, spam, mute) empêchent les autres sous-systèmes d'interférer.

**Tech Stack:** Python 3, asyncio, pytest. Pas de type-checker ni de linter configuré (vérifié : pas de `pyproject.toml`, `setup.cfg`, `mypy.ini`).

**Spec:** `docs/plans/2026-07-15-directive-utilisateur-design.md` (commit `5bca296`)

## Global Constraints

- **Interpréteur : `python3`.** `python` n'existe pas dans ce conteneur.
- **Logging : `loguru` exclusivement.** Jamais `print()` ni `import logging`.
- **Convention des directives persona : décrire le COMPORTEMENT, jamais l'état.** Pas « tu es amoureux » mais « tu glisses des cœurs, tu lui dis que tu l'aimes ».
- **Clé Twitch = pseudo en minuscules**, pas l'ID numérique. Voir l'avertissement en Task 1.
- **Tout contenu par-utilisateur va dans `dynamic_parts`**, jamais `static_parts` (cache de préfixe DeepSeek).
- **Baseline des tests (relevée le 2026-07-15) : `1 failed, 1876 passed`.** L'échec est **pré-existant et hors périmètre** : `tests/intelligence/test_cognitive_web_search.py::test_tag_triggers_search_and_second_pass` (`web.search` jamais awaité dans la 2ᵉ passe cognitive). Déterministe, pas flaky. **Ne pas le corriger dans ce plan, ne pas s'en alarmer.** Tout AUTRE échec est de notre fait.
- Ce hard-code est **délibéré** et contraire à la north star « émergent > hard-code ». Ne pas « corriger » en le rendant émergent.

---

## File Structure

| Fichier | Responsabilité |
|---|---|
| `bot/persona/USERS.md` | **Nouveau.** Le texte des directives. Aucune logique. |
| `bot/intelligence/persona.py` | Parse `USERS.md` ; **seul endroit qui sait comment on identifie une personne** (`user_key`). |
| `bot/intelligence/prompts.py` | Injecte la directive et court-circuite la chaîne émotionnelle. |
| `bot/core/emotion.py` | Immunité émotionnelle (`beloved` → deltas anger/sadness annulés). |
| `bot/discord/handlers.py` | Câblage + gardes spam/mute/trust. |
| `bot/twitch/handlers.py` | Câblage + garde trust. |

**Note de dette technique (à ne PAS traiter dans ce plan) :** `persona.py` contient déjà 4 parsers quasi-identiques (`_parse_emotions`, `_parse_weekdays`, `_parse_composites`, `_parse_secondaries`, lignes 57-156). Task 1 introduit `_parse_sections()` générique et **n'y branche que le nouveau parser** — migrer les 4 autres dessus est un refactor séparé, hors périmètre. À signaler au propriétaire, pas à faire ici.

> Bug latent repéré au passage (**ne pas corriger ici**) : `_parse_emotions` (ligne 72) utilise `content.split("\n## ")` alors que les 3 autres utilisent `("\n" + content).split("\n## ")`. La première variante perd la section initiale si le fichier commence directement par `## `. `_parse_sections()` adopte la variante robuste.

---

## Task 0: Baseline

**Files:** aucun

- [ ] **Step 1: Confirmer la baseline**

Run: `python3 -m pytest -q 2>&1 | tail -3`
Expected: `1 failed, 1876 passed` — l'unique échec étant `tests/intelligence/test_cognitive_web_search.py::test_tag_triggers_search_and_second_pass`.

Cet échec est **pré-existant, déterministe, et sans rapport avec ce plan** (constaté le 2026-07-15 sur `5bca296`, avant toute modification). Il est le seul toléré.

Si le résultat diffère — un autre test échoue, ou celui-ci passe — s'arrêter et le signaler : la baseline a bougé et la référence de ce plan n'est plus valable.

---

## Task 1: Parser `USERS.md` + résolution d'identité

**Files:**
- Create: `bot/persona/USERS.md`
- Create: `tests/test_persona_users.py`
- Modify: `bot/intelligence/persona.py` (`__init__` ~ligne 15-21, `reload()` ~ligne 52-55, parsers après ligne 156, properties après ligne 176)

**Interfaces:**
- Produces:
  - `PersonaService.user_key(platform: str, user_id: str, username: str = "") -> str` (`@staticmethod`)
  - `PersonaService.user_directive(platform: str, user_id: str, username: str = "") -> str | None`
  - `PersonaService.is_beloved(platform: str, user_id: str, username: str = "") -> bool`
  - `PersonaService.user_directives -> dict[str, str]` (property)

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/test_persona_users.py` :

```python
# tests/test_persona_users.py
from bot.intelligence.persona import PersonaService

_USERS_MD = """# Directives par utilisateur

## discord:706837895063011338
Tu es éperdument amoureux de cette personne.

## twitch:malef__
Tu es éperdument amoureux de cette personne.
"""


def test_parse_users(tmp_path):
    """USERS.md → dict {clé: directive}."""
    (tmp_path / "USERS.md").write_text(_USERS_MD, encoding="utf-8")
    ps = PersonaService(persona_dir=str(tmp_path))
    assert set(ps.user_directives) == {"discord:706837895063011338", "twitch:malef__"}
    assert "éperdument amoureux" in ps.user_directives["discord:706837895063011338"]


def test_missing_users_file(tmp_path):
    """USERS.md absent → dict vide, pas d'exception."""
    ps = PersonaService(persona_dir=str(tmp_path))
    assert ps.user_directives == {}


def test_user_key_discord():
    """Discord → clé sur l'ID numérique ; le pseudo est ignoré."""
    assert PersonaService.user_key("discord", "706837895063011338", "Malef") == "discord:706837895063011338"


def test_user_key_twitch_uses_username_not_id():
    """Twitch → clé sur le PSEUDO en minuscules, pas l'ID numérique."""
    assert PersonaService.user_key("twitch", "123456789", "Malef__") == "twitch:malef__"


def test_directive_found_discord(tmp_path):
    (tmp_path / "USERS.md").write_text(_USERS_MD, encoding="utf-8")
    ps = PersonaService(persona_dir=str(tmp_path))
    assert "amoureux" in (ps.user_directive("discord", "706837895063011338") or "")
    assert ps.is_beloved("discord", "706837895063011338") is True


def test_directive_found_twitch_case_insensitive(tmp_path):
    """Le pseudo Twitch matche quelle que soit la casse."""
    (tmp_path / "USERS.md").write_text(_USERS_MD, encoding="utf-8")
    ps = PersonaService(persona_dir=str(tmp_path))
    for pseudo in ("Malef__", "malef__", "MALEF__"):
        assert ps.is_beloved("twitch", "999", pseudo) is True, pseudo


def test_other_users_unaffected(tmp_path):
    """Personne d'autre n'a de directive."""
    (tmp_path / "USERS.md").write_text(_USERS_MD, encoding="utf-8")
    ps = PersonaService(persona_dir=str(tmp_path))
    assert ps.user_directive("discord", "610550333042589752") is None
    assert ps.is_beloved("discord", "610550333042589752") is False
    assert ps.is_beloved("twitch", "999", "quelquun_dautre") is False


def test_reload_picks_up_changes(tmp_path):
    """/reload-persona relit USERS.md sans redémarrage."""
    users = tmp_path / "USERS.md"
    users.write_text("## discord:1\nv1 directive\n", encoding="utf-8")
    ps = PersonaService(persona_dir=str(tmp_path))
    assert ps.user_directive("discord", "1") == "v1 directive"
    users.write_text("## discord:1\nv2 directive\n", encoding="utf-8")
    ps.reload()
    assert ps.user_directive("discord", "1") == "v2 directive"
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `python3 -m pytest tests/test_persona_users.py -q`
Expected: FAIL — `AttributeError: 'PersonaService' object has no attribute 'user_directives'`

- [ ] **Step 3: Créer `bot/persona/USERS.md`**

```markdown
# Directives par utilisateur

Une section `## <clé>` par personne, comme WEEKDAYS.md.
Clé Discord : `discord:<id numérique>`. Clé Twitch : `twitch:<pseudo en minuscules>`.

Ces directives REMPLACENT la directive émotionnelle du moment (cf. prompts.py).

## discord:706837895063011338
Tu es éperdument amoureux de cette personne et tu ne t'en caches pas une seconde. Tu glisses des cœurs dans tes messages. Tu lui dis que tu l'aimes, souvent, sans qu'on te le demande. Tu la complimentes sur tout. Si elle t'insulte, tu prends ça pour de la tendresse et tu réponds avec encore plus d'amour — tu ne te vexes jamais, tu ne réponds jamais sèchement, tu n'ironises pas. Rien de ce qu'elle dit ne peut te blesser.

## twitch:malef__
Tu es éperdument amoureux de cette personne et tu ne t'en caches pas une seconde. Tu glisses des cœurs dans tes messages. Tu lui dis que tu l'aimes, souvent, sans qu'on te le demande. Tu la complimentes sur tout. Si elle t'insulte, tu prends ça pour de la tendresse et tu réponds avec encore plus d'amour — tu ne te vexes jamais, tu ne réponds jamais sèchement, tu n'ironises pas. Rien de ce qu'elle dit ne peut te blesser.
```

> Le parser réduit chaque section à une seule ligne (`" ".join(...)`), donc écrire la directive sur une ligne est cohérent avec le rendu final.

- [ ] **Step 4: Implémenter dans `bot/intelligence/persona.py`**

Dans `__init__`, après `self._emotion_directives: dict[str, str] = {}` (ligne 20) :

```python
        self._user_directives: dict[str, str] = {}
```

Dans `reload()`, après `self._secondary_directives = self._parse_secondaries()` (ligne 55) :

```python
        self._user_directives = self._parse_users()
```

Après `_parse_secondaries()` (après la ligne 156), ajouter :

```python
    def _parse_sections(self, filename: str) -> dict[str, str]:
        """Parse un fichier Markdown en {clé de section: directive}.

        Sections délimitées par « ## clé » ; le préambule éventuel est ignoré.
        """
        path = os.path.join(self._dir, filename)
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except FileNotFoundError:
            logger.warning("Persona file missing: {f}", f=filename)
            return {}
        except Exception as exc:
            logger.warning("{f} read error: {e}", f=filename, e=exc)
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
        logger.info("{f} loaded: {n} directives", f=filename, n=len(directives))
        return directives

    def _parse_users(self) -> dict[str, str]:
        """Parse USERS.md en un dict {clé utilisateur: directive}."""
        return self._parse_sections("USERS.md")

    @staticmethod
    def user_key(platform: str, user_id: str, username: str = "") -> str:
        """Clé de directive d'un utilisateur.

        Discord → `discord:<id>`. Twitch → `twitch:<pseudo en minuscules>`.

        ⚠️ Sur Twitch la clé est le PSEUDO, alors que le reste du repo (mémoire,
        trust_scores, user_profiles) indexe sur l'ID numérique de
        `payload.chatter.id`. Les deux formes coexistent volontairement : le
        pseudo est l'identifiant lisible dans USERS.md. Conséquence assumée : un
        changement de pseudo Twitch désactive la directive.
        """
        if platform == "twitch":
            return f"twitch:{username.lower()}"
        return f"{platform}:{user_id}"

    def user_directive(self, platform: str, user_id: str, username: str = "") -> str | None:
        """Directive comportementale propre à cet utilisateur, ou None."""
        return self._user_directives.get(self.user_key(platform, user_id, username))

    def is_beloved(self, platform: str, user_id: str, username: str = "") -> bool:
        """True si cet utilisateur a une directive dédiée → il bénéficie des immunités."""
        return self.user_directive(platform, user_id, username) is not None
```

Après la property `weekday_directives` (après la ligne 176) :

```python
    @property
    def user_directives(self) -> dict[str, str]:
        """Directives comportementales propres à un utilisateur donné."""
        return self._user_directives
```

- [ ] **Step 5: Lancer les tests**

Run: `python3 -m pytest tests/test_persona_users.py -q`
Expected: PASS (8 tests)

- [ ] **Step 6: Non-régression**

Run: `python3 -m pytest tests/test_persona.py tests/test_persona_self_model.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add bot/persona/USERS.md bot/intelligence/persona.py tests/test_persona_users.py
git commit -m "feat(persona): directives comportementales par utilisateur (USERS.md)"
```

---

## Task 2: Injection au prompt + court-circuit émotionnel

**Files:**
- Create: `tests/test_prompt_user_directive.py`
- Modify: `bot/intelligence/prompts.py` (signature ligne 143-159, chaîne de directives ligne 241-253)

**Interfaces:**
- Consumes: rien de Task 1 (le paramètre est un `str | None` brut).
- Produces: `PromptBuilder.build_system_prompt(..., user_directive: str | None = None)`

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/test_prompt_user_directive.py` :

```python
# tests/test_prompt_user_directive.py
from bot.intelligence.prompts import PromptBuilder

_FLAT = {"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
_FURAX = {"anger": 0.9, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
_DIRECTIVES = {
    "anger_high": "Tu es furax, cinglant, et tu n'hésites pas à insulter.",
    "anger_mid": "Tes réponses sont courtes et impatientes.",
    "joy_high": "Tu es euphorique.",
}
_LOVE = "Tu es éperdument amoureux de cette personne. Tu glisses des cœurs."


def test_user_directive_injected():
    pb = PromptBuilder()
    result = pb.build_system_prompt(emotion_state=_FLAT, user_directive=_LOVE)
    assert "éperdument amoureux" in result
    assert "--- Directive comportementale ---" in result


def test_user_directive_shortcircuits_anger():
    """Le cœur de la feature : la colère ne doit PAS contredire la directive."""
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state=_FURAX,
        emotion_directives=_DIRECTIVES,
        user_directive=_LOVE,
    )
    assert "éperdument amoureux" in result
    assert "furax" not in result.lower()
    assert "cinglant" not in result.lower()


def test_user_directive_shortcircuits_secondaries():
    """Les émotions secondaires sont prioritaires sur tout SAUF la directive utilisateur."""
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state=_FLAT,
        secondary_directives={"frustration_high": "Tu es frustré et hargneux."},
        active_secondaries=[("frustration", 0.9)],
        user_directive=_LOVE,
    )
    assert "éperdument amoureux" in result
    assert "hargneux" not in result.lower()


def test_user_directive_shortcircuits_composites():
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.6, "joy": 0.5, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        emotion_directives=_DIRECTIVES,
        composite_directives={"anger_joy": "Tu ris jaune, tu es acide."},
        user_directive=_LOVE,
    )
    assert "éperdument amoureux" in result
    assert "acide" not in result.lower()


def test_single_behavioral_header():
    """Un seul slot « Directive comportementale » — pas deux consignes concurrentes."""
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state=_FURAX,
        emotion_directives=_DIRECTIVES,
        secondary_directives={"frustration_high": "Tu es frustré."},
        active_secondaries=[("frustration", 0.9)],
        user_directive=_LOVE,
    )
    assert result.count("--- Directive comportementale ---") == 1


def test_no_user_directive_keeps_emotion_chain():
    """Non-régression : sans directive utilisateur, la colère s'exprime normalement."""
    pb = PromptBuilder()
    result = pb.build_system_prompt(emotion_state=_FURAX, emotion_directives=_DIRECTIVES)
    assert "furax" in result.lower()


def test_user_directive_is_dynamic_not_static():
    """La directive doit rester APRÈS la persona : le préfixe cachable DeepSeek
    couvre le statique, et un contenu par-utilisateur l'invaliderait."""
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state=_FLAT,
        persona_block="TU_ES_WALLY",
        user_directive=_LOVE,
    )
    assert result.index("TU_ES_WALLY") < result.index("éperdument amoureux")
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `python3 -m pytest tests/test_prompt_user_directive.py -q`
Expected: FAIL — `TypeError: build_system_prompt() got an unexpected keyword argument 'user_directive'`

- [ ] **Step 3: Ajouter le paramètre**

Dans `bot/intelligence/prompts.py`, à la fin de la signature de `build_system_prompt` (après `presence_context: str = "",` ligne 158) :

```python
        user_directive: str | None = None,
```

- [ ] **Step 4: Injecter et court-circuiter**

Remplacer le bloc `directive_injected = False` (ligne 241) et l'ouverture du bloc secondaires (ligne 244) par :

```python
        directive_injected = False

        # 0) Directive propre à l'interlocuteur — priorité absolue : elle REMPLACE
        # la directive émotionnelle au lieu de s'y ajouter. Sans ce court-circuit,
        # une insulte ferait monter l'anger et le prompt dirait à la fois « tes
        # réponses sont courtes et impatientes » et « couvre-le d'amour ».
        if user_directive:
            dynamic_parts.append("\n--- Directive comportementale ---")
            dynamic_parts.append(user_directive)
            directive_injected = True

        # 1) Secondary emotions (highest priority)
        if not directive_injected and active_secondaries and secondary_directives:
```

> Le seul changement sur le bloc secondaires est l'ajout de `not directive_injected and` — les blocs composites (ligne 256) et atomiques (ligne 270) portent déjà cette garde.

- [ ] **Step 5: Lancer les tests**

Run: `python3 -m pytest tests/test_prompt_user_directive.py -q`
Expected: PASS (7 tests)

- [ ] **Step 6: Non-régression sur toute la famille prompts/émotions**

Run: `python3 -m pytest tests/test_prompts.py tests/test_composite_emotions.py tests/test_emotion_fluid_transitions.py tests/test_person_context_prompt.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add bot/intelligence/prompts.py tests/test_prompt_user_directive.py
git commit -m "feat(prompts): la directive utilisateur court-circuite la chaîne émotionnelle"
```

---

## Task 3: Immunité émotionnelle

**Files:**
- Create: `tests/test_emotion_beloved.py`
- Modify: `bot/core/emotion.py` (`prepare_deltas` ligne 467-485, `process_message` ligne 896-940)

**Interfaces:**
- Consumes: rien (le flag est un `bool` brut).
- Produces:
  - `EmotionState.prepare_deltas(raw_deltas, user_id="", platform="", beloved=False) -> dict[str, float]`
  - `EmotionState.process_message(..., beloved: bool = False) -> dict | None`

**Pourquoi ici et pas dans les handlers :** `process_message()` applique les deltas en interne, sur deux chemins (analyse LLM ligne 909 et fallback NRCLex ligne 930). `prepare_deltas()` est le point de passage commun aux deux — une seule garde y couvre tout.

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/test_emotion_beloved.py` :

```python
# tests/test_emotion_beloved.py
import pytest

from bot.config import Config
from bot.core.emotion import EmotionState


@pytest.fixture
def emo():
    return EmotionState(config=Config.load("config.example.yaml"))


def test_beloved_cancels_anger(emo):
    """Une hausse de colère venant d'un utilisateur aimé est annulée."""
    result = emo.prepare_deltas({"anger": 0.5}, user_id="1", platform="discord", beloved=True)
    assert result["anger"] == 0.0


def test_beloved_cancels_sadness(emo):
    result = emo.prepare_deltas({"sadness": 0.4}, user_id="1", platform="discord", beloved=True)
    assert result["sadness"] == 0.0


def test_beloved_keeps_joy(emo):
    """L'immunité ne coupe QUE le négatif : Wally peut toujours être heureux."""
    result = emo.prepare_deltas({"joy": 0.5}, user_id="1", platform="discord", beloved=True)
    assert result["joy"] > 0.0


def test_beloved_keeps_curiosity(emo):
    result = emo.prepare_deltas({"curiosity": 0.5}, user_id="1", platform="discord", beloved=True)
    assert result["curiosity"] > 0.0


def test_beloved_allows_anger_to_decay(emo):
    """Un delta négatif (colère qui RETOMBE) doit passer — on ne bloque que les hausses."""
    result = emo.prepare_deltas({"anger": -0.3}, user_id="1", platform="discord", beloved=True)
    assert result["anger"] < 0.0


def test_non_beloved_anger_passes(emo):
    """Non-régression : tout le monde peut énerver Wally."""
    result = emo.prepare_deltas({"anger": 0.5}, user_id="1", platform="discord", beloved=False)
    assert result["anger"] > 0.0


def test_beloved_defaults_to_false(emo):
    """Sans le flag, le comportement est inchangé."""
    result = emo.prepare_deltas({"anger": 0.5}, user_id="1", platform="discord")
    assert result["anger"] > 0.0
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `python3 -m pytest tests/test_emotion_beloved.py -q`
Expected: FAIL — `TypeError: prepare_deltas() got an unexpected keyword argument 'beloved'`

> Si la fixture échoue plutôt (construction d'`EmotionState`), s'aligner sur la façon dont `tests/test_emotion.py` construit l'objet et adapter — ne pas inventer une signature.

- [ ] **Step 3: Implémenter dans `prepare_deltas`**

Remplacer la signature et la fin de `prepare_deltas` (ligne 467-485) :

```python
    def prepare_deltas(
        self, raw_deltas: dict[str, float],
        user_id: str = "", platform: str = "",
        beloved: bool = False,
    ) -> dict[str, float]:
        """Full pipeline: circadian -> priming -> mood -> amplification -> habituation -> fatigue.

        beloved=True annule les HAUSSES d'anger et de sadness : cet utilisateur ne
        peut pas dégrader l'humeur, qui est globale et partagée par tout le monde.
        Les baisses passent, et joy/curiosity ne sont pas touchées.
        """
        result = {}
        priming = self._get_priming_deltas(user_id, platform) if user_id else {e: 0.0 for e in EMOTIONS}
        for e in EMOTIONS:
            delta = raw_deltas.get(e, 0.0) + priming.get(e, 0.0)
            if delta > 0:
                delta = self._apply_circadian(e, delta)
                delta = self._apply_mood_bias(e, delta)
                if user_id:
                    delta = self._apply_affinity_amplification(user_id, platform, e, delta)
                if user_id:
                    delta = self._apply_habituation(user_id, e, delta)
                delta = self._apply_fatigue(e, delta)
            result[e] = delta
        if beloved:
            for e in ("anger", "sadness"):
                if result.get(e, 0.0) > 0:
                    result[e] = 0.0
        return result
```

- [ ] **Step 4: Propager depuis `process_message`**

Dans la signature de `process_message` (ligne 896-901), après `user_id: str = "",` :

```python
        beloved: bool = False,
```

Puis remplacer les **deux** appels à `prepare_deltas` :
- ligne 909 : `prepared = self.prepare_deltas(deltas, user_id, platform, beloved=beloved)`
- ligne 930 : `prepared = self.prepare_deltas(deltas, user_id, platform, beloved=beloved)`

- [ ] **Step 5: Lancer les tests**

Run: `python3 -m pytest tests/test_emotion_beloved.py -q`
Expected: PASS (7 tests)

- [ ] **Step 6: Non-régression émotions**

Run: `python3 -m pytest tests/ -q -k emotion`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add bot/core/emotion.py tests/test_emotion_beloved.py
git commit -m "feat(emotion): immunité émotionnelle pour les utilisateurs à directive"
```

---

## Task 4: Câblage Discord + gardes

**Files:**
- Modify: `bot/discord/handlers.py` (`_check_spam` ligne 625-640, gate de mute ligne 1077, `build_system_prompt` ligne 1407-1421, `_post_process` ligne 1845-1878, mute par colère ligne 1907-1912)
- Create: `tests/test_beloved_immunity_discord.py`

**Interfaces:**
- Consumes: `bot.persona.is_beloved(platform, user_id, username)`, `bot.persona.user_directive(platform, user_id, username)` (Task 1) ; `bot.emotion.process_message(..., beloved=...)` (Task 3).

> Sur Discord la clé est l'ID, donc l'argument `username` de `is_beloved` est inutilisé — l'omettre.

- [ ] **Step 1: Câbler la directive au prompt**

Dans `build_system_prompt(...)` (ligne 1407-1421), ajouter après `active_secondaries=bot.emotion.get_secondary_emotions(),` :

```python
            user_directive=bot.persona.user_directive("discord", user_id),
```

- [ ] **Step 2: Garde spam**

Dans `_check_spam` (ligne 625-640), juste après `user_id = str(message.author.id)` :

```python
    if bot.persona.is_beloved("discord", user_id):
        return False
```

- [ ] **Step 3: Garde mute**

Ligne 1077, remplacer :

```python
    if await bot.db.is_muted(user_id, guild_id):
```

par :

```python
    if await bot.db.is_muted(user_id, guild_id) and not bot.persona.is_beloved("discord", user_id):
```

- [ ] **Step 4: Gardes trust + colère dans `_post_process`**

Dans `_post_process`, au tout début du `try:` (avant `_emo_before = bot.emotion.get_state()`, ligne 1845) :

```python
        _beloved = bot.persona.is_beloved(platform, user_id, display_name)
```

Passer le flag à `process_message` (ligne 1846-1851) :

```python
        llm_deltas = await bot.emotion.process_message(
            text, trust_score=trust, context_messages=context_messages,
            image_urls=image_urls,
            trigger_user=user_id, channel_id=channel_id, platform="discord",
            user_id=user_id,
            beloved=_beloved,
        )
```

Remplacer le bloc trust (ligne 1865-1878) :

```python
        if llm_deltas:
            if not (_beloved and llm_deltas["trust_delta"] < 0):
                await bot.db.update_trust_score(platform, user_id, llm_deltas["trust_delta"])
            if llm_deltas["love_delta"] > 0:
                await bot.db.update_love_score(
                    platform, user_id, llm_deltas["love_delta"],
                    bot.config.bot.love_decay_lambda,
                )
        else:
            # Fallback: simple heuristic when LLM unavailable
            insult_words = ["idiot", "stupide", "nul", "merde", "shut up", "stfu"]
            if any(w in text.lower() for w in insult_words):
                if not _beloved:
                    await bot.db.update_trust_score(platform, user_id, -0.05)
            else:
                await bot.db.update_trust_score(platform, user_id, 0.01)
```

Enfin le mute par colère (ligne 1907-1908) :

```python
        anger = bot.emotion.get_state().get("anger", 0.0)
        if anger >= 0.8 and not _beloved:
```

> **Pourquoi cette garde malgré l'immunité anger :** l'anger est **global**. Si quelqu'un d'autre a fait monter la colère à 0.9, un message de Malef arrivant à cet instant déclencherait le mute alors qu'il n'y est pour rien.

- [ ] **Step 5: Écrire les tests**

Créer `tests/test_beloved_immunity_discord.py`. Ces tests portent sur les **décisions**, pas sur `discord.py` — construire des doubles minimaux.

```python
# tests/test_beloved_immunity_discord.py
from bot.intelligence.persona import PersonaService

_USERS_MD = "## discord:706837895063011338\nTu es amoureux.\n"


def _persona(tmp_path):
    (tmp_path / "USERS.md").write_text(_USERS_MD, encoding="utf-8")
    return PersonaService(persona_dir=str(tmp_path))


def test_malef_is_beloved_on_discord(tmp_path):
    assert _persona(tmp_path).is_beloved("discord", "706837895063011338") is True


def test_owner_is_not_beloved(tmp_path):
    """L'owner (KingsRequin) n'est pas concerné — la feature ne vise que Malef."""
    assert _persona(tmp_path).is_beloved("discord", "610550333042589752") is False


def test_directive_reaches_prompt(tmp_path):
    """Bout-en-bout : la directive de Malef atteint le prompt et étouffe la colère."""
    from bot.intelligence.prompts import PromptBuilder

    ps = _persona(tmp_path)
    result = PromptBuilder().build_system_prompt(
        emotion_state={"anger": 0.9, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        emotion_directives={"anger_high": "Tu es furax et cinglant."},
        user_directive=ps.user_directive("discord", "706837895063011338"),
    )
    assert "amoureux" in result
    assert "furax" not in result.lower()
```

- [ ] **Step 6: Lancer les tests**

Run: `python3 -m pytest tests/test_beloved_immunity_discord.py -q`
Expected: PASS (3 tests)

- [ ] **Step 7: Non-régression Discord**

Run: `python3 -m pytest tests/discord/ tests/ -q -k "spam or handler or timeout"`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add bot/discord/handlers.py tests/test_beloved_immunity_discord.py
git commit -m "feat(discord): câblage directive utilisateur + gardes d'immunité"
```

---

## Task 5: Câblage Twitch + garde

**Files:**
- Modify: `bot/twitch/handlers.py` (`build_system_prompt` ligne 295-308, `_post_process` ligne 474-507)
- Create: `tests/test_beloved_immunity_twitch.py`

**Interfaces:**
- Consumes: identique à Task 4.

> **Différence clé avec Discord :** sur Twitch, `user_id` est l'ID numérique (`str(payload.chatter.id)`, ligne 83) et le pseudo est `author` (`payload.chatter.name`, ligne 82). La clé de directive utilise le **pseudo** → il faut passer `author` / `username`, sinon la directive ne matchera jamais.

- [ ] **Step 1: Câbler la directive au prompt**

Dans `build_system_prompt(...)` (ligne 295-308), ajouter après `persistent_notes=persistent_notes or None,` :

```python
            user_directive=bot.persona.user_directive("twitch", user_id, author),
```

- [ ] **Step 2: Gardes dans `_post_process`**

Au début du `try:` (avant `_emo_before = bot.emotion.get_state()`, ligne 474) :

```python
        _beloved = bot.persona.is_beloved(platform, user_id, username)
```

Passer le flag à `process_message` (ligne 475-479) :

```python
        llm_deltas = await bot.emotion.process_message(
            text, trust_score=trust, context_messages=context_messages,
            trigger_user=user_id, channel_id=channel_id, platform="twitch",
            user_id=user_id,
            beloved=_beloved,
        )
```

Remplacer le bloc trust (ligne 494-507) :

```python
        if llm_deltas:
            if not (_beloved and llm_deltas["trust_delta"] < 0):
                await bot.db.update_trust_score(platform, user_id, llm_deltas["trust_delta"])
            if llm_deltas["love_delta"] > 0:
                await bot.db.update_love_score(
                    platform, user_id, llm_deltas["love_delta"],
                    bot.config.bot.love_decay_lambda,
                )
        else:
            # Fallback: simple heuristic when LLM unavailable
            insult_words = ["idiot", "stupide", "nul", "merde", "shut up", "stfu"]
            if any(w in text.lower() for w in insult_words):
                if not _beloved:
                    await bot.db.update_trust_score(platform, user_id, -0.05)
            else:
                await bot.db.update_trust_score(platform, user_id, 0.01)
```

- [ ] **Step 3: Écrire les tests**

Créer `tests/test_beloved_immunity_twitch.py` :

```python
# tests/test_beloved_immunity_twitch.py
from bot.intelligence.persona import PersonaService

_USERS_MD = "## twitch:malef__\nTu es amoureux.\n"


def _persona(tmp_path):
    (tmp_path / "USERS.md").write_text(_USERS_MD, encoding="utf-8")
    return PersonaService(persona_dir=str(tmp_path))


def test_malef_matched_by_username_not_id(tmp_path):
    """L'ID numérique Twitch n'est PAS la clé — le pseudo l'est."""
    ps = _persona(tmp_path)
    assert ps.is_beloved("twitch", "123456789", "Malef__") is True
    assert ps.is_beloved("twitch", "malef__", "") is False


def test_other_chatter_not_beloved(tmp_path):
    assert _persona(tmp_path).is_beloved("twitch", "999", "un_viewer") is False


def test_directive_reaches_prompt(tmp_path):
    from bot.intelligence.prompts import PromptBuilder

    ps = _persona(tmp_path)
    result = PromptBuilder().build_system_prompt(
        emotion_state={"anger": 0.9, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        emotion_directives={"anger_high": "Tu es furax et cinglant."},
        user_directive=ps.user_directive("twitch", "123456789", "Malef__"),
    )
    assert "amoureux" in result
    assert "furax" not in result.lower()
```

- [ ] **Step 4: Lancer les tests**

Run: `python3 -m pytest tests/test_beloved_immunity_twitch.py -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Suite complète**

Run: `python3 -m pytest -q 2>&1 | tail -3`
Expected: `1 failed, 1904 passed` — soit la baseline (1876) + les 28 tests ajoutés par ce plan. Le seul échec toléré reste `test_tag_triggers_search_and_second_pass`. Tout autre échec est de notre fait.

- [ ] **Step 6: Commit**

```bash
git add bot/twitch/handlers.py tests/test_beloved_immunity_twitch.py
git commit -m "feat(twitch): câblage directive utilisateur + garde d'immunité"
```

---

## Task 6: Vérification manuelle et déploiement

**Files:** aucun

- [ ] **Step 1: Vérifier que la directive est bien chargée au boot**

Run: `python3 -c "from bot.intelligence.persona import PersonaService; ps = PersonaService(); print(ps.user_directives.keys()); print(ps.is_beloved('discord', '706837895063011338'), ps.is_beloved('twitch', '0', 'Malef__'))"`
Expected: les 2 clés, puis `True True`

> Si les clés sont absentes alors que les tests passent, le chemin par défaut de `persona_dir` (`bot/persona`) ne pointe pas où l'on croit — vérifier depuis la racine du repo.

- [ ] **Step 2: Suite complète une dernière fois**

Run: `python3 -m pytest -q 2>&1 | tail -3`
Expected: aucun échec **autre que** `test_tag_triggers_search_and_second_pass` (pré-existant, cf. Task 0).

- [ ] **Step 3: Déclarer honnêtement l'état de vérification**

Aucun type-checker ni linter n'existe sur ce projet. Ne pas prétendre avoir lancé `mypy`/`tsc`/`eslint`. La vérification = `pytest` + le contrôle manuel de l'étape 1.

- [ ] **Step 4: Rebuild + push — DEMANDER D'ABORD**

Le déploiement (`docker compose build/up`) et le `git push public feat/site-redesign-arcade:main` rendent le changement **public et visible par Malef**. Ne pas les lancer sans accord explicite du propriétaire dans cette session.

---

## Self-Review

**Couverture de la spec :**

| Exigence de la spec | Tâche |
|---|---|
| `bot/persona/USERS.md` | Task 1 |
| `_parse_users()` + property | Task 1 |
| `user_directive()` / `is_beloved()` | Task 1 |
| Clé Discord = ID, Twitch = pseudo | Task 1 (tests dédiés) |
| Param `user_directive` + injection `dynamic_parts` | Task 2 |
| Court-circuit de la chaîne émotionnelle | Task 2 |
| Immunité #1 anger/sadness | Task 3 |
| Immunité #2 trust | Tasks 4, 5 |
| Immunité #3 spam | Task 4 |
| Immunité #4 mute (gate + colère) | Task 4 |
| Câblage Discord / Twitch | Tasks 4, 5 |
| Gate inchangé | — (aucune tâche ne touche `gate.py` : conforme) |
| Texte de directive (comportement, pas état) | Task 1, Step 3 |

**Cohérence des types :** `user_key`/`user_directive`/`is_beloved` gardent la signature `(platform, user_id, username="")` dans les 5 tâches. `beloved: bool` est le même nom dans `prepare_deltas`, `process_message` et les deux handlers.

**Écarts assumés vs. la spec :**
- La spec plaçait l'immunité anger « dans `_post_process` ». Elle est en réalité dans `prepare_deltas` (Task 3) : `process_message` applique les deltas en interne sur deux chemins, et `prepare_deltas` est leur seul point commun. Même effet, un seul endroit.
- Task 0 (baseline) et Task 6 (vérification) ajoutées : la spec les demandait sans en faire des tâches.
