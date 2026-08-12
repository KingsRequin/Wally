# tests/test_apex_progression.py
"""L'action `progression` et la comparaison « depuis la dernière fois ».

Ces chiffres n'existent pas dans l'API : ils viennent de relevés pris au fil du
temps. Ce que le service ne doit JAMAIS faire, c'est présenter comme un total
de période un chiffre qui ne commence qu'au premier relevé.
"""
import time

import pytest
import pytest_asyncio

from bot.core.apex.history import ApexHistory, debut_de_periode
from bot.core.apex.service import ApexLegendsService
from bot.db.database import Database

UID = "1002761549602"
HEURE = 3600.0


@pytest_asyncio.fixture
async def db(tmp_path):
    base = await Database.create(str(tmp_path / "test.db"))
    try:
        yield base
    finally:
        await base.close()


@pytest_asyncio.fixture
async def service(db):
    svc = ApexLegendsService(client=object(), db=db)
    svc.history = ApexHistory(db)
    return svc


async def _releve(svc, t: float, kills: int) -> None:
    await svc.history.enregistrer(UID, {"kills": kills}, maintenant=t)


@pytest.mark.asyncio
async def test_la_progression_du_mois_se_calcule(service):
    debut = debut_de_periode("mois")
    # Dix minutes avant le mois : assez proche pour que le gain qui suit lui
    # appartienne. Au-delà d'une demi-heure, il n'est plus rattachable.
    await _releve(service, debut - 600, 1000)
    await _releve(service, debut + HEURE, 1120)
    rendu = await service._progression(
        "", "PC", period="mois", notion="kills", requester=None, uid=UID
    )
    assert "120 kills" in rendu
    assert "minimum" not in rendu                    # la période est couverte


@pytest.mark.asyncio
async def test_une_periode_mal_couverte_est_annoncee_comme_telle(service):
    """« Ce mois-ci » alors qu'on ne mesure que depuis le 12 : le dire."""
    debut = debut_de_periode("mois")
    await _releve(service, debut + HEURE, 1000)      # premier relevé DANS le mois
    await _releve(service, debut + 2 * HEURE, 1050)
    rendu = await service._progression(
        "", "PC", period="mois", notion="kills", requester=None, uid=UID
    )
    assert "50 kills" in rendu
    assert "minimum" in rendu


@pytest.mark.asyncio
async def test_sans_releve_on_n_invente_pas(service):
    rendu = await service._progression(
        "", "PC", period="mois", notion="kills", requester=None, uid=UID
    )
    assert "aucun relevé" in rendu.lower()
    assert "0" not in rendu.split("relevé")[0]       # surtout pas « +0 kills »


@pytest.mark.asyncio
async def test_sur_discord_la_reponse_interdit_d_inventer_un_lien(service):
    """Vécu en prod : « ![Courbe](https://wally.azrael.watch/progression-chart/…) »
    — une URL inventée de toutes pièces, alors que le PNG était déjà joint."""
    debut = debut_de_periode("mois")
    await _releve(service, debut - HEURE, 1000)
    await _releve(service, debut + HEURE, 1120)
    rendu = await service._progression(
        "", "PC", period="mois", notion="kills", requester=None, uid=UID,
        peut_joindre_image=True,
    )
    assert "pièce jointe" in rendu
    assert "aucun lien" in rendu


@pytest.mark.asyncio
async def test_sans_piece_jointe_on_le_dit_aussi(service):
    """Un chat Twitch ne porte pas d'image : surtout ne pas en promettre une."""
    debut = debut_de_periode("mois")
    await _releve(service, debut - HEURE, 1000)
    await _releve(service, debut + HEURE, 1120)
    rendu = await service._progression(
        "", "PC", period="mois", notion="kills", requester=None, uid=UID,
    )
    assert "pas envoyer d'image" in rendu
    assert "n'invente" in rendu


@pytest.mark.asyncio
async def test_aucune_courbe_n_est_retenue_pour_un_canal_sans_image(service):
    """Sinon elle attendrait, et s'attacherait à une question Discord ultérieure."""
    debut = debut_de_periode("mois")
    await _releve(service, debut - HEURE, 1000)
    await _releve(service, debut + HEURE, 1120)
    await service._progression(
        "", "PC", period="mois", notion="kills", requester="twitch:9", uid=UID,
    )
    assert await service.derniere_courbe("twitch:9") is None


@pytest.mark.asyncio
async def test_une_periode_inconnue_est_refusee(service):
    """Le refus liste les formes valides : sans elles, le modèle réessaie au
    hasard ou répond un chiffre qu'il n'a pas."""
    rendu = await service._progression(
        "", "PC", period="depuis mardi", notion="kills", requester=None, uid=UID
    )
    assert "incomprise" in rendu.lower()
    assert "stream" in rendu and "2h" in rendu


@pytest.mark.asyncio
async def test_sans_historique_le_service_le_dit(db):
    svc = ApexLegendsService(client=object(), db=db)   # history laissé à None
    rendu = await svc._progression(
        "", "PC", period="mois", notion="kills", requester=None, uid=UID
    )
    assert "historique" in rendu.lower()


@pytest.mark.asyncio
async def test_sans_compte_identifiable_on_demande(service):
    rendu = await service._progression(
        "", "PC", period="mois", notion="kills", requester=None, uid=""
    )
    assert "compte apex" in rendu.lower()


# ── « depuis la dernière fois » ──────────────────────────────────────────────

class _Profil:
    def __init__(self, uid: str, kills: int):
        self.uid = uid
        self.stats = {"kills": type("S", (), {"value": kills})()}


@pytest.mark.asyncio
async def test_la_consultation_rappelle_le_gain_depuis_la_derniere(service):
    await _releve(service, time.time() - 4 * HEURE, 500)
    rappel = await service._comparer_a_la_derniere_fois(_Profil(UID, 624))
    assert "+124 kills" in rappel


@pytest.mark.asyncio
async def test_une_premiere_consultation_ne_rappelle_rien(service):
    assert await service._comparer_a_la_derniere_fois(_Profil(UID, 500)) == ""


@pytest.mark.asyncio
async def test_deux_consultations_rapprochees_ne_rappellent_rien(service):
    """On redemande souvent deux fois de suite : « +0 kill » n'apprend rien."""
    await _releve(service, time.time() - 60, 500)
    assert await service._comparer_a_la_derniere_fois(_Profil(UID, 502)) == ""


@pytest.mark.asyncio
async def test_la_consultation_alimente_l_historique(service):
    """C'est le SEUL historique des comptes qu'on ne sonde pas."""
    await service._comparer_a_la_derniere_fois(_Profil(UID, 777))
    p = await service.history._derniere_valeur(UID, "kills")
    assert p == 777


@pytest.mark.asyncio
async def test_un_profil_sans_uid_ne_casse_rien(service):
    assert await service._comparer_a_la_derniere_fois(_Profil("", 500)) == ""
