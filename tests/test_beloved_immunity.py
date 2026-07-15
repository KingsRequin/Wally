# tests/test_beloved_immunity.py
"""
Tests pour les 4 gardes d'immunité "utilisateur aimé" (`is_beloved`) dans
bot/discord/handlers.py. La promesse de la feature est que RIEN ne peut casser
cet easter egg : ces tests exercent chaque garde avec un utilisateur réellement
"aimé" (is_beloved=True) ET un utilisateur normal (is_beloved=False), pour
détecter toute régression future sur les conditions `not _beloved`.

⚠️ PIÈGE MagicMock : un MagicMock non configuré est truthy, donc
`bot.persona.is_beloved(...)` semblerait toujours True si on ne le configure
pas explicitement. Chaque test ci-dessous fixe `bot.persona.is_beloved`
explicitement avec `MagicMock(return_value=True/False)`.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.discord.handlers import _check_spam, _post_process, handle_message, TIMEOUT_REACTIONS
from tests.test_spam_detection import _make_spam_bot, _make_msg
from tests.test_discord_handlers import make_bot, make_message


# ── Garde 1 : Spam (_check_spam, ~ligne 638) ───────────────────────────────────

@pytest.mark.asyncio
async def test_beloved_user_never_muted_by_spam():
    """Un utilisateur aimé qui floode n'est jamais détecté/muté, même largement
    au-dessus du seuil."""
    bot = _make_spam_bot(max_messages=3, window_seconds=10)
    bot.persona.is_beloved = MagicMock(return_value=True)
    msg = _make_msg()

    # Bien au-delà du seuil (3) : jamais détecté comme spam.
    for _ in range(6):
        assert await _check_spam(bot, msg) is False

    bot.db.add_timeout.assert_not_awaited()
    bot.persona.is_beloved.assert_called_with("discord", str(msg.author.id))


@pytest.mark.asyncio
async def test_normal_user_still_spam_muted():
    """Non-régression : un utilisateur normal qui floode est toujours mute."""
    bot = _make_spam_bot(max_messages=3, window_seconds=10)
    bot.persona.is_beloved = MagicMock(return_value=False)
    msg = _make_msg()

    assert await _check_spam(bot, msg) is False
    assert await _check_spam(bot, msg) is False
    assert await _check_spam(bot, msg) is True  # 3e message : spam détecté

    bot.db.add_timeout.assert_awaited_once()


# ── Garde 2 : Mute déjà en base (~ligne 1079) ─────────────────────────────────

@pytest.mark.asyncio
async def test_beloved_user_bypasses_existing_mute():
    """Un utilisateur aimé déjà mute en base (`is_muted` True) n'est pas
    bloqué : le pipeline de réponse continue normalement."""
    bot = make_bot(muted=True)
    bot.persona.is_beloved = MagicMock(return_value=True)
    message = make_message(content="wally salut")

    with patch("bot.discord.handlers.asyncio.create_task"):
        await handle_message(bot, message)

    # Le pipeline a continué jusqu'à la réponse (pas de blocage précoce).
    message.reply.assert_awaited_once()
    # Aucune réaction de type "mute" n'a été posée (seule la réaction 🔍 de
    # recherche peut être ajoutée pendant le traitement normal).
    used_emojis = [c.args[0] for c in message.add_reaction.call_args_list]
    assert not any(e in TIMEOUT_REACTIONS for e in used_emojis)


@pytest.mark.asyncio
async def test_normal_user_still_blocked_by_existing_mute():
    """Non-régression : un utilisateur normal déjà mute en base reste bloqué."""
    bot = make_bot(muted=True)
    bot.persona.is_beloved = MagicMock(return_value=False)
    message = make_message(content="wally salut")

    await handle_message(bot, message)

    message.add_reaction.assert_awaited_once()
    emoji_used = message.add_reaction.call_args.args[0]
    assert emoji_used in TIMEOUT_REACTIONS
    message.reply.assert_not_awaited()


# ── Garde 3 : Trust delta (_post_process, ~ligne 1871) ────────────────────────

@pytest.mark.asyncio
async def test_beloved_negative_trust_delta_not_applied():
    """Un delta de trust NÉGATIF venant d'un utilisateur aimé n'est jamais
    appliqué en base."""
    bot = make_bot()
    bot.persona.is_beloved = MagicMock(return_value=True)
    bot.emotion.process_message = AsyncMock(
        return_value={"trust_delta": -0.08, "love_delta": 0.0, "user_facts": []}
    )
    await _post_process(bot, "tu es nul", "discord", "12345", "99999", 0.5)
    bot.db.update_trust_score.assert_not_awaited()


@pytest.mark.asyncio
async def test_beloved_positive_trust_delta_still_applied():
    """Un delta de trust POSITIF venant d'un utilisateur aimé est appliqué
    normalement — l'immunité ne bloque que le négatif."""
    bot = make_bot()
    bot.persona.is_beloved = MagicMock(return_value=True)
    bot.emotion.process_message = AsyncMock(
        return_value={"trust_delta": 0.05, "love_delta": 0.0, "user_facts": []}
    )
    await _post_process(bot, "merci beaucoup", "discord", "12345", "99999", 0.5)
    bot.db.update_trust_score.assert_awaited_once()
    assert bot.db.update_trust_score.call_args.args[2] == 0.05


@pytest.mark.asyncio
async def test_normal_user_negative_trust_delta_applied():
    """Non-régression : un utilisateur normal subit bien le delta négatif."""
    bot = make_bot()
    bot.persona.is_beloved = MagicMock(return_value=False)
    bot.emotion.process_message = AsyncMock(
        return_value={"trust_delta": -0.08, "love_delta": 0.0, "user_facts": []}
    )
    await _post_process(bot, "tu es nul", "discord", "12345", "99999", 0.5)
    bot.db.update_trust_score.assert_awaited_once()
    assert bot.db.update_trust_score.call_args.args[2] == -0.08


@pytest.mark.asyncio
async def test_beloved_heuristic_insult_fallback_skipped():
    """Quand le LLM est indisponible (llm_deltas falsy), le fallback
    heuristique (insult_words -> -0.05) doit aussi être sauté pour un
    utilisateur aimé."""
    bot = make_bot()
    bot.persona.is_beloved = MagicMock(return_value=True)
    bot.emotion.process_message = AsyncMock(return_value=None)  # LLM indisponible
    await _post_process(bot, "espèce d'idiot", "discord", "12345", "99999", 0.5)
    bot.db.update_trust_score.assert_not_awaited()


@pytest.mark.asyncio
async def test_normal_user_heuristic_insult_fallback_applied():
    """Non-régression : le fallback heuristique s'applique bien à un
    utilisateur normal quand le LLM est indisponible."""
    bot = make_bot()
    bot.persona.is_beloved = MagicMock(return_value=False)
    bot.emotion.process_message = AsyncMock(return_value=None)  # LLM indisponible
    await _post_process(bot, "espèce d'idiot", "discord", "12345", "99999", 0.5)
    bot.db.update_trust_score.assert_awaited_once_with("discord", "12345", -0.05)


# ── Garde 4 : Mute par colère globale (_post_process, ~ligne 1915) ───────────

@pytest.mark.asyncio
async def test_beloved_user_immune_to_global_anger_mute():
    """Avec une colère globale à 0.9 (peu importe qui l'a fait monter — la
    colère est un état global, pas propre à cet utilisateur), un utilisateur
    aimé n'est jamais mute."""
    bot = make_bot()
    bot.persona.is_beloved = MagicMock(return_value=True)
    bot.emotion.get_state = MagicMock(
        return_value={"anger": 0.9, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    )
    bot.db.count_recent_triggers = AsyncMock(return_value=5)  # au-dessus du seuil
    await _post_process(bot, "salut wally", "discord", "12345", "99999", 0.5)
    bot.db.add_timeout.assert_not_awaited()


@pytest.mark.asyncio
async def test_normal_user_muted_by_global_anger():
    """Non-régression : un utilisateur normal est bien mute quand la colère
    globale dépasse 0.8 et le seuil de déclenchements est atteint."""
    bot = make_bot()
    bot.persona.is_beloved = MagicMock(return_value=False)
    bot.emotion.get_state = MagicMock(
        return_value={"anger": 0.9, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    )
    bot.db.count_recent_triggers = AsyncMock(return_value=5)
    await _post_process(bot, "salut wally", "discord", "12345", "99999", 0.5)
    assert bot.db.add_timeout.await_count == 2  # tracking (0) + mute réel


# ── beloved=True/False transmis à emotion.process_message ────────────────────

@pytest.mark.asyncio
async def test_post_process_passes_beloved_true_to_emotion():
    bot = make_bot()
    bot.persona.is_beloved = MagicMock(return_value=True)
    await _post_process(bot, "salut", "discord", "12345", "99999", 0.5)
    call_kwargs = bot.emotion.process_message.call_args.kwargs
    assert call_kwargs.get("beloved") is True


@pytest.mark.asyncio
async def test_post_process_passes_beloved_false_to_emotion():
    bot = make_bot()
    bot.persona.is_beloved = MagicMock(return_value=False)
    await _post_process(bot, "salut", "discord", "12345", "99999", 0.5)
    call_kwargs = bot.emotion.process_message.call_args.kwargs
    assert call_kwargs.get("beloved") is False
