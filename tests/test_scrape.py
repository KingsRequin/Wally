# tests/test_scrape.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.core.scrape import ScrapeService, SCRAPE_TOOL


def make_config(inline_max_tokens=2000, daily_limit=200):
    c = MagicMock()
    c.firecrawl.inline_max_tokens = inline_max_tokens
    c.firecrawl.daily_limit = daily_limit
    return c


def make_db(scrapes_today=0):
    db = MagicMock()
    db.log_scrape = AsyncMock()
    db.count_scrapes_today = AsyncMock(return_value=scrapes_today)
    return db


def _resp(markdown):
    r = MagicMock()
    r.status_code = 200
    r.json = MagicMock(return_value={"success": True, "data": {"markdown": markdown}})
    r.raise_for_status = MagicMock()
    return r


def test_tool_definition_shape():
    assert SCRAPE_TOOL["type"] == "function"
    assert SCRAPE_TOOL["function"]["name"] == "scrape_url"
    assert "url" in SCRAPE_TOOL["function"]["parameters"]["properties"]


def test_available_requires_url():
    import os
    with patch.dict(os.environ, {}, clear=True):
        svc = ScrapeService(make_config(), make_db())
        assert svc.available is False
    with patch.dict(os.environ, {"FIRECRAWL_API_URL": "http://firecrawl-api:3002"}):
        svc = ScrapeService(make_config(), make_db())
        assert svc.available is True


def test_is_scrapable_url_rejects_media():
    svc = ScrapeService(make_config(), make_db())
    assert svc.is_scrapable_url("https://example.com/article") is True
    assert svc.is_scrapable_url("https://cdn.discordapp.com/x/y.png") is False
    assert svc.is_scrapable_url("https://media.discordapp.net/a.jpg") is False
    assert svc.is_scrapable_url("https://example.com/video.mp4") is False
    assert svc.is_scrapable_url("not a url") is False


def test_is_scrapable_url_ssrf_guard():
    svc = ScrapeService(make_config(), make_db())
    # Cibles internes / privées — toutes doivent retourner False
    assert svc.is_scrapable_url("http://localhost:6379") is False
    assert svc.is_scrapable_url("http://127.0.0.1/x") is False
    assert svc.is_scrapable_url("http://192.168.1.185:8080/api") is False
    assert svc.is_scrapable_url("http://10.0.0.5/") is False
    assert svc.is_scrapable_url("http://169.254.169.254/latest/meta-data/") is False
    assert svc.is_scrapable_url("http://172.16.0.1/") is False
    assert svc.is_scrapable_url("http://firecrawl-api:3002/") is False
    assert svc.is_scrapable_url("http://redis/") is False
    # URL publique normale — doit retourner True
    assert svc.is_scrapable_url("https://example.com/article") is True


@pytest.mark.asyncio
async def test_scrape_short_content_inline():
    import os
    with patch.dict(os.environ, {"FIRECRAWL_API_URL": "http://firecrawl-api:3002"}):
        svc = ScrapeService(make_config(), make_db())
    with patch("httpx.AsyncClient.post", AsyncMock(return_value=_resp("Court contenu."))):
        out = await svc.scrape("https://example.com/a")
    assert "Court contenu." in out


@pytest.mark.asyncio
async def test_scrape_long_content_summarized():
    import os
    long_md = "mot " * 4000  # ~ largement au-dessus de inline_max_tokens
    summarizer = MagicMock()
    summarizer.complete = AsyncMock(return_value="Résumé court.")
    with patch.dict(os.environ, {"FIRECRAWL_API_URL": "http://firecrawl-api:3002"}):
        svc = ScrapeService(make_config(inline_max_tokens=100), make_db(), summarizer=summarizer)
    with patch("httpx.AsyncClient.post", AsyncMock(return_value=_resp(long_md))):
        out = await svc.scrape("https://example.com/long")
    summarizer.complete.assert_awaited()
    assert "Résumé court." in out


@pytest.mark.asyncio
async def test_scrape_daily_limit():
    import os
    with patch.dict(os.environ, {"FIRECRAWL_API_URL": "http://firecrawl-api:3002"}):
        svc = ScrapeService(make_config(daily_limit=5), make_db(scrapes_today=5))
    out = await svc.scrape("https://example.com/a")
    assert "limite" in out.lower()


@pytest.mark.asyncio
async def test_scrape_firecrawl_down_graceful():
    import os
    with patch.dict(os.environ, {"FIRECRAWL_API_URL": "http://firecrawl-api:3002"}):
        svc = ScrapeService(make_config(), make_db())
    with patch("httpx.AsyncClient.post", AsyncMock(side_effect=Exception("conn refused"))):
        out = await svc.scrape("https://example.com/a")
    assert out  # message dégradé, pas d'exception
    assert "impossible" in out.lower()


@pytest.mark.asyncio
async def test_scrape_long_content_summarizer_raises_fallback():
    import os
    long_md = "mot " * 4000  # bien au-dessus de inline_max_tokens=100
    summarizer = MagicMock()
    summarizer.complete = AsyncMock(side_effect=Exception("boom"))
    with patch.dict(os.environ, {"FIRECRAWL_API_URL": "http://firecrawl-api:3002"}):
        svc = ScrapeService(make_config(inline_max_tokens=100), make_db(), summarizer=summarizer)
    with patch("httpx.AsyncClient.post", AsyncMock(return_value=_resp(long_md))):
        out = await svc.scrape("https://example.com/long")
    # Ne doit pas lever d'exception et doit retourner le fallback tronqué
    assert out  # pas d'exception
    assert "tronqué" in out
