# Image Emotion Analysis Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Faire analyser le contenu émotionnel des images Discord par le LLM secondaire, en plus du texte, pour mettre à jour l'état émotionnel de Wally.

**Architecture:** On passe `image_urls` comme paramètre optionnel à travers la chaîne `_post_process` → `process_message` → `_analyze_llm` → `complete_secondary`. Le prompt LLM est enrichi quand des images sont présentes. Aucune rupture de compatibilité — tous les paramètres sont optionnels avec défaut `None`.

**Tech Stack:** Python asyncio, OpenAI API (vision multimodale), pytest, unittest.mock

---

## Fichiers modifiés

| Fichier | Modification |
|---|---|
| `bot/core/openai_client.py` | Ajouter `image_urls` à `complete_secondary()` |
| `bot/core/emotion.py` | Ajouter `image_urls` à `_analyze_llm()` et `process_message()` |
| `bot/discord/handlers.py` | Ajouter `image_urls` à `_post_process()`, passer `text_content` et `image_urls` depuis `_respond()` |
| `tests/test_emotion.py` | Ajouter 3 nouveaux tests |
| `tests/test_discord_handlers.py` | Ajouter 2 nouveaux tests |
| `tests/test_openai_client.py` | Ajouter 1 nouveau test |

---

## Task 1 : `complete_secondary` — support `image_urls`

**Files:**
- Modify: `bot/core/openai_client.py:186-197`
- Test: `tests/test_openai_client.py`

- [ ] **Étape 1 : Écrire le test qui échoue**

Ajouter à la fin de `tests/test_openai_client.py` :

```python
@pytest.mark.asyncio
async def test_complete_secondary_forwards_image_urls():
    """complete_secondary doit passer image_urls à complete()."""
    config = make_config()
    db = make_db()
    client = OpenAIClient(config, db)

    mock_response = make_mock_response("ok")
    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(return_value=mock_response)
    ) as mock_create:
        await client.complete_secondary(
            "system",
            [{"role": "user", "content": "test"}],
            image_urls=["https://example.com/img.png"],
        )
        # Le dernier message doit contenir des blocs multimodaux (type: text + type: image_url)
        call_args = mock_create.call_args
        messages = call_args.kwargs["messages"]
        last_content = messages[-1]["content"]
        assert isinstance(last_content, list)
        types = [block["type"] for block in last_content]
        assert "text" in types
        assert "image_url" in types
```

- [ ] **Étape 2 : Vérifier que le test échoue**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_openai_client.py::test_complete_secondary_forwards_image_urls -v
```

Attendu : `FAILED` — `TypeError: complete_secondary() got an unexpected keyword argument 'image_urls'`

- [ ] **Étape 3 : Implémenter le changement dans `complete_secondary`**

Dans `bot/core/openai_client.py`, remplacer la méthode `complete_secondary` (lignes 186-197) :

```python
async def complete_secondary(
    self,
    system_prompt: str,
    messages: list[dict],
    purpose: str = "summary",
    image_urls: list[str] | None = None,
) -> str:
    return await self.complete(
        system_prompt,
        messages,
        model=self._config.openai.secondary_model,
        purpose=purpose,
        image_urls=image_urls,
    )
```

- [ ] **Étape 4 : Vérifier que le test passe**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_openai_client.py -v
```

Attendu : tous les tests `PASSED`

- [ ] **Étape 5 : Commit**

```bash
git add bot/core/openai_client.py tests/test_openai_client.py
git commit -m "feat(openai): complete_secondary accepte image_urls"
```

---

## Task 2 : `_analyze_llm` — support `image_urls` + enrichissement prompt

**Files:**
- Modify: `bot/core/emotion.py:243-305`
- Test: `tests/test_emotion.py`

- [ ] **Étape 1 : Écrire les tests qui échouent**

Ajouter à la fin de `tests/test_emotion.py` :

```python
@pytest.mark.asyncio
async def test_analyze_llm_passes_image_urls_to_complete_secondary():
    """_analyze_llm doit transmettre image_urls à complete_secondary."""
    engine = EmotionEngine(make_config())
    mock_openai = MagicMock()
    mock_openai.complete_secondary = AsyncMock(return_value=json.dumps({
        "deltas": {"anger": 0.0, "joy": 0.15, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        "new_words": []
    }))
    engine.set_openai_client(mock_openai)

    await engine.process_message(
        "regarde cette image",
        trust_score=0.5,
        context_messages=[{"author": "Alice", "content": "regarde cette image"}],
        image_urls=["https://example.com/meme.png"],
    )

    call_kwargs = mock_openai.complete_secondary.call_args.kwargs
    assert call_kwargs.get("image_urls") == ["https://example.com/meme.png"]


@pytest.mark.asyncio
async def test_analyze_llm_enriches_prompt_with_images():
    """Quand image_urls est non-vide, le system_prompt doit mentionner les images."""
    engine = EmotionEngine(make_config())
    captured_prompt = {}

    async def capture_complete_secondary(system_prompt, messages, purpose="summary", image_urls=None):
        captured_prompt["system"] = system_prompt
        return json.dumps({
            "deltas": {"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
            "new_words": []
        })

    mock_openai = MagicMock()
    mock_openai.complete_secondary = capture_complete_secondary
    engine.set_openai_client(mock_openai)

    await engine.process_message(
        "voilà",
        trust_score=0.5,
        context_messages=[{"author": "Alice", "content": "voilà"}],
        image_urls=["https://example.com/img.png"],
    )

    assert "Images jointes" in captured_prompt["system"]


@pytest.mark.asyncio
async def test_analyze_llm_no_image_urls_no_prompt_enrichment():
    """Sans images, le system_prompt ne doit PAS contenir la directive images."""
    engine = EmotionEngine(make_config())
    captured_prompt = {}

    async def capture_complete_secondary(system_prompt, messages, purpose="summary", image_urls=None):
        captured_prompt["system"] = system_prompt
        return json.dumps({
            "deltas": {"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
            "new_words": []
        })

    mock_openai = MagicMock()
    mock_openai.complete_secondary = capture_complete_secondary
    engine.set_openai_client(mock_openai)

    await engine.process_message(
        "texte sans image",
        trust_score=0.5,
        context_messages=[{"author": "Alice", "content": "texte sans image"}],
    )

    assert "Images jointes" not in captured_prompt["system"]


@pytest.mark.asyncio
async def test_process_message_image_only_llm_available():
    """Message image-seul avec texte de substitution : le LLM est appelé avec image_urls."""
    engine = EmotionEngine(make_config())
    mock_openai = MagicMock()
    mock_openai.complete_secondary = AsyncMock(return_value=json.dumps({
        "deltas": {"anger": 0.0, "joy": 0.1, "sadness": 0.0, "curiosity": 0.05, "boredom": 0.0},
        "new_words": []
    }))
    engine.set_openai_client(mock_openai)

    # handlers.py passe "Regarde cette image." quand message.content est vide
    await engine.process_message(
        "Regarde cette image.",
        trust_score=0.5,
        context_messages=[{"author": "Alice", "content": "Regarde cette image."}],
        image_urls=["https://example.com/meme.png"],
    )

    mock_openai.complete_secondary.assert_called_once()
    call_kwargs = mock_openai.complete_secondary.call_args.kwargs
    assert call_kwargs.get("image_urls") == ["https://example.com/meme.png"]
    assert engine.get_state()["joy"] == pytest.approx(0.1, abs=0.01)


@pytest.mark.asyncio
async def test_process_message_image_only_llm_unavailable():
    """Message image-seul, LLM indisponible : fallback NRCLex sans erreur."""
    engine = EmotionEngine(make_config())
    # Pas d'openai injecté → fallback NRCLex
    await engine.process_message(
        "Regarde cette image.",
        trust_score=0.5,
        context_messages=[{"author": "Alice", "content": "Regarde cette image."}],
        image_urls=["https://example.com/img.png"],
    )
    # Pas d'exception, état valide
    assert all(0.0 <= v <= 1.0 for v in engine.get_state().values())


@pytest.mark.asyncio
async def test_process_message_text_image_llm_error_falls_back():
    """Texte + images, LLM échoue : fallback NRCLex sur le texte seul."""
    engine = EmotionEngine(make_config())
    mock_openai = MagicMock()
    mock_openai.complete_secondary = AsyncMock(side_effect=Exception("timeout"))
    engine.set_openai_client(mock_openai)

    # Pas d'exception levée — fallback silencieux vers NRCLex
    await engine.process_message(
        "happy joyful",
        trust_score=0.5,
        context_messages=[{"author": "Alice", "content": "happy joyful"}],
        image_urls=["https://example.com/img.png"],
    )
    assert all(0.0 <= v <= 1.0 for v in engine.get_state().values())
```

- [ ] **Étape 2 : Vérifier que les 6 tests échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest \
  tests/test_emotion.py::test_analyze_llm_passes_image_urls_to_complete_secondary \
  tests/test_emotion.py::test_analyze_llm_enriches_prompt_with_images \
  tests/test_emotion.py::test_analyze_llm_no_image_urls_no_prompt_enrichment \
  tests/test_emotion.py::test_process_message_image_only_llm_available \
  tests/test_emotion.py::test_process_message_image_only_llm_unavailable \
  tests/test_emotion.py::test_process_message_text_image_llm_error_falls_back \
  -v
```

Attendu : `FAILED` — les paramètres `image_urls` n'existent pas encore

- [ ] **Étape 3 : Modifier `_analyze_llm` dans `bot/core/emotion.py`**

Remplacer la signature et le corps de `_analyze_llm` (ligne 243) :

```python
async def _analyze_llm(
    self, text: str, trust_score: float, context_messages: list[dict],
    image_urls: list[str] | None = None,
) -> tuple[dict[str, float], list[dict]]:
    """Analyse émotionnelle via LLM — retourne (deltas, new_words)."""
    system_prompt = (
        "Tu es le module d'analyse émotionnelle de Wally, un bot de chat Discord. "
        "Ton rôle est de mesurer l'impact d'un échange sur l'état interne de Wally.\n\n"

        "## Émotions disponibles\n"
        "anger, joy, sadness, curiosity, boredom\n\n"

        "## Calcul des deltas\n"
        "- Chaque delta est un float dans [0.0, 0.3] représentant une variation positive de l'émotion.\n"
        "- Pondération par la cible :\n"
        "  • Émotion dirigée vers Wally → impact plein (delta normal)\n"
        "  • Émotion dirigée entre utilisateurs (Wally non concerné) → delta ÷ 3\n"
        "- Pondération par la confiance :\n"
        "  • trust_score proche de 0.0 → anger amplifié (×2 max)\n"
        "  • trust_score proche de 1.0 → pas d'amplification\n"
        "- Le dernier message (« Message déclencheur ») a un poids plus élevé que l'historique.\n"
        "- Si un message est neutre ou sans contenu émotionnel, laisse tous les deltas à 0.0.\n\n"

        "## Apprentissage de nouveaux mots (new_words)\n"
        "Identifie au maximum 3 mots ou expressions françaises absents du lexique standard "
        "qui expriment clairement une émotion dans ce message. "
        "Critères : mot non anglais, porteur d'émotion explicite, delta entre 0.05 et 0.3.\n\n"

        "## Exemple\n"
        "trust_score: 0.30\n"
        "Historique :\n"
        "[Alice]: c'est vraiment nul comme réponse\n"
        "Message déclencheur :\n"
        "[Bob]: ouais Wally t'es carrément à côté de la plaque là\n"
        "→ Réponse attendue :\n"
        '{"deltas": {"anger": 0.22, "joy": 0.0, "sadness": 0.05, "curiosity": 0.0, "boredom": 0.0}, '
        '"new_words": [{"word": "à côté de la plaque", "emotion": "anger", "delta": 0.10}]}\n\n'

        "## Format de sortie\n"
        "JSON valide uniquement, sans markdown ni commentaire :\n"
        '{"deltas": {"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}, '
        '"new_words": [{"word": "...", "emotion": "...", "delta": 0.0}]}'
    )
    if image_urls:
        system_prompt += (
            "\n\n## Images jointes\n"
            "Des images accompagnent ce message. Analyse aussi leur contenu émotionnel "
            "(ton visuel, sujet représenté, contexte apparent) pour affiner les deltas. "
            "Une image de rage, un mème sarcastique ou une photo triste doit influencer "
            "les deltas au même titre que le texte."
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
        image_urls=image_urls or None,
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

- [ ] **Étape 4 : Modifier `process_message` pour accepter `image_urls`**

Dans `bot/core/emotion.py`, remplacer la signature de `process_message` (ligne 395) :

```python
async def process_message(
    self, text: str, trust_score: float = 0.5, context_messages: list[dict] | None = None,
    image_urls: list[str] | None = None,
) -> None:
    if self._openai is not None and context_messages:
        try:
            deltas, new_words = await self._analyze_llm(
                text, trust_score, context_messages, image_urls=image_urls
            )
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

- [ ] **Étape 5 : Vérifier que tous les tests emotion passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_emotion.py -v
```

Attendu : tous `PASSED`

- [ ] **Étape 6 : Commit**

```bash
git add bot/core/emotion.py tests/test_emotion.py
git commit -m "feat(emotion): _analyze_llm et process_message acceptent image_urls"
```

---

## Task 3 : `_post_process` et `_respond` — passage des images

**Files:**
- Modify: `bot/discord/handlers.py:191-236` (dans `_respond`), `bot/discord/handlers.py:246-280` (`_post_process`)
- Test: `tests/test_discord_handlers.py`

- [ ] **Étape 1 : Vérifier les imports existants dans `tests/test_discord_handlers.py`**

Vérifier que les 3 imports suivants sont présents en haut du fichier :
```python
import asyncio
from bot.discord.handlers import handle_message, _respond, _post_process
```
`make_attachment` est déjà définie dans le fichier (ligne 75) avec la signature :
```python
def make_attachment(url: str, content_type: str = "image/png"):
```
Pas besoin de la recréer.

- [ ] **Étape 2 : Écrire les tests qui échouent**

Ajouter à la fin de `tests/test_discord_handlers.py` :

```python
# ── Image emotion ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_process_passes_image_urls_to_emotion():
    """_post_process doit transmettre image_urls à emotion.process_message."""
    bot = make_bot()
    await _post_process(
        bot, "regarde cette image", "discord", "12345", "99999", 0.5,
        context_messages=[],
        image_urls=["https://example.com/meme.png"],
    )
    call_kwargs = bot.emotion.process_message.call_args.kwargs
    assert call_kwargs.get("image_urls") == ["https://example.com/meme.png"]


@pytest.mark.asyncio
async def test_respond_passes_image_urls_to_post_process():
    """_respond doit passer image_urls et text_content (substitution image-only) à _post_process.

    handlers.py ligne 197 :
        text_content = message.content or ("Regarde cette image." if image_urls else "")
    C'est ce text_content qui est passé à _post_process, pas message.content.
    """
    bot = make_bot()
    attachment = make_attachment("https://example.com/img.png")
    message = make_message(content="", attachments=[attachment])

    # On ne patche pas create_task → _post_process s'exécute réellement
    await _respond(bot, message, "12345", "99999", [])
    await asyncio.sleep(0)  # laisse la tâche de fond se terminer

    call_kwargs = bot.emotion.process_message.call_args.kwargs
    assert call_kwargs.get("image_urls") == ["https://example.com/img.png"]
    # Texte de substitution pour message image-only
    call_args = bot.emotion.process_message.call_args.args
    assert call_args[0] == "Regarde cette image."
```

- [ ] **Étape 3 : Vérifier que les 2 tests échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_discord_handlers.py::test_post_process_passes_image_urls_to_emotion tests/test_discord_handlers.py::test_respond_passes_image_urls_to_post_process -v
```

Attendu : `FAILED`

- [ ] **Étape 4 : Modifier `_post_process`**

Dans `bot/discord/handlers.py`, remplacer la signature de `_post_process` (ligne 246) :

```python
async def _post_process(
    bot: "WallyDiscord",
    text: str,
    platform: str,
    user_id: str,
    guild_id: str,
    trust: float,
    context_messages: list[dict] | None = None,
    image_urls: list[str] | None = None,
) -> None:
    try:
        await bot.emotion.process_message(
            text, trust_score=trust, context_messages=context_messages,
            image_urls=image_urls,
        )
        # ... reste du corps inchangé
```

Le reste du corps de `_post_process` (trust score update, anger check, mute) reste identique.

- [ ] **Étape 5 : Modifier l'appel à `_fire(_post_process(...))` dans `_respond`**

Dans `_respond`, ligne 236, remplacer :

```python
_fire(_post_process(bot, message.content, platform, user_id, guild_id, trust, context_messages))
```

par :

```python
_fire(_post_process(
    bot, text_content, platform, user_id, guild_id, trust, context_messages,
    image_urls=image_urls or None,
))
```

`text_content` est déjà défini ligne 197 : `text_content = message.content or ("Regarde cette image." if image_urls else "")`

- [ ] **Étape 6 : Vérifier que tous les tests handlers passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_discord_handlers.py -v
```

Attendu : tous `PASSED`

- [ ] **Étape 7 : Commit**

```bash
git add bot/discord/handlers.py tests/test_discord_handlers.py
git commit -m "feat(discord): _post_process et _respond transmettent image_urls pour l'analyse émotionnelle"
```

---

## Task 4 : Vérification finale de la suite complète

- [ ] **Étape 1 : Lancer tous les tests**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/ -v
```

Attendu : tous `PASSED` (110+ tests)

- [ ] **Étape 2 : Si des tests échouent, corriger avant de continuer**

Vérifier que les signatures additives n'ont pas cassé les appels existants Twitch (qui n'ont pas de `image_urls`).

- [ ] **Étape 3 : Commit final si nécessaire**

Si des corrections ont été faites :

```bash
git add -p
git commit -m "fix: corrections suite review analyse émotionnelle images"
```
