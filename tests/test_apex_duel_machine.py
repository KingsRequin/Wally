"""La machine à états, rejouée sur des séquences de relevés.

Les durées imitent les mesures réelles du 2026-08-13 : partie de ~8 min,
39 s seulement entre un retour au lobby et le lancement suivant.
"""
import pytest

from bot.core.apex.duel import Duel, Etat, Releve

K0 = {"career_kills": 1000, "specialEvent_kills": 500}


def kills(n):
    return {"career_kills": 1000 + n, "specialEvent_kills": 500 + n}


def duel_pret():
    d = Duel(viewer_nom="Bob", viewer_uid="42", azrael_uid="7", manches=3)
    d.etat = Etat.ATTENTE_SQUAD
    return d


def test_la_manche_demarre_quand_LES_DEUX_sont_en_partie():
    d = duel_pret()
    d.avancer(Releve(t=0, azrael_in_game=True, viewer_in_game=False,
                     kills_azrael=K0, kills_viewer=K0))
    assert d.etat is Etat.ATTENTE_SQUAD, "Azraël seul ne lance pas le duel"

    evts = d.avancer(Releve(t=2, azrael_in_game=True, viewer_in_game=True,
                            kills_azrael=K0, kills_viewer=K0))
    assert d.etat is Etat.MANCHE
    assert [e.type for e in evts] == ["manche_debut"]


def test_la_manche_se_clot_quand_azrael_revient_au_lobby():
    d = duel_pret()
    d.avancer(Releve(t=0, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=K0, kills_viewer=K0))
    evts = d.avancer(Releve(t=480, azrael_in_game=False, viewer_in_game=False,
                            kills_azrael=kills(4), kills_viewer=kills(2)))
    assert d.etat is Etat.ENTRE_MANCHES
    assert [e.type for e in evts] == ["manche_fin"]
    assert evts[0].donnees["azrael"] == 4
    assert evts[0].donnees["viewer"] == 2


def test_trois_manches_puis_verdict_sur_la_SOMME():
    d = duel_pret()
    a = v = 0
    for i, (ka, kv) in enumerate([(4, 2), (0, 5), (3, 1)]):
        a, v = a + ka, v + kv
        d.avancer(Releve(t=i * 600, azrael_in_game=True, viewer_in_game=True,
                         kills_azrael=kills(a - ka), kills_viewer=kills(v - kv)))
        evts = d.avancer(Releve(t=i * 600 + 480, azrael_in_game=False, viewer_in_game=False,
                                kills_azrael=kills(a), kills_viewer=kills(v)))
    assert d.etat is Etat.VERDICT
    verdict = [e for e in evts if e.type == "verdict"][0]
    assert verdict.donnees["azrael"] == 7
    assert verdict.donnees["viewer"] == 8
    assert verdict.donnees["gagnant"] == "viewer"


def test_la_baseline_est_reprise_a_CHAQUE_manche():
    """Un tracker épinglé entre deux manches saute de milliers. La nouvelle
    baseline doit l'absorber au lieu de le compter."""
    d = duel_pret()
    d.avancer(Releve(t=0, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=K0, kills_viewer=K0))
    d.avancer(Releve(t=480, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=kills(3), kills_viewer=kills(1)))
    # Entre les manches, le viewer épingle un tracker : +7793 d'un coup.
    saute = {"career_kills": 1000 + 1 + 7793, "specialEvent_kills": 500 + 1}
    d.avancer(Releve(t=519, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=kills(3), kills_viewer=saute))
    apres = {"career_kills": saute["career_kills"], "specialEvent_kills": 500 + 3}
    evts = d.avancer(Releve(t=1000, azrael_in_game=False, viewer_in_game=False,
                            kills_azrael=kills(5), kills_viewer=apres))
    fin = [e for e in evts if e.type == "manche_fin"][0]
    assert fin.donnees["viewer"] == 2, "le saut d'épinglage doit être absorbé"


def test_manche_non_mesurable_annoncee_et_non_comptee():
    """Mixtape : aucun compteur ne bouge alors que la partie a bien eu lieu."""
    d = duel_pret()
    d.avancer(Releve(t=0, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael={}, kills_viewer={}))
    evts = d.avancer(Releve(t=480, azrael_in_game=False, viewer_in_game=False,
                            kills_azrael={}, kills_viewer={}))
    fin = [e for e in evts if e.type == "manche_fin"][0]
    assert fin.donnees["azrael"] is None
    assert fin.donnees["viewer"] is None
    assert fin.donnees["mesurable"] is False


def test_duel_entierement_non_mesurable_est_un_abandon_pas_un_nul():
    """0-0 sans qu'aucun compteur n'ait bougé = Mixtape ou API muette. Le duel
    n'est pas arbitrable : remboursement, jamais un faux match nul annoncé."""
    d = duel_pret()
    for i in range(3):
        d.avancer(Releve(t=i * 600, azrael_in_game=True, viewer_in_game=True,
                         kills_azrael={}, kills_viewer={}))
        evts = d.avancer(Releve(t=i * 600 + 480, azrael_in_game=False,
                                viewer_in_game=False, kills_azrael={}, kills_viewer={}))
    assert d.etat is Etat.ABANDON
    abandon = [e for e in evts if e.type == "abandon"][0]
    assert abandon.donnees["rembourser"] is True
    assert "mixtape" in abandon.donnees["motif"].lower()


def test_egalite_vraie_est_un_match_nul_sans_remboursement():
    d = duel_pret()
    for i in range(3):
        d.avancer(Releve(t=i * 600, azrael_in_game=True, viewer_in_game=True,
                         kills_azrael=kills(i * 2), kills_viewer=kills(i * 2)))
        evts = d.avancer(Releve(t=i * 600 + 480, azrael_in_game=False, viewer_in_game=False,
                                kills_azrael=kills(i * 2 + 2), kills_viewer=kills(i * 2 + 2)))
    verdict = [e for e in evts if e.type == "verdict"][0]
    assert verdict.donnees["gagnant"] is None
    assert verdict.donnees["azrael"] == verdict.donnees["viewer"] == 6


def test_personne_ne_rejoint_dans_le_delai_abandon_et_remboursement():
    d = duel_pret()
    d.avancer(Releve(t=0, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=K0, kills_viewer=K0))
    evts = d.avancer(Releve(t=16 * 60, azrael_in_game=False, viewer_in_game=False,
                            kills_azrael=K0, kills_viewer=K0))
    assert d.etat is Etat.ABANDON
    assert [e for e in evts if e.type == "abandon"][0].donnees["rembourser"] is True


def test_le_duel_survit_a_un_rebuild():
    d = duel_pret()
    d.avancer(Releve(t=0, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=K0, kills_viewer=K0))
    d.avancer(Releve(t=480, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=kills(4), kills_viewer=kills(2)))
    repris = Duel.from_dict(d.to_dict())
    assert repris.etat is d.etat
    assert repris.scores == d.scores
    assert repris.viewer_nom == "Bob"


def test_recommencer_remet_les_compteurs_a_zero():
    d = duel_pret()
    d.avancer(Releve(t=0, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=K0, kills_viewer=K0))
    d.avancer(Releve(t=480, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=kills(4), kills_viewer=kills(2)))
    d.recommencer()
    assert d.scores == []
    assert d.etat is Etat.ATTENTE_SQUAD
    assert d.viewer_nom == "Bob", "le duelliste garde sa place"
