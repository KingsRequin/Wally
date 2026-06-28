"""Tests pour bot/discord/voice/brain.py — heuristique de prise de parole + génération réponse vocale."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.discord.voice.brain import handle_transcript, generate_voice_reply, generate_voice_greeting


def _bot():
    bot = MagicMock()
    bot.emotion.get_state.return_value = {
        "anger": 0.0, "joy": 0.5, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.0
    }
    bot.emotion.get_secondary_emotions.return_value = []
    bot.memory.search = AsyncMock(return_value="")
    bot.llm.complete_with_tools = AsyncMock(return_value=("salut à tous", []))
    bot.prompts.build_voice_system = MagicMock(return_value="SYSTEM")
    # Persona attributes — must mirror what _respond uses
    bot.persona.build_prompt_block.return_value = "PERSONA_BLOCK"
    bot.persona.emotion_directives = {"joy_mid": "tu es joyeux"}
    bot.persona.weekday_directives = {}
    bot.persona.composite_directives = {}
    bot.persona.secondary_directives = {}
    # Lot A : émotions + mémoire vocale
    bot.emotion.process_message = AsyncMock(return_value=None)
    bot.fact_extractor.record_message = MagicMock()
    bot.memory.add = AsyncMock()
    bot.config.bot.name = "Wally"
    bot.config.bot.trigger_names = ["wally"]
    return bot


@pytest.mark.asyncio
async def test_respond_triggers_speak():
    bot = _bot()
    service = MagicMock()
    service.speak = AsyncMock()
    service.history = []
    service.is_responding = False
    service._pending = None
    await handle_transcript(bot, service, "42", "Alice (@alice)", "wally tu es là ?")
    service.speak.assert_awaited_once()
    assert service.speak.await_args.args[0] == "salut à tous"


@pytest.mark.asyncio
async def test_ignore_does_not_speak():
    """Parole anodine non adressée à Wally (pas nommé, pas une question) → il écoute, il ne parle pas."""
    bot = _bot()
    service = MagicMock()
    service.speak = AsyncMock()
    service.history = []
    service.is_responding = False
    service._pending = None
    await handle_transcript(bot, service, "42", "Alice (@alice)", "blabla")
    service.speak.assert_not_awaited()


@pytest.mark.asyncio
async def test_persona_parity_in_voice_prompt():
    """Vérifie que build_voice_system reçoit bien le bloc persona + toutes les
    directives émotionnelles, comme le chemin texte dans _respond."""
    bot = _bot()
    service = MagicMock()
    service.speak = AsyncMock()
    service.history = []
    service.is_responding = False
    service._pending = None

    await handle_transcript(bot, service, "610550333042589752", "Bob (@bob)", "wally bonjour")

    # build_voice_system doit être appelé avec les args persona
    bot.prompts.build_voice_system.assert_called_once()
    call_kwargs = bot.prompts.build_voice_system.call_args.kwargs

    assert call_kwargs.get("persona_block") == "PERSONA_BLOCK", (
        "persona_block absent ou vide dans l'appel à build_voice_system"
    )
    assert call_kwargs.get("emotion_directives") == {"joy_mid": "tu es joyeux"}, (
        "emotion_directives absent dans l'appel à build_voice_system"
    )
    assert "weekday_directives" in call_kwargs, "weekday_directives manquant"
    assert "composite_directives" in call_kwargs, "composite_directives manquant"
    assert "secondary_directives" in call_kwargs, "secondary_directives manquant"
    assert "active_secondaries" in call_kwargs, "active_secondaries manquant"

    # build_prompt_block doit avoir été appelé
    bot.persona.build_prompt_block.assert_called_once()


@pytest.mark.asyncio
async def test_group_history_consigned_before_reply():
    """La parole entendue est consignée dans le fil de groupe AVANT la réponse ;
    la réponse de Wally n'est ajoutée qu'APRÈS speak()."""
    bot = _bot()
    service = MagicMock()
    snap_at_speak: list = []

    async def capture_speak(text):
        snap_at_speak.extend(list(service.history))

    service.speak = AsyncMock(side_effect=capture_speak)
    service.history = []
    service.is_responding = False
    service._pending = None

    await handle_transcript(bot, service, "42", "Alice (@alice)", "wally ?")

    # Au moment de speak() : la parole de l'utilisateur est déjà dans le fil, mais pas la réponse.
    assert snap_at_speak == [{"role": "user", "content": "Alice (@alice): wally ?"}]
    # Après : user + assistant.
    assert len(service.history) == 2
    assert service.history[-1] == {"role": "assistant", "content": "salut à tous"}


@pytest.mark.asyncio
async def test_speaking_while_busy_only_consigns():
    """Si Wally répond déjà, une nouvelle parole est consignée mais ne déclenche pas
    de seconde réponse concurrente."""
    bot = _bot()
    service = MagicMock()
    service.speak = AsyncMock()
    service.history = []
    service.is_responding = True  # Wally est déjà en train de répondre
    service._pending = None
    await handle_transcript(bot, service, "42", "Bob (@bob)", "wally encore ?")
    service.speak.assert_not_awaited()  # pas de 2e réponse
    assert service.history == [{"role": "user", "content": "Bob (@bob): wally encore ?"}]  # mais consigné
    # La parole entendue n'est pas jetée : elle est mise en attente pour après.
    assert service._pending == ("42", "Bob (@bob)", "wally encore ?")


@pytest.mark.asyncio
async def test_voice_records_memory_and_updates_emotion():
    """Lot A : chaque parole alimente la mémoire (fact_extractor) ; une réponse
    déclenche la mise à jour émotionnelle en fond (process_message)."""
    bot = _bot()
    service = MagicMock()
    service.speak = AsyncMock()
    service.history = []
    service.is_responding = False
    service._pending = None
    service.channel_name = "Général"
    await handle_transcript(bot, service, "42", "Alice (@alice)", "wally salut")
    bot.fact_extractor.record_message.assert_called_once()  # mémoire de groupe
    await asyncio.sleep(0)  # laisse tourner la tâche de fond
    bot.emotion.process_message.assert_awaited()  # humeur mise à jour


@pytest.mark.asyncio
async def test_leave_request_disconnects():
    """Une demande de départ (même sans dire 'quitte le vocal') déconnecte vraiment."""
    bot = _bot()
    service = MagicMock()
    service.speak = AsyncMock()
    service.leave = AsyncMock()
    service.history = []
    service.is_responding = False
    service._pending = None
    await handle_transcript(bot, service, "42", "Alice (@alice)", "wally tu peux partir maintenant")
    service.leave.assert_awaited_once()
    service.speak.assert_awaited_once()  # dit au revoir avant de couper


@pytest.mark.asyncio
async def test_normal_message_does_not_leave():
    bot = _bot()
    service = MagicMock()
    service.speak = AsyncMock()
    service.leave = AsyncMock()
    service.history = []
    service.is_responding = False
    service._pending = None
    await handle_transcript(bot, service, "42", "Alice (@alice)", "wally tu fais quoi ce soir ?")
    service.leave.assert_not_awaited()


def test_stop_request_patterns():
    from bot.discord.voice.brain import _is_stop_request
    assert _is_stop_request("stop")
    assert _is_stop_request("tais-toi wally")
    assert _is_stop_request("chut")
    assert _is_stop_request("la ferme")
    assert not _is_stop_request("c'est top ça")   # 'top' != 'stop' (word boundary)
    assert not _is_stop_request("je raconte ma journée")


def test_leave_request_patterns():
    from bot.discord.voice.brain import _is_leave_request
    assert _is_leave_request("wally tu peux partir")
    assert _is_leave_request("aller dégage du vocal")
    assert _is_leave_request("quitte le vocal stp")
    assert _is_leave_request("casse-toi wally")
    assert _is_leave_request("tu peux nous laisser")
    assert not _is_leave_request("je vais partir bientôt")
    assert not _is_leave_request("tu fais quoi wally")


def _service_for_feed():
    service = MagicMock()
    service.speak = AsyncMock()
    service.history = []
    service.is_responding = False
    service._pending = None
    service.channel_id = 123
    service.channel_name = "vocal-test"
    return service


@pytest.mark.asyncio
async def test_publie_event_heard_avec_latence_stt():
    bot = _bot()
    bot.voice_feed = MagicMock()
    service = _service_for_feed()
    await handle_transcript(bot, service, "42", "Alex (@alex)", "il fait beau", stt_ms=850.0)
    events = [c.args[0] for c in bot.voice_feed.publish.call_args_list]
    heard = [e for e in events if e["type"] == "heard"]
    assert len(heard) == 1
    assert heard[0]["text"] == "il fait beau"
    assert heard[0]["speaker"] == "Alex (@alex)"
    assert heard[0]["stt_ms"] == 850
    assert heard[0]["channel_name"] == "vocal-test"


@pytest.mark.asyncio
async def test_publie_event_reply_quand_wally_repond():
    bot = _bot()
    bot.voice_feed = MagicMock()
    service = _service_for_feed()
    await handle_transcript(bot, service, "42", "Alex", "wally tu es là ?")
    events = [c.args[0] for c in bot.voice_feed.publish.call_args_list]
    replies = [e for e in events if e["type"] == "reply"]
    assert len(replies) == 1
    assert replies[0]["text"] == "salut à tous"
    assert "gen_ms" in replies[0]


@pytest.mark.asyncio
async def test_publie_event_ignored_quand_pas_adresse():
    bot = _bot()
    bot.voice_feed = MagicMock()
    service = _service_for_feed()
    await handle_transcript(bot, service, "42", "Alex", "il fait beau aujourd'hui")
    events = [c.args[0] for c in bot.voice_feed.publish.call_args_list]
    ignored = [e for e in events if e["type"] == "ignored"]
    assert len(ignored) == 1
    assert ignored[0]["text"] == "il fait beau aujourd'hui"


@pytest.mark.asyncio
async def test_generate_voice_reply_uses_speaker_user_id():
    """Vérifie que generate_voice_reply passe le bon user_id à memory.search."""
    bot = _bot()
    await generate_voice_reply(
        bot=bot,
        speaker_label="Alice",
        transcript="test",
        history=[],
        tools=[],
        tool_executor=None,
        speaker_user_id="123456789",
    )
    bot.memory.search.assert_awaited_once()
    call_kwargs = bot.memory.search.call_args.kwargs
    assert call_kwargs.get("user_id") == "123456789", (
        "memory.search appelé avec un user_id incorrect"
    )


def _greeting_user_message(bot) -> str:
    """Récupère le contenu du message user passé à bot.llm.complete par le greeting."""
    bot.llm.complete.assert_awaited_once()
    messages = bot.llm.complete.call_args.args[1]
    return messages[0]["content"]


@pytest.mark.asyncio
async def test_greeting_arrivee_nomme_invitant():
    """À l'arrivée, la salutation nomme la personne qui a invité Wally."""
    bot = _bot()
    bot.llm.complete = AsyncMock(return_value="salut Alex")
    await generate_voice_greeting(
        bot, present_label="Alex (@alex)", channel_name="Général", inviter="Alex",
    )
    msg = _greeting_user_message(bot)
    assert "Alex" in msg and "demandé" in msg, "l'invitant n'est pas nommé dans l'instruction"
    assert "Alex (@alex)" in msg, "la liste des présents n'est pas injectée dans l'instruction"


@pytest.mark.asyncio
async def test_greeting_arrivee_borne_singulier_pluriel():
    """L'instruction d'arrivée encadre l'emploi de « vous » (évite « vous m'avez appelé » à 1 personne)."""
    bot = _bot()
    bot.llm.complete = AsyncMock(return_value="salut")
    await generate_voice_greeting(
        bot, present_label="Alex (@alex)", channel_name="Général", inviter="Alex",
    )
    msg = _greeting_user_message(bot)
    assert "vous" in msg.lower(), "la consigne singulier/pluriel doit mentionner « vous »"


@pytest.mark.asyncio
async def test_greeting_arrivee_sans_invitant_reste_valide():
    """Sans invitant connu, la salutation d'arrivée fonctionne quand même."""
    bot = _bot()
    bot.llm.complete = AsyncMock(return_value="bonjour")
    out = await generate_voice_greeting(bot, present_label="Bob (@bob)", channel_name="Général")
    assert out == "bonjour"
    msg = _greeting_user_message(bot)
    assert "demandé" not in msg, "ne doit pas inventer un invitant absent"
