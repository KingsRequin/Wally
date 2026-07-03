import pytest

from bot.intelligence.attention_agent import AttentionAgent


class _FakeCat:
    THOUGHT = "THOUGHT"


class _Facts:
    async def sample_random(self, **k):
        return []


_ARTICLE = {
    "id": 7, "feed_name": "JeuxVideo.com", "title": "Sortie surprise d'un gros jeu",
    "summary": "un résumé", "link": "http://x/1", "lang": "fr",
}


@pytest.mark.asyncio
async def test_rss_seed_chosen_consumes_article(monkeypatch):
    # pas d'introspection, et on force random.choice à prendre l'amorce RSS
    monkeypatch.setattr("bot.intelligence.attention_agent.random.random", lambda: 0.99)
    monkeypatch.setattr("bot.intelligence.attention_agent.random.choice",
                        lambda pool: next(p for p in pool if "Sortie surprise" in p))
    consumed = []

    async def provider():
        return dict(_ARTICLE)

    async def consume(article):
        consumed.append(article["id"])

    agent = AttentionAgent(fact_store=_Facts(), rss_provider=provider, rss_consume=consume)
    seed, rss = await agent._build_idle_seed({}, [], [], "night", _FakeCat, None)

    assert "Sortie surprise" in seed
    assert rss is not None and rss["id"] == 7
    assert consumed == [7]  # consommé car réellement retenu


@pytest.mark.asyncio
async def test_rss_seed_not_chosen_is_not_consumed(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr("bot.intelligence.attention_agent.random.random", lambda: 0.99)

    # random.choice sert AUSSI à piocher le goal (SimpleNamespace) avant le pool
    # final (strings) → mock type-aware : parmi les strings, prend « objectif ».
    def pick(pool):
        strs = [p for p in pool if isinstance(p, str)]
        hit = [p for p in strs if "objectif" in p]
        return hit[0] if hit else pool[0]

    monkeypatch.setattr("bot.intelligence.attention_agent.random.choice", pick)
    consumed = []

    async def provider():
        return dict(_ARTICLE)

    async def consume(article):
        consumed.append(article["id"])

    goals = [SimpleNamespace(content="devenir plus curieux")]
    agent = AttentionAgent(fact_store=_Facts(), rss_provider=provider, rss_consume=consume)
    seed, rss = await agent._build_idle_seed({}, [], goals, "night", _FakeCat, None)

    assert "objectif" in seed
    assert rss is None
    assert consumed == []  # peek sans consommation → article réutilisable au prochain tick


@pytest.mark.asyncio
async def test_rss_english_article_gets_language_note(monkeypatch):
    monkeypatch.setattr("bot.intelligence.attention_agent.random.random", lambda: 0.99)
    monkeypatch.setattr("bot.intelligence.attention_agent.random.choice",
                        lambda pool: next(p for p in pool if "Apex" in p))

    async def provider():
        return {"id": 3, "feed_name": "Dexerto Apex", "title": "Apex Season 29 patch notes",
                "summary": "big changes", "link": "http://x", "lang": "en"}

    async def consume(article):
        return None

    agent = AttentionAgent(fact_store=_Facts(), rss_provider=provider, rss_consume=consume)
    seed, rss = await agent._build_idle_seed({}, [], [], "night", _FakeCat, None)
    assert "anglais" in seed and "réagis en français" in seed


@pytest.mark.asyncio
async def test_no_rss_provider_no_crash(monkeypatch):
    monkeypatch.setattr("bot.intelligence.attention_agent.random.random", lambda: 0.99)
    agent = AttentionAgent(fact_store=_Facts())
    seed, rss = await agent._build_idle_seed({}, [], [], "night", _FakeCat, None)
    assert rss is None  # aucune amorce RSS possible sans provider
