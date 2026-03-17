# Discord Vision Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre à Wally d'analyser les images Discord quand il est triggeré, via le même pipeline OpenAI que le texte.

**Architecture:** Deux modifications ciblées — `openai_client.py` reçoit un nouveau paramètre `image_urls` et construit le contenu multimodal selon l'API utilisée (Chat Completions ou Responses API) ; `handlers.py` extrait les URLs des pièces jointes image et les passe à `complete()`.

**Tech Stack:** discord.py `message.attachments`, OpenAI Python SDK (Chat Completions multimodal + Responses API multimodal), pytest/AsyncMock

---

## File Map

| Fichier | Rôle |
|---|---|
| `bot/core/openai_client.py` | Ajouter `FALLBACK_IMAGE_RESPONSE`, `_build_image_content()`, `image_urls` param dans `complete()` |
| `bot/discord/handlers.py` | Extraire les URLs image, passer à `complete()`, stocker `"[image]"` en mémoire si pas de texte |
| `tests/test_openai_client.py` | Tests : formats multimodal, fallback image vs générique |
| `tests/test_discord_handlers.py` | Tests : extraction, limite 4, texte par défaut, tag mémoire |

---

## Task 1 — OpenAI client : support vision

**Files:**
- Modify: `bot/core/openai_client.py`
- Test: `tests/test_openai_client.py`

- [ ] **Step 1 : Écrire les tests failing**

Ajouter à la fin de `tests/test_openai_client.py` :

```python
# ── Vision ────────────────────────────────────────────────────────────────────

from bot.core.openai_client import FALLBACK_IMAGE_RESPONSE, FALLBACK_RESPONSE


def test_build_image_content_chat_completions():
    config = make_config()
    db = make_db()
    client = OpenAIClient(config, db)

    result = client._build_image_content(
        "bonjour", ["http://img1.png", "http://img2.png"], use_responses_api=False
    )

    assert result[0] == {"type": "text", "text": "bonjour"}
    assert result[1] == {"type": "image_url", "image_url": {"url": "http://img1.png"}}
    assert result[2] == {"type": "image_url", "image_url": {"url": "http://img2.png"}}
    assert len(result) == 3


def test_build_image_content_responses_api():
    config = make_config()
    db = make_db()
    client = OpenAIClient(config, db)

    result = client._build_image_content(
        "bonjour", ["http://img1.png"], use_responses_api=True
    )

    assert result[0] == {"type": "input_text", "text": "bonjour"}
    assert result[1] == {"type": "input_image", "image_url": "http://img1.png"}
    assert len(result) == 2


@pytest.mark.asyncio
async def test_complete_with_images_transforms_last_message():
    config = make_config()
    db = make_db()
    client = OpenAIClient(config, db)

    captured = {}

    async def capture_create(**kwargs):
        captured["messages"] = kwargs["messages"]
        return make_mock_response("Je vois une image!")

    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(side_effect=capture_create)
    ):
        await client.complete(
            "System",
            [{"role": "user", "content": "regarde"}],
            image_urls=["https://cdn.discord.com/img.png"],
        )

    last_content = captured["messages"][-1]["content"]
    assert isinstance(last_content, list)
    assert last_content[0] == {"type": "text", "text": "regarde"}
    assert last_content[1] == {"type": "image_url", "image_url": {"url": "https://cdn.discord.com/img.png"}}


@pytest.mark.asyncio
async def test_complete_image_error_returns_image_fallback():
    config = make_config()
    db = make_db()
    client = OpenAIClient(config, db)

    with patch.object(
        client._client.chat.completions,
        "create",
        new=AsyncMock(side_effect=Exception("Invalid image URL")),
    ):
        result = await client.complete(
            "System",
            [{"role": "user", "content": "regarde"}],
            image_urls=["https://invalid.png"],
        )

    assert result == FALLBACK_IMAGE_RESPONSE


@pytest.mark.asyncio
async def test_complete_no_images_uses_generic_fallback():
    config = make_config()
    db = make_db()
    client = OpenAIClient(config, db)

    with patch.object(
        client._client.chat.completions,
        "create",
        new=AsyncMock(side_effect=Exception("Server error")),
    ):
        with patch("asyncio.sleep", new=AsyncMock()):
            result = await client.complete(
                "System",
                [{"role": "user", "content": "bonjour"}],
            )

    assert result == FALLBACK_RESPONSE
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```bash
cd /opt/stacks/wally-ai
pytest tests/test_openai_client.py::test_build_image_content_chat_completions tests/test_openai_client.py::test_build_image_content_responses_api tests/test_openai_client.py::test_complete_with_images_transforms_last_message tests/test_openai_client.py::test_complete_image_error_returns_image_fallback tests/test_openai_client.py::test_complete_no_images_uses_generic_fallback -v
```

Attendu : **5 FAILED** (ImportError ou AttributeError)

- [ ] **Step 3 : Implémenter dans `bot/core/openai_client.py`**

**3a.** Ajouter la constante après `FALLBACK_RESPONSE` (ligne ~39) :

```python
FALLBACK_IMAGE_RESPONSE = "Désolé, j'ai une poussière dans l'œil… j'arrive pas à la voir 👁️"
```

**3b.** Ajouter la méthode `_build_image_content` dans la classe `OpenAIClient`, avant `complete()` :

```python
def _build_image_content(
    self, text: str, image_urls: list[str], use_responses_api: bool
) -> list[dict]:
    if use_responses_api:
        content = [{"type": "input_text", "text": text}]
        for url in image_urls:
            content.append({"type": "input_image", "image_url": url})
    else:
        content = [{"type": "text", "text": text}]
        for url in image_urls:
            content.append({"type": "image_url", "image_url": {"url": url}})
    return content
```

**3c.** Modifier la signature de `complete()` :

```python
async def complete(
    self,
    system_prompt: str,
    messages: list[dict],
    model: Optional[str] = None,
    purpose: str = "response",
    image_urls: list[str] | None = None,
) -> str:
```

**3d.** Ajouter la transformation du contenu multimodal juste après l'assemblage de `full_messages` dans `complete()` :

```python
full_messages = [{"role": "system", "content": system_prompt}] + messages

if image_urls:
    last_msg = full_messages[-1]
    last_msg["content"] = self._build_image_content(
        last_msg["content"], image_urls, _uses_responses_api(model)
    )
```

**3e.** Rendre le fallback image-aware dans la branche Responses API de `complete()` :

```python
if _uses_responses_api(model):
    try:
        return await self._complete_responses_api(model, full_messages, purpose)
    except Exception as exc:
        logger.error("OpenAI Responses API error: {e}", e=exc)
        return FALLBACK_IMAGE_RESPONSE if image_urls else FALLBACK_RESPONSE
```

**3f.** Rendre le fallback image-aware en fin de boucle Chat Completions — changer le `return FALLBACK_RESPONSE` final (dernière ligne de `complete()`) :

```python
return FALLBACK_IMAGE_RESPONSE if image_urls else FALLBACK_RESPONSE
```

- [ ] **Step 4 : Vérifier que les nouveaux tests passent**

```bash
pytest tests/test_openai_client.py -v
```

Attendu : **tous les tests PASSED**

- [ ] **Step 5 : Commit**

```bash
git add bot/core/openai_client.py tests/test_openai_client.py
git commit -m "feat(openai): add vision support with multimodal content builder"
```

---

## Task 2 — Discord handler : extraction des images

**Files:**
- Modify: `bot/discord/handlers.py`
- Test: `tests/test_discord_handlers.py`

- [ ] **Step 1 : Écrire les tests failing**

**1a.** Modifier `make_message()` dans `tests/test_discord_handlers.py` pour accepter les pièces jointes. Ajouter le paramètre `attachments=None` et la ligne correspondante :

```python
def make_message(content="wally bonjour", author_bot=False, mentions=None, attachments=None):
    """Build a minimal discord.Message-like mock."""
    msg = MagicMock()
    msg.content = content
    msg.author.bot = author_bot
    msg.author.id = 12345
    msg.author.display_name = "TestUser"
    msg.guild.id = 99999
    msg.channel.id = 777
    msg.channel.typing = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=None),
        __aexit__=AsyncMock(return_value=None),
    ))
    msg.mentions = mentions or []
    msg.add_reaction = AsyncMock()
    msg.remove_reaction = AsyncMock()
    msg.reply = AsyncMock()
    msg.channel.send = AsyncMock()
    msg.attachments = attachments or []
    return msg
```

**1b.** Ajouter le helper `make_attachment()` juste après `make_message()` :

```python
def make_attachment(url: str, content_type: str = "image/png"):
    att = MagicMock()
    att.url = url
    att.content_type = content_type
    return att
```

**1c.** Ajouter les nouveaux tests en fin de fichier :

```python
# ── Vision ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_respond_extracts_image_urls():
    """_respond extrait les URLs image et les passe à complete() via image_urls."""
    bot = make_bot()
    message = make_message(
        content="wally regarde",
        attachments=[make_attachment("https://cdn.discord.com/img.png")],
    )
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])

    call_kwargs = bot.openai.complete.call_args.kwargs
    assert call_kwargs["image_urls"] == ["https://cdn.discord.com/img.png"]


@pytest.mark.asyncio
async def test_respond_limits_4_images():
    """_respond envoie au maximum 4 images à complete()."""
    bot = make_bot()
    attachments = [make_attachment(f"https://cdn.discord.com/img{i}.png") for i in range(6)]
    message = make_message(content="wally regarde", attachments=attachments)
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])

    call_kwargs = bot.openai.complete.call_args.kwargs
    assert len(call_kwargs["image_urls"]) == 4


@pytest.mark.asyncio
async def test_respond_no_text_uses_default_prompt():
    """Message image-only : le texte envoyé à OpenAI est 'Regarde cette image.'"""
    bot = make_bot()
    message = make_message(
        content="",
        attachments=[make_attachment("https://cdn.discord.com/img.png")],
    )
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])

    call_args = bot.openai.complete.call_args
    user_content = call_args.args[1][0]["content"]
    assert "Regarde cette image." in user_content


@pytest.mark.asyncio
async def test_respond_image_only_memory_tag():
    """Message image sans texte : append_message reçoit '[image]' comme contenu."""
    bot = make_bot()
    message = make_message(
        content="",
        attachments=[make_attachment("https://cdn.discord.com/img.png")],
    )
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])

    calls = bot.memory.append_message.call_args_list
    # Premier appel : message de l'utilisateur
    stored_content = calls[0].args[2]
    assert stored_content == "[image]"


@pytest.mark.asyncio
async def test_respond_no_images_no_image_urls_kwarg():
    """Sans pièce jointe image, image_urls n'est pas passé (None)."""
    bot = make_bot()
    message = make_message(content="wally bonjour", attachments=[])
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])

    call_kwargs = bot.openai.complete.call_args.kwargs
    assert call_kwargs.get("image_urls") is None


@pytest.mark.asyncio
async def test_respond_non_image_attachment_ignored():
    """Les pièces jointes non-image (PDF, etc.) sont ignorées."""
    bot = make_bot()
    pdf = make_attachment("https://cdn.discord.com/doc.pdf", content_type="application/pdf")
    message = make_message(content="wally regarde", attachments=[pdf])
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])

    call_kwargs = bot.openai.complete.call_args.kwargs
    assert call_kwargs.get("image_urls") is None
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```bash
pytest tests/test_discord_handlers.py::test_respond_extracts_image_urls tests/test_discord_handlers.py::test_respond_limits_4_images tests/test_discord_handlers.py::test_respond_no_text_uses_default_prompt tests/test_discord_handlers.py::test_respond_image_only_memory_tag tests/test_discord_handlers.py::test_respond_no_images_no_image_urls_kwarg tests/test_discord_handlers.py::test_respond_non_image_attachment_ignored -v
```

Attendu : **6 FAILED**

- [ ] **Step 3 : Implémenter dans `bot/discord/handlers.py`**

Dans `_respond()`, modifier le bloc de construction de `user_content` et l'appel à `complete()`. Remplacer la section à partir de `user_content = (` jusqu'à `openai_messages = [...]` par :

```python
# Extraction des images
image_urls = [
    a.url for a in message.attachments
    if a.content_type and a.content_type.startswith("image/")
][:4]

# Texte à envoyer (substitution si message image-only)
text_content = message.content or ("Regarde cette image." if image_urls else "")

user_content = (
    prelude_block
    + context_block
    + f"\n[{message.author.display_name}]: {text_content}"
)

if first_contact:
    user_content = (
        f"[CONTEXTE: C'est la première fois que {message.author.display_name} "
        f"t'adresse la parole sur ce serveur. Commence ta réponse par une "
        f"bienvenue chaleureuse en une phrase courte, puis réponds à son message.]\n\n"
        + user_content
    )

openai_messages = [{"role": "user", "content": user_content}]
```

Modifier l'appel à `complete()` :

```python
async with message.channel.typing():
    reply = await bot.openai.complete(
        system_prompt, openai_messages, purpose="discord_response",
        image_urls=image_urls or None,
    )
```

Modifier le stockage mémoire en fin de `_respond()` pour utiliser `stored_content` :

```python
stored_content = message.content or "[image]"
bot.memory.append_message(str(message.channel.id), message.author.display_name, stored_content)
bot.memory.append_message(str(message.channel.id), "Wally", reply)
```

- [ ] **Step 4 : Vérifier que tous les tests passent**

```bash
pytest tests/test_discord_handlers.py -v
```

Attendu : **tous PASSED**

- [ ] **Step 5 : Lancer la suite complète**

```bash
pytest tests/ -v
```

Attendu : **tous PASSED** (aucune régression)

- [ ] **Step 6 : Commit**

```bash
git add bot/discord/handlers.py tests/test_discord_handlers.py
git commit -m "feat(discord): extract image attachments and pass to OpenAI for vision analysis"
```
