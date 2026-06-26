# Phase 1 — Juge de progression + focus mortel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Casser la rumination cognitive en boucle : une pensée n'est publiée que si elle progresse ; un focus ressassé deux fois meurt, libérant l'esprit.

**Architecture:** Un nouveau composant `ThoughtProgressJudge` (LLM secondaire) classe chaque pensée fraîche en `PROGRESSE`/`RESSASSE`/`DIVAGUE` face au focus et aux pensées récentes. `CognitiveLoop._tick` l'utilise : sur `RESSASSE`, la pensée n'est ni publiée ni dispatchée, la pensée déjà stockée est archivée, et un compteur de ressassement incrémente ; à 2 ressassements le focus actif est archivé. Fallback gracieux sur l'ancien filtre lexical si le juge échoue.

**Tech Stack:** Python 3.11, asyncio, pytest, loguru, SQLite via `SQLiteFactStore`.

## Global Constraints

- Logging : `loguru` exclusivement — jamais `print()` ni `import logging`.
- Tout handler de haut niveau : try/except, log, continue — jamais de crash.
- Async : tout I/O est `await`. Le juge appelle `await llm.complete(...)`.
- Le LLM secondaire est DeepSeek (DeepSeek-only) : pas de JSON mode natif garanti → le juge parse un mot-clé, pas une sortie structurée.
- Conserver la baseline de tests : ~1010 verts (2 échecs préexistants connus : spam, cost). Ne pas en casser.
- Convention fact API : `user_id` brut. Ici on manipule `wally:self` (déjà préfixé, c'est un namespace interne — passer tel quel, comme le code existant `get_latest_by_source("wally:self", "focus")`).

---

### Task 1 : Composant `ThoughtProgressJudge`

**Files:**
- Create: `bot/intelligence/thought_progress.py`
- Create: `bot/persona/prompts/thought_progress_judge.md`
- Test: `tests/intelligence/test_thought_progress.py`

**Interfaces:**
- Produces:
  - `VERDICTS: frozenset[str]` = `{"PROGRESSE", "RESSASSE", "DIVAGUE"}`
  - `class ThoughtProgressJudge:`
    - `__init__(self, llm, prompts_dir: str | Path)` — charge le template `thought_progress_judge.md`.
    - `async def judge(self, thought_text: str, focus: str | None, recent_thoughts: list[str]) -> str` — renvoie un verdict ∈ `VERDICTS`. Défaut `"PROGRESSE"` si la réponse LLM ne contient aucun mot-clé reconnu (prudent : on ne supprime pas une pensée par erreur). Ne capture PAS les exceptions LLM — l'appelant gère le fallback.

- [ ] **Step 1 : Écrire le template du juge**

Créer `bot/persona/prompts/thought_progress_judge.md` :

```markdown
Tu es le juge interne du fil de pensée de Wally. On te donne une PENSÉE qu'il vient d'avoir, sa PRÉOCCUPATION du moment, et ses DERNIÈRES PENSÉES.

Ta tâche : dire si cette nouvelle pensée fait AVANCER sa vie mentale, ou si elle ressasse.

Réponds par UN SEUL mot, en majuscules :
- PROGRESSE : la pensée apporte un sujet neuf, une question neuve, une nuance réelle, OU une conclusion qui ferme le fil.
- RESSASSE : la pensée redit en substance la préoccupation ou une pensée récente, juste reformulée. Aucune avancée réelle.
- DIVAGUE : la pensée part sur un sujet sans rapport avec la préoccupation (c'est légitime, c'est du vagabondage).

Sois STRICT sur RESSASSE : reformuler la même conclusion (« c'est digéré », « je suis parti avec panache », « ça attendra ») pour la Nᵉ fois = RESSASSE, même si les mots changent.

Ne réponds QUE le mot. Rien d'autre.
```

- [ ] **Step 2 : Écrire le test qui échoue**

Créer `tests/intelligence/test_thought_progress.py` :

```python
import pytest
from pathlib import Path
from unittest.mock import AsyncMock
from bot.intelligence.thought_progress import ThoughtProgressJudge, VERDICTS

PROMPTS = Path("bot/persona/prompts")


def _judge(reply: str):
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=reply)
    return ThoughtProgressJudge(llm, PROMPTS), llm


@pytest.mark.asyncio
async def test_verdicts_set():
    assert VERDICTS == frozenset({"PROGRESSE", "RESSASSE", "DIVAGUE"})


@pytest.mark.asyncio
@pytest.mark.parametrize("reply,expected", [
    ("RESSASSE", "RESSASSE"),
    ("PROGRESSE", "PROGRESSE"),
    ("DIVAGUE", "DIVAGUE"),
    ("Verdict : RESSASSE, c'est la 4e fois.", "RESSASSE"),
    ("  progresse  ", "PROGRESSE"),
])
async def test_judge_parses_verdict(reply, expected):
    judge, _ = _judge(reply)
    out = await judge.judge("une pensée", "un focus", ["pensée A", "pensée B"])
    assert out == expected


@pytest.mark.asyncio
async def test_judge_defaults_to_progresse_on_garbage():
    judge, _ = _judge("je ne sais pas trop")
    out = await judge.judge("une pensée", None, [])
    assert out == "PROGRESSE"


@pytest.mark.asyncio
async def test_judge_passes_focus_and_thoughts_to_llm():
    judge, llm = _judge("RESSASSE")
    await judge.judge("PENSEE_X", "FOCUS_Y", ["ANCIENNE_Z"])
    # Le contenu utilisateur transmis au LLM contient bien les 3 éléments.
    user_msg = llm.complete.call_args.args[1][0]["content"]
    assert "PENSEE_X" in user_msg
    assert "FOCUS_Y" in user_msg
    assert "ANCIENNE_Z" in user_msg
```

- [ ] **Step 3 : Lancer le test → échec attendu**

Run: `python -m pytest tests/intelligence/test_thought_progress.py -q`
Expected: FAIL (`ModuleNotFoundError: bot.intelligence.thought_progress`).

- [ ] **Step 4 : Écrire l'implémentation minimale**

Créer `bot/intelligence/thought_progress.py` :

```python
from __future__ import annotations

from pathlib import Path

from loguru import logger

VERDICTS = frozenset({"PROGRESSE", "RESSASSE", "DIVAGUE"})


class ThoughtProgressJudge:
    """Classe une pensée fraîche face au focus et aux pensées récentes :
    PROGRESSE / RESSASSE / DIVAGUE. Sert l'anti-rumination sémantique."""

    def __init__(self, llm, prompts_dir: str | Path) -> None:
        self._llm = llm
        self._system = (Path(prompts_dir) / "thought_progress_judge.md").read_text(
            encoding="utf-8"
        )

    async def judge(
        self, thought_text: str, focus: str | None, recent_thoughts: list[str]
    ) -> str:
        recents = "\n".join(f"- {t[:300]}" for t in (recent_thoughts or [])[-6:])
        user_msg = (
            f"PRÉOCCUPATION DU MOMENT :\n{focus or '(aucune)'}\n\n"
            f"DERNIÈRES PENSÉES :\n{recents or '(aucune)'}\n\n"
            f"NOUVELLE PENSÉE À JUGER :\n{thought_text}"
        )
        reply = await self._llm.complete(
            self._system, [{"role": "user", "content": user_msg}]
        )
        upper = (reply or "").upper()
        for verdict in ("RESSASSE", "DIVAGUE", "PROGRESSE"):
            if verdict in upper:
                return verdict
        logger.debug("ThoughtProgressJudge : verdict illisible '{}' → PROGRESSE", reply)
        return "PROGRESSE"
```

Note : l'ordre de recherche met `PROGRESSE` en dernier — c'est le défaut prudent, on ne le retient que si aucun verdict « suppressif » n'est présent.

- [ ] **Step 5 : Lancer le test → succès attendu**

Run: `python -m pytest tests/intelligence/test_thought_progress.py -q`
Expected: PASS (tous les cas).

- [ ] **Step 6 : Commit**

```bash
git add bot/intelligence/thought_progress.py bot/persona/prompts/thought_progress_judge.md tests/intelligence/test_thought_progress.py
git commit -m "feat(cognition): ThoughtProgressJudge — juge de progression sémantique des pensées

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2 : Intégration dans `CognitiveLoop` (juge + focus mortel)

**Files:**
- Modify: `bot/intelligence/cognitive_loop.py` (`__init__` ~41-83 ; `_tick` bloc 191-209 ; ajout d'une méthode `_expire_focus`)
- Test: `tests/intelligence/core/test_cognitive_loop.py` (étendre `_make_loop` + nouveaux tests)

**Interfaces:**
- Consumes : `ThoughtProgressJudge.judge(thought_text, focus, recent_thoughts) -> str` (Task 1) ; `SQLiteFactStore.get_latest_by_source(user_id, source)`, `.set_status(fact_id, FactStatus)` ; `FactStatus.ARCHIVED`.
- Produces :
  - `CognitiveLoop.__init__` accepte deux nouveaux kwargs : `fact_store=None`, `progress_judge=None`.
  - Attributs : `self._facts`, `self._progress_judge`, `self._focus_rumination_count: int = 0`.
  - Constante module `RUMINATION_LIMIT = 2`.
  - `async def _expire_focus(self) -> None`.

- [ ] **Step 1 : Écrire les tests qui échouent**

Dans `tests/intelligence/core/test_cognitive_loop.py`, remplacer la fonction `_make_loop` par une version qui injecte un fact_store et un juge mockés, et expose le THINK publié :

```python
def _make_loop(verdict="PROGRESSE"):
    attention = MagicMock()
    reasoning = MagicMock()
    dispatcher = MagicMock()

    from bot.intelligence.attention_agent import AttentionContext
    attention.build_context = AsyncMock(return_value=AttentionContext(
        emotion_state={}, active_desires=[], active_goals=[],
        recent_thoughts=[], recent_interactions=[], time_of_day="evening",
        preoccupation="ma préoccupation",
    ))
    from bot.intelligence.reasoning_agent import ReasoningResult
    from bot.intelligence.meta_agent import MetaDecision
    reasoning.reason = AsyncMock(return_value=ReasoningResult(
        thought_text="pensée", thought_fact_id=7, decisions=[MetaDecision(action="THINK")]
    ))
    dispatcher.dispatch = AsyncMock()

    facts = MagicMock()
    facts.set_status = AsyncMock()
    focus_fact = MagicMock()
    focus_fact.id = 99
    facts.get_latest_by_source = AsyncMock(return_value=focus_fact)

    judge = MagicMock()
    judge.judge = AsyncMock(return_value=verdict)

    feed = MagicMock()
    feed.publish = MagicMock()

    loop = CognitiveLoop(
        attention, reasoning, dispatcher, feed=feed,
        fact_store=facts, progress_judge=judge,
    )
    return loop, attention, reasoning, dispatcher, facts, judge, feed
```

Puis ajouter ces tests :

```python
@pytest.mark.asyncio
async def test_ressasse_not_published_and_thought_archived():
    from bot.intelligence.memory.facts import FactStatus
    loop, _a, _r, _d, facts, _j, feed = _make_loop(verdict="RESSASSE")
    await loop._tick()
    # Pensée ressassée : aucun THINK publié sur le feed.
    think_published = any(c.args[0].get("type") == "THINK" for c in feed.publish.call_args_list)
    assert not think_published
    # La pensée déjà stockée (#7) est archivée.
    facts.set_status.assert_any_await(7, FactStatus.ARCHIVED)
    # Compteur incrémenté.
    assert loop._focus_rumination_count == 1


@pytest.mark.asyncio
async def test_two_ressasse_expire_focus():
    from bot.intelligence.memory.facts import FactStatus
    loop, _a, _r, _d, facts, _j, _f = _make_loop(verdict="RESSASSE")
    await loop._tick()
    await loop._tick()
    # Au 2e ressassement, le focus actif (#99) est archivé et le compteur remis à 0.
    facts.set_status.assert_any_await(99, FactStatus.ARCHIVED)
    assert loop._focus_rumination_count == 0


@pytest.mark.asyncio
async def test_progresse_published_and_counter_reset():
    loop, _a, _r, _d, facts, _j, feed = _make_loop(verdict="PROGRESSE")
    loop._focus_rumination_count = 1
    await loop._tick()
    think_published = any(c.args[0].get("type") == "THINK" for c in feed.publish.call_args_list)
    assert think_published
    assert "pensée" in loop._recent_thoughts
    assert loop._focus_rumination_count == 0


@pytest.mark.asyncio
async def test_judge_failure_falls_back_to_lexical():
    # Juge qui lève → on ne crashe pas ; la pensée est publiée (fallback : pas de
    # doublon lexical dans la fenêtre vide).
    loop, _a, _r, _d, _facts, judge, feed = _make_loop()
    judge.judge = AsyncMock(side_effect=RuntimeError("LLM down"))
    await loop._tick()
    think_published = any(c.args[0].get("type") == "THINK" for c in feed.publish.call_args_list)
    assert think_published
```

- [ ] **Step 2 : Lancer les tests → échec attendu**

Run: `python -m pytest tests/intelligence/core/test_cognitive_loop.py -q`
Expected: FAIL (`CognitiveLoop` n'accepte pas `fact_store`/`progress_judge` ; `_focus_rumination_count` inexistant).

- [ ] **Step 3 : Ajouter la constante et les paramètres au constructeur**

Dans `bot/intelligence/cognitive_loop.py`, après `REPLY_SPEAK_COOLDOWN = 600` (ligne ~21), ajouter :

```python
# Nombre de ressassements consécutifs d'un focus avant de le laisser mourir.
RUMINATION_LIMIT = 2
```

Dans la signature de `CognitiveLoop.__init__` (ligne ~42-51), ajouter deux kwargs après `conv_log=None,` :

```python
        conv_log=None,
        fact_store=None,
        progress_judge=None,
    ) -> None:
```

Dans le corps de `__init__`, après `self._conv_log = conv_log` (ligne ~59), ajouter :

```python
        self._facts = fact_store
        self._progress_judge = progress_judge
        # Anti-rumination sémantique : nombre de ressassements consécutifs du focus.
        self._focus_rumination_count = 0
```

- [ ] **Step 4 : Remplacer le bloc anti-rumination de `_tick`**

Dans `bot/intelligence/cognitive_loop.py`, remplacer les lignes 192-204 (le bloc `# Anti-rumination …` jusqu'au `return` inclus) par :

```python
            # Anti-rumination sémantique : le juge classe la pensée fraîche face au
            # focus et aux pensées récentes. RESSASSE → on ne publie pas, on archive
            # la pensée déjà stockée (sinon elle ré-amorce la boucle via recent_thoughts),
            # et on rapproche le focus de sa mort. Fallback lexical si le juge échoue.
            verdict = None
            if self._progress_judge is not None and result.thought_text:
                try:
                    verdict = await self._progress_judge.judge(
                        result.thought_text,
                        getattr(context, "preoccupation", None),
                        self._recent_thoughts,
                    )
                except Exception as e:
                    logger.warning("ThoughtProgressJudge a échoué, fallback lexical : {}", e)
                    verdict = None

            if verdict == "RESSASSE":
                from bot.intelligence.memory.facts import FactStatus
                if self._facts is not None and result.thought_fact_id:
                    try:
                        await self._facts.set_status(result.thought_fact_id, FactStatus.ARCHIVED)
                    except Exception as e:
                        logger.warning("Archivage pensée ressassée échoué : {}", e)
                self._focus_rumination_count += 1
                self._log_cog(
                    "think_skipped",
                    reason="ressassement (juge de progression)",
                    thought=(result.thought_text or "")[:200],
                )
                if self._focus_rumination_count >= RUMINATION_LIMIT:
                    await self._expire_focus()
                    self._focus_rumination_count = 0
                return

            # Fallback lexical : juge absent ou en échec → ancien filtre 0.92.
            if verdict is None and result.thought_text and any(
                _too_similar(result.thought_text, t) for t in self._recent_thoughts
            ):
                logger.debug("CognitiveLoop: pensée quasi identique (fenêtre récente), repos")
                self._log_cog(
                    "think_skipped",
                    reason="pensée quasi identique à une pensée récente",
                    thought=(result.thought_text or "")[:200],
                )
                return

            # PROGRESSE / DIVAGUE → la pensée vit ; le focus repart de zéro.
            self._focus_rumination_count = 0
```

(Les lignes suivantes — `self._recent_thoughts.append(...)`, publication THINK, etc. — restent inchangées.)

- [ ] **Step 5 : Ajouter la méthode `_expire_focus`**

Dans `bot/intelligence/cognitive_loop.py`, juste avant `async def _tick(self)` (ligne ~159), insérer :

```python
    async def _expire_focus(self) -> None:
        """Archive le focus actif ressassé → `preoccupation` redevient None au
        prochain tick, et l'amorce de nouveauté reprend la main."""
        if self._facts is None:
            return
        try:
            focus = await self._facts.get_latest_by_source("wally:self", "focus")
            fid = getattr(focus, "id", None) if focus else None
            if fid is not None:
                from bot.intelligence.memory.facts import FactStatus
                await self._facts.set_status(fid, FactStatus.ARCHIVED)
                logger.info("CognitiveLoop : focus ressassé expiré (#{})", fid)
        except Exception as e:
            logger.warning("_expire_focus a échoué : {}", e)
```

- [ ] **Step 6 : Lancer les tests → succès attendu**

Run: `python -m pytest tests/intelligence/core/test_cognitive_loop.py -q`
Expected: PASS (anciens tests + 4 nouveaux).

- [ ] **Step 7 : Commit**

```bash
git add bot/intelligence/cognitive_loop.py tests/intelligence/core/test_cognitive_loop.py
git commit -m "feat(cognition): focus mortel — RESSASSE archive la pensée et tue le focus à 2

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3 : Câblage dans le bot (construction + injection du juge)

**Files:**
- Modify: `bot/discord/bot.py` (~179-192 : construction de `ReasoningAgent`/`CognitiveLoop`)

**Interfaces:**
- Consumes : `ThoughtProgressJudge(llm, prompts_dir)` (Task 1) ; `CognitiveLoop(..., fact_store=, progress_judge=)` (Task 2).

- [ ] **Step 1 : Construire le juge et l'injecter**

Dans `bot/discord/bot.py`, juste avant `self.cognitive_loop = CognitiveLoop(` (ligne ~188), ajouter :

```python
            from bot.intelligence.thought_progress import ThoughtProgressJudge
            _progress_judge = ThoughtProgressJudge(self.llm_secondary, _prompts_dir)
```

Puis modifier l'appel `CognitiveLoop(...)` (lignes ~188-192) pour ajouter les deux kwargs :

```python
            self.cognitive_loop = CognitiveLoop(
                _attention, _reasoning, _dispatcher, self.emotion, self.cognitive_feed,
                speakable_channels=_chan_dir.speakable_ids(),
                conv_log=_conv_log,
                fact_store=_fact_store,
                progress_judge=_progress_judge,
            )
```

- [ ] **Step 2 : Vérifier que rien n'est cassé à l'import/au boot**

Run: `python -c "import bot.discord.bot"`
Expected: aucun import error.

- [ ] **Step 3 : Lancer la suite cognition complète (non-régression)**

Run: `python -m pytest tests/intelligence/ -q`
Expected: PASS (hors échecs préexistants spam/cost s'ils apparaissent ici — vérifier qu'ils sont identiques à la baseline).

- [ ] **Step 4 : Commit**

```bash
git add bot/discord/bot.py
git commit -m "feat(cognition): câble ThoughtProgressJudge dans la boucle cognitive Discord

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Vérification finale de la phase

- [ ] `python -m pytest tests/intelligence/ -q` vert (hors baseline préexistante).
- [ ] `python -m pytest -q` : total cohérent avec la baseline ~1010 verts.
- [ ] Revue manuelle : `git diff main --stat` ≤ 5 fichiers touchés.

**Déploiement** (après validation) : backend non bind-mount → rebuild image. Vérifier ensuite en base que la fréquence des THOUGHT publiés chute et que les focus s'archivent (`status='archived'`, `source='focus'`).

## Notes pour les phases suivantes (hors périmètre Phase 1)

- Phase 5 (nettoyage dette) : prochaine, repart sur une base saine.
- L'archivage de la pensée ressassée réduit l'accumulation, mais le `ReasoningAgent` stocke toujours la pensée AVANT le juge — acceptable (THOUGHT décaient), à revisiter si besoin.
