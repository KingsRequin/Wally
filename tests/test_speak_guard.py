import pytest

from bot.intelligence.action_dispatcher import ActionDispatcher
from bot.intelligence.speak_guard import SpeakGuard

PROMPTS_DIR = "bot/intelligence/persona/prompts"


class _FakeLLM:
    def __init__(self, reply="", raises=False):
        self.reply = reply
        self.raises = raises
        self.calls = 0

    async def complete(self, system, messages, **kw):
        self.calls += 1
        if self.raises:
            raise RuntimeError("boom")
        return self.reply


# --- SpeakGuard : décision ---------------------------------------------------

@pytest.mark.asyncio
async def test_taistoi_blocks():
    g = SpeakGuard(_FakeLLM("TAIS-TOI — rapport que personne n'a demandé"), PROMPTS_DIR)
    ok, reason = await g.worth_sending("Voici mon rapport sur l'emote")
    assert ok is False
    assert "rapport" in reason


@pytest.mark.asyncio
async def test_envoie_passes():
    g = SpeakGuard(_FakeLLM("ENVOIE — vraie question, pertinent"), PROMPTS_DIR)
    ok, _ = await g.worth_sending("T'as pensé quoi du stream ?")
    assert ok is True


@pytest.mark.asyncio
async def test_fail_open_on_error():
    llm = _FakeLLM(raises=True)
    g = SpeakGuard(llm, PROMPTS_DIR)
    ok, reason = await g.worth_sending("peu importe")
    assert ok is True and reason == ""


@pytest.mark.asyncio
async def test_disabled_skips_llm():
    llm = _FakeLLM("TAIS-TOI — devrait pas être appelé")
    g = SpeakGuard(llm, PROMPTS_DIR, enabled=False)
    ok, _ = await g.worth_sending("coucou")
    assert ok is True and llm.calls == 0


@pytest.mark.asyncio
async def test_illisible_fails_open():
    g = SpeakGuard(_FakeLLM("bla bla incohérent"), PROMPTS_DIR)
    ok, _ = await g.worth_sending("coucou")
    assert ok is True


# --- Intégration dispatcher : _speak est bien bloqué -------------------------

class _Channel:
    def __init__(self):
        self.sent = []
        self.guild = type("G", (), {"name": "srv"})()
        self.name = "général"

    async def send(self, msg, **kw):
        self.sent.append(msg)


class _Bot:
    def __init__(self, channel):
        self._channel = channel
        self._wally_recent_speaks = {}

    def get_channel(self, cid):
        return self._channel


@pytest.mark.asyncio
async def test_speak_suppressed_by_guard():
    ch = _Channel()
    guard = SpeakGuard(_FakeLLM("TAIS-TOI — creux"), PROMPTS_DIR)
    d = ActionDispatcher(bot=_Bot(ch), speak_guard=guard)
    await d._speak("123", "un truc inutile")
    assert ch.sent == []


@pytest.mark.asyncio
async def test_speak_passes_guard():
    ch = _Channel()
    guard = SpeakGuard(_FakeLLM("ENVOIE — ok"), PROMPTS_DIR)
    d = ActionDispatcher(bot=_Bot(ch), speak_guard=guard)
    await d._speak("123", "message pertinent")
    assert ch.sent == ["message pertinent"]
