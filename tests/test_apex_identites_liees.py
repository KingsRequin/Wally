"""Un compte Apex déclaré vaut pour la PERSONNE, pas pour une seule identité.

Constaté en prod le 2026-08-13 : Kassandre a déclaré son compte Apex sur son
identité Twitch, et ses comptes Discord et Twitch sont liés dans le panneau.
Wally le voyait quand elle écrivait sur Twitch, et l'ignorait complètement
quand elle écrivait sur Discord.

Le repli ne remontait que dans un sens — alias vers canonique. La liaison posée
sur l'ALIAS restait invisible depuis le CANONIQUE, c'est-à-dire depuis
l'identité qui porte l'essentiel de la mémoire.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from bot.core.apex.service import ApexLegendsService
from bot.db.database import Database
from bot.discord.handlers import _apex_account_context

UID = "1000741357161"
DISCORD = "discord:182881216884637696"   # l'identité canonique
TWITCH = "twitch:90774597"               # l'alias, qui porte la liaison Apex


@pytest_asyncio.fixture
async def db(tmp_path):
    base = await Database.create(str(tmp_path / "test.db"))
    try:
        yield base
    finally:
        await base.close()


@pytest_asyncio.fixture
async def kassandre(db):
    """Sa situation exacte en prod : Apex déclaré sur Twitch, comptes liés."""
    await db.upsert_memory_user(DISCORD, "discord", "KassandreYunikon")
    await db.upsert_memory_user(TWITCH, "twitch", "kassandreyunikon")
    await db.upsert_link_proposal(DISCORD, TWITCH, 0.95)
    props = await db.list_link_proposals()
    await db.accept_link(props[0]["id"])
    await db.apex_link_account(
        identity=TWITCH, display_name="kassandreyunikon",
        apex_name="LicorneKssandre", apex_platform="PC", uid=UID,
    )
    return db


def _bot(db):
    bot = MagicMock()
    bot.db = db
    memory = MagicMock()
    memory._user_id = MagicMock(side_effect=lambda p, u: f"{p}:{u}")
    bot.memory = memory
    return bot


@pytest.mark.asyncio
async def test_le_compte_suit_la_personne_sur_ses_deux_identites(kassandre):
    depuis_twitch = await _apex_account_context(_bot(kassandre), "twitch", "90774597")
    depuis_discord = await _apex_account_context(
        _bot(kassandre), "discord", "182881216884637696"
    )

    assert "LicorneKssandre" in depuis_twitch
    assert "LicorneKssandre" in depuis_discord, (
        "la liaison posée sur l'alias doit valoir depuis le canonique"
    )


@pytest.mark.asyncio
async def test_mes_stats_marchent_depuis_les_deux_cotes(kassandre):
    """Sans pseudo, l'outil vise le compte du DEMANDEUR : « donne mes stats »
    depuis Discord ne trouvait aucun compte à interroger."""
    service = ApexLegendsService(client=MagicMock(), db=kassandre)
    service._client.get = AsyncMock(return_value={
        "global": {"name": "LicorneKssandre", "uid": UID, "platform": "PC"},
        "total": {},
    })

    await service.execute("player_stats", "", requester=DISCORD)

    params = service._client.get.await_args.args[1]
    assert params.get("uid") == UID


@pytest.mark.asyncio
async def test_une_personne_sans_compte_reste_sans_compte(db):
    """Le voisinage d'identités ne doit pas attraper le compte de quelqu'un
    d'autre au passage."""
    await db.upsert_memory_user(DISCORD, "discord", "KassandreYunikon")

    assert await _apex_account_context(_bot(db), "discord", "182881216884637696") == ""


@pytest.mark.asyncio
async def test_un_lien_refuse_ne_transmet_rien(db):
    """Une proposition de liaison REJETÉE dit que ce ne sont pas les mêmes
    personnes : lui faire porter un compte Apex serait pire que rien."""
    await db.upsert_memory_user(DISCORD, "discord", "KassandreYunikon")
    await db.upsert_memory_user(TWITCH, "twitch", "kassandreyunikon")
    await db.upsert_link_proposal(DISCORD, TWITCH, 0.95)
    props = await db.list_link_proposals()
    await db.reject_link(props[0]["id"])
    await db.apex_link_account(
        identity=TWITCH, display_name="kassandreyunikon",
        apex_name="LicorneKssandre", apex_platform="PC", uid=UID,
    )

    assert await _apex_account_context(_bot(db), "discord", "182881216884637696") == ""


@pytest.mark.asyncio
async def test_la_declaration_de_lidentite_courante_prime(kassandre):
    """Si les deux identités ont déclaré un compte, celle qui parle gagne —
    sinon on servirait un compte périmé à quelqu'un qui vient d'en déclarer un."""
    await kassandre.apex_link_account(
        identity=DISCORD, display_name="KassandreYunikon",
        apex_name="AutreCompte", apex_platform="PC", uid="999",
    )

    bloc = await _apex_account_context(_bot(kassandre), "discord", "182881216884637696")

    assert "AutreCompte" in bloc
