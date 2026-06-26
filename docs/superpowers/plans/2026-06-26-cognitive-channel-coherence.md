# Cohérence cognitive des canaux — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Empêcher Wally de croiser les canaux (sujet d'un salon qui ressort dans un autre, DM qui fuite en public), le faire toujours répondre en DM, et rendre ses demandes de self-fix visibles dans le fil de conversation.

**Architecture:** Trois leviers indépendants. (1) Le **ResponseGate** reçoit `is_dm` (court-circuit RESPOND en DM) et le fil récent du canal (décision sur contexte, pas phrase-par-phrase). (2) La **boucle cognitive** étiquette chaque interaction par canal (nom + flag DM) et le `reasoning_agent` rend les interactions **groupées par canal** avec consigne anti-fuite. (3) Le flux **self-fix** réinjecte sa demande/issue dans le sliding context window du DM créateur.

**Tech Stack:** Python 3.12, asyncio, pytest (`pytest-asyncio`), loguru. Pas de nouvelle dépendance.

## Global Constraints

- Logging : `loguru` uniquement, jamais `print` ni `import logging`.
- Tout I/O async ; ne jamais bloquer l'event loop.
- Baseline tests à préserver : ~1010 verts ; échecs préexistants à ignorer (`tests/test_web_search.py::test_complete_with_tools_logs_cost`, `tests/test_dashboard_costs.py`).
- Décisions validées : DM = option B (étiqueté privé, jamais croisé public↔DM, rien de réellement confidentiel) ; gate en DM = **toujours RESPOND** sauf `is_ignored`.
- Style : suivre les patterns existants (mocks `AsyncMock`/`MagicMock` comme `tests/intelligence/core/test_gate.py`).
- Exécution **par phases** (directive projet, max 5 fichiers/phase). Ordre : Phase 1 (Gate) → Phase 2 (Cognition) → Phase 3 (Self-fix). Attendre validation entre phases.
- Vérification de fin de phase : `python3 -m pytest -q` vert (hors préexistants).

---

## PHASE 1 — ResponseGate : DM + fil de conversation

Fichiers : `bot/intelligence/gate.py`, `bot/discord/handlers.py`, `bot/intelligence/persona/prompts/gate_system.md`, `tests/intelligence/core/test_gate.py`.

### Task 1.1 : Gate — toujours répondre en DM

**Files:**
- Modify: `bot/intelligence/gate.py:70-86` (signature `decide` + court-circuit)
- Test: `tests/intelligence/core/test_gate.py`

**Interfaces:**
- Produces: `ResponseGate.decide(..., is_dm: bool = False)` — si `is_dm and not is_ignored`, retourne `GateDecision(decision="RESPOND", reason="DM 1:1 — réponse systématique")` **sans appel LLM**.

- [ ] **Step 1: Write the failing tests**

Ajouter à `tests/intelligence/core/test_gate.py` :

```python
@pytest.mark.asyncio
async def test_decide_dm_always_responds_without_llm():
    """En DM (is_dm=True), gate retourne RESPOND sans appeler le LLM."""
    gate = make_gate({"decision": "IGNORE"})  # le LLM dirait IGNORE...
    result = await gate.decide("ca", "discord:123", EMOTION_STATE, [], [], is_dm=True)
    assert result.decision == "RESPOND"           # ...mais le DM force RESPOND
    gate._llm.complete_structured.assert_not_called()


@pytest.mark.asyncio
async def test_decide_dm_respects_ignored_user():
    """is_ignored a priorité sur is_dm : un utilisateur banni reste ignoré."""
    gate = make_gate()
    result = await gate.decide("ca", "discord:123", EMOTION_STATE, [], [],
                               is_dm=True, is_ignored=True)
    assert result.decision == "IGNORE"
    gate._llm.complete_structured.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/intelligence/core/test_gate.py::test_decide_dm_always_responds_without_llm -v`
Expected: FAIL (`decide()` got an unexpected keyword argument `is_dm`).

- [ ] **Step 3: Implement**

Dans `bot/intelligence/gate.py`, ajouter le paramètre à la signature de `decide` (après `is_triggered`) :

```python
        is_triggered: bool = False,
        is_dm: bool = False,
```

Puis, juste après le bloc `if is_ignored:` (ligne ~86) :

```python
        if is_ignored:
            return GateDecision(decision="IGNORE", reason="utilisateur marqué comme ignoré")
        # DM 1:1 : l'utilisateur s'adresse forcément à Wally. Répondre est la règle ;
        # le gate (conçu pour filtrer le bruit d'un salon) n'a pas lieu d'être ici.
        if is_dm:
            return GateDecision(decision="RESPOND", reason="DM 1:1 — réponse systématique")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/intelligence/core/test_gate.py -v`
Expected: PASS (tous, anciens inclus).

- [ ] **Step 5: Commit**

```bash
git add bot/intelligence/gate.py tests/intelligence/core/test_gate.py
git commit -m "fix(gate): toujours répondre en DM (court-circuit sans LLM)"
```

### Task 1.2 : Gate — juger sur le fil récent

**Files:**
- Modify: `bot/intelligence/gate.py:70-122` (param `recent_messages` + rendu)
- Modify: `bot/intelligence/persona/prompts/gate_system.md` (mention du fil)
- Test: `tests/intelligence/core/test_gate.py`

**Interfaces:**
- Consumes: rien de nouveau.
- Produces: `ResponseGate.decide(..., recent_messages: list[dict] | None = None)` où chaque dict = `{"author": str, "content": str}`. Les messages sont insérés dans le prompt utilisateur sous un bloc « Fil récent du canal ».

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_decide_includes_recent_thread_in_prompt():
    """Le fil récent passé à decide() apparaît dans le message envoyé au LLM."""
    gate = make_gate({"decision": "RESPOND"})
    thread = [
        {"author": "KingsRequin", "content": "c'est nul ta blague"},
        {"author": "Wally", "content": "assume, c'est le degré zéro"},
    ]
    await gate.decide("c'est pas déjà le cas ?", "discord:123", EMOTION_STATE, [], [],
                      recent_messages=thread)
    sent = gate._llm.complete_structured.call_args.kwargs["messages"][0]["content"]
    assert "KingsRequin: c'est nul ta blague" in sent
    assert "Wally: assume" in sent
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/intelligence/core/test_gate.py::test_decide_includes_recent_thread_in_prompt -v`
Expected: FAIL (`unexpected keyword argument 'recent_messages'`).

- [ ] **Step 3: Implement**

Signature `decide` — ajouter après `emoji_usage`:

```python
        emoji_usage: list[str] | None = None,
        recent_messages: list[dict] | None = None,
```

Dans la construction de `context_parts`, juste après le `trigger_line` (avant `Émotion dominante`), insérer le fil :

```python
        if recent_messages:
            thread = "\n".join(
                f"  {m.get('author', '?')}: {(m.get('content') or '')[:200]}"
                for m in recent_messages[-5:]
            )
            context_parts.append(
                "Fil récent du canal (pour juger si une réponse a du sens dans le contexte) :\n"
                + thread
            )
```

Dans `bot/intelligence/persona/prompts/gate_system.md`, ajouter une ligne de cadrage (près des critères de décision) :

```markdown
- Tu reçois parfois le **fil récent du canal**. Juge la pertinence DANS ce fil :
  une courte relance ("c'est pas déjà le cas ?", "ah bon ?") qui s'inscrit dans
  une conversation vivante mérite une réponse — ne la classe pas "inutile" hors contexte.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/intelligence/core/test_gate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/intelligence/gate.py bot/intelligence/persona/prompts/gate_system.md tests/intelligence/core/test_gate.py
git commit -m "feat(gate): juger sur le fil récent du canal (plus phrase-par-phrase)"
```

### Task 1.3 : Brancher `is_dm` + fil dans le handler Discord

**Files:**
- Modify: `bot/discord/handlers.py:964-975` (appel `gate.decide`)
- Test: `tests/test_discord_handlers.py` (smoke d'intégration léger)

**Interfaces:**
- Consumes: `decide(is_dm=..., recent_messages=...)` (Tasks 1.1, 1.2), `bot.memory.get_context(channel_id) -> list[dict]`.

- [ ] **Step 1: Implement the wiring**

Dans `bot/discord/handlers.py`, à l'appel `_gd = await gate.decide(`, ajouter deux arguments. Récupérer le fil juste avant l'appel :

```python
            _thread = []
            try:
                _thread = bot.memory.get_context(str(message.channel.id))[-5:]
            except Exception:
                _thread = []
            _gd = await gate.decide(
                message_content=_resolve_mentions(message, message.content or ""),
                author_user_id=user_id,
                emotion_state=bot.emotion.get_state(),
                relationship_facts=_rel,
                active_desires=_desires,
                is_mentioned=mentioned,
                is_triggered=True,
                is_dm=message.guild is None,
                wally_last_message=_last,
                available_emojis=_guild_emojis,
                emoji_usage=_emoji_usage,
                recent_messages=_thread,
            )
```

- [ ] **Step 2: Verify the full suite still passes**

Run: `python3 -m pytest tests/test_discord_handlers.py -q`
Expected: PASS (pas de régression ; `decide` accepte les nouveaux kwargs avec défauts).

- [ ] **Step 3: Commit**

```bash
git add bot/discord/handlers.py
git commit -m "feat(gate): handler passe is_dm + fil récent au ResponseGate"
```

### Fin de Phase 1 — vérification

- [ ] Run: `python3 -m pytest -q`
- [ ] Expected: vert hors préexistants. **STOP — attendre validation avant Phase 2.**

---

## PHASE 2 — Cognition : cloisonnement par canal, noms, DM privé

Fichiers : `bot/intelligence/channels.py`, `bot/intelligence/cognitive_loop.py`, `bot/intelligence/reasoning_agent.py`, `bot/discord/bot.py`, `bot/discord/handlers.py`. (+ prompt `reasoning_system.md`, + tests.)

> Note : 5 fichiers de code + 1 prompt. Si le reviewer préfère, le prompt `reasoning_system.md` (Task 2.5) peut être commité avec Task 2.4.

### Task 2.1 : `ChannelDirectory.name_map()`

**Files:**
- Modify: `bot/intelligence/channels.py` (nouvelle méthode)
- Test: `tests/intelligence/test_channels_name_map.py` (créer)

**Interfaces:**
- Produces: `ChannelDirectory.name_map() -> dict[str, str]` — `{channel_id: name}` pour TOUS les canaux (texte + forum).

- [ ] **Step 1: Write the failing test**

Créer `tests/intelligence/test_channels_name_map.py` :

```python
from bot.intelligence.channels import ChannelDirectory, ChannelInfo


def test_name_map_returns_id_to_name():
    d = ChannelDirectory([
        ChannelInfo(id="111", name="chambre-de-wally", type="text", purpose="sa chambre"),
        ChannelInfo(id="222", name="general", type="text", purpose="discussion"),
    ])
    assert d.name_map() == {"111": "chambre-de-wally", "222": "general"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/intelligence/test_channels_name_map.py -v`
Expected: FAIL (`'ChannelDirectory' object has no attribute 'name_map'`).

- [ ] **Step 3: Implement**

Dans `bot/intelligence/channels.py`, après `speakable_ids` :

```python
    def name_map(self) -> dict[str, str]:
        """Mapping id → nom lisible, tous types de canaux confondus."""
        return {c.id: c.name for c in self._channels}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/intelligence/test_channels_name_map.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/intelligence/channels.py tests/intelligence/test_channels_name_map.py
git commit -m "feat(channels): name_map() id→nom pour la cognition"
```

### Task 2.2 : `notify_activity` étiquette les DM

**Files:**
- Modify: `bot/intelligence/cognitive_loop.py:84-104` (param `is_dm`)
- Test: `tests/intelligence/test_cognitive_dm_flag.py` (créer)

**Interfaces:**
- Produces: `CognitiveLoop.notify_activity(channel_id, author, content, message_id=None, is_dm=False)` ; chaque entrée de `_recent_interactions` porte `"is_dm": bool`.

- [ ] **Step 1: Write the failing test**

Créer `tests/intelligence/test_cognitive_dm_flag.py` :

```python
from unittest.mock import MagicMock
from bot.intelligence.cognitive_loop import CognitiveLoop


def make_loop():
    return CognitiveLoop(MagicMock(), MagicMock(), MagicMock())


def test_notify_activity_marks_dm():
    loop = make_loop()
    loop.notify_activity(999, "KingsRequin", "coucou en privé", is_dm=True)
    assert loop._recent_interactions[-1]["is_dm"] is True


def test_notify_activity_public_default_not_dm():
    loop = make_loop()
    loop.notify_activity(111, "KingsRequin", "coucou public")
    assert loop._recent_interactions[-1]["is_dm"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/intelligence/test_cognitive_dm_flag.py -v`
Expected: FAIL (`unexpected keyword argument 'is_dm'`).

- [ ] **Step 3: Implement**

Dans `bot/intelligence/cognitive_loop.py`, signature `notify_activity` :

```python
    def notify_activity(
        self, channel_id: int, author: str, content: str,
        message_id: str | None = None, is_dm: bool = False,
    ) -> None:
```

Et dans le dict appended, ajouter la clé :

```python
        self._recent_interactions.append({
            "channel": str(channel_id),
            "author": author,
            "content": content[:500],
            "message_id": message_id,
            "is_dm": is_dm,
            "ts": self._last_activity_ts,
        })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/intelligence/test_cognitive_dm_flag.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/intelligence/cognitive_loop.py tests/intelligence/test_cognitive_dm_flag.py
git commit -m "feat(cognition): notify_activity étiquette les interactions DM"
```

### Task 2.3 : `handlers` passe `is_dm` à `notify_activity`

**Files:**
- Modify: `bot/discord/handlers.py:866-871`

**Interfaces:**
- Consumes: `notify_activity(is_dm=...)` (Task 2.2).

- [ ] **Step 1: Implement**

Dans `bot/discord/handlers.py`, à l'appel `bot.cognitive_loop.notify_activity(` :

```python
            bot.cognitive_loop.notify_activity(
                channel_id=message.channel.id,
                author=str(message.author.display_name),
                content=_resolve_mentions(message, message.content or ""),
                message_id=str(message.id),
                is_dm=message.guild is None,
            )
```

- [ ] **Step 2: Verify no regression**

Run: `python3 -m pytest tests/test_discord_handlers.py -q`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add bot/discord/handlers.py
git commit -m "feat(cognition): handler marque les DM dans la perception cognitive"
```

### Task 2.4 : `reasoning_agent` — rendu groupé par canal + noms + DM privé

**Files:**
- Modify: `bot/intelligence/reasoning_agent.py:66-71` (constructeur) et `:192-205` (rendu interactions)
- Test: `tests/intelligence/test_reasoning_channel_isolation.py` (créer)

**Interfaces:**
- Consumes: `channel_names: dict[str,str]` (Task 2.1 via wiring Task 2.6), `is_dm` sur chaque interaction (Task 2.2).
- Produces: `ReasoningAgent(__init__ ..., channel_names: dict[str, str] | None = None)`. Le rendu groupe les interactions par canal, titre chaque bloc `### #<nom>` (public) ou `### DM privé avec <auteur>` (DM), et ajoute une consigne anti-fuite.

- [ ] **Step 1: Write the failing test**

Créer `tests/intelligence/test_reasoning_channel_isolation.py` :

```python
from bot.intelligence.attention_agent import AttentionContext
from bot.intelligence.reasoning_agent import ReasoningAgent


def make_agent():
    return ReasoningAgent(
        llm=None, fact_store=None,
        prompts_dir="bot/intelligence/persona/prompts",
        channel_names={"111": "general", "222": "chambre-de-wally"},
    )


def base_ctx(interactions):
    return AttentionContext(
        emotion_state={"joy": 0.5}, active_desires=[], active_goals=[],
        recent_thoughts=[], recent_interactions=interactions, time_of_day="evening",
    )


def test_render_groups_by_channel_with_names():
    ctx = base_ctx([
        {"channel": "111", "author": "KingsRequin", "content": "salut le général", "is_dm": False},
        {"channel": "222", "author": "KingsRequin", "content": "salut la chambre", "is_dm": False},
    ])
    out = make_agent()._format_context(ctx)
    assert "#general" in out and "#chambre-de-wally" in out
    # Chaque message est sous le bon bloc, pas mélangé
    gen = out.index("#general"); cha = out.index("#chambre-de-wally")
    assert "salut le général" in out and "salut la chambre" in out


def test_render_marks_dm_block_private():
    ctx = base_ctx([
        {"channel": "999", "author": "KingsRequin", "content": "un truc privé", "is_dm": True},
    ])
    out = make_agent()._format_context(ctx)
    assert "DM privé avec KingsRequin" in out
    assert "un truc privé" in out


def test_render_includes_anti_leak_instruction():
    ctx = base_ctx([
        {"channel": "111", "author": "X", "content": "a", "is_dm": False},
    ])
    out = make_agent()._format_context(ctx)
    assert "conversation" in out.lower() and "jamais" in out.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/intelligence/test_reasoning_channel_isolation.py -v`
Expected: FAIL (`__init__` n'accepte pas `channel_names`).

- [ ] **Step 3: Implement**

Constructeur `ReasoningAgent.__init__` — ajouter le param et le stocker :

```python
    def __init__(self, llm, fact_store, prompts_dir: str | Path, channels_text: str = "", capabilities_text: str = "", channel_names: dict[str, str] | None = None) -> None:
        self._llm = llm
        self._facts = fact_store
        self._system = render_identity((Path(prompts_dir) / "reasoning_system.md").read_text(encoding="utf-8"))
        self._channels_text = channels_text
        self._capabilities_text = capabilities_text
        self._channel_names = channel_names or {}
```

Remplacer le bloc `if ctx.recent_interactions:` (lignes ~192-205) par un rendu groupé :

```python
        if ctx.recent_interactions:
            recent = ctx.recent_interactions[-10:]
            last = recent[-1]
            last_name = self._channel_names.get(last.get("channel", ""), last.get("channel", "?"))
            last_label = (
                f"DM privé avec {last.get('author', '?')}" if last.get("is_dm")
                else f"#{last_name}"
            )
            lines.append(
                f"**Canal où tu peux parler maintenant :** {last_label} "
                f"(id {last.get('channel', '?')} — n'émets [SPEAK <id> ...] qu'avec cet id exact)"
            )
            lines.append(
                "**Conversations récentes — chaque bloc est une conversation SÉPARÉE.** "
                "Ne ramène JAMAIS dans un canal un sujet entendu dans un autre. "
                "Un bloc « DM privé » ne doit JAMAIS être évoqué ailleurs, et inversement."
            )
            # Regroupe en préservant l'ordre d'apparition des canaux.
            groups: dict[str, list[dict]] = {}
            order: list[str] = []
            for msg in recent:
                ch = msg.get("channel", "?")
                if ch not in groups:
                    groups[ch] = []
                    order.append(ch)
                groups[ch].append(msg)
            for ch in order:
                msgs = groups[ch]
                if msgs[0].get("is_dm"):
                    title = f"### DM privé avec {msgs[0].get('author', '?')}"
                else:
                    title = f"### #{self._channel_names.get(ch, ch)} (id {ch})"
                lines.append(title)
                for msg in msgs:
                    mid = msg.get("message_id")
                    mid_part = f"(msg {mid}) " if mid else ""
                    lines.append(
                        f"  {mid_part}{msg.get('author', '?')}: "
                        f"{_one_line(msg.get('content', ''), 220)}"
                    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/intelligence/test_reasoning_channel_isolation.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/intelligence/reasoning_agent.py tests/intelligence/test_reasoning_channel_isolation.py
git commit -m "feat(cognition): contexte cognitif cloisonné par canal (noms + DM privé)"
```

### Task 2.5 : Consigne durable dans `reasoning_system.md`

**Files:**
- Modify: `bot/intelligence/persona/prompts/reasoning_system.md`

- [ ] **Step 1: Add the directive**

Ajouter dans `reasoning_system.md` (section comportement / règles), verbatim :

```markdown
## Étanchéité des canaux
Chaque salon et chaque DM sont des conversations DISTINCTES et cloisonnées.
- Ne ressors jamais dans un salon un sujet entendu dans un autre salon.
- Ce qui se dit en DM reste en DM : ne l'évoque jamais dans un salon public.
- Ce qui se dit en public ne s'invite pas en DM sans raison.
Quand tu choisis un canal pour [SPEAK], ne parle QUE de ce qui appartient à ce canal.
```

- [ ] **Step 2: Sanity check (le prompt se charge sans erreur)**

Run: `python3 -c "from bot.intelligence.reasoning_agent import ReasoningAgent; ReasoningAgent(None, None, 'bot/intelligence/persona/prompts'); print('ok')"`
Expected: affiche `ok`.

- [ ] **Step 3: Commit**

```bash
git add bot/intelligence/persona/prompts/reasoning_system.md
git commit -m "feat(cognition): consigne durable d'étanchéité des canaux"
```

### Task 2.6 : Wiring — passer `name_map()` au ReasoningAgent

**Files:**
- Modify: `bot/discord/bot.py:179-182`

**Interfaces:**
- Consumes: `ChannelDirectory.name_map()` (Task 2.1), `ReasoningAgent(channel_names=...)` (Task 2.4).

- [ ] **Step 1: Implement**

Dans `bot/discord/bot.py`, à la construction de `_reasoning` :

```python
            _reasoning = ReasoningAgent(
                _reasoning_llm, _fact_store, _prompts_dir,
                channels_text=_chan_dir.render(), capabilities_text=_caps_text,
                channel_names=_chan_dir.name_map(),
            )
```

- [ ] **Step 2: Verify import/build path**

Run: `python3 -c "import bot.discord.bot; print('import ok')"`
Expected: `import ok`.

- [ ] **Step 3: Commit**

```bash
git add bot/discord/bot.py
git commit -m "feat(cognition): wiring name_map vers ReasoningAgent"
```

### Fin de Phase 2 — vérification

- [ ] Run: `python3 -m pytest -q`
- [ ] Expected: vert hors préexistants. **STOP — attendre validation avant Phase 3.**

---

## PHASE 3 — Self-fix visible dans l'historique conversationnel

Fichiers : `bot/intelligence/self_fix.py`, `tests/test_self_fix_history.py` (créer).

### Task 3.1 : Réinjecter la demande/issue self-fix dans le DM créateur

**Files:**
- Modify: `bot/intelligence/self_fix.py:8` (import `bot_name`), `:83-123` (`_run_upgrade`), nouvelle méthode `_remember_in_dm`
- Test: `tests/test_self_fix_history.py` (créer)

**Interfaces:**
- Consumes: `bot.memory.append_message(channel_id: str, author: str, content: str, platform="discord")`.
- Produces: `SelfFix._remember_in_dm(dm, text: str) -> None` — best-effort, ne propage jamais.

- [ ] **Step 1: Write the failing test**

Créer `tests/test_self_fix_history.py` :

```python
from types import SimpleNamespace
from unittest.mock import MagicMock
from bot.intelligence.self_fix import SelfFix


def test_remember_in_dm_appends_to_context_window():
    memory = MagicMock()
    bot = SimpleNamespace(memory=memory)
    sf = SelfFix(bridge=MagicMock(), bot=bot)
    dm = SimpleNamespace(id=4242)

    sf._remember_in_dm(dm, "[demande de self-fix] corriger le bug X")

    memory.append_message.assert_called_once()
    args, kwargs = memory.append_message.call_args
    assert args[0] == "4242"                              # channel_id = str(dm.id)
    assert "corriger le bug X" in args[2]                 # contenu injecté


def test_remember_in_dm_never_raises_without_memory():
    bot = SimpleNamespace(memory=None)
    sf = SelfFix(bridge=MagicMock(), bot=bot)
    sf._remember_in_dm(SimpleNamespace(id=1), "x")        # ne lève pas
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_self_fix_history.py -v`
Expected: FAIL (`'SelfFix' object has no attribute '_remember_in_dm'`).

- [ ] **Step 3: Implement**

Dans `bot/intelligence/self_fix.py`, étendre l'import (ligne 8) :

```python
from bot.intelligence.identity import render_identity, creator_name, bot_name
```

Ajouter la méthode (près de `_record_outcome`) :

```python
    def _remember_in_dm(self, dm, text: str) -> None:
        """Injecte un message du flux self-fix dans le sliding context window du
        DM créateur, pour que Wally en garde la trace conversationnelle et puisse
        en reparler. Best-effort : ne propage jamais.
        """
        try:
            memory = getattr(self._bot, "memory", None)
            if memory is None:
                return
            memory.append_message(str(dm.id), bot_name(), text, platform="discord")
        except Exception:  # noqa: BLE001 — la trace ne doit jamais casser le flux
            logger.exception("self-fix: impossible d'inscrire le message dans l'historique DM")
```

Dans `_run_upgrade`, après l'envoi de la demande (`msg = await dm.send(...)`, ligne ~96) :

```python
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")
        self._remember_in_dm(dm, f"[demande de self-fix] {goal}")
```

Et après acceptation (juste après `await dm.send("👍 C'est parti...")`, ligne ~119) :

```python
        self._remember_in_dm(dm, f"[self-fix accepté] {goal}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_self_fix_history.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/intelligence/self_fix.py tests/test_self_fix_history.py
git commit -m "feat(self-fix): demande/issue visibles dans l'historique du DM créateur"
```

### Fin de Phase 3 — vérification finale

- [ ] Run: `python3 -m pytest -q`
- [ ] Expected: vert hors préexistants (~1010+ verts, +9 nouveaux tests).
- [ ] Déploiement : rebuild image Docker (backend pas bind-monté). Hors périmètre de ce plan ; le créateur déclenche.

---

## Couverture spec → tâches

| Correction spec | Tâche(s) |
|---|---|
| 1. Cloisonnement par canal | 2.4, 2.5 |
| 2. Noms de salons | 2.1, 2.4, 2.6 |
| 3. DM privé non-croisé | 2.2, 2.3, 2.4, 2.5 |
| 4. Gate toujours répondre en DM | 1.1, 1.3 |
| 5. Gate juge sur le fil | 1.2, 1.3 |
| 6. Self-fix dans l'historique | 3.1 |
