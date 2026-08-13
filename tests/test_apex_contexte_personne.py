"""Wally sait-il que la personne à qui il parle joue à Apex ?

Le compte lié ne servait QU'AU moment où l'outil était appelé. Wally ne savait
donc pas spontanément qu'une personne joue, ni sous quel pseudo : « j'ai fait un
20 bombe hier » ne lui donnait aucune raison d'aller regarder, et « donne les
stats de X » ne marchait que si quelqu'un pensait à nommer X.

Le compte entre maintenant dans le contexte de la personne qui parle, à côté de
son portrait — un fait, pas une passe de LLM à attendre.
"""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from bot.db.database import Database
from bot.discord.handlers import _apex_account_context

UID = "2360523314"


@pytest_asyncio.fixture
async def db(tmp_path):
    base = await Database.create(str(tmp_path / "test.db"))
    try:
        yield base
    finally:
        await base.close()


def _bot(db, canonical=None):
    bot = MagicMock()
    bot.db = db
    memory = MagicMock()
    # `_user_id` résout les alias vers l'uid canonique — souvent l'id Discord.
    memory._user_id = MagicMock(side_effect=lambda p, u: canonical or f"{p}:{u}")
    bot.memory = memory
    return bot


@pytest.mark.asyncio
async def test_le_compte_lie_entre_dans_le_contexte(db):
    await db.apex_link_account(
        identity="discord:239473178722828288", display_name="keychka",
        apex_name="Keychka", apex_platform="PC", uid=UID,
    )

    bloc = await _apex_account_context(_bot(db), "discord", "239473178722828288")

    assert "Keychka" in bloc
    assert "PC" in bloc


@pytest.mark.asyncio
async def test_sans_compte_lie_rien_nest_dit(db):
    """Un « cette personne n'a pas de compte Apex » à chaque message coûterait
    des tokens pour dire du vide."""
    assert await _apex_account_context(_bot(db), "discord", "42") == ""


@pytest.mark.asyncio
async def test_un_compte_declare_sur_discord_vaut_sur_twitch(db):
    """Le panneau admin ne lie qu'UNE identité à la fois. Sans le repli sur
    l'uid canonique, la même personne serait inconnue dès qu'elle passe du
    Discord au chat Twitch — la moitié de ses messages."""
    await db.apex_link_account(
        identity="discord:239473178722828288", display_name="keychka",
        apex_name="Keychka", apex_platform="PC", uid=UID,
    )
    bot = _bot(db, canonical="discord:239473178722828288")

    bloc = await _apex_account_context(bot, "twitch", "999888")

    assert "Keychka" in bloc


@pytest.mark.asyncio
async def test_une_base_grippee_ne_casse_pas_la_reponse(db):
    bot = _bot(db)
    bot.db = MagicMock()
    bot.db.apex_get_account = AsyncMock(side_effect=RuntimeError("base HS"))

    assert await _apex_account_context(bot, "discord", "1") == ""


def test_les_deux_plateformes_injectent_le_bloc():
    """Un bloc de contexte branché d'un seul côté rend Wally amnésique sur
    l'autre, sans erreur ni trace — c'est la signature que le test de parité
    des outils traque déjà."""
    racine = Path(__file__).resolve().parents[1] / "bot"
    for fichier in ("discord/handlers.py", "twitch/handlers.py"):
        source = (racine / fichier).read_text(encoding="utf-8")
        assert "_apex_account_context(" in source, f"{fichier} n'injecte pas le compte Apex"
