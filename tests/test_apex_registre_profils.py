"""Le registre des profils Apex déjà croisés : uid ↔ pseudos ↔ plateforme.

Mesuré le 2026-08-13 contre l'API, avec notre clé :

    /bridge?player=licornekssandre    → « Player not found. […] low priority
        search service. »
    /bridge?player=LicorneKssandre    → même erreur, avec la casse OFFICIELLE
    /nametouid?player=licornekssandre → « Origin refusing the connection […] »
    /bridge?uid=1000741357161         → trouvé : « LicorneKssandre » [ATZ], PC

La recherche par NOM est donc un cul-de-sac pour ce compte, quelle que soit la
casse, et `/nametouid` tape dans le même index cassé. L'uid est le seul recours.
Or il n'était retenu que pour le compte DÉCLARÉ du demandeur (`apex_accounts`,
une ligne par identité Discord/Twitch) : un joueur croisé au hasard n'a pas
d'identité chez nous, donc son uid était perdu dès la réponse rendue. Il fallait
le redonner à chaque question.

Le registre garde chaque profil vu, et tous les noms sous lesquels on l'a vu —
y compris ceux que l'API ne sait pas résoudre.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from bot.core.apex.service import ApexLegendsService, _uid_valide, lien_profil
from bot.db.database import Database

UID = "1000741357161"


@pytest_asyncio.fixture
async def db(tmp_path):
    base = await Database.create(str(tmp_path / "test.db"))
    try:
        yield base
    finally:
        await base.close()


# ── Le registre lui-même ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_un_profil_croise_se_retrouve_par_son_nom_officiel(db):
    await db.apex_remember_profile(uid=UID, apex_name="LicorneKssandre", platform="PC")

    trouve = await db.apex_uid_pour_nom("licornekssandre")

    assert trouve["uid"] == UID
    assert trouve["apex_name"] == "LicorneKssandre"
    assert trouve["platform"] == "PC"
    assert trouve["exact"] is True, "la casse seule ne fait pas un rapprochement"


@pytest.mark.asyncio
async def test_le_nom_tape_devient_un_alias_meme_inconnu_de_lapi(db):
    """Le cœur du besoin : « licornekssandre » n'existe pour aucune recherche
    par nom de l'API. Une fois vu à côté de l'uid, il doit y mener seul."""
    await db.apex_remember_profile(
        uid=UID, apex_name="LicorneKssandre", platform="PC", saisi="licorne du 42"
    )

    trouve = await db.apex_uid_pour_nom("licorne du 42")

    assert trouve["uid"] == UID
    assert trouve["exact"] is True


@pytest.mark.asyncio
async def test_une_faute_de_frappe_est_rapprochee_et_signalee(db):
    await db.apex_remember_profile(uid=UID, apex_name="LicorneKssandre", platform="PC")

    trouve = await db.apex_uid_pour_nom("licornekassandre")

    assert trouve["uid"] == UID
    assert trouve["exact"] is False, "un rapprochement doit pouvoir être annoncé"


@pytest.mark.asyncio
async def test_un_nom_exact_l_emporte_sur_un_voisin_plus_court(db):
    """Sinon « Azrael » irait chercher « Azra », vu deux minutes plus tôt."""
    await db.apex_remember_profile(uid="111", apex_name="Azra", platform="PC")
    await db.apex_remember_profile(uid="222", apex_name="Azrael", platform="PC")

    trouve = await db.apex_uid_pour_nom("azrael")

    assert trouve["uid"] == "222"
    assert trouve["exact"] is True


@pytest.mark.asyncio
async def test_un_changement_de_pseudo_ne_perd_pas_lancien(db):
    """Un pseudo Apex se change ; l'uid non. L'ancien nom reste une porte."""
    await db.apex_remember_profile(uid=UID, apex_name="AncienNom", platform="PC")
    await db.apex_remember_profile(uid=UID, apex_name="NouveauNom", platform="PC")

    assert (await db.apex_uid_pour_nom("anciennom"))["uid"] == UID
    assert (await db.apex_uid_pour_nom("nouveaunom"))["uid"] == UID
    courant = await db.apex_uid_pour_nom("nouveaunom")
    assert courant["apex_name"] == "NouveauNom", "le nom courant est le dernier vu"


@pytest.mark.asyncio
async def test_deux_lettres_ne_designent_personne(db):
    """`matches_name` borne la sous-chaîne à 3 caractères — on hérite du garde-fou."""
    await db.apex_remember_profile(uid=UID, apex_name="LicorneKssandre", platform="PC")

    assert await db.apex_uid_pour_nom("li") is None
    assert await db.apex_uid_pour_nom("") is None


@pytest.mark.asyncio
async def test_revoir_un_profil_ne_cree_pas_de_doublon(db):
    """Le watcher sonde toutes les 30 s pendant tout le live."""
    for _ in range(5):
        await db.apex_remember_profile(uid=UID, apex_name="LicorneKssandre", platform="PC")

    lignes = await db.fetch_all("SELECT * FROM apex_profiles WHERE uid = ?", (UID,))
    noms = await db.fetch_all("SELECT * FROM apex_profile_names WHERE uid = ?", (UID,))
    assert len(lignes) == 1
    assert len(noms) == 1
    assert lignes[0]["seen_count"] == 5


# ── Le lien de vérification ─────────────────────────────────────────────────


def test_le_lien_du_profil_porte_luid_pas_le_pseudo():
    """`/profile/PC/<pseudo>` ne contient rien que l'API ne connaisse déjà —
    mesuré : elle refuse ce pseudo. Seule la forme `uid/` est vérifiable."""
    assert lien_profil(UID, "PC") == f"https://apexlegendsstatus.com/profile/uid/PC/{UID}"
    assert lien_profil(UID, "") == f"https://apexlegendsstatus.com/profile/uid/PC/{UID}"
    assert lien_profil("", "PC") == ""


def test_une_url_de_profil_collee_livre_son_uid():
    """Personne ne va extraire le nombre à la main : on colle l'URL."""
    assert _uid_valide(
        "https://apexlegendsstatus.com/profile/uid/PC/1000741357161"
    ) == UID
    assert _uid_valide("apexlegendsstatus.com/profile/uid/X1/1000741357161/") == UID


def test_une_url_sans_uid_nen_invente_pas():
    """`/profile/PC/licornekssandre` ne porte que le pseudo : l'accepter comme
    uid enverrait une requête absurde à l'API."""
    assert _uid_valide("https://apexlegendsstatus.com/profile/PC/licornekssandre") == ""


# ── Le service : consigner, puis s'en servir ────────────────────────────────


_PROFIL = {
    "global": {"name": "LicorneKssandre", "uid": UID, "platform": "PC", "level": 254},
    "total": {"kills": {"name": "BR Kills", "value": 120}},
}


def _service(db, reponse=_PROFIL):
    service = ApexLegendsService(client=MagicMock(), db=db)
    service._client.get = AsyncMock(return_value=reponse)
    return service


@pytest.mark.asyncio
async def test_un_profil_lu_par_uid_entre_au_registre_avec_le_nom_tape(db):
    """Le seul moment où l'on tient les deux bouts : le pseudo que la personne
    emploie et l'uid qui, lui, marche."""
    service = _service(db)

    await service.execute("player_stats", "licornekssandre", uid=UID)

    trouve = await db.apex_uid_pour_nom("licornekssandre")
    assert trouve["uid"] == UID
    assert trouve["apex_name"] == "LicorneKssandre"


@pytest.mark.asyncio
async def test_un_pseudo_connu_du_registre_est_interroge_par_uid(db):
    """Sans ça, on repartirait sur la recherche par nom — celle qui échoue."""
    await db.apex_remember_profile(uid=UID, apex_name="LicorneKssandre", platform="PC")
    service = _service(db)

    await service.execute("player_stats", "licornekssandre")

    params = service._client.get.await_args.args[1]
    assert params["uid"] == UID
    assert "player" not in params


@pytest.mark.asyncio
async def test_un_rapprochement_flou_est_annonce_avec_le_lien(db):
    """« on est sûr ou pas que c'est cette personne » — le lien tranche."""
    await db.apex_remember_profile(uid=UID, apex_name="LicorneKssandre", platform="PC")
    service = _service(db)

    texte = await service.execute("player_stats", "licornekassandre")

    assert "licornekassandre" in texte, "le nom demandé doit apparaître"
    assert "LicorneKssandre" in texte
    assert lien_profil(UID, "PC") in texte


@pytest.mark.asyncio
async def test_un_nom_exact_ne_declenche_aucune_mise_en_garde(db):
    """Mettre en garde à chaque réponse la rendrait inaudible."""
    await db.apex_remember_profile(uid=UID, apex_name="LicorneKssandre", platform="PC")
    service = _service(db)

    texte = await service.execute("player_stats", "LicorneKssandre")

    assert lien_profil(UID, "PC") not in texte


@pytest.mark.asyncio
async def test_un_compte_declare_passe_avant_le_registre(db):
    """La déclaration explicite d'une personne l'emporte sur ce qu'on a croisé."""
    await db.apex_link_account(
        identity="discord:1", display_name="Brain", apex_name="KingsRequin",
        apex_platform="PC", uid="1012242925358",
    )
    await db.apex_remember_profile(uid=UID, apex_name="Brain", platform="PC")
    service = _service(db)

    await service.execute("player_stats", "Brain", requester="discord:1")

    params = service._client.get.await_args.args[1]
    assert params["uid"] == "1012242925358"


@pytest.mark.asyncio
async def test_un_profil_introuvable_nentre_pas_au_registre(db):
    service = _service(db, {"Error": "Player not found."})

    await service.execute("player_stats", "personneicitres")

    assert await db.apex_uid_pour_nom("personneicitres") is None


@pytest.mark.asyncio
async def test_lechec_par_pseudo_pointe_lurl_qui_porte_luid(db):
    """Renvoyer vers `/profile/PC/<pseudo>` ferait tourner en rond : mesuré,
    l'API refuse ce pseudo. Il faut demander la page `uid/`."""
    service = _service(db, {"Error": "Player not found."})

    texte = await service.execute("player_stats", "licornekssandre")

    assert "profile/uid/" in texte


@pytest.mark.asyncio
async def test_une_base_grippee_ne_casse_pas_la_recherche(db):
    """Le registre est un bonus : son absence ne doit rien empêcher."""
    service = _service(db)
    service._db = MagicMock()
    service._db.apex_find_by_display_name = AsyncMock(return_value=None)
    service._db.apex_get_account = AsyncMock(return_value=None)
    service._db.apex_uid_pour_nom = AsyncMock(side_effect=RuntimeError("base HS"))
    service._db.apex_remember_profile = AsyncMock(side_effect=RuntimeError("base HS"))

    texte = await service.execute("player_stats", "licornekssandre")

    assert "LicorneKssandre" in texte


# ── Les autres chemins qui lisent un profil ─────────────────────────────────


@pytest.mark.asyncio
async def test_une_sonde_passive_alimente_le_registre(db):
    """`fetch_profile` sert au watcher et aux panneaux d'overlay : ce qu'il voit
    doit profiter aux questions posées plus tard dans le chat."""
    service = _service(db)

    await service.fetch_profile("LicorneKssandre")

    assert (await db.apex_uid_pour_nom("licornekssandre"))["uid"] == UID


@pytest.mark.asyncio
async def test_la_progression_vise_luid_connu_du_registre(db):
    """Sans ça, « la progression de licornekassandre » repartait interroger
    l'API par pseudo — et n'avait plus de compte à viser quand elle refusait.

    L'API est ici celle qu'on a mesurée : elle ne répond à AUCUNE recherche par
    nom pour ce compte. Le registre doit suffire.
    """
    await db.apex_remember_profile(uid=UID, apex_name="LicorneKssandre", platform="PC")
    service = _service(db, {"Error": "Player not found."})
    service.history = MagicMock()
    service.history.progression = AsyncMock(return_value=None)

    await service.execute("progression", "licornekassandre", period="24h")

    assert service.history.progression.await_args.args[0] == UID


def test_loutil_dit_au_modele_quon_peut_coller_le_lien():
    """« le nombre à la fin de l'URL » désignait aussi bien
    `/profile/PC/licornekssandre` — dont la fin n'est pas un nombre. Le modèle
    doit savoir quelle forme d'URL porte un uid, et qu'il peut la passer telle
    quelle."""
    from bot.core.apex.tool import APEX_LEGENDS_TOOL

    uid = APEX_LEGENDS_TOOL["function"]["parameters"]["properties"]["uid"]
    assert "profile/uid/" in uid["description"]


@pytest.mark.asyncio
async def test_une_faute_de_frappe_rapprochee_ne_devient_pas_un_alias(db):
    """Sinon le garde-fou s'annule lui-même : « licornekassandre » entrerait au
    registre comme nom EXACT du profil, et la fois suivante plus rien ne
    signalerait le rapprochement — une erreur de visée se figerait en silence."""
    await db.apex_remember_profile(uid=UID, apex_name="LicorneKssandre", platform="PC")
    service = _service(db)

    await service.execute("player_stats", "licornekassandre")

    assert (await db.apex_uid_pour_nom("licornekassandre"))["exact"] is False


@pytest.mark.asyncio
async def test_la_progression_annonce_aussi_le_rapprochement(db):
    """Le doute sur QUI est visé ne dépend pas de l'action demandée."""
    await db.apex_remember_profile(uid=UID, apex_name="LicorneKssandre", platform="PC")
    service = _service(db, {"Error": "Player not found."})
    service.history = MagicMock()
    service.history.progression = AsyncMock(return_value=None)

    texte = await service.execute("progression", "licornekassandre", period="24h")

    assert lien_profil(UID, "PC") in texte
    assert "LicorneKssandre" in texte


@pytest.mark.asyncio
async def test_un_pseudo_non_verifie_par_lapi_ne_devient_pas_un_alias(db):
    """Quand l'uid a servi, le pseudo passé À CÔTÉ n'a été validé par personne :
    l'inscrire en alias exact ferait entrer au registre ce que l'appelant a
    tapé au jugé."""
    service = _service(db)

    await service.fetch_profile("pseudoauhasard", uid=UID)

    trouve = await db.apex_uid_pour_nom("pseudoauhasard")
    assert trouve is None or trouve["exact"] is False


@pytest.mark.asyncio
async def test_un_panneau_overlay_profite_aussi_du_registre(db):
    """Le chat trouvait le compte et l'écran non : même question, deux réponses."""
    await db.apex_remember_profile(uid=UID, apex_name="LicorneKssandre", platform="PC")
    service = _service(db)

    await service.build_panel("stats", player="licornekssandre")

    params = service._client.get.await_args.args[1]
    assert params["uid"] == UID
    assert "player" not in params
