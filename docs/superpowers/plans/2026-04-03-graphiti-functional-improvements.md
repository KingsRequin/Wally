# Graphiti — Améliorations fonctionnelles — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corriger `get_affinity()` (Cypher direct), ajouter la community detection nocturne, enrichir le graph context dans le prompt, et injecter les relations sociales connues dans le system prompt.

**Architecture:** 3 axes indépendants sur 6 fichiers. Axe 1 = fix Cypher + scheduler nightly dans `graph.py`/`graph_jobs.py`/`main.py`. Axe 2 = query enrichie + budget tokens dans `handlers.py`/`config.py`. Axe 3 = nouvelle méthode `get_social_context()` + paramètre `social_context` dans `prompts.py` + appel parallèle dans `handlers.py`.

**Tech Stack:** Python asyncio, Neo4j bolt driver (via `graph._graphiti.driver`), apscheduler `AsyncIOScheduler`, graphiti-core, pytest-asyncio.

---

## Fichiers touchés

| Fichier | Action |
|---------|--------|
| `bot/core/graph.py` | Modifier `get_affinity()` + ajouter `get_social_context()` |
| `bot/core/graph_jobs.py` | Créer — job community detection nightly |
| `bot/config.py` | Ajouter `graph_context_max_tokens: int = 400` dans `GraphitiConfig` |
| `bot/core/prompts.py` | Ajouter paramètre `social_context: str = ""` dans `build_system_prompt()` |
| `bot/discord/handlers.py` | Enrichir graph search + ajouter appel `get_social_context()` parallèle |
| `bot/main.py` | Appeler `schedule_community_detection()` après `graph.initialize()` |
| `tests/test_graph.py` | Ajouter tests `get_affinity()` Cypher + `get_social_context()` |
| `tests/test_prompts.py` | Ajouter test paramètre `social_context` |

---

## Task 1 : Fix `get_affinity()` via Cypher direct

**Files:**
- Modify: `bot/core/graph.py` (méthode `get_affinity`, lignes 204–240)
- Modify: `tests/test_graph.py`

- [ ] **Step 1 : Écrire le test failing**

Ajouter dans `tests/test_graph.py` :

```python
@pytest.mark.asyncio
async def test_get_affinity_cypher_direct():
    """get_affinity() uses Cypher query, not semantic search."""
    svc = GraphService(_make_config())
    svc._ready = True
    svc._graphiti = MagicMock()

    # Mock du driver : retourne 2 arêtes de type "vocal" et 1 "reply"
    mock_record_voice = MagicMock()
    mock_record_voice.__getitem__ = lambda self, k: {"type": "EN_VOCAL_AVEC", "cnt": 2}[k]
    mock_record_reply = MagicMock()
    mock_record_reply.__getitem__ = lambda self, k: {"type": "REPOND_A", "cnt": 1}[k]

    mock_result = MagicMock()
    mock_result.records = [mock_record_voice, mock_record_reply]
    svc._graphiti.driver = AsyncMock()
    svc._graphiti.driver.execute_query = AsyncMock(return_value=mock_result)

    score = await svc.get_affinity("Alice", "Bob")
    # voice × 2 = 6.0, reply × 1 = 2.0 → total 8.0
    assert score == 8.0

    # Vérifier que execute_query a bien été appelé (pas graphiti.search)
    svc._graphiti.driver.execute_query.assert_called_once()
    call_args = svc._graphiti.driver.execute_query.call_args
    assert "RELATES_TO" in call_args[0][0]
```

- [ ] **Step 2 : Lancer le test, vérifier qu'il échoue**

```bash
cd /opt/stacks/wally-ai
python -m pytest tests/test_graph.py::test_get_affinity_cypher_direct -v
```

Attendu : FAIL (l'implémentation actuelle utilise `graphiti.search`)

- [ ] **Step 3 : Réécrire `get_affinity()` dans `bot/core/graph.py`**

Remplacer entièrement la méthode `get_affinity` (lignes 204–240) par :

```python
async def get_affinity(self, user_a: str, user_b: str, group_id: str | None = None) -> float:
    """Calculate affinity score between two users using a direct Cypher query."""
    if not self.ready:
        return 0.0
    try:
        gid = self._sanitize_group_id(group_id or self._config.graphiti.group_id)
        result = await self._graphiti.driver.execute_query(
            "MATCH (a:Entity {group_id: $gid})-[r:RELATES_TO]-(b:Entity {group_id: $gid}) "
            "WHERE toLower(a.name) = $name_a AND toLower(b.name) = $name_b "
            "  AND r.invalid_at IS NULL "
            "RETURN r.name AS type, count(r) AS cnt",
            params={"gid": gid, "name_a": user_a.lower(), "name_b": user_b.lower()},
        )
        weights = self._config.graphiti.affinity_weights
        _TYPE_TO_WEIGHT = {
            "EN_VOCAL_AVEC": weights.get("voice", 3.0),
            "REPOND_A": weights.get("reply", 2.0),
            "MENTIONNE": weights.get("mention", 1.5),
            "REAGIT_A": weights.get("reaction", 1.0),
            "THREAD_COMMUN": weights.get("thread", 1.0),
            "JOUE_AVEC": weights.get("game", 2.5),
        }
        score = 0.0
        for record in result.records:
            edge_type = record["type"] or ""
            cnt = record["cnt"] or 0
            score += _TYPE_TO_WEIGHT.get(edge_type, 0.5) * cnt
        return round(score, 2)
    except Exception as exc:
        logger.warning("Affinity calculation failed: {e}", e=exc)
        return 0.0
```

- [ ] **Step 4 : Lancer le test, vérifier qu'il passe**

```bash
python -m pytest tests/test_graph.py::test_get_affinity_cypher_direct -v
```

Attendu : PASS

- [ ] **Step 5 : Vérifier que les tests existants passent toujours**

```bash
python -m pytest tests/test_graph.py -v
```

Attendu : tous PASS

- [ ] **Step 6 : Commit**

```bash
git add bot/core/graph.py tests/test_graph.py
git commit -m "fix(graph): get_affinity() via Cypher direct — remplace semantic search"
```

---

## Task 2 : Ajouter `get_social_context()` dans GraphService

**Files:**
- Modify: `bot/core/graph.py`
- Modify: `tests/test_graph.py`

- [ ] **Step 1 : Écrire le test failing**

Ajouter dans `tests/test_graph.py` :

```python
@pytest.mark.asyncio
async def test_get_social_context_returns_pairs():
    """get_social_context() returns list of (name_a, name_b, strength) tuples."""
    svc = GraphService(_make_config())
    svc._ready = True
    svc._graphiti = MagicMock()

    # Mock : 2 paires, strength 12 et 4
    def _rec(ua, ub, strength):
        r = MagicMock()
        r.__getitem__ = lambda self, k: {"ua": ua, "ub": ub, "strength": strength}[k]
        return r

    mock_result = MagicMock()
    mock_result.records = [_rec("Keychka", "Azrael", 12), _rec("Saphira", "Keychka", 4)]
    svc._graphiti.driver = AsyncMock()
    svc._graphiti.driver.execute_query = AsyncMock(return_value=mock_result)

    pairs = await svc.get_social_context()
    assert pairs == [("Keychka", "Azrael", 12), ("Saphira", "Keychka", 4)]


@pytest.mark.asyncio
async def test_get_social_context_returns_empty_when_not_ready():
    svc = GraphService(_make_config())
    pairs = await svc.get_social_context()
    assert pairs == []
```

- [ ] **Step 2 : Lancer les tests, vérifier qu'ils échouent**

```bash
python -m pytest tests/test_graph.py::test_get_social_context_returns_pairs tests/test_graph.py::test_get_social_context_returns_empty_when_not_ready -v
```

Attendu : FAIL (`get_social_context` n'existe pas)

- [ ] **Step 3 : Ajouter `get_social_context()` dans `bot/core/graph.py`**

Insérer avant la méthode `close()` :

```python
async def get_social_context(
    self,
    group_id: str | None = None,
    min_strength: int = 3,
    limit: int = 10,
) -> list[tuple[str, str, int]]:
    """Return top social pairs as (name_a, name_b, strength) sorted by strength desc.

    Uses a direct Cypher query — no LLM call, no Graphiti search overhead.
    """
    if not self.ready:
        return []
    try:
        gid = self._sanitize_group_id(group_id or self._config.graphiti.group_id)
        result = await self._graphiti.driver.execute_query(
            "MATCH (a:Entity {group_id: $gid})-[r:RELATES_TO]-(b:Entity {group_id: $gid}) "
            "WHERE r.invalid_at IS NULL "
            "  AND a.name <> 'unknown' AND b.name <> 'unknown' "
            "  AND a.name <> 'system' AND b.name <> 'system' "
            "  AND NOT a.name CONTAINS '<@' AND NOT b.name CONTAINS '<@' "
            "WITH a.name AS ua, b.name AS ub, count(r) AS strength "
            "WHERE strength >= $min_strength "
            "RETURN ua, ub, strength "
            "ORDER BY strength DESC "
            "LIMIT $limit",
            params={"gid": gid, "min_strength": min_strength, "limit": limit},
        )
        return [
            (record["ua"], record["ub"], record["strength"])
            for record in result.records
        ]
    except Exception as exc:
        logger.warning("Social context query failed: {e}", e=exc)
        return []
```

- [ ] **Step 4 : Lancer les tests, vérifier qu'ils passent**

```bash
python -m pytest tests/test_graph.py -v
```

Attendu : tous PASS

- [ ] **Step 5 : Commit**

```bash
git add bot/core/graph.py tests/test_graph.py
git commit -m "feat(graph): add get_social_context() — Cypher query for top social pairs"
```

---

## Task 3 : Community detection nocturne

**Files:**
- Create: `bot/core/graph_jobs.py`
- Modify: `bot/main.py`

- [ ] **Step 1 : Créer `bot/core/graph_jobs.py`**

```python
"""Scheduled graph maintenance jobs (community detection, etc.)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bot.core.graph import GraphService


async def _run_community_detection(graph: "GraphService") -> None:
    """Trigger Graphiti community detection via a synthetic episode."""
    if not graph.ready:
        logger.debug("Community detection skipped — graph not ready")
        return
    try:
        result = await graph.add_episode(
            content="Mise à jour des communautés sociales du serveur.",
            author="system",
            source="system",
            update_communities=True,
        )
        logger.info("Community detection completed: {r}", r=result)
    except Exception as exc:
        logger.warning("Community detection job failed: {e}", e=exc)


def schedule_community_detection(graph: "GraphService", scheduler) -> None:
    """Add a nightly community detection job to the shared scheduler.

    Runs every night at 03:00 UTC.
    """
    scheduler.add_job(
        _run_community_detection,
        "cron",
        hour=3,
        minute=0,
        args=[graph],
        id="community_detection_nightly",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info("Community detection job scheduled (daily at 03:00 UTC)")
```

- [ ] **Step 2 : Intégrer dans `bot/main.py`**

Après la ligne `await graph.initialize()` (ligne ~98) et avant la ligne `from bot.discord.social import SocialTracker` (ligne ~176), ajouter :

```python
    # Community detection nocturne
    from bot.core.graph_jobs import schedule_community_detection
    if graph.ready:
        schedule_community_detection(graph, shared_scheduler)
```

Note : `shared_scheduler` est défini ligne ~145 de `main.py`. Le bloc doit être placé **après** `await graph.initialize()` et **avant** `shared_scheduler.start()` (ligne ~413).

- [ ] **Step 3 : Vérifier que le bot démarre sans erreur**

```bash
cd /opt/stacks/wally-ai
python -c "from bot.core.graph_jobs import schedule_community_detection; print('OK')"
```

Attendu : `OK`

- [ ] **Step 4 : Lancer la suite de tests complète**

```bash
python -m pytest tests/test_graph.py tests/test_journal.py -v
```

Attendu : tous PASS

- [ ] **Step 5 : Commit**

```bash
git add bot/core/graph_jobs.py bot/main.py
git commit -m "feat(graph): community detection nocturne via apscheduler (03:00 UTC)"
```

---

## Task 4 : `graph_context_max_tokens` dans config + enrichir la query dans handlers

**Files:**
- Modify: `bot/config.py` (classe `GraphitiConfig`, lignes 241–252)
- Modify: `bot/discord/handlers.py` (bloc graph context, lignes 801–819)
- Modify: `tests/test_graph.py`

- [ ] **Step 1 : Ajouter `graph_context_max_tokens` dans `GraphitiConfig`**

Dans `bot/config.py`, modifier la classe `GraphitiConfig` pour ajouter le champ après `affinity_weights` :

```python
@dataclass
class GraphitiConfig:
    enabled: bool = False
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "changeme"
    llm_model: str = "gpt-5-nano"
    community_detection: bool = False
    group_id: str = "discord-default"
    affinity_weights: dict[str, float] = field(default_factory=lambda: {
        "voice": 3.0, "reply": 2.0, "mention": 1.5,
        "reaction": 1.0, "thread": 1.0, "game": 2.5,
    })
    graph_context_max_tokens: int = 400
```

- [ ] **Step 2 : Mettre à jour `_make_config()` dans `tests/test_graph.py`**

Ajouter `config.graphiti.graph_context_max_tokens = 400` dans la fonction `_make_config()` :

```python
def _make_config(enabled=False):
    config = MagicMock()
    config.graphiti.enabled = enabled
    config.graphiti.neo4j_uri = "bolt://localhost:7687"
    config.graphiti.neo4j_user = "neo4j"
    config.graphiti.neo4j_password = "test"
    config.graphiti.llm_model = "gpt-5-nano"
    config.graphiti.group_id = "test:default"
    config.graphiti.community_detection = False
    config.graphiti.graph_context_max_tokens = 400
    config.graphiti.affinity_weights = {
        "voice": 3.0, "reply": 2.0, "mention": 1.5,
        "reaction": 1.0, "thread": 1.0, "game": 2.5,
    }
    return config
```

- [ ] **Step 3 : Enrichir le bloc graph context dans `bot/discord/handlers.py`**

Remplacer le bloc lignes 801–819 par :

```python
        # Knowledge graph context (Graphiti)
        graph_context = ""
        if hasattr(bot, 'graph') and bot.graph and bot.graph.ready:
            _graph_facts_count = 0
            try:
                _author_label = _get_author_label(message.author, message.guild)
                graph_results = await bot.graph.search(
                    query=f"{_author_label}: {message.content}",
                    group_id=None,
                    num_results=10,
                )
                if graph_results:
                    # Filtrer les facts invalidés
                    valid_results = [r for r in graph_results if r.get("invalid_at") is None]
                    facts_lines = []
                    token_budget = bot.config.graphiti.graph_context_max_tokens
                    used = 0
                    for r in valid_results:
                        fact = r.get("fact", "")
                        if not fact:
                            continue
                        valid_at = r.get("valid_at")
                        date_str = f"  [depuis {valid_at[:10]}]" if valid_at else ""
                        line = f"• {fact}{date_str}"
                        used += len(line) // 4  # approximation tokens
                        if used > token_budget:
                            break
                        facts_lines.append(line)
                    if facts_lines:
                        _graph_facts_count = len(facts_lines)
                        graph_context = "\n--- Connaissances du graphe ---\n" + "\n".join(facts_lines)
            except Exception:
                pass
            finally:
                create_span(trace, name="graph:search", input={"query": message.content}, output={"facts_count": _graph_facts_count})
```

Note : `_get_author_label` est déjà importé/disponible dans `handlers.py` (c'est la fonction `_author_label` — vérifier le nom exact dans le fichier avant d'éditer).

- [ ] **Step 4 : Vérifier le nom exact de la fonction author label dans handlers.py**

```bash
grep -n "def _author_label\|def _get_author_label" /opt/stacks/wally-ai/bot/discord/handlers.py
```

Utiliser le nom exact retourné.

- [ ] **Step 5 : Lancer les tests**

```bash
python -m pytest tests/test_graph.py tests/test_config.py tests/test_discord_handlers.py -v
```

Attendu : tous PASS

- [ ] **Step 6 : Commit**

```bash
git add bot/config.py bot/discord/handlers.py tests/test_graph.py
git commit -m "feat(graph): graph context enrichi — query auteur+contenu, filtrage invalid_at, budget tokens"
```

---

## Task 5 : `social_context` dans le system prompt

**Files:**
- Modify: `bot/core/prompts.py` (signature `build_system_prompt`, lignes 134–150 et 273–275)
- Modify: `bot/discord/handlers.py` (appel parallèle + rate-limit)
- Modify: `tests/test_prompts.py`

- [ ] **Step 1 : Écrire le test failing pour prompts.py**

Chercher comment `test_prompts.py` teste `build_system_prompt` :

```bash
grep -n "build_system_prompt\|graph_context" /opt/stacks/wally-ai/tests/test_prompts.py | head -20
```

Puis ajouter dans `tests/test_prompts.py` :

```python
def test_social_context_injected():
    builder = PromptBuilder()
    prompt = builder.build_system_prompt(
        emotion_state={"joy": 0.5, "anger": 0.0, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.1},
        social_context="--- Relations sociales connues ---\n• Keychka ↔ Azrael  (très proches)",
    )
    assert "Relations sociales connues" in prompt
    assert "Keychka ↔ Azrael" in prompt


def test_social_context_empty_not_injected():
    builder = PromptBuilder()
    prompt = builder.build_system_prompt(
        emotion_state={"joy": 0.5, "anger": 0.0, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.1},
        social_context="",
    )
    assert "Relations sociales" not in prompt
```

- [ ] **Step 2 : Lancer les tests, vérifier qu'ils échouent**

```bash
python -m pytest tests/test_prompts.py::test_social_context_injected tests/test_prompts.py::test_social_context_empty_not_injected -v
```

Attendu : FAIL (`social_context` n'est pas un paramètre de `build_system_prompt`)

- [ ] **Step 3 : Ajouter le paramètre `social_context` dans `bot/core/prompts.py`**

**Signature** — ajouter après `graph_context: str = ""` :

```python
    def build_system_prompt(
        self,
        emotion_state: dict[str, float],
        memory_context: str = "",
        global_memory_context: str = "",
        situation: dict | None = None,
        persona_block: str = "",
        emotion_directives: dict[str, str] | None = None,
        weekday_directives: dict[str, str] | None = None,
        composite_directives: dict[str, str] | None = None,
        relationship_context: str = "",
        secondary_directives: dict[str, str] | None = None,
        active_secondaries: list[tuple[str, float]] | None = None,
        mood_state: dict[str, float] | None = None,
        persistent_notes: list[dict] | None = None,
        graph_context: str = "",
        social_context: str = "",
    ) -> str:
```

**Injection** — dans le corps de la méthode, après le bloc `if graph_context:` (ligne ~274) :

```python
        # Social awareness (top affinités du serveur)
        if social_context:
            parts.append(social_context)
```

- [ ] **Step 4 : Lancer les tests, vérifier qu'ils passent**

```bash
python -m pytest tests/test_prompts.py -v
```

Attendu : tous PASS

- [ ] **Step 5 : Ajouter l'appel parallèle dans `bot/discord/handlers.py`**

Après la déclaration de `_memory_check_cooldowns` (ligne ~168), ajouter :

```python
_social_context_cooldowns: dict[int, float] = {}  # rate-limit social context per channel
```

Puis, dans `on_message`, après le bloc graph context (après le `finally` de graph search), ajouter avant `situation: dict = ...` :

```python
        # Social context — relations sociales du serveur (rate-limited 60s/channel)
        social_context = ""
        if hasattr(bot, 'graph') and bot.graph and bot.graph.ready:
            chan_id = message.channel.id
            now = time.time()
            if now - _social_context_cooldowns.get(chan_id, 0) >= 60:
                _social_context_cooldowns[chan_id] = now
                try:
                    pairs = await bot.graph.get_social_context()
                    if pairs:
                        _LABELS = {10: "très proches", 5: "proches", 3: "interagissent"}
                        def _label(s: int) -> str:
                            for threshold in (10, 5, 3):
                                if s >= threshold:
                                    return _LABELS[threshold]
                            return "interagissent"
                        lines = [f"• {a} ↔ {b}  ({_label(s)})" for a, b, s in pairs]
                        social_context = "--- Relations sociales connues ---\n" + "\n".join(lines)
                except Exception:
                    pass
```

Et ajouter `social_context=social_context` dans l'appel `build_system_prompt()` (après `graph_context=graph_context`) :

```python
        system_prompt = bot.prompts.build_system_prompt(
            ...
            graph_context=graph_context,
            social_context=social_context,
        )
```

- [ ] **Step 6 : Lancer la suite de tests complète**

```bash
python -m pytest tests/test_graph.py tests/test_prompts.py tests/test_discord_handlers.py -v
```

Attendu : tous PASS

- [ ] **Step 7 : Commit**

```bash
git add bot/core/prompts.py bot/discord/handlers.py tests/test_prompts.py
git commit -m "feat(graph): social awareness dans le prompt — relations sociales connues injectées"
```

---

## Task 6 : Vérification finale

- [ ] **Step 1 : Lancer toute la suite de tests**

```bash
cd /opt/stacks/wally-ai
python -m pytest --tb=short -q
```

Attendu : tous PASS (989+ tests)

- [ ] **Step 2 : Type check**

```bash
python -m py_compile bot/core/graph.py bot/core/graph_jobs.py bot/core/prompts.py bot/discord/handlers.py bot/config.py
echo "Compilation OK"
```

Attendu : `Compilation OK` sans erreur

- [ ] **Step 3 : Commit de clôture si nécessaire**

```bash
git log --oneline -6
```

Vérifier que les 5 commits des tasks 1–5 sont présents.
