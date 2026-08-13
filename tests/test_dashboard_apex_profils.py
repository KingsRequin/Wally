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
    assert profil["owners"] == [
        {"identity": "discord:610550333042589752", "display_name": "Brain"}
    ]


@pytest.mark.asyncio
async def test_un_profil_sans_proprietaire_le_dit_sans_mentir(db, client):
    """Le watcher consigne des joueurs qui n'appartiennent à personne d'ici."""
    await db.apex_remember_profile(uid=UID, apex_name="LicorneKssandre", platform="PC")

    r = await client.get("/api/admin/apex/profiles", headers=HEADERS)

    assert r.json()["profiles"][0]["owners"] == []


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


@pytest.mark.asyncio
async def test_un_compte_lie_sur_deux_plateformes_napparait_quune_fois(db, client):
    """Vu en prod dès la première ouverture : Azraël est déclaré sur ses DEUX
    identités (le vocal l'identifie en Discord, le chat en Twitch), et le
    profil sortait en double — une ligne par liaison, pas une par compte."""
    await db.apex_remember_profile(uid=UID, apex_name="LicorneKssandre", platform="PC")
    for identity in ("discord:419172225451556874", "twitch:659251746"):
        await db.apex_link_account(
            identity=identity, display_name="azrael_ttv",
            apex_name="LicorneKssandre", apex_platform="PC", uid=UID,
        )

    r = await client.get("/api/admin/apex/profiles", headers=HEADERS)

    profils = r.json()["profiles"]
    assert len(profils) == 1, "un compte, une carte — quel que soit le nombre de liaisons"
    assert {o["identity"] for o in profils[0]["owners"]} == {
        "discord:419172225451556874", "twitch:659251746"
    }


# ── Lier en s'appuyant sur ce qu'on connaît déjà ────────────────────────────


@pytest.mark.asyncio
async def test_lier_par_un_pseudo_deja_au_registre(db, client):
    """Vu en prod : lier « licornekssandre » échouait en 404 alors que ce
    profil était AU REGISTRE avec son uid. La route interrogeait l'API par
    pseudo — l'échec que tout le registre existe pour contourner."""
    await db.apex_remember_profile(uid=UID, apex_name="LicorneKssandre", platform="PC")
    # L'API ne répond QUE par uid, comme mesuré sur ce compte.
    apex = client._transport.app.state.wally.apex
    apex._client.get = AsyncMock(
        side_effect=lambda ep, params: _PROFIL if params.get("uid") else
        {"Error": "Player not found."}
    )

    r = await client.post(
        "/api/admin/apex/link", headers=HEADERS,
        json={"identity": "discord:1", "display_name": "Kassandre",
              "ref": "licornekssandre"},
    )

    assert r.status_code == 200
    assert (await db.apex_get_account("discord:1"))["uid"] == UID


@pytest.mark.asyncio
async def test_lier_par_rapprochement_le_signale(db, client):
    """Une liaison est durable : la poser sur une simple ressemblance sans le
    dire ferait porter à quelqu'un le compte d'un autre, sans trace."""
    await db.apex_remember_profile(uid=UID, apex_name="LicorneKssandre", platform="PC")
    apex = client._transport.app.state.wally.apex
    apex._client.get = AsyncMock(
        side_effect=lambda ep, params: _PROFIL if params.get("uid") else
        {"Error": "Player not found."}
    )

    r = await client.post(
        "/api/admin/apex/link", headers=HEADERS,
        json={"identity": "discord:1", "display_name": "Kassandre",
              "ref": "licornekassandre"},
    )

    assert r.status_code == 200
    assert r.json()["rapproche"] is True


@pytest.mark.asyncio
async def test_un_pseudo_inconnu_partout_reste_refuse(db, client):
    apex = client._transport.app.state.wally.apex
    apex._client.get = AsyncMock(return_value={"Error": "Player not found."})

    r = await client.post(
        "/api/admin/apex/link", headers=HEADERS,
        json={"identity": "discord:1", "display_name": "X", "ref": "personneicitres"},
    )

    assert r.status_code == 404
    assert await db.apex_get_account("discord:1") is None


# ── L'annuaire cherchable ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lannuaire_ne_sarrete_pas_a_deux_cents_personnes(db, client):
    """Le formulaire chargeait `limit=200` : sur 494 personnes connues en prod,
    294 étaient introuvables — pas seulement longues à trouver."""
    for i in range(230):
        await db.upsert_memory_user(f"discord:{100000 + i}", "discord", f"personne{i}")

    r = await client.get("/api/admin/apex/personnes", headers=HEADERS)

    assert r.status_code == 200
    assert len(r.json()["people"]) >= 230


@pytest.mark.asyncio
async def test_on_retrouve_quelquun_par_son_surnom(db, client):
    """« mon ptit pote » désigne KingsRequin : 189 alias existent en prod, et
    c'est souvent le seul nom dont on se souvienne."""
    await db.upsert_memory_user("discord:610550333042589752", "discord", "KingsRequin")
    await db.upsert_alias("mon ptit pote", "discord:610550333042589752",
                          "KingsRequin", "manual", 1.0)

    r = await client.get("/api/admin/apex/personnes", headers=HEADERS)

    fiche = next(p for p in r.json()["people"]
                 if p["identity"] == "discord:610550333042589752")
    assert "mon ptit pote" in fiche["noms"]
    assert "KingsRequin" in fiche["noms"]


@pytest.mark.asyncio
async def test_on_retrouve_quelquun_par_son_pseudo_de_lautre_plateforme(db, client):
    """Quelqu'un change de pseudo Discord mais garde son pseudo Twitch — ou
    l'inverse. Les deux doivent mener à la même personne."""
    # Un vrai snowflake : `_fix_platform` reclasse en Twitch tout id Discord de
    # moins de 13 chiffres, et le test porterait alors sur autre chose.
    moi = "discord:610550333042589752"
    await db.upsert_memory_user(moi, "discord", "NouveauPseudo")
    await db.upsert_memory_user("twitch:105904256", "twitch", "ancienpseudo_ttv")
    await db.upsert_link_proposal(moi, "twitch:105904256", 0.9)
    props = await db.list_link_proposals()
    await db.accept_link(props[0]["id"])

    r = await client.get("/api/admin/apex/personnes", headers=HEADERS)

    fiche = next(p for p in r.json()["people"] if p["identity"] == moi)
    assert "ancienpseudo_ttv" in fiche["noms"], "le pseudo Twitch lié doit être cherchable"


@pytest.mark.asyncio
async def test_lannuaire_necarte_les_identites_sans_plateforme(db, client):
    """91 entrées « unknown: » existent en prod — des pseudos croisés sans
    jamais être rattachés à un compte. Les proposer offrirait un choix qui ne
    peut pas marcher : le contexte n'interroge que `discord:` et `twitch:`, une
    liaison posée là serait muette pour toujours. Idem pour « global: », qui
    n'est pas une personne mais la mémoire communautaire."""
    await db.upsert_memory_user("discord:610550333042589752", "discord", "KingsRequin")
    await db.execute(
        "INSERT INTO memory_users(user_id, platform, last_updated, username) "
        "VALUES(?,?,?,?)", ("unknown:mks_zedd", "unknown", 0, None),
    )
    await db.execute(
        "INSERT INTO memory_users(user_id, platform, last_updated, username) "
        "VALUES(?,?,?,?)", ("global:communaute", "global", 0, None),
    )

    r = await client.get("/api/admin/apex/personnes", headers=HEADERS)

    identites = {p["identity"] for p in r.json()["people"]}
    assert "discord:610550333042589752" in identites
    assert not [i for i in identites if i.startswith(("unknown:", "global:"))]


@pytest.mark.asyncio
async def test_la_carte_montre_les_identites_couvertes(db, client):
    """Déclarer le compte sur Twitch le rend valable sur Discord aussi, les
    deux comptes étant liés. Ne montrer que l'identité déclarée laisse croire
    que l'autre côté est resté sans compte."""
    disc, tw = "discord:182881216884637696", "twitch:90774597"
    await db.upsert_memory_user(disc, "discord", "KassandreYunikon")
    await db.upsert_memory_user(tw, "twitch", "kassandreyunikon")
    await db.upsert_link_proposal(disc, tw, 0.95)
    props = await db.list_link_proposals()
    await db.accept_link(props[0]["id"])
    await db.apex_remember_profile(uid=UID, apex_name="LicorneKssandre", platform="PC")
    await db.apex_link_account(
        identity=tw, display_name="kassandreyunikon",
        apex_name="LicorneKssandre", apex_platform="PC", uid=UID,
    )

    r = await client.get("/api/admin/apex/profiles", headers=HEADERS)

    profil = r.json()["profiles"][0]
    assert [o["identity"] for o in profil["owners"]] == [tw], "une seule liaison déclarée"
    assert disc in profil["couvre"], "l'identité liée est couverte par la même déclaration"
