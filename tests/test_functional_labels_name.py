# tests/test_functional_labels_name.py
"""
TDD: vérifie que les étiquettes mémoire (/ask, web chat) utilisent config.bot.name
et non la chaîne en dur "Wally".

Cas couverts :
  (a) /ask étiquette la réponse du bot avec config.bot.name
  (b) web chat _wally_respond étiquette/affiche config.bot.name dans le broadcast
      et dans append_prelude/append_message
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_ask_bot(name: str = "Cindy"):
    """Construit un mock de bot Discord avec config.bot.name configuré."""
    bot = MagicMock()
    bot.config.bot.name = name

    bot.db.get_trust_score = AsyncMock(return_value=0.5)

    bot.memory.search = AsyncMock(return_value="")
    bot.memory.get_context_summarized_if_needed = AsyncMock(return_value=[])
    bot.memory.append_message = MagicMock()

    bot.prompts.build_system_prompt = MagicMock(return_value="sys")
    bot.prompts.build_context_block = MagicMock(return_value="")

    bot.llm.complete = AsyncMock(return_value="Réponse de Cindy")

    bot.persona = MagicMock()
    bot.persona.build_prompt_block = MagicMock(return_value="persona block")
    bot.emotion.get_state = MagicMock(
        return_value={"anger": 0.0, "joy": 0.5, "sadness": 0.0,
                      "curiosity": 0.3, "boredom": 0.0}
    )

    return bot


def _make_interaction(channel_id: int = 100):
    interaction = MagicMock()
    interaction.user.id = 42
    interaction.user.display_name = "Testeur"
    interaction.channel_id = channel_id
    interaction.guild_id = 200
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    interaction.guild = MagicMock()
    interaction.channel = MagicMock()
    interaction.channel.name = "general"
    return interaction


def _make_app_state(name: str = "Cindy"):
    """Construit un mock d'AppState pour les routes du dashboard."""
    state = MagicMock()
    state.config.bot.name = name
    state.config.web_chat.cooldown_seconds = 0

    state.db.get_trust_score = AsyncMock(return_value=0.5)
    state.db.insert_chat_message = AsyncMock(return_value="msg-001")

    state.memory.append_message = MagicMock()
    state.memory.append_prelude = MagicMock()
    state.memory.search = AsyncMock(return_value="")
    state.memory.get_context_summarized_if_needed = AsyncMock(return_value=[])

    state.prompts.build_system_prompt = MagicMock(return_value="sys")
    state.prompts.build_context_block = MagicMock(return_value="")

    state.primary_llm.complete = AsyncMock(return_value="Réponse de Cindy")

    state.persona = MagicMock()
    state.persona.build_prompt_block = MagicMock(return_value="persona block")
    state.emotion.get_state = MagicMock(
        return_value={"anger": 0.0, "joy": 0.5, "sadness": 0.0,
                      "curiosity": 0.3, "boredom": 0.0}
    )
    state.record_response_time = MagicMock()
    state.fact_extractor = None
    state.message_count = 0
    state.message_count_web = 0

    return state


# ── (a) /ask — étiquette du bot ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ask_labels_bot_reply_with_config_name():
    """
    /ask doit appeler append_message avec config.bot.name comme auteur du reply,
    pas la chaîne en dur "Wally".
    """
    from bot.discord.commands.ask import AskCog

    bot = _make_ask_bot(name="Cindy")
    cog = AskCog(bot)
    interaction = _make_interaction()

    with patch("bot.discord.commands.ask._fire"):
        await cog.ask.callback(cog, interaction, question="Bonjour?")

    # Deux appels à append_message : user, puis bot
    assert bot.memory.append_message.call_count == 2
    _, second_call = bot.memory.append_message.call_args_list

    # 2e appel : (channel_id, bot_name, reply)
    args = second_call[0]
    assert args[1] == "Cindy", (
        f"Le label du bot dans append_message devrait être 'Cindy', obtenu '{args[1]}'"
    )
    assert args[1] != "Wally", "Le label ne doit pas être la chaîne en dur 'Wally'"


@pytest.mark.asyncio
async def test_ask_uses_wally_by_default():
    """Régression : quand config.bot.name == 'Wally', le label reste 'Wally'."""
    from bot.discord.commands.ask import AskCog

    bot = _make_ask_bot(name="Wally")
    cog = AskCog(bot)
    interaction = _make_interaction()

    with patch("bot.discord.commands.ask._fire"):
        await cog.ask.callback(cog, interaction, question="Test")

    _, second_call = bot.memory.append_message.call_args_list
    args = second_call[0]
    assert args[1] == "Wally"


# ── (b) web chat — étiquette/affichage config.bot.name ───────────────────────


@pytest.mark.asyncio
async def test_web_chat_broadcast_uses_config_name():
    """
    _wally_respond doit diffuser username=config.bot.name dans le broadcast,
    pas la chaîne en dur "Wally".
    """
    from bot.dashboard.routes.chat import _wally_respond

    state = _make_app_state(name="Cindy")

    broadcasts = []

    async def capture_broadcast(data: dict) -> None:
        broadcasts.append(data)

    with patch("bot.dashboard.routes.chat._broadcast", side_effect=capture_broadcast), \
         patch("bot.dashboard.routes.chat._parse_react_tag", return_value=(None, "Réponse de Cindy")), \
         patch("bot.dashboard.routes.chat.asyncio.create_task"):
        await _wally_respond(state, "discord:42", "Testeur", "Bonjour!")

    # Trouver le message de type "message" émis par le bot
    bot_msg = next(
        (m for m in broadcasts if m.get("type") == "message" and m.get("is_wally")),
        None,
    )
    assert bot_msg is not None, "Aucun broadcast de type message is_wally=True trouvé"
    assert bot_msg["username"] == "Cindy", (
        f"username broadcast attendu 'Cindy', obtenu '{bot_msg['username']}'"
    )
    assert bot_msg["username"] != "Wally", "username broadcast ne doit pas être 'Wally' en dur"


@pytest.mark.asyncio
async def test_web_chat_append_message_uses_config_name():
    """
    _wally_respond doit appeler append_prelude et append_message avec config.bot.name,
    pas la chaîne en dur "Wally".
    """
    from bot.dashboard.routes.chat import _wally_respond

    state = _make_app_state(name="Cindy")

    async def noop_broadcast(data: dict) -> None:
        pass

    with patch("bot.dashboard.routes.chat._broadcast", side_effect=noop_broadcast), \
         patch("bot.dashboard.routes.chat._parse_react_tag", return_value=(None, "Réponse de Cindy")), \
         patch("bot.dashboard.routes.chat.asyncio.create_task"):
        await _wally_respond(state, "discord:42", "Testeur", "Bonjour!")

    # append_prelude("web:chat", config.bot.name, reply)
    prelude_args = state.memory.append_prelude.call_args[0]
    assert prelude_args[1] == "Cindy", (
        f"append_prelude auteur attendu 'Cindy', obtenu '{prelude_args[1]}'"
    )

    # append_message("web:chat", config.bot.name, reply, ...)
    # Le 2e appel à append_message est celui du bot
    bot_msg_call = state.memory.append_message.call_args_list[-1]
    msg_args = bot_msg_call[0]
    assert msg_args[1] == "Cindy", (
        f"append_message auteur attendu 'Cindy', obtenu '{msg_args[1]}'"
    )


@pytest.mark.asyncio
async def test_web_chat_typing_event_uses_config_name():
    """
    _wally_respond doit diffuser typing username=config.bot.name,
    pas la chaîne en dur "Wally".
    """
    from bot.dashboard.routes.chat import _wally_respond

    state = _make_app_state(name="Cindy")

    broadcasts = []

    async def capture_broadcast(data: dict) -> None:
        broadcasts.append(data)

    with patch("bot.dashboard.routes.chat._broadcast", side_effect=capture_broadcast), \
         patch("bot.dashboard.routes.chat._parse_react_tag", return_value=(None, "Réponse de Cindy")), \
         patch("bot.dashboard.routes.chat.asyncio.create_task"):
        await _wally_respond(state, "discord:42", "Testeur", "Bonjour!")

    typing_events = [m for m in broadcasts if m.get("type") == "typing"]
    assert len(typing_events) >= 1, "Aucun événement typing diffusé"
    assert typing_events[0]["username"] == "Cindy", (
        f"typing username attendu 'Cindy', obtenu '{typing_events[0]['username']}'"
    )


@pytest.mark.asyncio
async def test_web_chat_insert_message_uses_config_name():
    """
    _wally_respond doit appeler insert_chat_message avec config.bot.name,
    pas la chaîne en dur "Wally".
    """
    from bot.dashboard.routes.chat import _wally_respond

    state = _make_app_state(name="Cindy")

    async def noop_broadcast(data: dict) -> None:
        pass

    with patch("bot.dashboard.routes.chat._broadcast", side_effect=noop_broadcast), \
         patch("bot.dashboard.routes.chat._parse_react_tag", return_value=(None, "Réponse de Cindy")), \
         patch("bot.dashboard.routes.chat.asyncio.create_task"):
        await _wally_respond(state, "discord:42", "Testeur", "Bonjour!")

    # insert_chat_message("wally", config.bot.name, None, reply, True, now)
    db_call_args = state.db.insert_chat_message.call_args[0]
    # args: (sender_id, username, avatar_url, content, is_wally, now)
    sender_id = db_call_args[0]
    username_arg = db_call_args[1]
    assert sender_id == "wally", f"sender_id doit rester 'wally' (stable interne), obtenu '{sender_id}'"
    assert username_arg == "Cindy", (
        f"username insert_chat_message attendu 'Cindy', obtenu '{username_arg}'"
    )
