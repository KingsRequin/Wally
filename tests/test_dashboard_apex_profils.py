"""Le registre des profils Apex, vu et corrigé depuis le panneau admin.

Le registre se remplit tout seul (chat, overlay, sonde du watcher) et personne
ne valide derrière : un rapprochement approximatif peut y inscrire un pseudo qui
mène au mauvais joueur. Sans écran pour le lire, l'erreur reste invisible — et
sans geste pour la retirer, elle est définitive.

La liaison manuelle, elle, évite d'avoir à faire parler Wally dans le chat pour
déclarer le compte de quelqu'un.
"""
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from bot.config import (
    BotConfig,
    DiscordConfig,
    EmotionDecayConfig,
    OpenAIConfig,
    TwitchConfig,
    TwitchEventConfig,
)
from bot.core.apex.service import ApexLegendsService
from bot.dashboard.app import create_dashboard_app
from bot.dashboard.state import AppState
from bot.db.database import Database

HEADERS = {"Authorization": "Bearer testtoken"}
UID = "1000741357161"

_PROFIL = {
    "global": {"name": "LicorneKssandre", "uid": UID, "platform": "PC", "level": 254},
    "total": {"kills": {"name": "BR Kills", "value": 120}},
}


def _make_config():
    cfg = MagicMock()
    cfg.bot = BotConfig(
        trigger_names=["wally"], language_default="fr", context_window_size=20,
        context_token_threshold=3000, journal_time="03:00",
        dashboard_token="testtoken", cost_alert_threshold=25.0,
    )
    cfg.openai = OpenAIConfig(
        primary_model="gpt-5", secondary_model="gpt-5-mini",
        temperature=0.8, max_tokens=1000,
    )
    cfg.discord = DiscordConfig(anger_trigger_threshold=3, timeout_minutes=10)
    cfg.twitch = TwitchConfig(guest_channels=[], cooldown_seconds=10)
    cfg.emotions = {
        n: EmotionDecayConfig(decay_lambda=0.1)
        for n in ("anger", "joy", "sadness", "curiosity", "boredom")
    }
    cfg.twitch_events = {"follow": TwitchEventConfig(active=True, message="Hey!")}
    cfg.save = MagicMock()
    return cfg


@pytest_asyncio.fixture
async def db(tmp_path):
    base = await Database.create(str(tmp_path / "test.db"))
    try:
        yield base
    finally:
        await base.close()


@pytest_asyncio.fixture
async def client(db):
    apex = ApexLegendsService(client=MagicMock(), db=db)
    apex._client.get = AsyncMock(return_value=_PROFIL)
    emotion = MagicMock()
    emotion.get_state.return_value = dict.fromkeys(
        ("anger", "joy", "sadness", "curiosity", "boredom"), 0.1
    )
    state = AppState(
        config=_make_config(), db=db, emotion=emotion, memory=MagicMock(),
        persona=MagicMock(), primary_llm=MagicMock(), secondary_llm=MagicMock(),
        image_client=MagicMock(), token_manager=MagicMock(), twitch_api=None,
        discord_bot=None, twitch_bot=None, start_time=time.time() - 100,
    )
    state.apex = apex
    app = create_dashboard_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ── Lire le registre ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_la_liste_donne_le_lien_du_profil(db, client):
    """Sans le lien, aucun moyen de vérifier que le profil est le bon."""
    await db.apex_remember_profile(
        uid=UID, apex_name="LicorneKssandre", platform="PC", saisi="licorne du 42"
    )

    r = await client.get("/api/admin/apex/profiles", headers=HEADERS)

    assert r.status_code == 200
    profil = r.json()["profiles"][0]
    assert profil["uid"] == UID
    assert profil["apex_name"] == "LicorneKssandre"
    assert profil["url"] == f"https://apexlegendsstatus.com/profile/uid/PC/{UID}"
    assert set(profil["names"]) == {"licorne du 42", "LicorneKssandre"}


@pytest.mark.asyncio
async def test_la_liste_dit_a_qui_le_compte_appartient(db, client):
    """C'est la question de départ : quels comptes Apex sont liés à qui."""
    await db.apex_remember_profile(uid=UID, apex_name="LicorneKssandre", platform="PC")
    await db.apex_link_account(
        identity="discord:610550333042589752", display_name="Brain",
        apex_name="LicorneKssandre", apex_platform="PC", uid=UID,
    )

    r = await client.get("/api/admin/apex/profiles", headers=HEADERS)

    profil = r.json()["profiles"][0]
    assert profil["owner"]["identity"] == "discord:610550333042589752"
    assert profil["owner"]["display_name"] == "Brain"


@pytest.mark.asyncio
async def test_un_profil_sans_proprietaire_le_dit_sans_mentir(db, client):
    """Le watcher consigne des joueurs qui n'appartiennent à personne d'ici."""
    await db.apex_remember_profile(uid=UID, apex_name="LicorneKssandre", platform="PC")

    r = await client.get("/api/admin/apex/profiles", headers=HEADERS)

    assert r.json()["profiles"][0]["owner"] is None


@pytest.mark.asyncio
async def test_la_liste_exige_le_jeton_admin(client):
    """Un uid Apex est une donnée de joueur : elle ne sort pas sans authentification."""
    r = await client.get("/api/admin/apex/profiles")
    assert r.status_code in (401, 403)


# ── Corriger le registre ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_oublier_un_alias_fautif(db, client):
    """Le geste qui répare un rapprochement raté."""
    await db.apex_remember_profile(
        uid=UID, apex_name="LicorneKssandre", platform="PC", saisi="licorne du 42"
    )

    r = await client.delete(
        f"/api/admin/apex/profiles/{UID}/names/licorne du 42", headers=HEADERS
    )

    assert r.status_code == 200
    restants = await db.fetch_all(
        "SELECT name FROM apex_profile_names WHERE uid = ?", (UID,)
    )
    assert [r["name"] for r in restants] == ["LicorneKssandre"]
    # Le nom retiré peut encore être RAPPROCHÉ — deux pseudos voisins le sont
    # par construction. Ce qui compte est qu'il ne soit plus une certitude :
    # le rapprochement, lui, s'annonce avec le lien du profil.
    reste = await db.apex_uid_pour_nom("licorne du 42")
    assert reste is None or reste["exact"] is False
    assert (await db.apex_uid_pour_nom("LicorneKssandre"))["uid"] == UID


@pytest.mark.asyncio
async def test_le_nom_officiel_ne_soublie_pas(db, client):
    """Le prochain scan le réinscrirait : proposer ce geste serait mentir sur
    son effet."""
    await db.apex_remember_profile(uid=UID, apex_name="LicorneKssandre", platform="PC")

    r = await client.delete(
        f"/api/admin/apex/profiles/{UID}/names/LicorneKssandre", headers=HEADERS
    )

    assert r.status_code == 409
    assert (await db.apex_uid_pour_nom("LicorneKssandre"))["uid"] == UID


@pytest.mark.asyncio
async def test_oublier_un_profil_emporte_ses_noms(db, client):
    """Sinon les alias resteraient orphelins et continueraient de matcher."""
    await db.apex_remember_profile(
        uid=UID, apex_name="LicorneKssandre", platform="PC", saisi="licorne du 42"
    )

    r = await client.delete(f"/api/admin/apex/profiles/{UID}", headers=HEADERS)

    assert r.status_code == 200
    assert await db.apex_uid_pour_nom("licorne du 42") is None
    assert await db.apex_uid_pour_nom("LicorneKssandre") is None


# ── Lier à la main ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lier_une_personne_depuis_une_url_collee(db, client):
    """Le cas réel : on a l'URL du profil sous les yeux, pas l'uid."""
    r = await client.post(
        "/api/admin/apex/link", headers=HEADERS,
        json={"identity": "discord:1", "display_name": "Brain",
              "ref": f"https://apexlegendsstatus.com/profile/uid/PC/{UID}"},
    )

    assert r.status_code == 200
    compte = await db.apex_get_account("discord:1")
    assert compte["uid"] == UID
    assert compte["apex_name"] == "LicorneKssandre", "le nom OFFICIEL, pas celui tapé"


@pytest.mark.asyncio
async def test_lier_inscrit_aussi_le_profil_au_registre(db, client):
    """Un compte déclaré doit être joignable par son pseudo comme les autres."""
    await client.post(
        "/api/admin/apex/link", headers=HEADERS,
        json={"identity": "discord:1", "display_name": "Brain", "ref": UID},
    )

    assert (await db.apex_uid_pour_nom("LicorneKssandre"))["uid"] == UID


@pytest.mark.asyncio
async def test_lier_un_compte_inexistant_est_refuse(db, client):
    """Écrire une liaison sans avoir vérifié le compte laisserait un uid mort
    en base, que plus rien ne viendrait corriger."""
    client._transport.app.state.wally.apex._client.get = AsyncMock(
        return_value={"Error": "Player not found."}
    )

    r = await client.post(
        "/api/admin/apex/link", headers=HEADERS,
        json={"identity": "discord:1", "display_name": "Brain", "ref": "9999999999"},
    )

    assert r.status_code == 404
    assert await db.apex_get_account("discord:1") is None


@pytest.mark.asyncio
async def test_delier_rend_la_personne_libre(db, client):
    await db.apex_link_account(
        identity="discord:1", display_name="Brain", apex_name="LicorneKssandre",
        apex_platform="PC", uid=UID,
    )

    r = await client.delete("/api/admin/apex/link/discord:1", headers=HEADERS)

    assert r.status_code == 200
    assert await db.apex_get_account("discord:1") is None


@pytest.mark.asyncio
async def test_delier_ne_supprime_pas_le_profil_du_registre(db, client):
    """Ce que Wally a croisé reste vrai : seule l'appartenance change."""
    await db.apex_remember_profile(uid=UID, apex_name="LicorneKssandre", platform="PC")
    await db.apex_link_account(
        identity="discord:1", display_name="Brain", apex_name="LicorneKssandre",
        apex_platform="PC", uid=UID,
    )

    r = await client.delete("/api/admin/apex/link/discord:1", headers=HEADERS)

    assert r.status_code == 200, "sans déliage effectif, l'assertion suivante ne prouve rien"
    assert (await db.apex_uid_pour_nom("LicorneKssandre"))["uid"] == UID
