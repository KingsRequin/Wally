import pytest

from bot.intelligence.watcher import ServerWatcher

PROMPTS_DIR = "bot/persona/prompts"


class _FakeDB:
    def __init__(self, messages, raises=False):
        self._messages = messages
        self.raises = raises
        self.calls = 0

    async def get_messages_since(self, since_ts):
        self.calls += 1
        if self.raises:
            raise RuntimeError("db down")
        return self._messages


class _FakeLLM:
    def __init__(self, reply="Ça chahute sur #général."):
        self.reply = reply
        self.calls = 0

    async def complete(self, system, messages, **kw):
        self.calls += 1
        self.last_user = messages[-1]["content"]
        return self.reply


def _msgs(n):
    return [
        {"timestamp": float(i), "channel_id": "777", "author": f"u{i}",
         "content": f"message {i}", "platform": "discord"}
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_current_empty_before_refresh():
    w = ServerWatcher(_FakeDB(_msgs(10)), _FakeLLM(), PROMPTS_DIR)
    assert w.current() == ""


@pytest.mark.asyncio
async def test_refresh_builds_digest():
    llm = _FakeLLM("Ambiance calme, deux habitués papotent.")
    w = ServerWatcher(_FakeDB(_msgs(10)), llm, PROMPTS_DIR)
    await w.maybe_refresh()
    assert w.current() == "Ambiance calme, deux habitués papotent."
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_calm_server_gives_empty_digest():
    llm = _FakeLLM()
    w = ServerWatcher(_FakeDB(_msgs(2)), llm, PROMPTS_DIR)  # < _MIN_MESSAGES
    await w.maybe_refresh()
    assert w.current() == ""
    assert llm.calls == 0  # pas d'appel LLM inutile


@pytest.mark.asyncio
async def test_throttle_no_second_llm_call():
    llm = _FakeLLM()
    w = ServerWatcher(_FakeDB(_msgs(10)), llm, PROMPTS_DIR)
    await w.maybe_refresh()
    await w.maybe_refresh()  # dans l'heure → throttlé
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_refresh_failsafe_on_db_error():
    llm = _FakeLLM()
    w = ServerWatcher(_FakeDB(_msgs(10), raises=True), llm, PROMPTS_DIR)
    await w.maybe_refresh()  # ne doit pas lever
    assert w.current() == ""
    assert llm.calls == 0


@pytest.mark.asyncio
async def test_channel_names_used_in_transcript():
    llm = _FakeLLM()
    w = ServerWatcher(_FakeDB(_msgs(5)), llm, PROMPTS_DIR,
                      channel_names={"777": "général"})
    await w.maybe_refresh()
    assert "#général" in llm.last_user
