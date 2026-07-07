# tests/test_discord_handlers.py
"""
Tests for Discord message handler pipeline.
All Discord objects and services are mocked — no real bot connection needed.
"""
import asyncio
import discord
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.discord.handlers import (
    handle_message,
    _respond,
    _post_process,
    _build_mention_directory,
    _resolve_mentions,
    _ALLOWED_MENTIONS,
)


def make_bot(trigger_names=None, muted=False, welcomed=False, trust=0.5):
    bot = MagicMock()
    bot.user = MagicMock()
    bot.config.bot.name = "Wally"
    bot.config.bot.trigger_names = trigger_names or ["wally"]
    bot.config.bot.prelude_window_size = 5        # ← nouveau
    bot.config.discord.allowed_channels = []
    bot.config.discord.channel_filter_mode = "blacklist"
    bot.config.discord.channel_blacklist = []
    bot.config.discord.per_guild_channel_whitelist = {}
    bot.config.discord.anger_trigger_threshold = 3
    bot.config.discord.timeout_minutes = 10
    bot.config.discord.emoji_reaction_probability = 0.05
    bot.config.discord.spam_detection.enabled = False
    bot.config.bot.spontaneous_discord_enabled = False

    bot.db.is_muted = AsyncMock(return_value=muted)
    bot.db.is_welcomed = AsyncMock(return_value=welcomed)
    bot.db.get_trust_score = AsyncMock(return_value=trust)
    bot.db.update_trust_score = AsyncMock()
    bot.db.update_love_score = AsyncMock()
    bot.db.get_love_score = AsyncMock(return_value=0.0)
    bot.db.count_recent_triggers = AsyncMock(return_value=0)
    bot.db.add_timeout = AsyncMock()
    bot.db.mark_welcomed = AsyncMock()
    bot.db.upsert_memory_user = AsyncMock()
    bot.config.bot.love_decay_lambda = 0.02

    bot.emotion.get_state = MagicMock(
        return_value={"anger": 0.0, "joy": 0.5, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.0}
    )
    bot.emotion.get_dominant = MagicMock(return_value=["joy"])
    bot.emotion.process_message = AsyncMock(return_value=None)

    bot.memory.search = AsyncMock(return_value="")
    bot.memory.search_global = AsyncMock(return_value="")
    bot.memory.get_context_summarized_if_needed = AsyncMock(return_value=[])
    bot.memory.append_message = MagicMock()
    bot.memory.get_prelude = MagicMock(return_value=[])      # ← nouveau
    bot.memory.append_prelude = MagicMock()                  # ← nouveau
    bot.memory.get_pending_question_directive = AsyncMock(return_value="")

    bot.db.get_last_interaction = AsyncMock(return_value=None)
    bot.db.get_recent_jokes = AsyncMock(return_value=[])
    bot.db.get_topics = AsyncMock(return_value=[])
    bot.db.get_persistent_notes = AsyncMock(return_value=[])

    bot.language.detect = MagicMock(return_value="fr")
    bot.prompts.build_system_prompt = MagicMock(return_value="system prompt")
    bot.prompts.build_context_block = MagicMock(return_value="")
    bot.prompts.build_prelude_block = MagicMock(return_value="")  # ← nouveau
    bot.llm.complete = AsyncMock(return_value="Bonjour!")
    bot.llm.complete_with_tools = AsyncMock(return_value=("Bonjour!", []))

    bot.persona = MagicMock()
    bot.persona.build_prompt_block = MagicMock(return_value="persona block")

    bot.llm_secondary = MagicMock()
    bot.llm_secondary.complete = AsyncMock(return_value="Un paysage de montagne avec un lac.")
    bot.memory.add = AsyncMock()

    bot.web_search = None  # désactivé par défaut dans les tests
    bot.apex_api = None
    bot.scrape = None  # ScrapeService désactivé par défaut dans les tests
    bot.vision = None  # VisionService désactivé par défaut dans les tests
    bot.response_gate = None  # gate V2 désactivé dans les tests V1
    bot.cognitive_loop = None  # cognitive loop V2 désactivé dans les tests V1
    bot.self_fix = None       # SelfFix V2 désactivé dans les tests V1
    bot.self_upgrade = None   # SelfUpgrade V2 désactivé dans les tests V1

    return bot


def make_message(content="wally bonjour", author_bot=False, mentions=None, attachments=None):
    """Build a minimal discord.Message-like mock."""
    msg = MagicMock()
    msg.content = content
    msg.author.bot = author_bot
    msg.author.id = 12345
    msg.author.display_name = "TestUser"
    msg.author.name = "TestUser"
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


def make_attachment(url: str, content_type: str = "image/png"):
    att = MagicMock()
    att.url = url
    att.content_type = content_type
    return att


# ── handle_message ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ignores_bot_messages():
    bot = make_bot()
    message = make_message(author_bot=True)
    await handle_message(bot, message)
    bot.db.is_muted.assert_not_called()


@pytest.mark.asyncio
async def test_ignores_untriggered_messages():
    bot = make_bot(trigger_names=["wally"])
    message = make_message(content="hello there")
    await handle_message(bot, message)
    bot.db.is_muted.assert_not_called()


@pytest.mark.asyncio
async def test_trigger_by_name_calls_respond():
    bot = make_bot(trigger_names=["wally"])
    message = make_message(content="wally bonjour")
    with patch("bot.discord.handlers.asyncio.create_task"):
        await handle_message(bot, message)
    message.reply.assert_awaited_once()


@pytest.mark.asyncio
async def test_trigger_by_mention_calls_respond():
    bot = make_bot(trigger_names=["wally"])
    message = make_message(content="hey!", mentions=[bot.user])
    with patch("bot.discord.handlers.asyncio.create_task"):
        await handle_message(bot, message)
    message.reply.assert_awaited_once()


@pytest.mark.asyncio
async def test_muted_user_gets_reaction_not_reply():
    bot = make_bot(muted=True)
    message = make_message(content="wally salut")
    await handle_message(bot, message)
    message.add_reaction.assert_awaited_once()
    message.reply.assert_not_awaited()


# ── _respond ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_respond_injects_presence_context():
    bot = make_bot()
    bot.presence.describe = MagicMock(return_value="TestUser est en ligne — joue à Valorant.")
    message = make_message(content="wally salut")
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])
    kwargs = bot.prompts.build_system_prompt.call_args.kwargs
    assert kwargs["presence_context"] == "TestUser est en ligne — joue à Valorant."
    bot.presence.describe.assert_called_once_with("12345", "TestUser")


@pytest.mark.asyncio
async def test_respond_presence_absent_injects_explicit_negative():
    # Pas de donnée de présence → on injecte un négatif explicite plutôt qu'un
    # vide silencieux, pour que le LLM n'invente pas de statut.
    bot = make_bot()
    bot.presence.enabled = True
    bot.presence.describe = MagicMock(return_value=None)
    message = make_message(content="wally c'est quoi mon statut")
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])
    kwargs = bot.prompts.build_system_prompt.call_args.kwargs
    assert "ne l'invente pas" in kwargs["presence_context"]
    assert "TestUser" in kwargs["presence_context"]


@pytest.mark.asyncio
async def test_respond_presence_disabled_stays_empty():
    # Service de présence désactivé (pas de serveur principal) → aucun négatif,
    # sinon on spammerait le prompt à chaque message.
    bot = make_bot()
    bot.presence.enabled = False
    bot.presence.describe = MagicMock(return_value=None)
    message = make_message(content="wally salut")
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])
    kwargs = bot.prompts.build_system_prompt.call_args.kwargs
    assert kwargs["presence_context"] == ""


@pytest.mark.asyncio
async def test_respond_presence_failure_does_not_break():
    bot = make_bot()
    bot.presence.describe = MagicMock(side_effect=RuntimeError("boom"))
    message = make_message(content="wally salut")
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])
    kwargs = bot.prompts.build_system_prompt.call_args.kwargs
    assert kwargs["presence_context"] == ""
    message.reply.assert_awaited()


@pytest.mark.asyncio
async def test_respond_adds_and_removes_reaction():
    bot = make_bot()
    message = make_message()
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])
    message.add_reaction.assert_awaited_once_with("🔍")
    message.remove_reaction.assert_awaited_once_with("🔍", bot.user)


@pytest.mark.asyncio
async def test_respond_appends_to_context_window():
    bot = make_bot()
    message = make_message(content="wally qui es-tu?")
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])
    assert bot.memory.append_message.call_count == 2
    calls = bot.memory.append_message.call_args_list
    assert calls[0].args[1] == "TestUser"
    assert calls[1].args[1] == "Wally"


@pytest.mark.asyncio
async def test_respond_includes_context_block_when_present():
    bot = make_bot()
    bot.prompts.build_context_block = MagicMock(return_value="[ctx block]")
    message = make_message(content="wally continue")
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])
    call_args = bot.llm.complete_with_tools.call_args
    assert "[ctx block]" in call_args.args[1][0]["content"]


def _make_reply_ref(content, author_id, display_name="X", name="x"):
    # spec=discord.Message pour passer le garde isinstance() de _fetch_referenced_message
    ref = MagicMock(spec=discord.Message)
    ref.content = content
    ref.author = MagicMock()
    ref.author.id = author_id
    ref.author.display_name = display_name
    ref.author.name = name
    ref.attachments = []
    ref.embeds = []
    return ref


@pytest.mark.asyncio
async def test_respond_injects_replied_message_from_wally():
    """Reply Discord vers un ancien message de Wally → texte cité + attribution 'toi'."""
    bot = make_bot()
    message = make_message(content="wally et ça donne quoi?")
    message.reference = MagicMock()
    message.reference.message_id = 555
    message.reference.resolved = _make_reply_ref(
        "Voici ma réponse précédente sur le sujet", bot.user.id
    )
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])
    content = bot.llm.complete_with_tools.call_args.args[1][0]["content"]
    assert "Voici ma réponse précédente sur le sujet" in content
    assert "toi (Wally)" in content


@pytest.mark.asyncio
async def test_respond_injects_replied_message_attributes_other_author():
    """Reply vers le message d'un tiers → texte cité attribué au bon auteur."""
    bot = make_bot()
    message = make_message(content="wally t'en penses quoi?")
    message.reference = MagicMock()
    message.reference.message_id = 556
    message.reference.resolved = _make_reply_ref(
        "Message original d'Alice", 88888, display_name="Alice", name="alice_xyz"
    )
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])
    content = bot.llm.complete_with_tools.call_args.args[1][0]["content"]
    assert "Message original d'Alice" in content
    assert "Alice (@alice_xyz)" in content


@pytest.mark.asyncio
async def test_respond_enriches_memory_search_with_replied_message():
    """La requête mémoire inclut le contenu du message cité — ancrage factuel
    anti-confabulation : répondre 'j'ai po la ref' à un message parlant de jubeii
    doit chercher 'jubeii' en mémoire, pas seulement 'j'ai po la ref'."""
    bot = make_bot()
    message = make_message(content="j'ai po la ref")
    message.reference = MagicMock()
    message.reference.message_id = 555
    message.reference.resolved = _make_reply_ref(
        "jubeii1979 qui dislikes froid", bot.user.id
    )
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])
    query = bot.memory.search.call_args.args[2]
    assert "jubeii1979" in query
    assert "j'ai po la ref" in query


# ── _post_process ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_process_calls_emotion_and_trust():
    bot = make_bot()
    await _post_process(bot, "thank you", "discord", "12345", "99999", 0.5)
    bot.emotion.process_message.assert_awaited_once_with(
        "thank you", trust_score=0.5, context_messages=None, image_urls=None,
        trigger_user="12345", channel_id="", platform="discord",
        user_id="12345",
    )
    bot.db.update_trust_score.assert_awaited_once()


@pytest.mark.asyncio
async def test_post_process_decreases_trust_on_insult():
    bot = make_bot()
    await _post_process(bot, "tu es un idiot", "discord", "12345", "99999", 0.5)
    call = bot.db.update_trust_score.call_args
    assert call.args[2] < 0  # negative delta


@pytest.mark.asyncio
async def test_post_process_mutes_on_high_anger_and_threshold():
    bot = make_bot()
    bot.emotion.get_state = MagicMock(return_value={"anger": 0.9})
    bot.db.count_recent_triggers = AsyncMock(return_value=5)
    await _post_process(bot, "merde", "discord", "12345", "99999", 0.5)
    # Called twice: once for the anger trigger (duration=0), once for the actual mute
    assert bot.db.add_timeout.await_count == 2
    # First call: trigger tracking (duration=0)
    assert bot.db.add_timeout.await_args_list[0].args[2] == 0
    # Second call: real mute (duration=timeout_minutes)
    assert bot.db.add_timeout.await_args_list[1].args[2] == 10


# ── Premier contact (bienvenue intégrée) ──────────────────────────────────────

@pytest.mark.asyncio
async def test_first_contact_marks_welcomed():
    """Lors du premier contact, mark_welcomed est appelé après la réponse."""
    bot = make_bot(welcomed=False)
    message = make_message(content="wally bonjour")
    with patch("bot.discord.handlers.asyncio.create_task"):
        await handle_message(bot, message)
    bot.db.mark_welcomed.assert_awaited_once_with("12345", "99999")


@pytest.mark.asyncio
async def test_already_welcomed_no_mark():
    """Si déjà accueilli, mark_welcomed n'est pas rappelé."""
    bot = make_bot(welcomed=True)
    message = make_message(content="wally bonjour")
    with patch("bot.discord.handlers.asyncio.create_task"):
        await handle_message(bot, message)
    bot.db.mark_welcomed.assert_not_awaited()


@pytest.mark.asyncio
async def test_first_contact_injects_welcome_context():
    """Lors du premier contact, le contexte bienvenue est injecté dans le prompt."""
    bot = make_bot(welcomed=False)
    message = make_message(content="wally salut")
    with patch("bot.discord.handlers.asyncio.create_task"):
        await handle_message(bot, message)
    call_args = bot.llm.complete_with_tools.call_args
    user_content = call_args[0][1][0]["content"]
    assert "première fois" in user_content


# ── Prelude context ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_passive_capture_non_triggered_message():
    """append_prelude est appelé même sans trigger, dans les canaux autorisés."""
    bot = make_bot()
    message = make_message(content="juste un message normal")  # pas de trigger
    # bot.user pas dans les mentions, pas de trigger name dans content
    await handle_message(bot, message)
    bot.memory.append_prelude.assert_called_once_with(
        str(message.channel.id),
        message.author.display_name,
        message.content,
    )
    # pas de réponse envoyée
    bot.llm.complete.assert_not_called()


@pytest.mark.asyncio
async def test_cognitive_loop_perceives_non_triggered_message():
    """Le cerveau (cognitive_loop) perçoit les messages passifs des salons
    autorisés, même sans mention — base de l'intervention spontanée pertinente."""
    bot = make_bot()
    bot.cognitive_loop = MagicMock()
    bot.cognitive_loop.notify_activity = MagicMock()
    message = make_message(content="juste un message normal")  # pas de trigger
    await handle_message(bot, message)
    bot.cognitive_loop.notify_activity.assert_called_once_with(
        channel_id=message.channel.id,
        author=str(message.author.display_name),
        content=message.content,
        message_id=str(message.id),
        is_dm=False,
        relevant=False,  # message passif → pas de cadence vive (Phase 2c)
        user_key=f"discord:{message.author.id}",  # #A1 enrichissement mémoire
    )
    # toujours pas de réponse directe : le cerveau décidera seul d'intervenir
    bot.llm.complete.assert_not_called()


@pytest.mark.asyncio
async def test_cognitive_loop_not_notified_in_disallowed_channel():
    """Salon non autorisé → le cerveau ne perçoit rien (pas de perception)."""
    bot = make_bot()
    bot.config.discord.channel_filter_mode = "whitelist"
    bot.config.discord.channel_whitelist = [424242]  # le canal du message (777) n'y est pas
    bot.cognitive_loop = MagicMock()
    bot.cognitive_loop.notify_activity = MagicMock()
    message = make_message(content="juste un message normal")
    await handle_message(bot, message)
    bot.cognitive_loop.notify_activity.assert_not_called()


@pytest.mark.asyncio
async def test_cognitive_loop_notified_once_on_trigger():
    """Sur un message qui mentionne Wally, notify_activity n'est appelé
    qu'UNE fois (pas de double-feed après suppression du doublon)."""
    bot = make_bot(trigger_names=["wally"])
    bot.cognitive_loop = MagicMock()
    bot.cognitive_loop.notify_activity = MagicMock()
    bot.cognitive_loop.notify_reply = MagicMock()
    message = make_message(content="wally bonjour")
    with patch("bot.discord.handlers.asyncio.create_task"):
        await handle_message(bot, message)
    bot.cognitive_loop.notify_activity.assert_called_once_with(
        channel_id=message.channel.id,
        author=str(message.author.display_name),
        content=message.content,
        message_id=str(message.id),
        is_dm=False,
        relevant=True,  # « wally bonjour » vise Wally → cadence vive (Phase 2c)
        user_key=f"discord:{message.author.id}",  # #A1 enrichissement mémoire
    )


@pytest.mark.asyncio
async def test_prelude_included_in_prompt_on_mention():
    """build_prelude_block est appelé avec le prelude au moment de la mention."""
    bot = make_bot()
    prelude_msgs = [{"author": "Alice", "content": "on parlait de trucs", "timestamp": 1.0}]
    bot.memory.get_prelude = MagicMock(return_value=prelude_msgs)
    bot.prompts.build_prelude_block = MagicMock(return_value="[PRELUDE]")

    message = make_message(content="wally c'est quoi ton avis")
    await handle_message(bot, message)

    bot.prompts.build_prelude_block.assert_called_once_with(prelude_msgs)
    # Le prelude doit apparaître dans user_content envoyé à OpenAI
    call_args = bot.llm.complete_with_tools.call_args
    user_content = call_args[0][1][0]["content"]  # messages[0]["content"]
    assert "[PRELUDE]" in user_content


@pytest.mark.asyncio
async def test_cold_start_fallback_to_channel_history():
    """Si prelude vide, channel.history() est appelé en fallback."""
    bot = make_bot()
    bot.memory.get_prelude = MagicMock(return_value=[])  # vide = cold start

    # Mock channel.history() — retourne 2 messages dans l'ordre inverse (Discord API)
    history_msg1 = MagicMock()
    history_msg1.author.bot = False
    history_msg1.author.display_name = "Alice"
    history_msg1.author.name = "Alice"
    history_msg1.content = "premier message"

    history_msg2 = MagicMock()
    history_msg2.author.bot = False
    history_msg2.author.display_name = "Bob"
    history_msg2.author.name = "Bob"
    history_msg2.content = "deuxième message"

    async def fake_history(limit):
        for m in [history_msg2, history_msg1]:  # Discord retourne du plus récent au plus ancien
            yield m

    message = make_message(content="wally dis moi")
    message.channel.history = fake_history

    await handle_message(bot, message)

    # build_prelude_block doit avoir reçu les messages dans l'ordre chronologique
    call_args = bot.prompts.build_prelude_block.call_args[0][0]
    assert len(call_args) == 2
    assert call_args[0]["author"] == "Alice"   # ordre chronologique : plus ancien d'abord
    assert call_args[1]["author"] == "Bob"


@pytest.mark.asyncio
async def test_channel_history_permission_error_graceful():
    """Une erreur sur channel.history() → log WARNING + réponse sans prelude."""
    bot = make_bot()
    bot.memory.get_prelude = MagicMock(return_value=[])  # vide

    async def broken_history(limit):
        raise Exception("Missing Access")
        return  # pragma: no cover
        yield  # make it a generator

    message = make_message(content="wally aide moi")
    message.channel.history = broken_history

    # Ne doit pas lever d'exception
    await handle_message(bot, message)

    # build_prelude_block appelé avec liste vide (graceful degradation)
    bot.prompts.build_prelude_block.assert_called_once_with([])
    # La réponse est quand même envoyée
    bot.llm.complete_with_tools.assert_called_once()


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

    call_kwargs = bot.llm.complete_with_tools.call_args.kwargs
    assert call_kwargs["image_urls"] == ["https://cdn.discord.com/img.png"]


@pytest.mark.asyncio
async def test_respond_limits_4_images():
    """_respond envoie au maximum 4 images à complete()."""
    bot = make_bot()
    attachments = [make_attachment(f"https://cdn.discord.com/img{i}.png") for i in range(6)]
    message = make_message(content="wally regarde", attachments=attachments)
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])

    call_kwargs = bot.llm.complete_with_tools.call_args.kwargs
    assert len(call_kwargs["image_urls"]) == 4


# ── Mirror pass ────────────────────────────────────────────────────────────

class _FakeLLMSecondary:
    def __init__(self, response: str):
        self._response = response

    async def complete(self, system_prompt, messages, purpose=None, **kwargs):
        return self._response


class _FakeMemory:
    def __init__(self, prelude):
        self._prelude = prelude

    def get_prelude(self, channel_id):
        return self._prelude


class _FakeBotConfig:
    class bot:
        name = "Wally"


class _FakeBot:
    def __init__(self, secondary_response: str, prelude=None):
        self.llm_secondary = _FakeLLMSecondary(secondary_response)
        self.memory = _FakeMemory(prelude or [])
        self.config = _FakeBotConfig()


@pytest.mark.asyncio
async def test_mirror_pass_returns_draft_on_ok(monkeypatch):
    from bot.discord.handlers import _mirror_pass
    monkeypatch.setattr("bot.discord.handlers.load_prompt", lambda name, fallback="": "check this" if name == "response_mirror_system" else fallback)
    bot = _FakeBot("OK")
    result = await _mirror_pass(bot, "ch1", "Ouais bof.", "user likes cats")
    assert result == "Ouais bof."


@pytest.mark.asyncio
async def test_mirror_pass_returns_corrected_on_fix(monkeypatch):
    from bot.discord.handlers import _mirror_pass
    monkeypatch.setattr("bot.discord.handlers.load_prompt", lambda name, fallback="": "check this" if name == "response_mirror_system" else fallback)
    bot = _FakeBot("Ah tiens, t'as toujours pas réparé ton vélo !")
    result = await _mirror_pass(bot, "ch1", "Ah ouais c'est sympa ce truc là non ?", "user has a broken bike")
    assert result == "Ah tiens, t'as toujours pas réparé ton vélo !"


@pytest.mark.asyncio
async def test_mirror_pass_skips_short_reply(monkeypatch):
    from bot.discord.handlers import _mirror_pass
    monkeypatch.setattr("bot.discord.handlers.load_prompt", lambda name, fallback="": "check this")
    bot = _FakeBot("something different")
    result = await _mirror_pass(bot, "ch1", "ok", "mem")
    assert result == "ok"


@pytest.mark.asyncio
async def test_mirror_pass_returns_draft_on_llm_error(monkeypatch):
    from bot.discord.handlers import _mirror_pass
    monkeypatch.setattr("bot.discord.handlers.load_prompt", lambda name, fallback="": "check this")

    class _BrokenLLM:
        async def complete(self, *a, **kw):
            raise RuntimeError("LLM unavailable")

    class _Bot:
        llm_secondary = _BrokenLLM()
        memory = _FakeMemory([])
        config = _FakeBotConfig()

    result = await _mirror_pass(_Bot(), "ch1", "Ouais c'est pas terrible comme idée en fait.", "mem")
    assert result == "Ouais c'est pas terrible comme idée en fait."


@pytest.mark.asyncio
async def test_mirror_pass_skips_when_no_prompt(monkeypatch):
    from bot.discord.handlers import _mirror_pass
    monkeypatch.setattr("bot.discord.handlers.load_prompt", lambda name, fallback="": "")
    bot = _FakeBot("corrected text")
    result = await _mirror_pass(bot, "ch1", "Ouais c'est pas terrible comme idée en fait.", "mem")
    assert result == "Ouais c'est pas terrible comme idée en fait."


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

    call_args = bot.llm.complete_with_tools.call_args
    user_content = call_args.args[1][0]["content"]
    assert "Regarde cette image." in user_content


@pytest.mark.asyncio
async def test_respond_image_only_memory_tag():
    """Message image sans texte : append_message reçoit le tag enrichi via enriched_content."""
    bot = make_bot()
    message = make_message(
        content="",
        attachments=[make_attachment("https://cdn.discord.com/img.png")],
    )
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [],
                        enriched_content="[a envoyé une image]")

    calls = bot.memory.append_message.call_args_list
    # Premier appel : message de l'utilisateur
    stored_content = calls[0].args[2]
    assert stored_content == "[a envoyé une image]"


@pytest.mark.asyncio
async def test_respond_image_with_text_memory_tag():
    """Message avec texte + image : append_message reçoit le texte enrichi."""
    bot = make_bot()
    message = make_message(
        content="regarde ça",
        attachments=[make_attachment("https://cdn.discord.com/img.png")],
    )
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [],
                        enriched_content="regarde ça [+ une image]")

    calls = bot.memory.append_message.call_args_list
    stored_content = calls[0].args[2]
    assert stored_content == "regarde ça [+ une image]"


@pytest.mark.asyncio
async def test_respond_no_images_no_image_urls_kwarg():
    """Sans pièce jointe image, image_urls n'est pas passé (None)."""
    bot = make_bot()
    message = make_message(content="wally bonjour", attachments=[])
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])

    call_kwargs = bot.llm.complete_with_tools.call_args.kwargs
    assert call_kwargs.get("image_urls") is None


class _FakeVision:
    """VisionService factice : retourne une analyse fixe."""

    def __init__(self, analysis: str | None = "Un screenshot Valorant. Rang : Diamant 2. K/D/A : 21/14/7."):
        self.available = True
        self._analysis = analysis
        self.calls: list[dict] = []

    async def analyze(self, image_urls, caption="", purpose="image_analysis"):
        self.calls.append({"image_urls": list(image_urls), "caption": caption})
        return self._analysis


@pytest.mark.asyncio
async def test_respond_injects_vision_analysis():
    """Quand VisionService voit l'image, son analyse est injectée dans le prompt."""
    bot = make_bot()
    bot.vision = _FakeVision()
    message = make_message(
        content="wally regarde mes stats",
        attachments=[make_attachment("https://cdn.discord.com/val.png")],
    )
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])

    # L'analyse réelle doit apparaître dans le user_content envoyé au LLM principal
    user_content = bot.llm.complete_with_tools.call_args.args[1][0]["content"]
    assert "ANALYSE VISUELLE" in user_content
    assert "Diamant 2" in user_content
    # Et la légende du message a bien été transmise au service de vision
    assert bot.vision.calls[0]["caption"] == "wally regarde mes stats"


@pytest.mark.asyncio
async def test_respond_no_vision_injection_when_unavailable():
    """VisionService indisponible : aucun bloc d'analyse injecté, pas de crash."""
    bot = make_bot()  # bot.vision = None par défaut
    message = make_message(
        content="wally regarde",
        attachments=[make_attachment("https://cdn.discord.com/img.png")],
    )
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])

    user_content = bot.llm.complete_with_tools.call_args.args[1][0]["content"]
    assert "ANALYSE VISUELLE" not in user_content


@pytest.mark.asyncio
async def test_post_process_stores_vision_analysis():
    """_post_process stocke l'analyse visuelle fournie comme fait mémoire."""
    bot = make_bot()
    bot.vision = _FakeVision()
    await _post_process(
        bot, "regarde", "discord", "12345", "99999", 0.5,
        image_urls=["https://cdn.discord.com/val.png"],
        image_analysis="Screenshot Apex. Rang : Prédateur. 3200 dégâts, 8 kills.",
        display_name="Bob",
    )
    # L'analyse fournie est réutilisée telle quelle — pas de 2e appel vision
    assert bot.vision.calls == []
    stored = [c.args[2] for c in bot.memory.add.call_args_list]
    assert any("Prédateur" in s and s.startswith("Bob a envoyé une image") for s in stored)


@pytest.mark.asyncio
async def test_post_process_computes_vision_when_no_analysis():
    """Sans analyse pré-calculée, _post_process appelle VisionService lui-même."""
    bot = make_bot()
    bot.vision = _FakeVision(analysis="Une photo de chat roux endormi.")
    await _post_process(
        bot, "regarde", "discord", "12345", "99999", 0.5,
        image_urls=["https://cdn.discord.com/cat.png"],
        image_analysis=None,
        display_name="Bob",
    )
    assert len(bot.vision.calls) == 1
    stored = [c.args[2] for c in bot.memory.add.call_args_list]
    assert any("chat roux" in s for s in stored)


@pytest.mark.asyncio
async def test_respond_non_image_attachment_ignored():
    """Les pièces jointes non-image (PDF, etc.) sont ignorées."""
    bot = make_bot()
    pdf = make_attachment("https://cdn.discord.com/doc.pdf", content_type="application/pdf")
    message = make_message(content="wally regarde", attachments=[pdf])
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])

    call_kwargs = bot.llm.complete_with_tools.call_args.kwargs
    assert call_kwargs.get("image_urls") is None


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


@pytest.mark.asyncio
async def test_post_process_stores_image_description_in_memory():
    """_post_process décrit l'image via VisionService (et non DeepSeek aveugle)."""
    bot = make_bot()
    bot.vision = _FakeVision(analysis="Un chat roux assis sur un clavier.")

    await _post_process(
        bot, "regarde mon chat", "discord", "12345", "99999", 0.5,
        context_messages=[],
        image_urls=["https://example.com/cat.png"],
        display_name="TestUser",
    )

    # La vision a été appelée pour décrire réellement l'image
    assert len(bot.vision.calls) == 1
    assert bot.vision.calls[0]["image_urls"] == ["https://example.com/cat.png"]
    # Le LLM secondaire (DeepSeek) ne doit PAS être sollicité pour la description
    bot.llm_secondary.complete.assert_not_called()

    # Vérifie que le fait est stocké en mémoire
    bot.memory.add.assert_called_once()
    fact = bot.memory.add.call_args.args[2]
    assert "TestUser" in fact
    assert "Un chat roux assis sur un clavier." in fact


@pytest.mark.asyncio
async def test_post_process_no_image_description_without_images():
    """_post_process ne génère pas de description si pas d'images."""
    bot = make_bot()

    await _post_process(
        bot, "salut wally", "discord", "12345", "99999", 0.5,
        context_messages=[],
        image_urls=None,
        display_name="TestUser",
    )

    bot.llm_secondary.complete.assert_not_called()


# ── Mentions <@id> ──────────────────────────────────────────────────────────────

def _make_member(member_id, display_name, name, is_bot=False):
    m = MagicMock()
    m.id = member_id
    m.display_name = display_name
    m.name = name
    m.bot = is_bot
    return m


def test_build_mention_directory_lists_members_with_ids():
    message = make_message()
    message.guild.members = [
        _make_member(111, "Alice", "alice_x"),
        _make_member(222, "Bob", "Bob"),
        _make_member(999, "WallyBot", "wally", is_bot=True),
    ]
    directory = _build_mention_directory(message)
    # Syntaxe expliquée + identifiants présents
    assert "<@id>" in directory
    assert "<@111>" in directory
    assert "<@222>" in directory
    assert "Alice (@alice_x)" in directory
    # Les bots sont exclus
    assert "<@999>" not in directory
    # L'auteur (TestUser, 12345) est listé en premier
    assert directory.index("<@12345>") < directory.index("<@111>")


def test_resolve_mentions_replaces_id_with_display_name():
    message = make_message()
    message.mentions = [_make_member(792, "Azrael", "azrael_x")]
    out = _resolve_mentions(message, "salut <@792> ça va ?")
    assert out == "salut @Azrael ça va ?"


def test_resolve_mentions_handles_nickname_form_and_guild_fallback():
    message = make_message()
    message.mentions = []  # pas dans message.mentions → repli cache serveur
    message.guild.get_member = MagicMock(
        return_value=_make_member(111, "Bob", "bob")
    )
    # <@!id> (forme nickname) doit aussi être résolue
    out = _resolve_mentions(message, "yo <@!111>")
    assert out == "yo @Bob"


def test_resolve_mentions_leaves_unknown_id_untouched():
    message = make_message()
    message.mentions = []
    message.guild.get_member = MagicMock(return_value=None)
    out = _resolve_mentions(message, "qui est <@404> ?")
    assert out == "qui est <@404> ?"


def test_resolve_mentions_noop_without_mention():
    message = make_message()
    assert _resolve_mentions(message, "aucune mention ici") == "aucune mention ici"


def test_build_mention_directory_empty_for_dm():
    message = make_message()
    message.guild = None
    assert _build_mention_directory(message) == ""


def test_build_mention_directory_respects_cap():
    message = make_message()
    message.guild.members = [
        _make_member(1000 + i, f"User{i}", f"user{i}") for i in range(120)
    ]
    directory = _build_mention_directory(message, max_members=10)
    assert directory.count("→ <@") == 10


@pytest.mark.asyncio
async def test_respond_injects_mention_directory():
    bot = make_bot()
    message = make_message(content="wally ping alice")
    message.guild.members = [_make_member(111, "Alice", "alice_x")]
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])
    content = bot.llm.complete_with_tools.call_args.args[1][0]["content"]
    assert "<@111>" in content
    assert "Membres du serveur" in content


@pytest.mark.asyncio
async def test_respond_sends_with_allowed_mentions():
    """Les réponses bloquent @everyone/@here/rôles mais autorisent les pings membres."""
    bot = make_bot()
    message = make_message(content="wally salut")
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])
    assert message.reply.call_args.kwargs["allowed_mentions"] is _ALLOWED_MENTIONS
    assert _ALLOWED_MENTIONS.everyone is False
    assert _ALLOWED_MENTIONS.roles is False
    assert _ALLOWED_MENTIONS.users is True


# ── Cohérence stockage/filtre étiquette bot (config.bot.name) ─────────────────

@pytest.mark.asyncio
async def test_bot_label_uses_config_name_in_append():
    """Avec config.bot.name='Cindy', les messages sortants sont étiquetés 'Cindy'
    dans append_prelude et append_message — pas 'Wally' en dur."""
    bot = make_bot()
    bot.config.bot.name = "Cindy"
    message = make_message(content="wally bonjour")
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])

    # append_prelude doit avoir reçu "Cindy"
    prelude_calls = bot.memory.append_prelude.call_args_list
    assert any(call.args[1] == "Cindy" for call in prelude_calls), (
        "append_prelude n'a pas été appelé avec 'Cindy'. Appels: "
        + str([c.args for c in prelude_calls])
    )

    # append_message doit avoir reçu "Cindy" (pour le message de réponse du bot)
    msg_calls = bot.memory.append_message.call_args_list
    assert any(call.args[1] == "Cindy" for call in msg_calls), (
        "append_message n'a pas été appelé avec 'Cindy'. Appels: "
        + str([c.args for c in msg_calls])
    )


@pytest.mark.asyncio
async def test_bot_label_filter_matches_storage():
    """Le filtre 'Dernières réponses' dans _mirror_pass retrouve les messages
    étiquetés avec config.bot.name — cohérence stockage/lecture garantie
    même si name='Cindy'."""
    from bot.discord.handlers import _mirror_pass

    bot = make_bot()
    bot.config.bot.name = "Cindy"
    # Simule un prelude contenant 2 messages étiquetés "Cindy" (comme stockés)
    bot.memory.get_prelude = MagicMock(return_value=[
        {"author": "Cindy", "content": "Salut, je suis Cindy !"},
        {"author": "TestUser", "content": "Cool"},
        {"author": "Cindy", "content": "Heureux de te voir."},
    ])

    # _mirror_pass est skippé si draft < 30 chars — on envoie un draft suffisant
    draft = "Voici une réponse suffisamment longue pour ne pas être skippée."
    await _mirror_pass(bot, "777", draft, "")

    # Le LLM secondaire doit avoir reçu les réponses de Cindy (pas vide)
    call_args = bot.llm_secondary.complete.call_args
    assert call_args is not None, (
        "_mirror_pass n'a pas appelé llm_secondary.complete — "
        "vérifier le prompt response_mirror_system (chargé via load_prompt)."
    )
    user_msg = call_args.args[1][0]["content"] if call_args.args else ""
    assert "Cindy" in user_msg or "Salut" in user_msg, (
        "Le contexte 'Dernières réponses' est vide : le filtre ne retrouve pas "
        "les messages étiquetés 'Cindy'. user_msg=" + user_msg[:200]
    )


