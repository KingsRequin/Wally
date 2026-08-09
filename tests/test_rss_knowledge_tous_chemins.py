"""Le recall des patch notes doit valoir sur les TROIS chemins de réponse.

Signalé par l'owner le 2026-08-09 : « on lui demande souvent les patch notes Apex,
il dit qu'il ne sait pas ». Le mécanisme existait pourtant et fonctionnait — testé sur
quatre formulations réelles, `rss_search_knowledge` remonte les bonnes sections. Mais
`_rss_knowledge_context` n'avait **qu'un seul appelant**, sur le chemin Discord.

Or on parle d'Apex sur Twitch et en vocal, pendant les lives. Là, Wally n'avait
aucune donnée sous les yeux : son « je sais pas » était exact.

Ce n'est donc pas un défaut de DÉCISION — d'où le choix de garder une injection
automatique plutôt que d'ajouter un outil que le modèle devrait penser à appeler.
"""
import re
from pathlib import Path

import pytest

_RACINE = Path(__file__).parent.parent
_CHEMINS = {
    "discord": _RACINE / "bot" / "discord" / "handlers.py",
    "twitch": _RACINE / "bot" / "twitch" / "handlers.py",
    "vocal": _RACINE / "bot" / "discord" / "voice" / "brain.py",
}


@pytest.mark.parametrize("nom", sorted(_CHEMINS))
def test_le_recall_est_branche_sur_ce_chemin(nom):
    """Un mécanisme de contexte utile ne vaut que par ses points d'appel."""
    src = _CHEMINS[nom].read_text(encoding="utf-8")
    assert re.search(r"_rss_knowledge_context\s*\(", src), (
        f"le chemin {nom} ne consulte pas les articles knowledge : sur ce chemin, "
        "une question sur les patch notes Apex reste sans réponse"
    )


@pytest.mark.asyncio
async def test_le_bloc_cite_les_sources_et_coupe_le_web():
    """Contenu du bloc : les marqueurs cliquables et la consigne anti-web_search."""
    from unittest.mock import AsyncMock, MagicMock

    from bot.discord.handlers import _rss_knowledge_context

    bot = MagicMock()
    bot.config.rss.enabled = True
    bot.config.rss.knowledge_max_age_days = 30
    flux = MagicMock()
    flux.role, flux.enabled = "knowledge", True
    bot.config.rss.feeds = [flux]
    bot.db.rss_search_knowledge_avec_synthese = AsyncMock(return_value=[{
        "title": "Apex Legends: Overclocked Midseason Patch Notes — WEAPONS",
        "summary": "Le Nemesis perd 2 dégâts par balle.",
        "link": "https://example.invalid/patch",
    }])

    bloc = await _rss_knowledge_context(bot, "c'est quoi le dernier patch note apex ?")

    assert bloc is not None
    assert "Nemesis" in bloc
    assert "[¹](<https://example.invalid/patch>)" in bloc
    assert "inutile de chercher sur le web" in bloc


@pytest.mark.asyncio
async def test_pas_de_bloc_quand_aucun_article_ne_matche():
    from unittest.mock import AsyncMock, MagicMock

    from bot.discord.handlers import _rss_knowledge_context

    bot = MagicMock()
    bot.config.rss.enabled = True
    bot.config.rss.knowledge_max_age_days = 30
    flux = MagicMock()
    flux.role, flux.enabled = "knowledge", True
    bot.config.rss.feeds = [flux]
    bot.db.rss_search_knowledge_avec_synthese = AsyncMock(return_value=[])

    assert await _rss_knowledge_context(bot, "tu aimes les pâtes ?") is None
