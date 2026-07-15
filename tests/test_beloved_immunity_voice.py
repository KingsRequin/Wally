# tests/test_beloved_immunity_voice.py
"""
Tests pour le câblage VOCAL de l'easter egg "utilisateur aimé" (Malef,
`discord:706837895063011338`) : le prompt vocal doit recevoir sa directive
comportementale (court-circuitant la colère), et l'immunité émotionnelle
(`beloved=`) doit être transmise à `bot.emotion.process_message` depuis le
vocal comme elle l'est déjà à l'écrit (tests/test_beloved_immunity.py) et
sur Twitch (tests/test_beloved_immunity_twitch.py).

⚠️ PIÈGE MagicMock : un MagicMock non configuré est truthy, donc
`bot.persona.is_beloved(...)` semblerait toujours True si on ne le configure
pas explicitement. Chaque test de garde ci-dessous fixe explicitement
`bot.persona.is_beloved` avec `MagicMock(return_value=True/False)`.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.discord.voice.brain import _voice_system, _voice_post_emotion
from bot.intelligence.persona import PersonaService
from bot.intelligence.prompts import PromptBuilder

_MALEF_ID = "706837895063011338"
_NORMAL_ID = "111111111111111111"

_USERS_MD = f"## discord:{_MALEF_ID}\nTu es éperdument amoureux de cette personne. Tu glisses des cœurs.\n"
_EMOTIONS_MD = "\n## anger_high\nTu es furax, cinglant, et tu n'hésites pas à insulter.\n"

_FURAX = {"anger": 0.9, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}


def _voice_bot(tmp_path):
    (tmp_path / "USERS.md").write_text(_USERS_MD, encoding="utf-8")
    (tmp_path / "EMOTIONS.md").write_text(_EMOTIONS_MD, encoding="utf-8")
    bot = MagicMock()
    bot.persona = PersonaService(persona_dir=str(tmp_path))
    bot.prompts = PromptBuilder()
    bot.emotion.get_state.return_value = dict(_FURAX)
    bot.emotion.get_secondary_emotions.return_value = []
    return bot


# ── (a) build_voice_system transmet bien user_directive à build_system_prompt ──

def test_build_voice_system_forwards_user_directive():
    pb = PromptBuilder()
    flat = {"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    result = pb.build_voice_system(
        emotion_state=flat,
        user_directive="Tu es éperdument amoureux de cette personne.",
    )
    assert "éperdument amoureux" in result
    assert "--- Directive comportementale ---" in result


# ── (b) prompt vocal d'un utilisateur aimé : directive présente, colère absente ──

def test_voice_system_beloved_user_gets_directive_not_anger(tmp_path):
    bot = _voice_bot(tmp_path)
    result = _voice_system(bot, speaker_user_id=_MALEF_ID)
    assert "amoureux" in result.lower()
    assert "furax" not in result.lower()
    assert "cinglant" not in result.lower()


# ── (c) non-régression : un utilisateur normal garde sa directive de colère ──

def test_voice_system_normal_user_keeps_anger_directive(tmp_path):
    bot = _voice_bot(tmp_path)
    result = _voice_system(bot, speaker_user_id=_NORMAL_ID)
    assert "furax" in result.lower()
    assert "amoureux" not in result.lower()


# ── (d) _voice_post_emotion transmet beloved=True/False à process_message ──

@pytest.mark.asyncio
async def test_voice_post_emotion_passes_beloved_true():
    bot = MagicMock()
    bot.persona.is_beloved = MagicMock(return_value=True)
    bot.emotion.process_message = AsyncMock(return_value=None)
    await _voice_post_emotion(bot, _MALEF_ID, "Malef", "salut wally", 123, "Général", [])
    call_kwargs = bot.emotion.process_message.call_args.kwargs
    assert call_kwargs.get("beloved") is True
    bot.persona.is_beloved.assert_called_with("discord", _MALEF_ID)


@pytest.mark.asyncio
async def test_voice_post_emotion_passes_beloved_false():
    bot = MagicMock()
    bot.persona.is_beloved = MagicMock(return_value=False)
    bot.emotion.process_message = AsyncMock(return_value=None)
    await _voice_post_emotion(bot, _NORMAL_ID, "Bob", "salut wally", 123, "Général", [])
    call_kwargs = bot.emotion.process_message.call_args.kwargs
    assert call_kwargs.get("beloved") is False
