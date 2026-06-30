# Recherche web en pensée cognitive — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre à Wally de lancer une recherche web de sa propre initiative pendant un tick cognitif (`[ACT web_search {"query"}]`), puis de re-penser immédiatement avec le résultat.

**Architecture:** Déclenchement émergent via tag texte dans la pensée (le chemin cognitif n'utilise pas de tool-calling natif). Interception dans `cognitive_loop._tick` après la 1ʳᵉ passe de raisonnement : si le tag est présent et les gardes passent, on exécute `web_search.search`, on **mute** `context.web_finding` sur l'objet déjà construit, et on relance `reason(context)` (2ᵉ passe). La capacité est dérivée dans le self-model pour que Wally sache qu'il peut.

**Tech Stack:** Python 3.11, asyncio, pytest, `WebSearchService` (Tavily).

## Global Constraints

- Logging : `loguru` exclusivement (`from loguru import logger`), jamais `print`/`logging`.
- Tout I/O async ; jamais bloquant dans le tick.
- North Star : émergent > hard-code. Wally décide ; aucune amorce ne le force.
- Périmètre : tous les ticks cognitifs (pas seulement idle). Chemin réactif hors scope.
- Une seule recherche web par tick (garantie structurellement : `_maybe_web_search` est appelé une fois, sans boucle).
- Garde-fous : capacité utilisée seulement si `web_search.available` ET `not await is_quota_exceeded()` ET cooldown écoulé.
- Cooldown : `config.tavily.cognitive_cooldown_minutes` (défaut 45).
- Ne jamais faire planter le tick : toute exception web → log WARNING + on garde la pensée de la 1ʳᵉ passe.
- Baseline tests : la suite `tests/intelligence/` doit rester verte (hors 3 échecs + 16 erreurs costs préexistants, non liés).

---

## File Structure

| Fichier | Responsabilité / changement |
|---|---|
| `bot/config.py` | `TavilyConfig` : nouveau champ `cognitive_cooldown_minutes: int = 45`. |
| `bot/intelligence/self_model.py` | Signature `build_self_model(static_text, config, *, web_available=False)` + capacité web dérivée du flag. |
| `bot/persona/CAPABILITIES.md` | Retirer la ligne qui nie la navigation web. |
| `bot/discord/bot.py` | Câblage : `build_self_model(..., web_available=…)` (l.219) + `CognitiveLoop(..., web_search=…, web_search_cooldown_s=…)` (l.241). |
| `bot/intelligence/persona.py` | Câblage : `build_self_model(..., web_available=…)` (l.187). |
| `bot/intelligence/attention_agent.py` | `AttentionContext` : champ `web_finding: str \| None = None`. |
| `bot/intelligence/reasoning_agent.py` | `_format_context` : bloc « Tu viens de chercher » quand `web_finding` présent. |
| `bot/intelligence/cognitive_loop.py` | `__init__` params `web_search`/`web_search_cooldown_s` + méthode `_maybe_web_search` + appel dans `_tick`. |
| `bot/intelligence/persona/prompts/reasoning_system.md` | Documenter `[ACT web_search {"query"}]`. |
| `tests/intelligence/test_self_model.py` | Tests web_available on/off. |
| `tests/intelligence/test_reasoning_web_finding.py` | (créé) Test rendu du bloc web_finding. |
| `tests/intelligence/test_cognitive_web_search.py` | (créé) Tests `_maybe_web_search`. |

---

## Task 1 : Config — cooldown cognitif Tavily

**Files:**
- Modify: `bot/config.py` (`TavilyConfig`, ≈ l.225)
- Test: `tests/test_config_tavily_cooldown.py` (créé)

**Interfaces:**
- Produces: `config.tavily.cognitive_cooldown_minutes: int` (défaut 45).

- [ ] **Step 1 : Test qui échoue**

Créer `tests/test_config_tavily_cooldown.py` :

```python
from bot.config import TavilyConfig


def test_tavily_cooldown_default():
    assert TavilyConfig().cognitive_cooldown_minutes == 45


def test_tavily_cooldown_override():
    assert TavilyConfig(cognitive_cooldown_minutes=10).cognitive_cooldown_minutes == 10
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `python -m pytest tests/test_config_tavily_cooldown.py -v`
Expected: FAIL (`TypeError: __init__() got an unexpected keyword argument` ou `AttributeError`).

- [ ] **Step 3 : Implémenter**

Dans `bot/config.py`, classe `TavilyConfig` (qui ne contient aujourd'hui que `monthly_limit: int = 200`), ajouter le champ :

```python
@dataclass
class TavilyConfig:
    monthly_limit: int = 200
    # Délai minimal entre deux recherches web déclenchées par la cognition
    # (pensées) — garde-fou anti-boucle, en plus du quota mensuel.
    cognitive_cooldown_minutes: int = 45
```

- [ ] **Step 4 : Lancer, vérifier le succès**

Run: `python -m pytest tests/test_config_tavily_cooldown.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5 : Commit**

```bash
git add bot/config.py tests/test_config_tavily_cooldown.py
git commit -m "feat(config): TavilyConfig.cognitive_cooldown_minutes (garde-fou recherche web cognitive)"
```

---

## Task 2 : self-model — capacité web dérivée + câblage + CAPABILITIES.md

**Files:**
- Modify: `bot/intelligence/self_model.py`
- Modify: `bot/discord/bot.py:219`
- Modify: `bot/intelligence/persona.py:187`
- Modify: `bot/persona/CAPABILITIES.md`
- Test: `tests/intelligence/test_self_model.py`

**Interfaces:**
- Consumes: rien.
- Produces: `build_self_model(static_text, config, *, web_available: bool = False) -> str`. Quand `web_available` est True, la section capacités contient la phrase active web ; sinon la phrase inactive.

- [ ] **Step 1 : Test qui échoue**

Ajouter à `tests/intelligence/test_self_model.py` :

```python
def test_web_available_phrase_active():
    out = build_self_model("", object(), web_available=True)
    assert "chercher sur le web" in out.lower()
    assert "indisponible" not in out.lower()


def test_web_unavailable_phrase_inactive():
    out = build_self_model("", object(), web_available=False)
    assert "indisponible" in out.lower()
```

(Si `build_self_model` n'est pas déjà importé dans ce fichier, ajouter `from bot.intelligence.self_model import build_self_model` en tête.)

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `python -m pytest tests/intelligence/test_self_model.py -v`
Expected: FAIL (`TypeError: build_self_model() got an unexpected keyword argument 'web_available'`).

- [ ] **Step 3 : Implémenter dans `self_model.py`**

Ajouter les constantes après `_SECTION_TITLE` :

```python
_WEB_ON = (
    "Je peux chercher sur le web de moi-même quand une vraie curiosité me prend, "
    "même sans qu'on me le demande."
)
_WEB_OFF = (
    "Je pourrais chercher sur le web, mais c'est indisponible pour l'instant."
)
```

Remplacer la signature et le corps de `build_self_model` :

```python
def build_self_model(static_text: str, config, *, web_available: bool = False) -> str:
    """Assemble le self-model : narratif statique + capacités dérivées de l'état réel.

    `static_text` = CAPABILITIES.md nettoyé (vérités de personnage stables).
    `config` = la config runtime ; chaque capacité à bascule est évaluée contre elle.
    `web_available` = dispo RÉELLE de la recherche web (Tavily configuré). Dérivée
    d'un flag plutôt que de `config` car la clé vit dans l'environnement, pas la config.

    Fonction pure : aucune I/O, insensible à l'ordre de montage. Un `config`
    malformé fait juste tomber une capacité en « inactive », jamais une exception.
    """
    lines = []
    for condition, on_text, off_text in _TOGGLE_CAPABILITIES:
        try:
            active = bool(condition(config))
        except Exception:
            active = False
        lines.append(f"- {on_text if active else off_text}")
    lines.append(f"- {_WEB_ON if web_available else _WEB_OFF}")
    derived = _SECTION_TITLE + "\n" + "\n".join(lines)

    static = (static_text or "").rstrip()
    return f"{static}\n\n{derived}\n" if static else f"{derived}\n"
```

- [ ] **Step 4 : Lancer, vérifier le succès**

Run: `python -m pytest tests/intelligence/test_self_model.py -v`
Expected: PASS (tous, dont les 2 nouveaux).

- [ ] **Step 5 : Câbler les deux appelants**

Dans `bot/discord/bot.py`, remplacer la ligne 219 :

```python
            _caps_text = build_self_model(_caps_static, self.config)
```

par :

```python
            _web_ok = bool(getattr(self, "web_search", None) and self.web_search.available)
            _caps_text = build_self_model(_caps_static, self.config, web_available=_web_ok)
```

Dans `bot/intelligence/persona.py`, remplacer (l.187) :

```python
            build_self_model(self._caps_static, self._config)
```

par :

```python
            build_self_model(
                self._caps_static, self._config,
                # Dispo web côté persona : la clé Tavily vit dans l'env (le service
                # WebSearchService n'est pas injecté ici). En prod la lib est
                # installée, donc la présence de la clé suffit comme approximation.
                web_available=bool(__import__("os").environ.get("TAVILY_API_KEY")),
            )
```

- [ ] **Step 6 : Retirer la négation web de CAPABILITIES.md**

Dans `bot/persona/CAPABILITIES.md`, supprimer entièrement la ligne :

```
- Je ne navigue pas sur le web librement — seulement via un outil précis quand on m'en donne un.
```

(La capacité réelle est désormais portée dynamiquement par le self-model.)

- [ ] **Step 7 : Re-vérifier la suite self-model + non-régression import**

Run: `python -m pytest tests/intelligence/test_self_model.py -v`
Expected: PASS.

- [ ] **Step 8 : Commit**

```bash
git add bot/intelligence/self_model.py bot/discord/bot.py bot/intelligence/persona.py bot/persona/CAPABILITIES.md tests/intelligence/test_self_model.py
git commit -m "feat(self-model): capacité web dérivée de la dispo réelle (Tavily) + retrait négation CAPABILITIES"
```

---

## Task 3 : AttentionContext.web_finding + rendu dans le prompt

**Files:**
- Modify: `bot/intelligence/attention_agent.py` (dataclass `AttentionContext`, ≈ l.79)
- Modify: `bot/intelligence/reasoning_agent.py` (`_format_context`, ≈ l.131)
- Test: `tests/intelligence/test_reasoning_web_finding.py` (créé)

**Interfaces:**
- Produces: `AttentionContext.web_finding: str | None` (défaut None). Quand non vide, `ReasoningAgent._format_context(ctx)` inclut un bloc commençant par « **Tu viens de chercher sur le web** ».

- [ ] **Step 1 : Test qui échoue**

Créer `tests/intelligence/test_reasoning_web_finding.py` :

```python
from types import SimpleNamespace

from bot.intelligence.reasoning_agent import ReasoningAgent


def _agent(tmp_path):
    # _format_context ne touche pas au LLM ; on construit un agent minimal en
    # pointant prompts_dir sur le dossier réel des prompts cognitifs.
    import bot.intelligence as _pkg
    from pathlib import Path
    prompts = Path(_pkg.__file__).parent / "persona" / "prompts"
    return ReasoningAgent(llm=None, fact_store=None, prompts_dir=prompts)


def _ctx(**kw):
    base = dict(
        preoccupation=None, emotional_drive=None, idle_seed=None,
        emotion_state={}, time_of_day="afternoon", active_desires=[],
        active_goals=[], recent_thoughts=[], recent_interactions=[],
        web_finding=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_web_finding_rendered(tmp_path):
    agent = _agent(tmp_path)
    out = agent._format_context(_ctx(web_finding="qui a gagné l'euro 2024 → l'Espagne"))
    assert "Tu viens de chercher sur le web" in out
    assert "l'Espagne" in out


def test_no_web_finding_no_block(tmp_path):
    agent = _agent(tmp_path)
    out = agent._format_context(_ctx())
    assert "Tu viens de chercher" not in out
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `python -m pytest tests/intelligence/test_reasoning_web_finding.py -v`
Expected: FAIL (`test_web_finding_rendered` : le bloc n'est pas rendu).

- [ ] **Step 3 : Implémenter le rendu**

Dans `bot/intelligence/reasoning_agent.py`, au tout début du corps de `_format_context` (juste après `lines: list[str] = []`, avant le bloc `preoccupation`), insérer :

```python
        if getattr(ctx, "web_finding", None):
            lines.append(
                "**Tu viens de chercher sur le web — voici ce que tu as trouvé :**\n"
                f"{ctx.web_finding}\n"
                "(Réagis à cette info : ce qu'elle t'apprend, ce que tu en penses. Tu peux "
                "la mémoriser ([ACT create_memory]), la partager si c'est pertinent, ou "
                "juste y réfléchir. Ne relance PAS de recherche maintenant.)"
            )
```

- [ ] **Step 4 : Ajouter le champ au dataclass**

Dans `bot/intelligence/attention_agent.py`, dans `AttentionContext`, à la suite des champs existants (après `receptivity_score: float = 0.5`), ajouter :

```python
    # Résultat d'une recherche web déclenchée par la cognition au tick courant
    # (2e passe de raisonnement). None hors de ce cas. Muté par CognitiveLoop, pas
    # calculé par build_context.
    web_finding: str | None = None
```

- [ ] **Step 5 : Lancer, vérifier le succès**

Run: `python -m pytest tests/intelligence/test_reasoning_web_finding.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6 : Commit**

```bash
git add bot/intelligence/attention_agent.py bot/intelligence/reasoning_agent.py tests/intelligence/test_reasoning_web_finding.py
git commit -m "feat(cognition): AttentionContext.web_finding + rendu prompt (2e passe recherche web)"
```

---

## Task 4 : CognitiveLoop — interception web_search + 2ᵉ passe + câblage + prompt

**Files:**
- Modify: `bot/intelligence/cognitive_loop.py` (`__init__` ≈ l.69 ; `_tick` ≈ l.356 ; nouvelle méthode `_maybe_web_search`)
- Modify: `bot/discord/bot.py:241` (construction `CognitiveLoop`)
- Modify: `bot/intelligence/persona/prompts/reasoning_system.md`
- Test: `tests/intelligence/test_cognitive_web_search.py` (créé)

**Interfaces:**
- Consumes: `AttentionContext.web_finding` (Task 3), `ReasoningResult` (`thought_text`, `thought_fact_id`, `decisions`), `MetaDecision(action, act_name, act_args)`, `WebSearchService.available` / `is_quota_exceeded()` / `search(query, platform)`.
- Produces: `CognitiveLoop._maybe_web_search(context, result) -> ReasoningResult`. Retourne le `result` initial si pas de tag / gardes KO ; sinon exécute la recherche, mute `context.web_finding`, et retourne le `ReasoningResult` de la 2ᵉ passe. Nouveaux attributs `__init__` : `web_search=None`, `web_search_cooldown_s: float = 2700.0`.

- [ ] **Step 1 : Test qui échoue**

Créer `tests/intelligence/test_cognitive_web_search.py` :

```python
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.intelligence.cognitive_loop import CognitiveLoop
from bot.intelligence.meta_agent import MetaDecision
from bot.intelligence.reasoning_agent import ReasoningResult


def _result(*, with_search, query="quelle météo demain"):
    decisions = [MetaDecision(action="THINK")]
    if with_search:
        decisions.append(MetaDecision(action="ACT", act_name="web_search",
                                      act_args={"query": query}))
    return ReasoningResult(thought_text="je me demande...", thought_fact_id=1,
                           decisions=decisions)


def _loop(reasoning, web_search, **kw):
    return CognitiveLoop(
        MagicMock(), reasoning, MagicMock(),
        web_search=web_search, **kw,
    )


def _web(available=True, quota=False, result="→ il fera beau"):
    w = MagicMock()
    w.available = available
    w.is_quota_exceeded = AsyncMock(return_value=quota)
    w.search = AsyncMock(return_value=result)
    return w


@pytest.mark.asyncio
async def test_no_tag_no_search():
    reasoning = MagicMock()
    reasoning.reason = AsyncMock()
    web = _web()
    loop = _loop(reasoning, web)
    ctx = SimpleNamespace(web_finding=None)
    out = await loop._maybe_web_search(ctx, _result(with_search=False))
    web.search.assert_not_called()
    reasoning.reason.assert_not_called()
    assert out.thought_text == "je me demande..."


@pytest.mark.asyncio
async def test_tag_triggers_search_and_second_pass():
    second = ReasoningResult(thought_text="ah donc il fera beau", thought_fact_id=2,
                             decisions=[MetaDecision(action="THINK")])
    reasoning = MagicMock()
    reasoning.reason = AsyncMock(return_value=second)
    web = _web()
    loop = _loop(reasoning, web)
    ctx = SimpleNamespace(web_finding=None)
    out = await loop._maybe_web_search(ctx, _result(with_search=True, query="météo demain"))
    web.search.assert_awaited_once()
    assert web.search.await_args.args[0] == "météo demain"
    assert ctx.web_finding is not None and "il fera beau" in ctx.web_finding
    reasoning.reason.assert_awaited_once()
    assert out is second


@pytest.mark.asyncio
async def test_cooldown_blocks_search():
    reasoning = MagicMock()
    reasoning.reason = AsyncMock()
    web = _web()
    loop = _loop(reasoning, web)
    loop._web_search_cooldown_ts = time.monotonic()  # vient de chercher
    ctx = SimpleNamespace(web_finding=None)
    await loop._maybe_web_search(ctx, _result(with_search=True))
    web.search.assert_not_called()


@pytest.mark.asyncio
async def test_quota_exceeded_blocks_search():
    reasoning = MagicMock()
    reasoning.reason = AsyncMock()
    web = _web(quota=True)
    loop = _loop(reasoning, web)
    ctx = SimpleNamespace(web_finding=None)
    await loop._maybe_web_search(ctx, _result(with_search=True))
    web.search.assert_not_called()


@pytest.mark.asyncio
async def test_unavailable_blocks_search():
    reasoning = MagicMock()
    reasoning.reason = AsyncMock()
    web = _web(available=False)
    loop = _loop(reasoning, web)
    ctx = SimpleNamespace(web_finding=None)
    await loop._maybe_web_search(ctx, _result(with_search=True))
    web.search.assert_not_called()


@pytest.mark.asyncio
async def test_web_search_none_is_noop():
    reasoning = MagicMock()
    reasoning.reason = AsyncMock()
    loop = _loop(reasoning, None)
    ctx = SimpleNamespace(web_finding=None)
    out = await loop._maybe_web_search(ctx, _result(with_search=True))
    reasoning.reason.assert_not_called()
    assert out.thought_fact_id == 1


@pytest.mark.asyncio
async def test_empty_query_is_noop():
    reasoning = MagicMock()
    reasoning.reason = AsyncMock()
    web = _web()
    loop = _loop(reasoning, web)
    ctx = SimpleNamespace(web_finding=None)
    await loop._maybe_web_search(ctx, _result(with_search=True, query=""))
    web.search.assert_not_called()
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `python -m pytest tests/intelligence/test_cognitive_web_search.py -v`
Expected: FAIL (`TypeError` sur `web_search=` inconnu, ou `AttributeError: _maybe_web_search`).

- [ ] **Step 3 : Étendre `__init__`**

Dans `bot/intelligence/cognitive_loop.py`, ajouter deux paramètres à la fin de la signature `__init__` (après `social_rhythm=None,`) :

```python
        social_rhythm=None,
        web_search=None,
        web_search_cooldown_s: float = 2700.0,
    ) -> None:
```

Et dans le corps, après `self._social_rhythm = social_rhythm` :

```python
        # Recherche web déclenchée par la cognition (chantier B self-model). None →
        # capacité absente. Cooldown anti-boucle + horodatage du dernier appel.
        self._web_search = web_search
        self._web_search_cooldown_s = web_search_cooldown_s
        self._web_search_cooldown_ts = 0.0
```

- [ ] **Step 4 : Ajouter la méthode `_maybe_web_search`**

Toujours dans `cognitive_loop.py`, ajouter cette méthode dans la classe (par ex. juste avant `_tick`) :

```python
    async def _maybe_web_search(self, context, result):
        """Si la pensée demande une recherche web et que les gardes passent :
        exécute la recherche, injecte le résultat dans le contexte, et relance UNE
        2e passe de raisonnement. Sinon renvoie le `result` initial inchangé.

        Ne fait jamais planter le tick : toute erreur → on garde la 1re pensée.
        Une seule recherche par tick (appelé une fois, sans boucle, depuis _tick).
        """
        if self._web_search is None:
            return result
        ws = next(
            (d for d in result.decisions
             if d.action == "ACT" and d.act_name == "web_search"),
            None,
        )
        if ws is None:
            return result
        query = (ws.act_args or {}).get("query")
        if not query or not isinstance(query, str):
            return result
        now = time.monotonic()
        if now - self._web_search_cooldown_ts < self._web_search_cooldown_s:
            logger.debug("web_search cognitif ignoré (cooldown)")
            return result
        if not self._web_search.available:
            return result
        try:
            if await self._web_search.is_quota_exceeded():
                logger.info("web_search cognitif ignoré (quota Tavily dépassé)")
                return result
        except Exception as e:  # noqa: BLE001
            logger.warning("is_quota_exceeded: {}", e)
            return result
        # Armer le cooldown AVANT l'appel : même un échec compte, pour ne pas
        # marteler Tavily en boucle sur une erreur répétée.
        self._web_search_cooldown_ts = now
        try:
            finding = await self._web_search.search(query, platform="discord")
        except Exception as e:  # noqa: BLE001
            logger.warning("web_search cognitif a échoué: {}", e)
            return result
        if self._feed:
            self._feed.publish({
                "type": "ACT", "name": "web_search",
                "content_snippet": query[:160],
            })
        context.web_finding = f"{query} → {finding}"
        logger.debug("web_search cognitif : 2e passe de raisonnement sur « {} »", query[:60])
        return await self._reasoning.reason(context)
```

- [ ] **Step 5 : Brancher dans `_tick`**

Dans `_tick`, juste après la ligne `result = await self._reasoning.reason(context)` (≈ l.356), ajouter :

```python
            result = await self._reasoning.reason(context)
            result = await self._maybe_web_search(context, result)
```

- [ ] **Step 6 : Lancer, vérifier le succès**

Run: `python -m pytest tests/intelligence/test_cognitive_web_search.py -v`
Expected: PASS (7 tests).

- [ ] **Step 7 : Câbler la construction du CognitiveLoop**

Dans `bot/discord/bot.py`, dans l'appel `CognitiveLoop(...)` (l.241-248), ajouter les deux arguments avant la parenthèse fermante :

```python
            self.cognitive_loop = CognitiveLoop(
                _attention, _reasoning, _dispatcher, self.emotion, self.cognitive_feed,
                speakable_channels=_chan_dir.speakable_ids(),
                conv_log=_conv_log,
                fact_store=_fact_store,
                progress_judge=_progress_judge,
                social_rhythm=self.social_rhythm,
                web_search=getattr(self, "web_search", None),
                web_search_cooldown_s=self.config.tavily.cognitive_cooldown_minutes * 60,
            )
```

- [ ] **Step 8 : Documenter l'action dans le prompt cognitif**

Dans `bot/intelligence/persona/prompts/reasoning_system.md`, dans la liste des actions `[ACT …]` (juste après la ligne `[ACT reflect_self …]`), ajouter :

```
- `[ACT web_search {"query": "<ce que tu veux savoir>"}]` — chercher sur le web quand une vraie curiosité te prend (une question qui te travaille, un truc que tu veux vérifier). Rare, pas à chaque pensée. Tu recevras le résultat juste après et pourras y réagir, le retenir ou le partager.
```

- [ ] **Step 9 : Commit**

```bash
git add bot/intelligence/cognitive_loop.py bot/discord/bot.py bot/intelligence/persona/prompts/reasoning_system.md tests/intelligence/test_cognitive_web_search.py
git commit -m "feat(cognition): recherche web émergente en pensée ([ACT web_search] + 2e passe)"
```

---

## Task 5 : Vérification d'intégration (non-régression)

**Files:** aucun (vérification seule).

- [ ] **Step 1 : Suite intelligence complète**

Run: `python -m pytest tests/intelligence/ -q`
Expected: PASS sur les nouveaux tests + aucune régression sur l'existant.

- [ ] **Step 2 : Import smoke des modules touchés**

Run: `python -c "import bot.intelligence.cognitive_loop, bot.intelligence.self_model, bot.intelligence.reasoning_agent, bot.intelligence.attention_agent, bot.config"`
Expected: aucun output, aucune exception.

- [ ] **Step 3 : Suite globale (constat baseline)**

Run: `python -m pytest -q`
Expected: seuls les échecs préexistants connus (3 échecs + 16 erreurs costs, non liés). Aucun NOUVEL échec.

- [ ] **Step 4 : Commit (si ajustements)**

Si des ajustements de non-régression ont été nécessaires :

```bash
git add -A
git commit -m "test: vérification d'intégration recherche web cognitive"
```

---

## Self-Review (rempli à la rédaction)

- **Couverture spec :** déclenchement émergent (Task 4, prompt + parsing existant) ✓ ; 2ᵉ passe immédiate (Task 4 `_maybe_web_search`) ✓ ; cooldown + quota (Task 1 + Task 4 gardes) ✓ ; tous les ticks cognitifs (appel dans `_tick`, pas de garde `is_idle`) ✓ ; self-model dérivé (Task 2) ✓ ; CAPABILITIES corrigé (Task 2 Step 6) ✓ ; une seule recherche/tick (appel unique, doc + couvert par construction) ✓.
- **Placeholders :** aucun — chaque step porte le code réel.
- **Cohérence des types :** `web_finding: str | None` (Task 3) consommé par `_format_context` (Task 3) et muté par `_maybe_web_search` (Task 4) ; `build_self_model(..., web_available=…)` (Task 2) appelé identiquement dans bot.py et persona.py ; `web_search.search(query, platform="discord")` cohérent avec `web_search.py:109`.
- **Note comportementale :** la 1ʳᵉ pensée (« je vais chercher ») est stockée comme THOUGHT par `reason()`, puis la 2ᵉ pensée (« j'ai appris ») l'est aussi — c'est voulu (trace du raisonnement). Seule la 2ᵉ entre dans `recent_thoughts`.
