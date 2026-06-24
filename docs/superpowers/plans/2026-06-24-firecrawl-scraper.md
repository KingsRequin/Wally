# Scraper Firecrawl — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Doter Wally d'une capacité de scraping d'URL (lecture de page complète) via Firecrawl auto-hébergé, déclenchée par tool LLM et automatiquement sur lien collé.

**Architecture:** Un `ScrapeService` (calqué sur `WebSearchService`) appelle l'API Firecrawl self-host via httpx, nettoie/borne le contenu (injection directe si court, résumé via LLM secondaire si long), et l'expose au LLM comme tool `scrape_url`. Un hook dans le handler Discord scrape automatiquement le 1er lien web d'un message (cooldown par canal). La stack Firecrawl tourne dans le `docker-compose.yml` de Wally.

**Tech Stack:** Python 3 asyncio, httpx (déjà dépendance), aiosqlite, Docker Compose, Firecrawl self-host.

## Global Constraints

- Logging : `from loguru import logger` uniquement — jamais `print()` ni `import logging`.
- Tout I/O est async ; jamais de blocage dans l'event loop.
- Tools au format OpenAI Chat Completions : `{"type": "function", "function": {...}}`.
- API mémoire : `user_id` brut (jamais préfixé) — non concerné ici mais règle générale.
- Secrets dans `.env` uniquement ; jamais committer `.env` ; fournir `.env.example`.
- Après modif via config : `config.save()` réécrit `config.yaml` (hot-reload).
- Gestion d'erreur : tout handler top-level try/except, log, continue — jamais crash.
- Firecrawl self-host : pas de clé API ; URL interne `http://firecrawl-api:3002`.
- Valeurs par défaut : `inline_max_tokens=2000`, `auto_scrape_cooldown_s=30`, `daily_limit=200`.
- Vérification finale OBLIGATOIRE avant « terminé » : `python3 -m pytest -q` (suite complète) doit passer (baseline : échecs préexistants costs/spam tolérés, documentés dans MEMORY.md).
- Invocation Python = `python3` (PAS de venv ; pytest 9.0.2 global). Tous les `pytest ...` / `python -c ...` du plan se lisent `python3 -m pytest ...` / `python3 -c ...`.

---

### Task 1: Config — `FirecrawlConfig`

**Files:**
- Modify: `bot/config.py` (ajouter dataclass + champ `Config` + parsing `load()` + sérialisation `save()`)
- Modify: `config.yaml` (nouveau bloc `firecrawl:`)
- Test: `tests/test_config_firecrawl.py`

**Interfaces:**
- Produces: `FirecrawlConfig(enabled: bool=True, inline_max_tokens: int=2000, auto_scrape_links: bool=True, auto_scrape_cooldown_s: int=30, daily_limit: int=200)` ; accessible via `config.firecrawl`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config_firecrawl.py
from bot.config import FirecrawlConfig


def test_firecrawl_config_defaults():
    cfg = FirecrawlConfig()
    assert cfg.enabled is True
    assert cfg.inline_max_tokens == 2000
    assert cfg.auto_scrape_links is True
    assert cfg.auto_scrape_cooldown_s == 30
    assert cfg.daily_limit == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config_firecrawl.py -v`
Expected: FAIL — `ImportError: cannot import name 'FirecrawlConfig'`

- [ ] **Step 3: Add the dataclass**

Dans `bot/config.py`, juste après la classe `TavilyConfig` (≈ ligne 196) :

```python
@dataclass
class FirecrawlConfig:
    enabled: bool = True
    inline_max_tokens: int = 2000
    auto_scrape_links: bool = True
    auto_scrape_cooldown_s: int = 30
    daily_limit: int = 200
```

- [ ] **Step 4: Wire into `Config` dataclass, `load()`, `save()`**

Dans la dataclass `Config` (après le champ `tavily: TavilyConfig = ...`, ≈ ligne 252) :

```python
    firecrawl: FirecrawlConfig = field(default_factory=FirecrawlConfig)
```

Dans `Config.load()`, près de `tavily_raw = raw.get("tavily", {})` (≈ ligne 335) :

```python
            firecrawl_raw = raw.get("firecrawl", {})
```

Dans l'appel `cls(...)`, après `tavily=TavilyConfig(**tavily_raw),` (≈ ligne 404) :

```python
                firecrawl=FirecrawlConfig(**firecrawl_raw),
```

Dans `Config.save()`, après `"tavily": asdict(self.tavily),` (≈ ligne 436) :

```python
            "firecrawl": asdict(self.firecrawl),
```

- [ ] **Step 5: Add the `config.yaml` block**

Dans `config.yaml`, à côté du bloc `tavily:` :

```yaml
firecrawl:
  enabled: true
  inline_max_tokens: 2000
  auto_scrape_links: true
  auto_scrape_cooldown_s: 30
  daily_limit: 200
```

- [ ] **Step 6: Add a load/save round-trip test**

```python
# append to tests/test_config_firecrawl.py
from bot.config import Config


def test_firecrawl_load_roundtrip(tmp_path):
    import yaml, textwrap
    base = yaml.safe_load(open("config.yaml"))
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(base))
    cfg = Config.load(str(p))
    assert isinstance(cfg.firecrawl.inline_max_tokens, int)
    cfg.save()  # must not raise
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_config_firecrawl.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add bot/config.py config.yaml tests/test_config_firecrawl.py
git commit -m "feat(config): FirecrawlConfig pour le scraper"
```

---

### Task 2: DB — table `scrape_log` + méthodes log/count

**Files:**
- Modify: `bot/db/database.py` (DDL `scrape_log`, ≈ après le bloc `web_search_log` ligne 169)
- Modify: `bot/db/mixins/social.py` (méthodes `log_scrape`, `count_scrapes_today`, ≈ après `count_web_searches_this_month` ligne 247)
- Test: `tests/test_scrape_log.py`

**Interfaces:**
- Produces: `Database.log_scrape(url: str) -> None` ; `Database.count_scrapes_today() -> int`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scrape_log.py
import pytest
from bot.db.database import Database


@pytest.mark.asyncio
async def test_scrape_log_and_count(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.init()
    assert await db.count_scrapes_today() == 0
    await db.log_scrape("https://example.com/article")
    await db.log_scrape("https://example.com/other")
    assert await db.count_scrapes_today() == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scrape_log.py -v`
Expected: FAIL — `AttributeError: 'Database' object has no attribute 'log_scrape'`

- [ ] **Step 3: Add the DDL**

Dans `bot/db/database.py`, juste après l'index `idx_web_search_log_ts` (≈ ligne 169) :

```sql
CREATE TABLE IF NOT EXISTS scrape_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    url TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scrape_log_ts ON scrape_log(timestamp);
```

(Le placer dans la même string SQL multi-statements que `web_search_log`.)

- [ ] **Step 4: Add the mixin methods**

Dans `bot/db/mixins/social.py`, juste après `count_web_searches_this_month` (≈ ligne 247). `time`, `datetime`, `_TZ_DB` sont déjà importés dans ce fichier :

```python
    # ── Scrape log ──────────────────────────────────────────────────────────

    async def log_scrape(self, url: str) -> None:
        await self.execute(
            "INSERT INTO scrape_log (timestamp, url) VALUES (?, ?)",
            (time.time(), url),
        )

    async def count_scrapes_today(self) -> int:
        now = datetime.now(_TZ_DB)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        row = await self.fetch_one(
            "SELECT COUNT(*) AS cnt FROM scrape_log WHERE timestamp >= ?",
            (day_start.timestamp(),),
        )
        return int(row["cnt"]) if row else 0
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_scrape_log.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add bot/db/database.py bot/db/mixins/social.py tests/test_scrape_log.py
git commit -m "feat(db): scrape_log + log_scrape/count_scrapes_today"
```

---

### Task 3: `ScrapeService` core

**Files:**
- Create: `bot/core/scrape.py`
- Test: `tests/test_scrape.py`

**Interfaces:**
- Consumes: `config.firecrawl` (Task 1) ; `db.log_scrape`, `db.count_scrapes_today` (Task 2) ; `BaseLLMClient.complete(system_prompt, messages, purpose=..., max_tokens=...)`.
- Produces:
  - `SCRAPE_TOOL: dict` (format OpenAI)
  - `class ScrapeService(config, db, summarizer=None)` avec :
    - `available -> bool`
    - `async scrape(url: str) -> str`
    - `get_tool_definitions() -> list[dict]`
    - `is_scrapable_url(url: str) -> bool`  (publique — réutilisée Task 7)
    - `async daily_limit_reached() -> bool`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_scrape.py
import json
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scrape.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.core.scrape'`

- [ ] **Step 3: Implement `bot/core/scrape.py`**

```python
# bot/core/scrape.py
from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx
from loguru import logger

if TYPE_CHECKING:
    from bot.config import Config
    from bot.core.llm.base import BaseLLMClient
    from bot.db.database import Database

_MEDIA_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg",
    ".mp4", ".webm", ".mov", ".avi", ".mkv",
    ".mp3", ".wav", ".ogg", ".flac",
    ".pdf", ".zip", ".rar", ".7z", ".tar", ".gz",
)
_MEDIA_HOSTS = ("cdn.discordapp.com", "media.discordapp.net")

_SUMMARY_SYSTEM = (
    "Tu résumes une page web pour un assistant. Restitue les informations factuelles "
    "essentielles en français, en 2 à 4 phrases, sans préambule ni mise en forme superflue. "
    "Conserve chiffres, noms et dates importants."
)

SCRAPE_TOOL = {
    "type": "function",
    "function": {
        "name": "scrape_url",
        "description": (
            "Lis le contenu COMPLET d'une page web précise à partir de son URL. "
            "Utilise quand tu as une URL et que tu dois en connaître le contenu détaillé "
            "(article, patch notes, documentation). N'utilise PAS pour chercher une info "
            "générale — utilise web_search pour ça."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "L'URL exacte de la page à lire (http/https).",
                }
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
}


class ScrapeService:
    def __init__(self, config: "Config", db: "Database", summarizer: "BaseLLMClient | None" = None):
        self._config = config
        self._db = db
        self._summarizer = summarizer
        self._base_url = os.environ.get("FIRECRAWL_API_URL", "").rstrip("/")

    @property
    def available(self) -> bool:
        return bool(self._base_url) and self._config.firecrawl.enabled

    def is_scrapable_url(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
        except Exception:
            return False
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return False
        host = parsed.netloc.lower()
        if any(h in host for h in _MEDIA_HOSTS):
            return False
        path = parsed.path.lower()
        if path.endswith(_MEDIA_EXTENSIONS):
            return False
        return True

    async def daily_limit_reached(self) -> bool:
        count = await self._db.count_scrapes_today()
        return count >= self._config.firecrawl.daily_limit

    async def scrape(self, url: str) -> str:
        if not self.available:
            return "Le scraping n'est pas disponible (Firecrawl non configuré)."
        if not self.is_scrapable_url(url):
            return "Cette URL ne peut pas être lue (média ou lien non supporté)."
        if await self.daily_limit_reached():
            return "Limite quotidienne de scraping atteinte."

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self._base_url}/v1/scrape",
                    json={"url": url, "formats": ["markdown"], "onlyMainContent": True},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("Firecrawl scrape error for {u}: {e}", u=url, e=exc)
            return f"Impossible de lire la page ({url})."

        markdown = (data.get("data") or {}).get("markdown") or ""
        if not markdown.strip():
            return f"La page ne contient pas de texte lisible ({url})."

        await self._db.log_scrape(url)
        return await self._apply_budget(markdown, url)

    async def _apply_budget(self, markdown: str, url: str) -> str:
        approx_tokens = len(markdown) // 4
        if approx_tokens <= self._config.firecrawl.inline_max_tokens:
            return f"Contenu de {url} :\n{markdown.strip()}"

        if self._summarizer is None:
            # Pas de résumeur : on tronque proprement.
            budget_chars = self._config.firecrawl.inline_max_tokens * 4
            return f"Contenu (tronqué) de {url} :\n{markdown[:budget_chars].strip()}…"

        try:
            summary = await self._summarizer.complete(
                _SUMMARY_SYSTEM,
                [{"role": "user", "content": markdown[:24000]}],
                purpose="scrape_summary",
                max_tokens=400,
            )
        except Exception as exc:
            logger.warning("Scrape summary failed for {u}: {e}", u=url, e=exc)
            budget_chars = self._config.firecrawl.inline_max_tokens * 4
            return f"Contenu (tronqué) de {url} :\n{markdown[:budget_chars].strip()}…"

        return f"Résumé de {url} :\n{summary.strip()}"

    def get_tool_definitions(self) -> list[dict]:
        return [SCRAPE_TOOL]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_scrape.py -v`
Expected: PASS (les 7 tests)

- [ ] **Step 5: Commit**

```bash
git add bot/core/scrape.py tests/test_scrape.py
git commit -m "feat(scrape): ScrapeService Firecrawl (tool + budget hybride)"
```

---

### Task 4: Wiring DI (bootstrap + main)

**Files:**
- Modify: `bot/bootstrap.py` (champ `CoreServices.scrape` ≈ ligne 52 ; construction ≈ ligne 129)
- Modify: `bot/main.py` (extraction `svc.scrape` ≈ ligne 96 ; attribut bots ≈ lignes 108, 213)
- Test: manuel (import + boot) — pas de test unitaire dédié (wiring pur)

**Interfaces:**
- Consumes: `ScrapeService` (Task 3), `secondary_llm` (déjà dans bootstrap).
- Produces: `bot.scrape` (attribut sur discord_bot et twitch_bot).

- [ ] **Step 1: Add field to `CoreServices`**

Dans `bot/bootstrap.py`, dans la dataclass `CoreServices`, après `web_search: "WebSearchService"` (≈ ligne 52) :

```python
    scrape: "ScrapeService"
```

- [ ] **Step 2: Import + construct in `build_core_services`**

Ajouter l'import en tête de `build_core_services` (près de `from bot.core.web_search import WebSearchService`, ≈ ligne 68) :

```python
    from bot.core.scrape import ScrapeService
```

Après le bloc `web_search = WebSearchService(config, db)` (≈ ligne 129) :

```python
    scrape = ScrapeService(config, db, summarizer=secondary_llm)
    if scrape.available:
        logger.info("ScrapeService initialized (Firecrawl)")
    else:
        logger.warning("ScrapeService disabled — FIRECRAWL_API_URL missing or disabled in config")
```

- [ ] **Step 3: Add `scrape` to the returned `CoreServices(...)`**

Dans le `return CoreServices(...)` de `build_core_services`, ajouter `scrape=scrape,` à côté de `web_search=web_search,`.

(Si la construction n'est pas par kwargs, suivre le style existant — repérer la ligne `web_search=web_search` ou la position positionnelle de `web_search` et insérer `scrape` juste après, en cohérence avec l'ordre du dataclass.)

- [ ] **Step 4: Extract + attach in `main.py`**

Après `web_search = svc.web_search` (≈ ligne 96) :

```python
    scrape           = svc.scrape
```

Après `discord_bot.web_search = web_search` (≈ ligne 108) :

```python
    discord_bot.scrape = scrape
```

Après `twitch_bot.web_search = web_search` (≈ ligne 213) :

```python
        twitch_bot.scrape = scrape
```

- [ ] **Step 5: Verify import + boot wiring**

Run: `python -c "import bot.bootstrap, bot.main, bot.core.scrape; print('imports ok')"`
Expected: `imports ok` (pas d'ImportError)

- [ ] **Step 6: Commit**

```bash
git add bot/bootstrap.py bot/main.py
git commit -m "feat(scrape): wiring DI ScrapeService (bootstrap + main)"
```

---

### Task 5: Tool dispatch `scrape_url` (Discord + Twitch)

**Files:**
- Modify: `bot/discord/handlers.py` (collecte tools ≈ ligne 1141 ; dispatch ≈ ligne 1174)
- Modify: `bot/twitch/handlers.py` (collecte tools ≈ ligne 299 ; dispatch ≈ ligne 323)
- Test: aucun nouveau test unitaire — le dispatch est une transcription calquée verbatim sur le bloc `web_search`/`image_search` existant ; sa vérification est le check d'import (Step 6) + l'e2e Task 8. (Un test mockant la collecte ré-implémenterait la garde dans le test plutôt que de tester le handler réel — défaut connu, donc évité.)

**Interfaces:**
- Consumes: `bot.scrape` (Task 4), `ScrapeService.get_tool_definitions`, `ScrapeService.scrape`.

- [ ] **Step 1: Discord — collecte des tools**

Dans `bot/discord/handlers.py`, après le bloc `web_search` qui fait `tools.extend(web_search.get_tool_definitions())` (≈ ligne 1141) :

```python
        scrape = getattr(bot, "scrape", None)
        if scrape and scrape.available and not await scrape.daily_limit_reached():
            tools.extend(scrape.get_tool_definitions())
```

- [ ] **Step 2: Discord — dispatch**

Dans `_tool_executor_impl`, juste après le bloc `if name in ("web_search", "image_search"):` (≈ ligne 1183) :

```python
            if name == "scrape_url":
                if "🌐" not in _reaction_emojis:
                    try:
                        await message.add_reaction("🌐")
                        _reaction_emojis.add("🌐")
                    except Exception:
                        pass
                return await scrape.scrape(args["url"])
```

- [ ] **Step 3: Twitch — collecte + dispatch**

Dans `bot/twitch/handlers.py`, après `tools.extend(web_search.get_tool_definitions())` (≈ ligne 299) :

```python
        scrape = getattr(bot, "scrape", None)
        if scrape and scrape.available and not await scrape.daily_limit_reached():
            tools.extend(scrape.get_tool_definitions())
```

Dans le dispatch, après le bloc `if name in ("web_search", "image_search"):` (≈ ligne 326) :

```python
            if name == "scrape_url":
                return await scrape.scrape(args["url"])
```

- [ ] **Step 4: Import check**

Run: `python3 -c "import bot.discord.handlers, bot.twitch.handlers; print('ok')"`
Expected: `ok` (aucune SyntaxError/ImportError)

- [ ] **Step 5: Commit**

```bash
git add bot/discord/handlers.py bot/twitch/handlers.py
git commit -m "feat(scrape): tool scrape_url dispatch Discord + Twitch"
```

---

### Task 6: Auto-scrape du 1er lien collé (Discord)

**Files:**
- Modify: `bot/discord/handlers.py` (cooldown module-level ; helper `_auto_scrape_block` ; appel dans `_respond` près de la construction de `user_content` ≈ ligne 1117)
- Test: `tests/test_auto_scrape.py`

**Interfaces:**
- Consumes: `bot.scrape` (`is_scrapable_url`, `available`, `scrape`), `config.firecrawl.auto_scrape_links`, `config.firecrawl.auto_scrape_cooldown_s`.
- Produces: `_auto_scrape_block(bot, message) -> str` (bloc `--- Page web ---\n...` ou `""`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auto_scrape.py
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import bot.discord.handlers as H


def _msg(content, channel_id="chan1"):
    m = MagicMock()
    m.content = content
    m.channel.id = channel_id
    return m


def _bot(cooldown=30, enabled=True, scrape_return="Contenu page."):
    b = MagicMock()
    b.config.firecrawl.auto_scrape_links = enabled
    b.config.firecrawl.auto_scrape_cooldown_s = cooldown
    b.scrape.available = True
    b.scrape.is_scrapable_url = lambda u: u.startswith("http") and not u.endswith(".png")
    b.scrape.scrape = AsyncMock(return_value=scrape_return)
    return b


@pytest.mark.asyncio
async def test_auto_scrape_extracts_first_link():
    H._scrape_cooldowns.clear()
    bot = _bot()
    out = await H._auto_scrape_block(bot, _msg("regarde ça https://example.com/a et ça https://example.com/b"))
    assert "Contenu page." in out
    bot.scrape.scrape.assert_awaited_once_with("https://example.com/a")


@pytest.mark.asyncio
async def test_auto_scrape_ignores_media_link():
    H._scrape_cooldowns.clear()
    bot = _bot()
    out = await H._auto_scrape_block(bot, _msg("photo https://example.com/x.png"))
    assert out == ""
    bot.scrape.scrape.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_scrape_respects_cooldown():
    H._scrape_cooldowns.clear()
    bot = _bot(cooldown=999)
    await H._auto_scrape_block(bot, _msg("https://example.com/a"))
    out = await H._auto_scrape_block(bot, _msg("https://example.com/c"))
    assert out == ""  # cooldown actif


@pytest.mark.asyncio
async def test_auto_scrape_disabled():
    H._scrape_cooldowns.clear()
    bot = _bot(enabled=False)
    out = await H._auto_scrape_block(bot, _msg("https://example.com/a"))
    assert out == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auto_scrape.py -v`
Expected: FAIL — `AttributeError: module 'bot.discord.handlers' has no attribute '_scrape_cooldowns'`

- [ ] **Step 3: Add module-level cooldown + URL regex**

Dans `bot/discord/handlers.py`, près des autres dicts module-level (`_spam_tracker`, `_memory_check_cooldowns`) :

```python
import re as _re  # si `re` pas déjà importé au niveau module ; sinon réutiliser `re`

_scrape_cooldowns: dict[str, float] = {}
_URL_RE = _re.compile(r"https?://[^\s<>\"]+")
```

(Si `re` est déjà importé en tête du fichier, n'ajoute PAS de second import — utilise `re.compile(...)` et nomme `_URL_RE`.)

- [ ] **Step 4: Add the helper**

```python
async def _auto_scrape_block(bot: "WallyDiscord", message: "discord.Message") -> str:
    """Scrape le 1er lien web d'un message (cooldown par canal). Retourne un bloc ou ""."""
    import time
    scrape = getattr(bot, "scrape", None)
    if not scrape or not scrape.available:
        return ""
    if not bot.config.firecrawl.auto_scrape_links:
        return ""

    match = _URL_RE.search(message.content or "")
    if not match:
        return ""
    url = match.group(0).rstrip(").,;")
    if not scrape.is_scrapable_url(url):
        return ""

    channel_id = str(message.channel.id)
    now = time.time()
    last = _scrape_cooldowns.get(channel_id, 0.0)
    if now - last < bot.config.firecrawl.auto_scrape_cooldown_s:
        return ""
    _scrape_cooldowns[channel_id] = now

    try:
        content = await scrape.scrape(url)
    except Exception as exc:
        logger.warning("Auto-scrape failed for {u}: {e}", u=url, e=exc)
        return ""
    if not content:
        return ""
    return f"--- Page web ---\n{content}\n"
```

- [ ] **Step 5: Inject into `_respond`**

Dans `_respond`, juste avant la construction de `user_content` (≈ ligne 1117), récupérer le bloc :

```python
        auto_scrape_block = await _auto_scrape_block(bot, message)
```

Puis l'insérer dans la concaténation de `user_content` (≈ ligne 1117-1126), après `prelude_block` :

```python
        user_content = (
            prelude_block
            + auto_scrape_block
            # … reste de la concaténation existante inchangé …
        )
```

(Appliquer la même insertion dans la 2e variante de `user_content` si elle existe au même endroit, ≈ ligne 1128.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_auto_scrape.py -v`
Expected: PASS (4 tests)

- [ ] **Step 7: Commit**

```bash
git add bot/discord/handlers.py tests/test_auto_scrape.py
git commit -m "feat(scrape): auto-scrape du 1er lien collé (cooldown par canal)"
```

---

### Task 7: Infra Docker Firecrawl (stack séparée + réseau partagé)

**Décision retenue :** Firecrawl vit dans sa **propre stack Dockge** à `/opt/stacks/firecrawl/`, basée sur le compose upstream **v2.11.0** quasi verbatim. Wally s'y connecte via un **réseau docker externe partagé**. Backend de file = **Postgres** (`nuq-postgres`) → on **retire FoundationDB** (`foundationdb` + `foundationdb-init` + volumes fdb, expérimental, opt-in seulement). Images **pré-buildées pinnées sur v2.11.0** (pas de build local). Stack finale = 5 services : `api`, `playwright-service`, `redis`, `rabbitmq`, `nuq-postgres`.

**Files:**
- Create: `/opt/stacks/firecrawl/docker-compose.yml` (stack Firecrawl)
- Create: `/opt/stacks/firecrawl/.env` (variables Firecrawl ; non committé)
- Modify: `/opt/stacks/wally-ai/docker-compose.yml` (rattacher `wally` au réseau externe partagé)
- Modify: `/opt/stacks/wally-ai/.env.example` (ajouter `FIRECRAWL_API_URL`)
- Test: `docker compose config` + smoke test API depuis le conteneur Wally

**Interfaces:**
- Produces: l'API Firecrawl joignable depuis le conteneur `wally` à `http://firecrawl-api:3002` (alias réseau).

> **NOTE pour l'implémenteur :** Référence = `https://raw.githubusercontent.com/firecrawl/firecrawl/v2.11.0/docker-compose.yaml`. Les services internes se parlent par hostnames upstream (`redis`, `playwright-service`, `nuq-postgres`, `rabbitmq`) — **garder ces noms** dans la stack Firecrawl (réseau interne `backend`). Seul le service `api` reçoit en plus le réseau externe partagé avec un **alias `firecrawl-api`** pour que Wally le joigne sans ambiguïté.

- [ ] **Step 1: Créer le réseau externe partagé**

Run: `docker network create firecrawl-shared 2>/dev/null; docker network ls | grep firecrawl-shared`
Expected: la ligne `firecrawl-shared` (créé, ou déjà existant).

- [ ] **Step 2: Récupérer le compose de référence**

Run: `curl -fsSL https://raw.githubusercontent.com/firecrawl/firecrawl/v2.11.0/docker-compose.yaml -o /tmp/firecrawl-2.11.0.yaml && grep -c 'service' /tmp/firecrawl-2.11.0.yaml`
Expected: le fichier est téléchargé (sert de base ; on l'adapte ci-dessous).

- [ ] **Step 3: Écrire `/opt/stacks/firecrawl/docker-compose.yml`**

Adapter le compose upstream : images pinnées, FoundationDB retiré, caps mémoire réduits pour CT100, `api` ajouté au réseau partagé avec alias. Squelette cible :

```yaml
name: firecrawl

networks:
  backend:
    driver: bridge
  shared:
    external: true
    name: firecrawl-shared

x-common-env: &common-env
  REDIS_URL: redis://redis:6379
  REDIS_RATE_LIMIT_URL: redis://redis:6379
  PLAYWRIGHT_MICROSERVICE_URL: http://playwright-service:3000/scrape
  POSTGRES_USER: postgres
  POSTGRES_PASSWORD: postgres
  POSTGRES_DB: postgres
  POSTGRES_HOST: nuq-postgres
  POSTGRES_PORT: 5432
  USE_DB_AUTHENTICATION: "false"
  NUM_WORKERS_PER_QUEUE: 4
  CRAWL_CONCURRENT_REQUESTS: 4
  MAX_CONCURRENT_JOBS: 3
  BROWSER_POOL_SIZE: 2

services:
  playwright-service:
    image: ghcr.io/firecrawl/playwright-service:v2.11.0
    container_name: firecrawl-playwright
    environment:
      PORT: 3000
      MAX_CONCURRENT_PAGES: 2
      BLOCK_MEDIA: "true"
    networks: [backend]
    cpus: 2.0
    mem_limit: 2G
    restart: unless-stopped

  api:
    image: ghcr.io/firecrawl/firecrawl:v2.11.0
    container_name: firecrawl-api
    environment:
      <<: *common-env
      HOST: "0.0.0.0"
      PORT: 3002
      WORKER_PORT: 3005
      EXTRACT_WORKER_PORT: 3004
      NUQ_RABBITMQ_URL: amqp://rabbitmq:5672
      ENV: local
    depends_on:
      redis:
        condition: service_started
      playwright-service:
        condition: service_started
      rabbitmq:
        condition: service_healthy
      nuq-postgres:
        condition: service_started
    networks:
      backend:
      shared:
        aliases: [firecrawl-api]
    cpus: 4.0
    mem_limit: 3G
    restart: unless-stopped

  redis:
    image: redis:alpine
    container_name: firecrawl-redis
    command: redis-server --bind 0.0.0.0
    networks: [backend]
    restart: unless-stopped

  rabbitmq:
    image: rabbitmq:3-management
    container_name: firecrawl-rabbitmq
    command: rabbitmq-server
    healthcheck:
      test: ["CMD", "rabbitmq-diagnostics", "-q", "check_running"]
      interval: 5s
      timeout: 5s
      retries: 3
      start_period: 5s
    networks: [backend]
    restart: unless-stopped

  nuq-postgres:
    image: ghcr.io/firecrawl/nuq-postgres:v2.11.0
    container_name: firecrawl-nuq-postgres
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: postgres
    networks: [backend]
    restart: unless-stopped
```

> ⚠️ Le service `api` upstream a `command: node dist/src/harness.js --start-docker` et un volume `fdb-cluster-file`. Avec le backend Postgres (NUQ_BACKEND non défini), le volume FDB est inutile et omis ci-dessus. Si l'image pinnée exige un `command`/volume particulier, le récupérer depuis `/tmp/firecrawl-2.11.0.yaml` et l'ajouter SANS réintroduire FoundationDB. Le smoke test (Step 6) valide le bon démarrage.

- [ ] **Step 4: Rattacher `wally` au réseau partagé**

Dans `/opt/stacks/wally-ai/docker-compose.yml`, déclarer le réseau externe et l'ajouter au service `wally`.

Section `networks:` (haut du fichier) — ajouter :

```yaml
  firecrawl-shared:
    external: true
```

Service `wally` — la clé `networks:` passe de `- wally-net` à :

```yaml
    networks:
      - wally-net
      - firecrawl-shared
```

- [ ] **Step 5: Variables d'environnement**

Dans `/opt/stacks/wally-ai/.env.example`, ajouter :

```bash
# Firecrawl self-host (scraping). Hostname = alias réseau de la stack firecrawl.
FIRECRAWL_API_URL=http://firecrawl-api:3002
```

Ajouter la même ligne dans le `.env` réel (non committé). Créer `/opt/stacks/firecrawl/.env` (peut rester quasi vide : les valeurs par défaut du compose suffisent en self-host sans auth).

- [ ] **Step 6: Démarrer Firecrawl + smoke test depuis Wally**

Run:
```bash
cd /opt/stacks/firecrawl && docker compose config >/dev/null && echo "firecrawl compose valide"
docker compose up -d
sleep 30
docker exec wally-bot sh -c 'curl -fsS -X POST http://firecrawl-api:3002/v1/scrape -H "Content-Type: application/json" -d "{\"url\":\"https://example.com\",\"formats\":[\"markdown\"]}"' | head -c 400
```
Expected: `firecrawl compose valide` puis une réponse JSON contenant `"markdown"`. Si l'API ne répond pas, inspecter `docker compose -f /opt/stacks/firecrawl/docker-compose.yml logs api` et ajuster `command`/env d'après le compose upstream (sans FDB).

- [ ] **Step 7: Commit**

```bash
cd /opt/stacks/wally-ai
git add docker-compose.yml .env.example
git commit -m "feat(scrape): rattache wally au reseau partage Firecrawl"
```

(La stack `/opt/stacks/firecrawl/` n'est pas dans le repo Wally — la documenter dans MEMORY.md à la fin.)

---

### Task 8: Vérification finale + rebuild

**Files:** aucun (validation)

- [ ] **Step 1: Suite de tests complète**

Run: `pytest -q`
Expected: PASS, hors échecs préexistants connus (costs/spam — voir MEMORY.md). Aucun NOUVEL échec.

- [ ] **Step 2: Lint (si configuré)**

Run: `ruff check bot/core/scrape.py bot/discord/handlers.py bot/twitch/handlers.py bot/config.py 2>/dev/null || echo "ruff non configuré — skip"`
Expected: aucune erreur, ou message skip.

- [ ] **Step 3: Rebuild image Wally (backend pas bind-mount)**

Run: `docker compose build wally && docker compose up -d wally`
Expected: build OK, `wally-bot` redémarre. Vérifier les logs : `docker compose logs --tail=30 wally | grep -i scrape`
Expected log : `ScrapeService initialized (Firecrawl)`.

- [ ] **Step 4: Test bout-en-bout manuel**

Dans un salon Discord : coller un lien d'article web → Wally doit pouvoir en parler (auto-scrape). Demander explicitement « lis cette page : <url> » → le LLM appelle `scrape_url`.
Expected : réponse pertinente basée sur le contenu de la page ; réaction 🌐 ajoutée.

- [ ] **Step 5: Commit final (si ajustements)**

```bash
git add -A
git commit -m "chore(scrape): vérification finale + ajustements"
```

---

## Self-Review (effectuée)

**Couverture du spec :** §1 infra Docker → Task 7 ; §2 ScrapeService → Task 3 ; §3 tool LLM → Task 5 ; §4 auto-scrape → Task 6 ; §5 budget hybride → Task 3 (`_apply_budget`) ; §6 config/env → Task 1 + Task 7 ; §7 logging/quota → Task 2 + Task 3 (`daily_limit_reached`) ; §8 erreurs → Task 3 (try/except gracieux) + Task 7 (`depends_on` non bloquant) ; §9 tests → chaque task.

**Écarts assumés vs spec (raffinements) :** (1) prompt de résumé = constante `_SUMMARY_SYSTEM` dans `scrape.py` plutôt que fichier `bot/persona/prompts/scrape_summary.md` (évite le couplage `load_prompt`/persona). (2) Auto-scrape **attendu inline avec timeout** dans `_respond` plutôt que `asyncio.create_task`, car le contenu doit entrer dans la réponse du message courant. (3) Auto-scrape implémenté côté Discord uniquement (le spec citait `on_message` Discord ; Twitch garde le tool LLM via Task 5).

**Placeholder scan :** le seul `<TAG>` (Task 7) est intentionnel — la composition exacte dépend du tag Firecrawl retenu, avec procédure explicite pour le résoudre (Steps 1-2).

**Cohérence des types :** `ScrapeService(config, db, summarizer=None)`, `scrape(url)->str`, `is_scrapable_url(url)->bool`, `daily_limit_reached()->bool`, `get_tool_definitions()->list[dict]`, `db.log_scrape(url)`, `db.count_scrapes_today()->int`, `_auto_scrape_block(bot, message)->str` — cohérents entre toutes les tasks.
