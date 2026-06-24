import pytest

from bot.core.vision import VisionService
from bot.core.llm.base import FALLBACK_IMAGE_RESPONSE, FALLBACK_RESPONSE


class _FakeClient:
    """Client OpenAI factice capturant l'appel complete()."""

    def __init__(self, response="Une photo de plage au coucher du soleil."):
        self._response = response
        self.last_call = None
        self.raises = False

    async def complete(self, system_prompt, messages, purpose="response",
                       image_urls=None, user_id=None, max_tokens=None):
        if self.raises:
            raise RuntimeError("boom")
        self.last_call = {
            "system_prompt": system_prompt,
            "messages": messages,
            "purpose": purpose,
            "image_urls": image_urls,
            "max_tokens": max_tokens,
        }
        return self._response


def test_available_reflects_client_presence():
    assert VisionService(None).available is False
    assert VisionService(_FakeClient()).available is True


@pytest.mark.asyncio
async def test_analyze_returns_none_without_client():
    svc = VisionService(None)
    assert await svc.analyze(["https://x/img.png"]) is None


@pytest.mark.asyncio
async def test_analyze_returns_none_without_urls():
    svc = VisionService(_FakeClient())
    assert await svc.analyze(None) is None
    assert await svc.analyze([]) is None
    assert await svc.analyze([""]) is None  # URLs vides filtrées


@pytest.mark.asyncio
async def test_analyze_returns_stripped_text_and_passes_images():
    client = _FakeClient(response="  Un screenshot de stats Valorant.  ")
    svc = VisionService(client)
    result = await svc.analyze(
        ["https://cdn/img1.png", "https://cdn/img2.png"],
        caption="mes stats",
    )
    assert result == "Un screenshot de stats Valorant."
    assert client.last_call["image_urls"] == ["https://cdn/img1.png", "https://cdn/img2.png"]
    assert client.last_call["purpose"] == "image_analysis"
    # La légende est transmise comme message utilisateur
    assert client.last_call["messages"][0]["content"] == "mes stats"


@pytest.mark.asyncio
async def test_analyze_default_caption_when_empty():
    client = _FakeClient()
    svc = VisionService(client)
    await svc.analyze(["https://cdn/img.png"], caption="   ")
    assert client.last_call["messages"][0]["content"] == "Décris cette image."


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback", [FALLBACK_IMAGE_RESPONSE, FALLBACK_RESPONSE, "", "   "])
async def test_analyze_filters_fallback_and_empty(fallback):
    svc = VisionService(_FakeClient(response=fallback))
    assert await svc.analyze(["https://cdn/img.png"]) is None


@pytest.mark.asyncio
async def test_analyze_swallows_client_exception():
    client = _FakeClient()
    client.raises = True
    svc = VisionService(client)
    assert await svc.analyze(["https://cdn/img.png"]) is None
