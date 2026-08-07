"""Citations du live.

Tout l'intérêt est le décalage : une réplique reprise dix minutes après fait
sourire, la même trois jours plus tard fait rire. D'où la persistance.
"""
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.quotes import QuoteBook
from bot.discord.handlers import _quote_age, run_quote_tool


class _FakeDB:
    def __init__(self):
        self.rows = []
        self._next = 1

    async def execute(self, query, params=()):
        q = " ".join(query.split())
        if q.startswith("INSERT INTO quotes"):
            author, text, created, shown = params
            self.rows.append({"id": self._next, "author": author, "text": text,
                              "created_at": created, "shown_at": shown})
            self._next += 1
        elif q.startswith("UPDATE quotes SET shown_at"):
            at, rid = params
            for r in self.rows:
                if r["id"] == rid:
                    r["shown_at"] = at

    async def fetch_all(self, query, params=()):
        if "COUNT(*)" in query:
            return [{"n": len(self.rows)}]
        rows = self.rows
        if "WHERE author" in query:
            rows = [r for r in rows if r["author"].lower() == params[0].lower()]
        return sorted(rows, key=lambda r: r["shown_at"] or 0)[:12]


def _book():
    return QuoteBook(_FakeDB())


@pytest.mark.asyncio
async def test_une_citation_est_retenue():
    b = _book()
    assert (await b.add("Azraël", "j'avais plus de balles"))["author"] == "Azraël"
    assert await b.count() == 1


@pytest.mark.asyncio
async def test_une_citation_vide_est_refusee():
    b = _book()
    assert await b.add("Azraël", "ok") is None
    assert await b.add("", "une vraie phrase") is None


@pytest.mark.asyncio
async def test_une_citation_trop_longue_est_coupee():
    """Au-delà, ce n'est plus une punchline et ça ne tient pas à l'écran."""
    b = _book()
    row = await b.add("Azraël", "mot " * 100)
    assert len(row["text"]) <= 160


@pytest.mark.asyncio
async def test_ressortir_ecarte_les_plus_recemment_vues():
    """Le tirage porte sur les moins vues : au-delà de douze citations, celles
    qu'on vient de montrer ne peuvent plus ressortir tout de suite."""
    b = _book()
    for i in range(15):
        await b.add("Azraël", f"réplique {i}")
    for i, row in enumerate(b._db.rows):
        row["shown_at"] = i          # la 14 est la plus récemment vue
    # Un seul tirage : au fil des rappels, tout le monde redevient candidat —
    # c'est la rotation voulue, pas un défaut.
    sorti = (await b.recall())["text"]
    assert sorti not in {"réplique 12", "réplique 13", "réplique 14"}


@pytest.mark.asyncio
async def test_ressortir_marque_la_citation_comme_vue():
    """Sinon la même reviendrait en boucle."""
    b = _book()
    await b.add("Azraël", "une réplique")
    b._db.rows[0]["shown_at"] = 0
    await b.recall()
    assert b._db.rows[0]["shown_at"] > 0


@pytest.mark.asyncio
async def test_ressortir_peut_viser_un_auteur():
    b = _book()
    await b.add("Azraël", "phrase A")
    await b.add("Rina", "phrase B")
    assert (await b.recall("Rina"))["text"] == "phrase B"


@pytest.mark.asyncio
async def test_ressortir_sans_rien_en_stock():
    assert await _book().recall() is None


# ── l'âge affiché ──

def test_l_age_est_dit_en_langage_de_personne():
    now = time.time()
    assert _quote_age(now - 60) == "tout à l'heure"
    assert _quote_age(now - 7200) == "plus tôt aujourd'hui"
    assert _quote_age(now - 86400 * 1.2) == "hier"
    assert _quote_age(now - 86400 * 4) == "il y a 4 jours"
    assert _quote_age(None) == ""


# ── l'outil ──

@pytest.mark.asyncio
async def test_l_outil_retient_et_affiche():
    narrator = MagicMock()
    bot = SimpleNamespace(quotes=MagicMock(), overlay_narrator=narrator)
    bot.quotes.add = AsyncMock(return_value={"author": "Azraël", "text": "ça pique"})
    bot.quotes.count = AsyncMock(return_value=3)
    out = json.loads(await run_quote_tool(bot, {"author": "Azraël", "text": "ça pique"}))
    assert out["status"] == "ok"
    narrator.show_quote.assert_called_once()


@pytest.mark.asyncio
async def test_l_outil_ressort_une_ancienne():
    narrator = MagicMock()
    bot = SimpleNamespace(quotes=MagicMock(), overlay_narrator=narrator)
    bot.quotes.recall = AsyncMock(return_value={
        "author": "Azraël", "text": "ça pique", "created_at": time.time() - 86400 * 3})
    msg = json.loads(await run_quote_tool(bot, {"recall": True}))["message"]
    assert "il y a 3 jours" in msg


@pytest.mark.asyncio
async def test_l_outil_le_dit_quand_le_carnet_est_vide():
    bot = SimpleNamespace(quotes=MagicMock(), overlay_narrator=None)
    bot.quotes.recall = AsyncMock(return_value=None)
    assert json.loads(await run_quote_tool(bot, {"recall": True}))["status"] == "empty"


@pytest.mark.asyncio
async def test_sans_carnet_l_outil_le_dit():
    out = json.loads(await run_quote_tool(SimpleNamespace(), {"recall": True}))
    assert out["status"] == "unavailable"
