# Outils cognitifs en vocal + santé des canaux — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Brancher recherche web (« à voix haute »), notes persistantes et rappels dans le contexte vocal de Wally, et valider au démarrage que chaque channel id configuré existe encore.

**Architecture:** Le pipeline vocal passe déjà par `complete_with_tools(system, history, tools, executor)`. On rend la liste d'outils vocale dynamique (`build_voice_tools`) et on étend l'exécuteur (`make_voice_tool_executor`) pour router les nouveaux outils. La recherche web reçoit un traitement spécial (`_search_aloud`) qui parle une amorce + des bruits générés par LLM pendant que la recherche tourne. Un validateur de canaux indépendant tourne à `on_ready`.

**Tech Stack:** Python 3.11, asyncio, discord.py, pytest. LLM via `bot.llm` / `bot.llm_secondary` (interface `BaseLLMClient`). Tests = `pytest`, mocks `unittest.mock`.

## Global Constraints

- **Aucun DM à un utilisateur autre que le créateur** (`config.bot.owner_discord_id`). Seul DM autorisé : l'alerte santé des canaux au créateur. Rappels jamais en DM à un tiers.
- Logging : `from loguru import logger` exclusivement, jamais `print` / `logging`.
- Async first : tout I/O est `await` ; jamais de blocage de la boucle.
- Outil exposé seulement si dispo : un outil indisponible (clé absente, quota dépassé, service non câblé) n'est pas ajouté à la liste.
- `config.bot.bedroom_channel_id` = `1485380606224502844` (#chambre-de-wally, serveur « Le Purgatoire »). Type `int | None`, défaut `None`.
- Lancer la suite avec `python3 -m pytest` (pas `python`).
- Tests existants de référence : `tests/discord/voice/test_brain.py` (mock `_bot()`), `tests/discord/voice/test_voice_cmd.py`.

---

### Task 1: Champ config `bedroom_channel_id`

**Files:**
- Modify: `bot/config.py` (dataclass `BotConfig`, après `notification_channel_id` ~ligne 21)
- Test: `tests/test_config_bedroom.py` (créer)

**Interfaces:**
- Produces: `config.bot.bedroom_channel_id: int | None` — lu/écrit via `Config.load()` / `Config.save()` (qui font `BotConfig(**raw["bot"])` et `asdict(self.bot)`, donc round-trip automatique).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config_bedroom.py
from dataclasses import asdict
from bot.config import BotConfig


def test_bedroom_channel_id_default_none():
    cfg = BotConfig(
        name="Wally", trigger_names=[], language_default="fr",
        context_window_size=10, context_token_threshold=1000,
        journal_time="09:00",
    )
    assert cfg.bedroom_channel_id is None


def test_bedroom_channel_id_roundtrips_in_asdict():
    cfg = BotConfig(
        name="Wally", trigger_names=[], language_default="fr",
        context_window_size=10, context_token_threshold=1000,
        journal_time="09:00", bedroom_channel_id=1485380606224502844,
    )
    d = asdict(cfg)
    assert d["bedroom_channel_id"] == 1485380606224502844
    # Reconstruit depuis le dict (ce que fait Config.load avec **raw["bot"])
    assert BotConfig(**d).bedroom_channel_id == 1485380606224502844
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_config_bedroom.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'bedroom_channel_id'`

- [ ] **Step 3: Add the field**

Dans `bot/config.py`, dataclass `BotConfig`, juste après la ligne `notification_channel_id: int | None = None` :

```python
    bedroom_channel_id: int | None = None   # #chambre-de-wally — cible des rappels créés en vocal
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_config_bedroom.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Set the real value in config.yaml**

Dans `config.yaml`, sous la clé `bot:`, ajouter (près de `notification_channel_id`) :

```yaml
  bedroom_channel_id: 1485380606224502844
```

- [ ] **Step 6: Commit**

```bash
git add bot/config.py tests/test_config_bedroom.py config.yaml
git commit -m "feat(config): champ bedroom_channel_id (#chambre-de-wally)"
```

---

### Task 2: `generate_search_filler` — amorce + bruits dans le style de Wally

**Files:**
- Modify: `bot/discord/voice/brain.py` (ajouter fonction + schéma + repli, après `generate_voice_greeting`)
- Test: `tests/discord/voice/test_search_filler.py` (créer)

**Interfaces:**
- Consumes: `bot.llm_secondary.complete_structured(system_prompt, messages, schema, schema_name, purpose)` → `dict` ; `_voice_system(bot)` (helper existant dans `brain.py`).
- Produces: `async def generate_search_filler(bot, query: str) -> dict` → `{"amorce": str, "bruits": list[str]}`. Ne lève jamais : repli déterministe `_FILLER_FALLBACK` en cas d'échec/vide.

- [ ] **Step 1: Write the failing test**

```python
# tests/discord/voice/test_search_filler.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.discord.voice.brain import generate_search_filler


def _bot():
    bot = MagicMock()
    bot.emotion.get_state.return_value = {
        "anger": 0.0, "joy": 0.5, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.0
    }
    bot.emotion.get_secondary_emotions.return_value = []
    bot.prompts.build_voice_system = MagicMock(return_value="SYSTEM")
    bot.persona.build_prompt_block.return_value = "PERSONA"
    bot.persona.emotion_directives = {}
    bot.persona.weekday_directives = {}
    bot.persona.composite_directives = {}
    bot.persona.secondary_directives = {}
    return bot


@pytest.mark.asyncio
async def test_filler_renvoie_amorce_et_bruits():
    bot = _bot()
    bot.llm_secondary.complete_structured = AsyncMock(
        return_value={"amorce": "attends je regarde", "bruits": ["mh...", "ok je vois"]}
    )
    out = await generate_search_filler(bot, "prix ps5")
    assert out["amorce"] == "attends je regarde"
    assert out["bruits"] == ["mh...", "ok je vois"]


@pytest.mark.asyncio
async def test_filler_repli_si_llm_echoue():
    bot = _bot()
    bot.llm_secondary.complete_structured = AsyncMock(side_effect=RuntimeError("boom"))
    out = await generate_search_filler(bot, "prix ps5")
    assert out["amorce"]                      # repli non vide
    assert isinstance(out["bruits"], list)


@pytest.mark.asyncio
async def test_filler_repli_si_amorce_vide():
    bot = _bot()
    bot.llm_secondary.complete_structured = AsyncMock(return_value={"amorce": "", "bruits": []})
    out = await generate_search_filler(bot, "prix ps5")
    assert out["amorce"]                      # repli car amorce vide
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/discord/voice/test_search_filler.py -v`
Expected: FAIL — `ImportError: cannot import name 'generate_search_filler'`

- [ ] **Step 3: Implement**

Dans `bot/discord/voice/brain.py`, après la fonction `generate_voice_greeting` :

```python
_FILLER_FALLBACK = {
    "amorce": "attends, je regarde ça",
    "bruits": ["mh...", "ok je vois...", "deux secondes..."],
}

_FILLER_SCHEMA = {
    "type": "object",
    "properties": {
        "amorce": {"type": "string"},
        "bruits": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["amorce", "bruits"],
}


async def generate_search_filler(bot, query: str) -> dict:
    """Génère, dans le style/l'humeur de Wally, une amorce parlée (« attends je cherche »)
    et 2-3 petits bruits de réflexion. Un seul appel LLM ; repli déterministe si échec."""
    try:
        system_prompt = _voice_system(bot)
        instruction = (
            "Tu vas chercher une information sur internet, ça prend quelques secondes. "
            f"Sujet de la recherche : « {query} ». "
            "Donne 'amorce' : une courte phrase parlée, dans ton style, qui annonce que tu "
            "regardes (ex. « attends, je vérifie ça »). Donne 'bruits' : 2 à 3 très courtes "
            "onomatopées/interjections de réflexion à dire pendant que ça charge "
            "(ex. « mh... », « ok je vois... »). Pas de markdown, pas d'emoji."
        )
        messages = [{"role": "user", "content": instruction}]
        out = await bot.llm_secondary.complete_structured(
            system_prompt, messages, _FILLER_SCHEMA,
            schema_name="search_filler", purpose="discord_voice_search_filler",
        )
        amorce = (out.get("amorce") or "").strip()
        bruits = [b.strip() for b in (out.get("bruits") or []) if b and b.strip()]
        if not amorce:
            return dict(_FILLER_FALLBACK)
        return {"amorce": amorce, "bruits": bruits}
    except Exception as e:  # noqa: BLE001
        logger.warning("generate_search_filler a échoué: {e}", e=e)
        return dict(_FILLER_FALLBACK)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/discord/voice/test_search_filler.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add bot/discord/voice/brain.py tests/discord/voice/test_search_filler.py
git commit -m "feat(voice): generate_search_filler (amorce + bruits dans le style)"
```

---

### Task 3: `_search_aloud` + outil web_search en vocal

**Files:**
- Modify: `bot/discord/voice/tools.py` (ajouter `build_voice_tools`, `_search_aloud`, routage `web_search`)
- Modify: `bot/discord/voice/brain.py` (`_respond_once` : `tools = await build_voice_tools(bot)`)
- Test: `tests/discord/voice/test_voice_tools_web.py` (créer)

**Interfaces:**
- Consumes: `generate_search_filler(bot, query)` (Task 2) ; `bot.web_search.available` (bool), `await bot.web_search.is_quota_exceeded()` (bool), `await bot.web_search.search(query, platform="discord")` (str) ; `service.speak(text)` (coroutine séquentielle).
- Produces: `async def build_voice_tools(bot) -> list[dict]` ; `async def _search_aloud(bot, service, query: str) -> str`. L'exécuteur retourné par `make_voice_tool_executor` route désormais `name == "web_search"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/discord/voice/test_voice_tools_web.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.discord.voice.tools import build_voice_tools, make_voice_tool_executor


def _names(tools):
    return {t["function"]["name"] for t in tools}


@pytest.mark.asyncio
async def test_web_search_propose_si_dispo():
    bot = MagicMock()
    bot.web_search.available = True
    bot.web_search.is_quota_exceeded = AsyncMock(return_value=False)
    bot.action_service = None
    tools = await build_voice_tools(bot)
    assert "web_search" in _names(tools)


@pytest.mark.asyncio
async def test_web_search_absent_si_quota_depasse():
    bot = MagicMock()
    bot.web_search.available = True
    bot.web_search.is_quota_exceeded = AsyncMock(return_value=True)
    bot.action_service = None
    tools = await build_voice_tools(bot)
    assert "web_search" not in _names(tools)


@pytest.mark.asyncio
async def test_search_aloud_parle_amorce_puis_renvoie_resultat():
    bot = MagicMock()
    bot.web_search.search = AsyncMock(return_value="RESULTAT")
    service = MagicMock()
    service.speak = AsyncMock()
    with patch("bot.discord.voice.tools.generate_search_filler",
               new=AsyncMock(return_value={"amorce": "j'regarde", "bruits": ["mh..."]})):
        executor = make_voice_tool_executor(bot, service, current_speaker_id=lambda: "1")
        out = await executor("web_search", json.dumps({"query": "prix ps5"}))
    assert out == "RESULTAT"
    # l'amorce a bien été parlée
    spoken = [c.args[0] for c in service.speak.await_args_list]
    assert "j'regarde" in spoken
    bot.web_search.search.assert_awaited_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/discord/voice/test_voice_tools_web.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_voice_tools'`

- [ ] **Step 3: Implement in `tools.py`**

En tête de `bot/discord/voice/tools.py`, ajouter l'import :

```python
import asyncio
from bot.core.web_search import WEB_SEARCH_TOOL
from bot.discord.voice.brain import generate_search_filler
```

Ajouter les fonctions (niveau module) :

```python
async def build_voice_tools(bot) -> list[dict]:
    """Liste des outils proposés en vocal, selon ce qui est disponible."""
    tools = list(VOICE_TOOLS)
    web = getattr(bot, "web_search", None)
    if web is not None and web.available and not await web.is_quota_exceeded():
        tools.append(WEB_SEARCH_TOOL)
    return tools


async def _search_aloud(bot, service, query: str) -> str:
    """Cherche sur le web en « parlant tout haut » : amorce + bruits pendant l'attente."""
    filler_task = asyncio.create_task(generate_search_filler(bot, query))
    search_task = asyncio.create_task(bot.web_search.search(query, platform="discord"))
    try:
        filler = await filler_task
        await service.speak(filler.get("amorce") or "")
        for bruit in filler.get("bruits") or []:
            if search_task.done():
                break
            await service.speak(bruit)
    except Exception as e:  # noqa: BLE001
        logger.warning("_search_aloud filler a échoué: {e}", e=e)
    return await search_task
```

Dans la fonction `executor` (à l'intérieur de `make_voice_tool_executor`), router `web_search` AVANT le `return ... "Outil inconnu"` final :

```python
        if name == "web_search":
            args = {}
            try:
                args = json.loads(arguments or "{}")
            except Exception:  # noqa: BLE001
                pass
            query = (args.get("query") or "").strip()
            if not query:
                return json.dumps({"status": "error", "message": "Requête vide."})
            return await _search_aloud(bot, service, query)
```

- [ ] **Step 4: Wire dynamic tool list in `brain.py`**

Dans `bot/discord/voice/brain.py`, fonction `_respond_once`, remplacer :

```python
    tools = getattr(service, "voice_tools", [])
    tool_executor = getattr(service, "tool_executor", None)
```

par :

```python
    from bot.discord.voice.tools import build_voice_tools
    tools = await build_voice_tools(bot)
    tool_executor = getattr(service, "tool_executor", None)
```

(Import local pour éviter tout cycle d'import au chargement du module.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/discord/voice/test_voice_tools_web.py tests/discord/voice/test_brain.py -v`
Expected: PASS (les 3 nouveaux + la suite brain existante verte)

- [ ] **Step 6: Commit**

```bash
git add bot/discord/voice/tools.py bot/discord/voice/brain.py tests/discord/voice/test_voice_tools_web.py
git commit -m "feat(voice): recherche web à voix haute (build_voice_tools + _search_aloud)"
```

---

### Task 4: Notes persistantes en vocal

**Files:**
- Modify: `bot/discord/voice/tools.py` (`build_voice_tools` ajoute `_NOTE_TOOLS` ; executor route les 2 outils note)
- Test: `tests/discord/voice/test_voice_tools_notes.py` (créer)

**Interfaces:**
- Consumes: `_NOTE_TOOLS` et rien d'autre depuis `bot.discord.handlers` (import paresseux pour éviter le cycle `handlers ↔ voice.tools`) ; `bot.db.upsert_persistent_note(title, content)` ; `bot.db.delete_persistent_note(title) -> bool`.
- Produces: `build_voice_tools` inclut `save_persistent_note` + `delete_persistent_note` ; executor les exécute.

- [ ] **Step 1: Write the failing test**

```python
# tests/discord/voice/test_voice_tools_notes.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.discord.voice.tools import build_voice_tools, make_voice_tool_executor


def _names(tools):
    return {t["function"]["name"] for t in tools}


@pytest.mark.asyncio
async def test_notes_proposees_en_vocal():
    bot = MagicMock()
    bot.web_search = None
    bot.action_service = None
    tools = await build_voice_tools(bot)
    assert {"save_persistent_note", "delete_persistent_note"} <= _names(tools)


@pytest.mark.asyncio
async def test_save_note_execute_en_vocal():
    bot = MagicMock()
    bot.db.upsert_persistent_note = AsyncMock()
    service = MagicMock()
    executor = make_voice_tool_executor(bot, service, current_speaker_id=lambda: "1")
    out = await executor("save_persistent_note",
                         json.dumps({"title": "LAN", "content": "samedi 20h"}))
    bot.db.upsert_persistent_note.assert_awaited_once_with("LAN", "samedi 20h")
    assert json.loads(out)["status"] == "ok"


@pytest.mark.asyncio
async def test_delete_note_introuvable():
    bot = MagicMock()
    bot.db.delete_persistent_note = AsyncMock(return_value=False)
    service = MagicMock()
    executor = make_voice_tool_executor(bot, service, current_speaker_id=lambda: "1")
    out = await executor("delete_persistent_note", json.dumps({"title": "X"}))
    assert json.loads(out)["status"] == "not_found"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/discord/voice/test_voice_tools_notes.py -v`
Expected: FAIL — `save_persistent_note` absent de la liste / route inconnue

- [ ] **Step 3: Implement**

Dans `build_voice_tools` (tools.py), avant le `return tools`, ajouter (import paresseux) :

```python
    from bot.discord.handlers import _NOTE_TOOLS
    tools.extend(_NOTE_TOOLS)
```

Dans `executor`, router les notes (avant le `return ... "Outil inconnu"`) :

```python
        if name == "save_persistent_note":
            a = json.loads(arguments or "{}")
            await bot.db.upsert_persistent_note(a["title"], a["content"])
            return json.dumps({"status": "ok", "message": f"Note '{a['title']}' sauvegardée."})

        if name == "delete_persistent_note":
            a = json.loads(arguments or "{}")
            deleted = await bot.db.delete_persistent_note(a["title"])
            if deleted:
                return json.dumps({"status": "ok", "message": f"Note '{a['title']}' supprimée."})
            return json.dumps({"status": "not_found", "message": f"Note '{a['title']}' introuvable."})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/discord/voice/test_voice_tools_notes.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add bot/discord/voice/tools.py tests/discord/voice/test_voice_tools_notes.py
git commit -m "feat(voice): notes persistantes accessibles en vocal"
```

---

### Task 5: Rappels en vocal (vers la chambre)

**Files:**
- Modify: `bot/discord/voice/tools.py` (`build_voice_tools` ajoute les outils action ; executor route vers `action_service.execute_tool` avec la chambre)
- Test: `tests/discord/voice/test_voice_tools_reminder.py` (créer)

**Interfaces:**
- Consumes: `bot.action_service.get_tool_definitions() -> list[dict]` ; `await bot.action_service.execute_tool(name, args, user_id, platform, user_roles, channel_id, guild_id) -> dict` ; `_resolve_discord_roles(member)` (import paresseux depuis `bot.discord.handlers`) ; `config.bot.bedroom_channel_id` (Task 1) ; `service._channel.members` (pour résoudre le membre courant), `service._channel.guild.id`.
- Produces: `build_voice_tools` inclut les outils d'`action_service` ; executor route `create_action_task` / `cancel_action_task` / `list_action_tasks`. Refus propre si `bedroom_channel_id` est `None` pour la création.

- [ ] **Step 1: Write the failing test**

```python
# tests/discord/voice/test_voice_tools_reminder.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.discord.voice.tools import build_voice_tools, make_voice_tool_executor


def _names(tools):
    return {t["function"]["name"] for t in tools}


def _action_tool(name):
    return {"type": "function", "function": {"name": name, "description": "", "parameters": {}}}


@pytest.mark.asyncio
async def test_outils_action_proposes_si_service_present():
    bot = MagicMock()
    bot.web_search = None
    bot.action_service.get_tool_definitions.return_value = [_action_tool("create_action_task")]
    tools = await build_voice_tools(bot)
    assert "create_action_task" in _names(tools)


@pytest.mark.asyncio
async def test_create_reminder_utilise_la_chambre():
    bot = MagicMock()
    bot.config.bot.bedroom_channel_id = 1485380606224502844
    bot.config.admin_ids = []
    bot.action_service.execute_tool = AsyncMock(return_value={"status": "ok"})
    member = MagicMock(); member.id = 42
    service = MagicMock()
    service._channel.members = [member]
    service._channel.guild.id = 999
    executor = make_voice_tool_executor(bot, service, current_speaker_id=lambda: "42")
    out = await executor("create_action_task", json.dumps({"foo": "bar"}))
    assert json.loads(out)["status"] == "ok"
    kwargs = bot.action_service.execute_tool.await_args.kwargs
    assert kwargs["channel_id"] == "1485380606224502844"
    assert kwargs["user_id"] == "42"
    assert kwargs["guild_id"] == "999"


@pytest.mark.asyncio
async def test_create_reminder_refuse_sans_chambre():
    bot = MagicMock()
    bot.config.bot.bedroom_channel_id = None
    bot.action_service.execute_tool = AsyncMock()
    service = MagicMock()
    executor = make_voice_tool_executor(bot, service, current_speaker_id=lambda: "42")
    out = await executor("create_action_task", json.dumps({}))
    assert json.loads(out)["status"] == "denied"
    bot.action_service.execute_tool.assert_not_awaited()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/discord/voice/test_voice_tools_reminder.py -v`
Expected: FAIL — outils action absents / route inconnue

- [ ] **Step 3: Implement**

Dans `build_voice_tools` (tools.py), avant `return tools` :

```python
    action_service = getattr(bot, "action_service", None)
    if action_service is not None:
        tools.extend(action_service.get_tool_definitions())
```

Dans `executor`, router les outils action (avant le `return ... "Outil inconnu"`). Helper de résolution du membre + rôles via import paresseux :

```python
        if name in ("create_action_task", "cancel_action_task", "list_action_tasks"):
            from bot.discord.handlers import _resolve_discord_roles
            a = json.loads(arguments or "{}")
            speaker_id = current_speaker_id()
            channel = getattr(service, "_channel", None)
            member = None
            if channel is not None and speaker_id is not None:
                member = next((m for m in channel.members if str(m.id) == str(speaker_id)), None)
            user_roles = _resolve_discord_roles(member) if member is not None else []
            admin_ids = [str(x) for x in getattr(bot.config, "admin_ids", [])]
            if speaker_id is not None and str(speaker_id) in admin_ids:
                user_roles.append("admin")
            # Création → besoin d'un salon cible (la chambre). Refus propre sinon.
            if name == "create_action_task":
                bedroom = getattr(bot.config.bot, "bedroom_channel_id", None)
                if bedroom is None:
                    return json.dumps({"status": "denied",
                                       "message": "Je ne sais pas encore où poster tes rappels."})
                channel_id = str(bedroom)
            else:
                channel_id = None
            guild_id = str(channel.guild.id) if channel is not None and getattr(channel, "guild", None) else None
            result = await bot.action_service.execute_tool(
                name, a, user_id=str(speaker_id), platform="discord",
                user_roles=user_roles, channel_id=channel_id, guild_id=guild_id,
            )
            return json.dumps(result)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/discord/voice/test_voice_tools_reminder.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the whole voice suite (no regression)**

Run: `python3 -m pytest tests/discord/voice/ -v`
Expected: PASS (toute la suite vocale verte)

- [ ] **Step 6: Commit**

```bash
git add bot/discord/voice/tools.py tests/discord/voice/test_voice_tools_reminder.py
git commit -m "feat(voice): rappels en vocal délivrés dans la chambre de Wally"
```

---

### Task 6: Santé des canaux configurés au démarrage

**Files:**
- Create: `bot/discord/channel_health.py`
- Modify: `bot/discord/bot.py` (`on_ready`, ~ligne 343 : appeler le rapport)
- Test: `tests/discord/test_channel_health.py` (créer)

**Interfaces:**
- Consumes: `bot.config.bot.notification_channel_id` / `.bedroom_channel_id` / `.journal_channel_id` ; `ChannelDirectory.load(path)` (`bot/intelligence/channels.py`) → `.channels` (list de `ChannelInfo(id, name, type, purpose)`) ; `bot.get_channel(int)` ; `await bot.fetch_channel(int)` (lève `discord.NotFound` si mort) ; `await bot.fetch_user(int)` puis `.send(text)` ; `config.bot.owner_discord_id`.
- Produces: `async def find_dead_channels(bot, channels_md_path) -> list[tuple[str, str]]` (liste `(id, provenance)`) ; `async def report_dead_channels(bot, channels_md_path=None) -> None` (log WARNING + DM créateur si au moins un mort).

- [ ] **Step 1: Write the failing test**

```python
# tests/discord/test_channel_health.py
import pytest
from unittest.mock import AsyncMock, MagicMock
import discord
from bot.discord.channel_health import find_dead_channels, report_dead_channels


def _bot_with_config(notif=None, bedroom=None, journal=None):
    bot = MagicMock()
    bot.config.bot.notification_channel_id = notif
    bot.config.bot.bedroom_channel_id = bedroom
    bot.config.bot.journal_channel_id = journal
    return bot


@pytest.mark.asyncio
async def test_canal_vivant_non_signale(tmp_path):
    bot = _bot_with_config(notif=111)
    bot.get_channel.return_value = object()        # présent dans le cache → vivant
    dead = await find_dead_channels(bot, tmp_path / "absent.md")
    assert dead == []


@pytest.mark.asyncio
async def test_canal_mort_detecte(tmp_path):
    bot = _bot_with_config(notif=111)
    bot.get_channel.return_value = None
    bot.fetch_channel = AsyncMock(side_effect=discord.NotFound(MagicMock(), "gone"))
    dead = await find_dead_channels(bot, tmp_path / "absent.md")
    assert [d[0] for d in dead] == ["111"]
    assert "notification_channel_id" in dead[0][1]


@pytest.mark.asyncio
async def test_report_dm_createur_si_mort(tmp_path):
    bot = _bot_with_config(notif=111)
    bot.config.bot.owner_discord_id = "610550333042589752"
    bot.get_channel.return_value = None
    bot.fetch_channel = AsyncMock(side_effect=discord.NotFound(MagicMock(), "gone"))
    owner = MagicMock(); owner.send = AsyncMock()
    bot.fetch_user = AsyncMock(return_value=owner)
    await report_dead_channels(bot, tmp_path / "absent.md")
    owner.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_report_pas_de_dm_si_tout_vivant(tmp_path):
    bot = _bot_with_config(notif=111)
    bot.config.bot.owner_discord_id = "610550333042589752"
    bot.get_channel.return_value = object()
    bot.fetch_user = AsyncMock()
    await report_dead_channels(bot, tmp_path / "absent.md")
    bot.fetch_user.assert_not_awaited()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/discord/test_channel_health.py -v`
Expected: FAIL — `ModuleNotFoundError: bot.discord.channel_health`

- [ ] **Step 3: Implement `channel_health.py`**

```python
"""Validation au démarrage des channel ids configurés : prévient si l'un est mort."""
from pathlib import Path

import discord
from loguru import logger


async def _is_dead(bot, channel_id: int) -> bool:
    """Un canal est mort s'il n'est ni dans le cache ni récupérable via l'API."""
    if bot.get_channel(channel_id) is not None:
        return False
    try:
        await bot.fetch_channel(channel_id)
        return False
    except discord.NotFound:
        return True
    except Exception as e:  # noqa: BLE001 — accès refusé / réseau : on signale sans planter
        logger.warning("channel_health: {id} non vérifiable ({e})", id=channel_id, e=e)
        return True


async def find_dead_channels(bot, channels_md_path) -> list[tuple[str, str]]:
    """Retourne [(id, provenance)] pour chaque channel id configuré introuvable."""
    candidates: list[tuple[int, str]] = []
    bot_cfg = bot.config.bot
    for attr in ("notification_channel_id", "bedroom_channel_id", "journal_channel_id"):
        val = getattr(bot_cfg, attr, None)
        if val:
            candidates.append((int(val), f"config.bot.{attr}"))
    try:
        from bot.intelligence.channels import ChannelDirectory
        directory = ChannelDirectory.load(Path(channels_md_path))
        for c in directory.channels:
            candidates.append((int(c.id), f"CHANNELS.md ({c.name})"))
    except Exception as e:  # noqa: BLE001 — CHANNELS.md absent/illisible : on continue
        logger.warning("channel_health: CHANNELS.md illisible ({e})", e=e)

    dead: list[tuple[str, str]] = []
    for cid, origin in candidates:
        if await _is_dead(bot, cid):
            dead.append((str(cid), origin))
    return dead


async def report_dead_channels(bot, channels_md_path=None) -> None:
    """Log WARNING + DM au créateur si au moins un channel id configuré est mort."""
    if channels_md_path is None:
        channels_md_path = (
            Path(__file__).parent.parent / "intelligence" / "persona" / "CHANNELS.md"
        )
    try:
        dead = await find_dead_channels(bot, channels_md_path)
    except Exception as e:  # noqa: BLE001
        logger.warning("channel_health: scan a échoué ({e})", e=e)
        return
    if not dead:
        logger.info("channel_health: tous les canaux configurés sont vivants")
        return
    lines = [f"- {cid} ({origin})" for cid, origin in dead]
    logger.warning("channel_health: {n} canal(aux) mort(s):\n{l}", n=len(dead), l="\n".join(lines))
    owner_id = getattr(bot.config.bot, "owner_discord_id", "")
    if not owner_id:
        return
    try:
        owner = await bot.fetch_user(int(owner_id))
        body = "⚠️ Canaux configurés introuvables (supprimés ou accès perdu) :\n" + "\n".join(lines)
        await owner.send(body)
    except Exception as e:  # noqa: BLE001
        logger.warning("channel_health: DM créateur a échoué ({e})", e=e)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/discord/test_channel_health.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Call it from `on_ready`**

Dans `bot/discord/bot.py`, méthode `on_ready`, après les `start()` existants :

```python
        from bot.discord.channel_health import report_dead_channels
        try:
            await report_dead_channels(self)
        except Exception as e:  # noqa: BLE001
            logger.warning("channel_health au boot a échoué: {e}", e=e)
```

- [ ] **Step 6: Commit**

```bash
git add bot/discord/channel_health.py bot/discord/bot.py tests/discord/test_channel_health.py
git commit -m "feat(discord): valide les channel ids configurés au démarrage"
```

---

### Task 7: Vérification finale

- [ ] **Step 1: Run the full suite**

Run: `python3 -m pytest tests/ -q`
Expected: la suite passe (baseline connue : ~2 échecs préexistants spam + cost, non liés à ce chantier — vérifier qu'aucun NOUVEL échec n'apparaît).

- [ ] **Step 2: Compile check des fichiers touchés**

Run: `python3 -m py_compile bot/discord/voice/tools.py bot/discord/voice/brain.py bot/discord/channel_health.py bot/discord/bot.py bot/config.py`
Expected: aucune sortie (OK)

- [ ] **Step 3: Manuel — note pour le déploiement**

Le backend n'est pas bind-mount : le déploiement de ce chantier nécessite un **rebuild d'image** Docker. Le signaler à l'utilisateur (ne pas déployer sans son accord).

---

## Self-Review

**Spec coverage :**
- Composant 1 (recherche à voix haute) → Tasks 2 + 3 ✓
- Composant 2 (notes) → Task 4 ✓
- Composant 3 (rappels → chambre, refus si pas de chambre) → Tasks 1 + 5 ✓
- Composant 4 (santé canaux au boot, DM créateur) → Task 6 ✓
- Contrainte « aucun DM hors créateur » → seul DM = `report_dead_channels` vers `owner_discord_id` ; rappels sans chambre = refus, pas de DM ✓
- `bedroom_channel_id` config + hot-reload via save() → Task 1 ✓

**Placeholders :** aucun « TBD/TODO » ; chaque step de code montre le code complet.

**Type consistency :** `build_voice_tools(bot) -> list[dict]`, `_search_aloud(bot, service, query) -> str`, `generate_search_filler(bot, query) -> {"amorce", "bruits"}`, `find_dead_channels(bot, path) -> list[tuple[str,str]]`, `report_dead_channels(bot, path=None) -> None` — noms et signatures cohérents entre tâches. `execute_tool(...)` appelé en kwargs conformes à `bot/intelligence/actions/service.py:114`.

**Note d'implémentation (cycle d'import) :** `bot.discord.handlers` importe `VOICE_TOOLS` depuis `voice.tools`. Donc `voice.tools` importe `_NOTE_TOOLS` et `_resolve_discord_roles` **en paresseux** (dans le corps des fonctions), jamais au niveau module. Idem `build_voice_tools` importé en local dans `brain._respond_once`.
