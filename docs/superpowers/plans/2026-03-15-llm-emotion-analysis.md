# LLM Emotion Analysis Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer NRCLex par une analyse émotionnelle LLM avec historique, ajouter l'apprentissage persistant des mots français, supporter la Responses API pour les modèles de raisonnement, et ajouter une commande `/wally journal`.

**Architecture:** `OpenAIClient.complete()` route vers `_complete_responses_api()` pour les modèles `gpt-5*`/`o1`/`o3`/`o4`, et vers Chat Completions pour les autres. `EmotionEngine` reçoit le client OpenAI via injection et appelle `complete_secondary()` avec le contexte conversationnel pour obtenir des deltas JSON. Les nouveaux mots appris sont persistés dans `data/fr_emotion_words.json` avec écriture atomique.

**Tech Stack:** Python 3.11, openai SDK v2, asyncio, discord.py 2.x, pytest + unittest.mock

---

## File Map

| Fichier | Action | Rôle |
|---|---|---|
| `bot/core/openai_client.py` | Modifier | Routing Responses API / Chat Completions |
| `bot/core/emotion.py` | Modifier | Analyse LLM, apprentissage, persistance |
| `bot/discord/handlers.py` | Modifier | Passer `context_messages` à `_post_process` |
| `bot/twitch/handlers.py` | Modifier | Idem |
| `bot/main.py` | Modifier | Injection OpenAI → EmotionEngine, journal → discord_bot |
| `bot/discord/commands/journal_cmd.py` | Créer | Commande `/wally journal` |
| `bot/discord/bot.py` | Modifier | Ajouter `journal` attr + `JournalCog` |
| `tests/test_openai_client.py` | Modifier | 3 nouveaux tests Responses API |
| `tests/test_emotion.py` | Modifier | 8 nouveaux tests LLM + apprentissage |

---

## Chunk 1: OpenAIClient — Responses API routing

### Task 1: Ajouter la détection et le routing Responses API

**Files:**
- Modify: `bot/core/openai_client.py`
- Modify: `tests/test_openai_client.py`

- [ ] **Écrire les tests qui vont échouer**

Ajouter à `tests/test_openai_client.py` :

```python
from bot.core.openai_client import OpenAIClient, estimate_cost, _uses_responses_api


def test_uses_responses_api_detection():
    assert _uses_responses_api("gpt-5-mini") is True
    assert _uses_responses_api("gpt-5.2-mini") is True
    assert _uses_responses_api("o1-mini") is True
    assert _uses_responses_api("o3-mini") is True
    assert _uses_responses_api("o4") is True
    assert _uses_responses_api("gpt-4o") is False
    assert _uses_responses_api("gpt-4o-mini") is False


@pytest.mark.asyncio
async def test_complete_routes_to_responses_api_for_gpt5():
    config = make_config()
    config.openai.primary_model = "gpt-5-mini"
    db = make_db()
    client = OpenAIClient(config, db)

    mock_response = MagicMock()
    mock_response.output_text = "Réponse LLM"
    mock_response.usage = MagicMock(input_tokens=10, output_tokens=5)

    with patch.object(client, "_complete_responses_api", new=AsyncMock(return_value="Réponse LLM")) as mock_resp:
        result = await client.complete("System", [{"role": "user", "content": "Hi"}])

    mock_resp.assert_called_once()
    assert result == "Réponse LLM"


@pytest.mark.asyncio
async def test_complete_routes_to_chat_completions_for_gpt4():
    config = make_config()
    db = make_db()
    client = OpenAIClient(config, db)

    mock_response = make_mock_response("Chat response")
    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(return_value=mock_response)
    ) as mock_create:
        result = await client.complete("System", [{"role": "user", "content": "Hi"}])

    mock_create.assert_called_once()
    assert result == "Chat response"
```

- [ ] **Vérifier que les tests échouent**

```bash
cd /opt/stacks/wally-ai
python3 -m pytest tests/test_openai_client.py::test_uses_responses_api_detection tests/test_openai_client.py::test_complete_routes_to_responses_api_for_gpt5 tests/test_openai_client.py::test_complete_routes_to_chat_completions_for_gpt4 -v
```

Attendu : `ImportError` ou `FAILED`

- [ ] **Implémenter le routing dans `bot/core/openai_client.py`**

Ajouter après les imports, avant la classe :

```python
_RESPONSES_API_PREFIXES = ("o1", "o3", "o4", "gpt-5")


def _uses_responses_api(model: str) -> bool:
    return any(model.startswith(p) for p in _RESPONSES_API_PREFIXES)
```

Ajouter dans la classe `OpenAIClient`, après `__init__` :

```python
async def _complete_responses_api(
    self, model: str, messages: list[dict], purpose: str
) -> str:
    response = await self._client.responses.create(
        model=model,
        input=messages,
        reasoning={"effort": "low"},
        text={"verbosity": "medium"},
    )
    text = response.output_text
    if response.usage:
        cost = estimate_cost(
            model, response.usage.input_tokens, response.usage.output_tokens
        )
        await self._db.log_cost(
            model,
            response.usage.input_tokens,
            response.usage.output_tokens,
            cost,
            purpose,
        )
        logger.info(
            "OpenAI {model} (Responses) — {inp}in/{out}out tokens, ${cost:.6f} [{purpose}]",
            model=model,
            inp=response.usage.input_tokens,
            out=response.usage.output_tokens,
            cost=cost,
            purpose=purpose,
        )
    return text
```

Modifier le début de `complete()` pour router avant la boucle de retry :

```python
async def complete(
    self,
    system_prompt: str,
    messages: list[dict],
    model: Optional[str] = None,
    purpose: str = "response",
) -> str:
    model = model or self._config.openai.primary_model
    full_messages = [{"role": "system", "content": system_prompt}] + messages

    if _uses_responses_api(model):
        return await self._complete_responses_api(model, full_messages, purpose)

    for attempt in range(3):
        # ... reste du code inchangé
```

- [ ] **Vérifier que les tests passent**

```bash
python3 -m pytest tests/test_openai_client.py -v
```

Attendu : tous les tests passent (y compris les anciens).

- [ ] **Commit**

```bash
git add bot/core/openai_client.py tests/test_openai_client.py
git commit -m "feat: route reasoning models (gpt-5*, o1/o3/o4) to Responses API in OpenAIClient"
```

---

## Chunk 2: EmotionEngine — analyse LLM + apprentissage

### Task 2: Injection OpenAI + analyse LLM + persistance FR_EMOTION_WORDS

**Files:**
- Modify: `bot/core/emotion.py`
- Modify: `tests/test_emotion.py`

- [ ] **Écrire les tests qui vont échouer**

Ajouter à `tests/test_emotion.py` :

```python
import json
import os
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ── LLM analysis ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_process_message_uses_llm_when_openai_injected():
    engine = EmotionEngine(make_config())
    mock_openai = MagicMock()
    mock_openai.complete_secondary = AsyncMock(return_value=json.dumps({
        "deltas": {"anger": 0.2, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        "new_words": []
    }))
    engine.set_openai_client(mock_openai)

    await engine.process_message("t'es nul", trust_score=0.5, context_messages=[
        {"author": "Alice", "content": "t'es nul"}
    ])

    assert engine.get_state()["anger"] == pytest.approx(0.2, abs=0.01)
    mock_openai.complete_secondary.assert_called_once()


@pytest.mark.asyncio
async def test_process_message_falls_back_on_llm_failure():
    engine = EmotionEngine(make_config())
    mock_openai = MagicMock()
    mock_openai.complete_secondary = AsyncMock(side_effect=Exception("API error"))
    engine.set_openai_client(mock_openai)

    # Should not raise — falls back to NRCLex (English text to get non-zero)
    await engine.process_message("happy joyful", trust_score=0.5, context_messages=[
        {"author": "Alice", "content": "happy joyful"}
    ])
    # Fallback ran without error — state is valid
    assert all(0.0 <= v <= 1.0 for v in engine.get_state().values())


@pytest.mark.asyncio
async def test_process_message_falls_back_on_invalid_json():
    engine = EmotionEngine(make_config())
    mock_openai = MagicMock()
    mock_openai.complete_secondary = AsyncMock(return_value="pas du json")
    engine.set_openai_client(mock_openai)

    await engine.process_message("test", trust_score=0.5, context_messages=[
        {"author": "Alice", "content": "test"}
    ])
    assert all(0.0 <= v <= 1.0 for v in engine.get_state().values())


@pytest.mark.asyncio
async def test_process_message_without_context_uses_fallback():
    """Sans context_messages, l'analyse LLM est skippée même si OpenAI est injecté."""
    engine = EmotionEngine(make_config())
    mock_openai = MagicMock()
    mock_openai.complete_secondary = AsyncMock()
    engine.set_openai_client(mock_openai)

    await engine.process_message("happy joyful", trust_score=0.5)

    mock_openai.complete_secondary.assert_not_called()


# ── Learned words ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_learn_new_word_persisted(tmp_path):
    engine = EmotionEngine(make_config())

    with patch("bot.core.emotion._LEARNED_WORDS_PATH", str(tmp_path / "fr_emotion_words.json")):
        await engine._learn_words([{"word": "relou", "emotion": "boredom", "delta": 0.08}])

        saved = json.loads((tmp_path / "fr_emotion_words.json").read_text())
        assert ["relou", 0.08] in saved["boredom"]


@pytest.mark.asyncio
async def test_learn_word_deduplication_hardcoded():
    """Un mot déjà dans FR_EMOTION_WORDS ne doit pas être réappris."""
    engine = EmotionEngine(make_config())
    initial_count = sum(len(v) for v in engine._learned_words.values())

    # "merde" est dans FR_EMOTION_WORDS (anger)
    await engine._learn_words([{"word": "merde", "emotion": "anger", "delta": 0.10}])

    final_count = sum(len(v) for v in engine._learned_words.values())
    assert final_count == initial_count


@pytest.mark.asyncio
async def test_learn_word_invalid_emotion_ignored():
    engine = EmotionEngine(make_config())
    await engine._learn_words([{"word": "relou", "emotion": "fear", "delta": 0.08}])
    assert all("relou" not in [w for w, _ in v] for v in engine._learned_words.values())


@pytest.mark.asyncio
async def test_learn_word_invalid_delta_ignored():
    engine = EmotionEngine(make_config())
    await engine._learn_words([{"word": "relou", "emotion": "boredom", "delta": 5.0}])
    assert all("relou" not in [w for w, _ in v] for v in engine._learned_words.values())
```

- [ ] **Vérifier que les tests échouent**

```bash
python3 -m pytest tests/test_emotion.py::test_process_message_uses_llm_when_openai_injected tests/test_emotion.py::test_learn_new_word_persisted -v
```

Attendu : `AttributeError` (méthodes inexistantes)

- [ ] **Implémenter dans `bot/core/emotion.py`**

Ajouter les imports en tête du fichier :
```python
import asyncio
import json
import os
from pathlib import Path
```

Ajouter après les constantes existantes :
```python
_LEARNED_WORDS_PATH = "data/fr_emotion_words.json"
```

Modifier `EmotionEngine.__init__()` pour ajouter :
```python
self._openai = None
self._learned_words: dict[str, list[tuple[str, float]]] = {e: [] for e in EMOTIONS}
self._learned_lock = asyncio.Lock()
self._load_learned_words()
```

Ajouter les méthodes suivantes dans la classe (après `reset()`):

```python
def set_openai_client(self, client) -> None:
    """Injection du client OpenAI (pattern identique à MemoryService)."""
    self._openai = client

def _load_learned_words(self) -> None:
    """Charge les mots appris depuis le disque au démarrage."""
    try:
        with open(_LEARNED_WORDS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        for emotion in EMOTIONS:
            self._learned_words[emotion] = [
                (pair[0], float(pair[1])) for pair in data.get(emotion, [])
            ]
        logger.info("Learned emotion words loaded from {p}", p=_LEARNED_WORDS_PATH)
    except FileNotFoundError:
        pass  # premier démarrage — normal
    except Exception as exc:
        logger.warning("Failed to load learned words: {e}", e=exc)

def _is_known_word(self, word: str) -> bool:
    """Vérifie si un mot existe déjà (hardcodé ou appris) — case-insensitive."""
    word_lower = word.lower()
    for entries in FR_EMOTION_WORDS.values():
        if any(w.lower() == word_lower for w, _ in entries):
            return True
    for entries in self._learned_words.values():
        if any(w.lower() == word_lower for w, _ in entries):
            return True
    return False

@staticmethod
def _write_learned_words_sync(data: dict, path: str) -> None:
    """Écriture atomique dans un thread — ne pas appeler directement."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)

async def _save_learned_words(self) -> None:
    """Sauvegarde atomique des mots appris (lock + to_thread)."""
    async with self._learned_lock:
        data = {e: [[w, d] for w, d in self._learned_words[e]] for e in EMOTIONS}
        try:
            await asyncio.to_thread(self._write_learned_words_sync, data, _LEARNED_WORDS_PATH)
        except Exception as exc:
            logger.warning("Failed to save learned words: {e}", e=exc)

async def _learn_words(self, new_words: list[dict]) -> None:
    """Valide et ajoute les nouveaux mots appris depuis le LLM."""
    added = False
    for entry in new_words:
        word = entry.get("word", "")
        emotion = entry.get("emotion", "")
        delta = entry.get("delta", 0.0)
        if emotion not in EMOTIONS:
            continue
        if not (0.0 < delta <= MAX_DELTA_PER_MESSAGE):
            continue
        if len(word) < 2:
            continue
        if self._is_known_word(word):
            continue
        self._learned_words[emotion].append((word, float(delta)))
        logger.info("New emotion word learned: {w} → {e} ({d})", w=word, e=emotion, d=delta)
        added = True
    if added:
        await self._save_learned_words()

async def _analyze_llm(
    self, text: str, trust_score: float, context_messages: list[dict]
) -> tuple[dict[str, float], list[dict]]:
    """Analyse émotionnelle via LLM — retourne (deltas, new_words)."""
    system_prompt = (
        "Tu analyses l'état émotionnel de Wally (bot de chat) après un échange.\n"
        "Wally a 5 émotions : anger, joy, sadness, curiosity, boredom.\n"
        "Tu retournes des deltas (variations à additionner à l'état courant).\n\n"
        "Règles :\n"
        "- Chaque delta est un float entre 0.0 et 0.3\n"
        "- Si une émotion est dirigée vers un autre utilisateur et non vers Wally, divise le delta par 3\n"
        "- Si dirigée vers Wally → impact normal\n"
        "- trust_score (0.0–1.0) : trust faible amplifie anger (×2 max à trust=0.0)\n"
        "- Le dernier message est le plus important\n"
        "- new_words : mots/expressions français pertinents (max 3)\n\n"
        "Réponds uniquement en JSON valide, sans markdown :\n"
        '{"deltas": {"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}, '
        '"new_words": [{"word": "...", "emotion": "...", "delta": 0.0}]}'
    )
    context_lines = "\n".join(
        f"[{m['author']}]: {m['content']}" for m in context_messages
    )
    user_msg = (
        f"trust_score: {trust_score:.2f}\n\n"
        f"Historique récent :\n{context_lines}\n\n"
        f"Message déclencheur :\n{text}"
    )
    raw = await self._openai.complete_secondary(
        system_prompt,
        [{"role": "user", "content": user_msg}],
        purpose="emotion_analysis",
    )
    parsed = json.loads(raw)
    raw_deltas = parsed.get("deltas", {})
    deltas = {
        e: min(max(float(raw_deltas.get(e, 0.0)), 0.0), MAX_DELTA_PER_MESSAGE)
        for e in EMOTIONS
    }
    new_words = parsed.get("new_words", [])
    return deltas, new_words
```

Remplacer `process_message()` par :

```python
async def process_message(
    self, text: str, trust_score: float = 0.5, context_messages: list[dict] | None = None
) -> None:
    if self._openai is not None and context_messages:
        try:
            deltas, new_words = await self._analyze_llm(text, trust_score, context_messages)
            for emotion, delta in deltas.items():
                self.apply_delta(emotion, delta)
            if new_words:
                await self._learn_words(new_words)
            return
        except Exception as exc:
            logger.warning("LLM emotion analysis failed, using fallback: {e}", e=exc)
    # Fallback : NRCLex + FR_EMOTION_WORDS
    deltas = await self.analyze_message(text, trust_score)
    for emotion, delta in deltas.items():
        self.apply_delta(emotion, delta)
```

Dans `_analyze_sync()`, fusionner les mots appris avec FR_EMOTION_WORDS dans la boucle FR. Remplacer le bloc "Supplement with French keyword detection" par :

```python
# Supplement with French keyword detection (NRCLex is English-only)
# Merge hardcoded + learned words
text_lower = text.lower()
all_fr_words: dict[str, list[tuple[str, float]]] = {}
for emotion in EMOTIONS:
    all_fr_words[emotion] = list(FR_EMOTION_WORDS.get(emotion, [])) + list(self._learned_words.get(emotion, []))

for emotion, word_deltas in all_fr_words.items():
    fr_raw = sum(d for w, d in word_deltas if w in text_lower)
    if fr_raw > 0:
        combined = deltas.get(emotion, 0.0) + fr_raw
        if emotion == "anger":
            combined = min(combined * (1.0 + max(0.0, 1.0 - trust_score)), MAX_DELTA_PER_MESSAGE)
        else:
            combined = min(combined, MAX_DELTA_PER_MESSAGE)
        deltas[emotion] = combined
```

- [ ] **Vérifier que tous les tests passent**

```bash
python3 -m pytest tests/test_emotion.py -v
```

Attendu : tous les tests passent.

- [ ] **Commit**

```bash
git add bot/core/emotion.py tests/test_emotion.py
git commit -m "feat: LLM emotion analysis with context, French word learning + persistence"
```

---

## Chunk 3: Handlers + main.py wiring

### Task 3: Passer context_messages dans _post_process

**Files:**
- Modify: `bot/discord/handlers.py`
- Modify: `bot/twitch/handlers.py`
- Modify: `bot/main.py`

- [ ] **Mettre à jour `bot/discord/handlers.py`**

Modifier la signature de `_post_process` (ajouter `context_messages`) :

```python
async def _post_process(
    bot: "WallyDiscord",
    text: str,
    platform: str,
    user_id: str,
    guild_id: str,
    trust: float,
    context_messages: list[dict] | None = None,
) -> None:
    try:
        await bot.emotion.process_message(text, trust_score=trust, context_messages=context_messages)
        # ... reste du code inchangé
```

Dans `_respond()`, passer `context_messages` (déjà calculé) à `_post_process` :

```python
# Remplacer :
_fire(_post_process(bot, message.content, platform, user_id, guild_id, trust))
# Par :
_fire(_post_process(bot, message.content, platform, user_id, guild_id, trust, context_messages))
```

- [ ] **Mettre à jour `bot/twitch/handlers.py`**

Modifier la signature de `_post_process` Twitch :

```python
async def _post_process(
    bot: "WallyTwitch",
    text: str,
    platform: str,
    user_id: str,
    trust: float,
    context_messages: list[dict] | None = None,
) -> None:
    try:
        await bot.emotion.process_message(text, trust_score=trust, context_messages=context_messages)
        # ... reste du code inchangé
```

Dans `handle_message()`, passer `context_msgs` à `_post_process` :

```python
# Remplacer :
_fire(_post_process(bot, content, platform, user_id, trust))
# Par :
_fire(_post_process(bot, content, platform, user_id, trust, context_msgs))
```

- [ ] **Mettre à jour `bot/main.py`**

Après `openai_client = OpenAIClient(config, db)` et `memory.set_openai_client(openai_client)`, ajouter :

```python
emotion.set_openai_client(openai_client)
```

- [ ] **Vérifier que tous les tests passent**

```bash
python3 -m pytest --tb=short -q
```

Attendu : 154+ tests passent.

- [ ] **Commit**

```bash
git add bot/discord/handlers.py bot/twitch/handlers.py bot/main.py
git commit -m "feat: wire context_messages through _post_process and inject OpenAI into EmotionEngine"
```

---

## Chunk 4: Commande /wally journal

### Task 4: Créer JournalCog et exposer journal sur WallyDiscord

**Files:**
- Create: `bot/discord/commands/journal_cmd.py`
- Modify: `bot/discord/bot.py`
- Modify: `bot/main.py`

- [ ] **Créer `bot/discord/commands/journal_cmd.py`**

```python
# bot/discord/commands/journal_cmd.py
import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger


class JournalCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="journal",
        description="Génère et envoie le journal de Wally maintenant (admin)",
    )
    @app_commands.default_permissions(administrator=True)
    async def journal(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            await self.bot.journal.generate_and_send()
            await interaction.followup.send("Journal généré et envoyé.", ephemeral=True)
        except Exception as e:
            logger.error("Error generating journal on demand: {e}", e=e)
            await interaction.followup.send(
                "Erreur lors de la génération du journal.", ephemeral=True
            )
```

- [ ] **Ajouter `journal` à `WallyDiscord` dans `bot/discord/bot.py`**

Dans `__init__()`, ajouter après `self.persona = persona` :

```python
self.journal = None  # set by main.py after construction
```

Dans `setup_hook()`, ajouter :

```python
from bot.discord.commands.journal_cmd import JournalCog
await self.add_cog(JournalCog(self))
```

- [ ] **Câbler dans `bot/main.py`**

Après `discord_bot = WallyDiscord(...)`, ajouter :

```python
discord_bot.journal = journal
```

- [ ] **Vérifier que les tests passent**

```bash
python3 -m pytest --tb=short -q
```

Attendu : tous les tests passent.

- [ ] **Commit**

```bash
git add bot/discord/commands/journal_cmd.py bot/discord/bot.py bot/main.py
git commit -m "feat: add /wally journal command (admin) to trigger journal generation on demand"
```

---

## Vérification finale

- [ ] **Lancer la suite complète**

```bash
python3 -m pytest -v 2>&1 | tail -20
```

Attendu : tous les tests verts.

- [ ] **Rebuild Docker pour appliquer la contrainte openai<2.0.0**

```bash
docker compose build wally && docker compose up -d
```

- [ ] **Vérifier dans les logs que le journal ne produit plus d'erreur temperature**

```bash
docker compose logs wally --since 24h | grep -E "(journal|temperature|ERROR)"
```

Attendu : `INFO | Daily journal sent to channel ...` sans erreur 400.
