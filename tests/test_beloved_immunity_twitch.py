# tests/test_beloved_immunity_twitch.py
"""
Tests pour le câblage Twitch de l'easter egg "utilisateur aimé" :
- persona.user_directive/is_beloved matchent sur le PSEUDO (clé Twitch), pas
  sur l'ID numérique (bot.persona.py, déjà couvert côté Discord par
  tests/test_beloved_immunity_discord.py) ;
- la garde trust de `_post_process` (bot/twitch/handlers.py) et le câblage
  `user_directive` du chemin spontané (`_spontaneous_respond_twitch`).

⚠️ PIÈGE MagicMock : un MagicMock non configuré est truthy, donc
`bot.persona.is_beloved(...)` semblerait toujours True si on ne le configure
pas explicitement. Chaque test de garde ci-dessous fixe `bot.persona.is_beloved`
explicitement avec `MagicMock(return_value=True/False)` (voir aussi le fix
apporté à `make_bot()` dans tests/test_twitch_handlers.py).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.intelligence.persona import PersonaService
from bot.twitch.handlers import _post_process, _spontaneous_respond_twitch
from tests.test_twitch_handlers import make_bot
from tests.test_spontaneous import make_bot_for_spontaneous

_USERS_MD = "## twitch:malef__\nTu es amoureux.\n"


def _persona(tmp_path):
    (tmp_path / "USERS.md").write_text(_USERS_MD, encoding="utf-8")
    return PersonaService(persona_dir=str(tmp_path))


def test_malef_matched_by_username_not_id(tmp_path):
    """L'ID numérique Twitch n'est PAS la clé — le pseudo l'est."""
    ps = _persona(tmp_path)
    assert ps.is_beloved("twitch", "123456789", "Malef__") is True
    assert ps.is_beloved("twitch", "malef__", "") is False


def test_other_chatter_not_beloved(tmp_path):
    assert _persona(tmp_path).is_beloved("twitch", "999", "un_viewer") is False


def test_directive_reaches_prompt(tmp_path):
    from bot.intelligence.prompts import PromptBuilder

    ps = _persona(tmp_path)
    result = PromptBuilder().build_system_prompt(
        emotion_state={"anger": 0.9, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        emotion_directives={"anger_high": "Tu es furax et cinglant."},
        user_directive=ps.user_directive("twitch", "123456789", "Malef__"),
    )
    assert "amoureux" in result
    assert "furax" not in result.lower()


# ── Garde trust dans `_post_process` (Twitch) ─────────────────────────────────
# Miroir des gardes Discord (tests/test_beloved_immunity.py, Garde 3) : le
# chemin Twitch n'a ni spam-detection ni mute par colère globale, seule la
# garde trust_delta/heuristique existe.

@pytest.mark.asyncio
async def test_beloved_negative_trust_delta_not_applied():
    """Un delta de trust NÉGATIF venant d'un chatter aimé n'est jamais appliqué."""
    bot = make_bot()
    bot.persona.is_beloved = MagicMock(return_value=True)
    bot.emotion.process_message = AsyncMock(
        return_value={"trust_delta": -0.08, "love_delta": 0.0, "user_facts": []}
    )
    await _post_process(bot, "tu es nul", "twitch", "111", 0.5, username="Malef__")
    bot.db.update_trust_score.assert_not_awaited()


@pytest.mark.asyncio
async def test_beloved_positive_trust_delta_still_applied():
    """L'immunité ne bloque que le delta négatif — le positif passe normalement."""
    bot = make_bot()
    bot.persona.is_beloved = MagicMock(return_value=True)
    bot.emotion.process_message = AsyncMock(
        return_value={"trust_delta": 0.05, "love_delta": 0.0, "user_facts": []}
    )
    await _post_process(bot, "merci beaucoup", "twitch", "111", 0.5, username="Malef__")
    bot.db.update_trust_score.assert_awaited_once()
    assert bot.db.update_trust_score.call_args.args[2] == 0.05


@pytest.mark.asyncio
async def test_normal_user_negative_trust_delta_applied():
    """Non-régression : un chatter normal subit bien le delta négatif."""
    bot = make_bot()
    bot.persona.is_beloved = MagicMock(return_value=False)
    bot.emotion.process_message = AsyncMock(
        return_value={"trust_delta": -0.08, "love_delta": 0.0, "user_facts": []}
    )
    await _post_process(bot, "tu es nul", "twitch", "111", 0.5, username="un_viewer")
    bot.db.update_trust_score.assert_awaited_once()
    assert bot.db.update_trust_score.call_args.args[2] == -0.08


@pytest.mark.asyncio
async def test_beloved_heuristic_insult_fallback_skipped():
    """LLM indisponible (llm_deltas falsy) : le fallback heuristique
    (insult_words -> -0.05) est aussi sauté pour un chatter aimé."""
    bot = make_bot()
    bot.persona.is_beloved = MagicMock(return_value=True)
    bot.emotion.process_message = AsyncMock(return_value=None)
    await _post_process(bot, "espèce d'idiot", "twitch", "111", 0.5, username="Malef__")
    bot.db.update_trust_score.assert_not_awaited()


@pytest.mark.asyncio
async def test_normal_user_heuristic_insult_fallback_applied():
    """Non-régression : le fallback heuristique s'applique à un chatter normal."""
    bot = make_bot()
    bot.persona.is_beloved = MagicMock(return_value=False)
    bot.emotion.process_message = AsyncMock(return_value=None)
    await _post_process(bot, "espèce d'idiot", "twitch", "111", 0.5, username="un_viewer")
    bot.db.update_trust_score.assert_awaited_once_with("twitch", "111", -0.05)


@pytest.mark.asyncio
async def test_post_process_passes_beloved_to_emotion():
    """`beloved` est transmis à `emotion.process_message`, calculé sur le pseudo."""
    bot = make_bot()
    bot.persona.is_beloved = MagicMock(return_value=True)
    await _post_process(bot, "salut", "twitch", "111", 0.5, username="Malef__")
    call_kwargs = bot.emotion.process_message.call_args.kwargs
    assert call_kwargs.get("beloved") is True


@pytest.mark.asyncio
async def test_post_process_checks_is_beloved_with_username_not_id_alone():
    """`_post_process` doit interroger `is_beloved` avec le PSEUDO — sur Twitch,
    l'ID numérique seul ne permet jamais de matcher la directive."""
    bot = make_bot()
    bot.persona.is_beloved = MagicMock(return_value=False)
    await _post_process(bot, "salut", "twitch", "111", 0.5, username="Malef__")
    bot.persona.is_beloved.assert_called_once_with("twitch", "111", "Malef__")


# ── Câblage `user_directive` dans le chemin spontané ──────────────────────────

@pytest.mark.asyncio
async def test_spontaneous_wires_user_directive_by_author():
    """`_spontaneous_respond_twitch` n'a pas de `user_id` : la directive doit
    être résolue via l'`author` (pseudo) seul, avec user_id="" explicite."""
    bot = make_bot_for_spontaneous()
    bot._channel_ids = {"testchannel": "123"}
    mock_channel = MagicMock()
    mock_channel.send = AsyncMock()
    bot.get_channel = MagicMock(return_value=mock_channel)
    bot.persona.user_directive = MagicMock(return_value="Tu es amoureux de Malef__.")

    await _spontaneous_respond_twitch(
        bot, "testchannel", "123", "Malef__", "je regarde le stream",
    )

    bot.persona.user_directive.assert_called_once_with("twitch", "", "Malef__")
    prompt_kwargs = bot.prompts.build_system_prompt.call_args.kwargs
    assert prompt_kwargs.get("user_directive") == "Tu es amoureux de Malef__."
