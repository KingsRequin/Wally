"""La machine à états, rejouée sur des séquences de relevés.

Les durées imitent les mesures réelles du 2026-08-13 : partie de ~8 min,
39 s seulement entre un retour au lobby et le lancement suivant.

Les transitions d'état (entrée en partie, retour au lobby) exigent DEUX
relevés consécutifs concordants — un flag de présence EA hoquette parfois sur
une seule lecture, donc la plupart des séquences envoient le même relevé deux
fois de suite (t puis t+2) pour confirmer.
"""
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

    d.avancer(Releve(t=2, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=K0, kills_viewer=K0))
    assert d.etat is Etat.ATTENTE_SQUAD, "une seule lecture ne suffit pas à confirmer"

    evts = d.avancer(Releve(t=4, azrael_in_game=True, viewer_in_game=True,
                            kills_azrael=K0, kills_viewer=K0))
    assert d.etat is Etat.MANCHE
    assert [e.type for e in evts] == ["manche_debut"]


def test_la_manche_se_clot_quand_azrael_revient_au_lobby():
    d = duel_pret()
    d.avancer(Releve(t=0, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=K0, kills_viewer=K0))
    d.avancer(Releve(t=2, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=K0, kills_viewer=K0))
    assert d.etat is Etat.MANCHE

    d.avancer(Releve(t=480, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=kills(4), kills_viewer=kills(2)))
    evts = d.avancer(Releve(t=482, azrael_in_game=False, viewer_in_game=False,
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
        base_a, base_v = kills(a - ka), kills(v - kv)
        d.avancer(Releve(t=i * 600, azrael_in_game=True, viewer_in_game=True,
                         kills_azrael=base_a, kills_viewer=base_v))
        d.avancer(Releve(t=i * 600 + 2, azrael_in_game=True, viewer_in_game=True,
                         kills_azrael=base_a, kills_viewer=base_v))
        fin_a, fin_v = kills(a), kills(v)
        d.avancer(Releve(t=i * 600 + 480, azrael_in_game=False, viewer_in_game=False,
                         kills_azrael=fin_a, kills_viewer=fin_v))
        evts = d.avancer(Releve(t=i * 600 + 482, azrael_in_game=False, viewer_in_game=False,
                                kills_azrael=fin_a, kills_viewer=fin_v))
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
    d.avancer(Releve(t=2, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=K0, kills_viewer=K0))
    d.avancer(Releve(t=480, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=kills(3), kills_viewer=kills(1)))
    d.avancer(Releve(t=482, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=kills(3), kills_viewer=kills(1)))
    # Entre les manches, le viewer épingle un tracker : +7793 d'un coup.
    saute = {"career_kills": 1000 + 1 + 7793, "specialEvent_kills": 500 + 1}
    d.avancer(Releve(t=519, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=kills(3), kills_viewer=saute))
    d.avancer(Releve(t=521, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=kills(3), kills_viewer=saute))
    apres = {"career_kills": saute["career_kills"], "specialEvent_kills": 500 + 3}
    d.avancer(Releve(t=1000, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=kills(5), kills_viewer=apres))
    evts = d.avancer(Releve(t=1002, azrael_in_game=False, viewer_in_game=False,
                            kills_azrael=kills(5), kills_viewer=apres))
    fin = [e for e in evts if e.type == "manche_fin"][0]
    assert fin.donnees["viewer"] == 2, "le saut d'épinglage doit être absorbé"


def test_manche_non_mesurable_annoncee_et_non_comptee():
    """API muette : les dicts de kills sont vides à chaque relevé, pour les
    deux joueurs. À distinguer de la vraie Mixtape (trackers présents mais
    figés) — voir test_vraie_mixtape_..."""
    d = duel_pret()
    d.avancer(Releve(t=0, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael={}, kills_viewer={}))
    d.avancer(Releve(t=2, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael={}, kills_viewer={}))
    d.avancer(Releve(t=480, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael={}, kills_viewer={}))
    evts = d.avancer(Releve(t=482, azrael_in_game=False, viewer_in_game=False,
                            kills_azrael={}, kills_viewer={}))
    fin = [e for e in evts if e.type == "manche_fin"][0]
    assert fin.donnees["azrael"] is None
    assert fin.donnees["viewer"] is None
    assert fin.donnees["mesurable"] is False


def test_duel_entierement_non_mesurable_est_un_abandon_pas_un_nul():
    """API muette sur tout le duel : les dicts de kills restent vides à
    chaque relevé, pour les deux joueurs. Le duel n'est pas arbitrable :
    remboursement, jamais un faux match nul annoncé."""
    d = duel_pret()
    for i in range(3):
        d.avancer(Releve(t=i * 600, azrael_in_game=True, viewer_in_game=True,
                         kills_azrael={}, kills_viewer={}))
        d.avancer(Releve(t=i * 600 + 2, azrael_in_game=True, viewer_in_game=True,
                         kills_azrael={}, kills_viewer={}))
        d.avancer(Releve(t=i * 600 + 480, azrael_in_game=False,
                         viewer_in_game=False, kills_azrael={}, kills_viewer={}))
        evts = d.avancer(Releve(t=i * 600 + 482, azrael_in_game=False,
                                viewer_in_game=False, kills_azrael={}, kills_viewer={}))
    assert d.etat is Etat.ABANDON
    abandon = [e for e in evts if e.type == "abandon"][0]
    assert abandon.donnees["rembourser"] is True
    assert "mixtape" in abandon.donnees["motif"].lower()


def test_vraie_mixtape_compteurs_presents_mais_figes_est_un_abandon():
    """Vraie Mixtape : les trackers sont PRÉSENTS mais aucun ne bouge — 10
    kills joués, 0 compté (mesuré en prod). `score_manche` rend alors 0, pas
    None : sans ce test, `_clore()` ne détecterait que l'API muette (dicts
    vides) et annoncerait un faux 0-0 match nul à deux joueurs qui ont joué."""
    d = duel_pret()
    for i in range(3):
        d.avancer(Releve(t=i * 600, azrael_in_game=True, viewer_in_game=True,
                         kills_azrael=K0, kills_viewer=K0))
        d.avancer(Releve(t=i * 600 + 2, azrael_in_game=True, viewer_in_game=True,
                         kills_azrael=K0, kills_viewer=K0))
        d.avancer(Releve(t=i * 600 + 480, azrael_in_game=False,
                         viewer_in_game=False, kills_azrael=K0, kills_viewer=K0))
        evts = d.avancer(Releve(t=i * 600 + 482, azrael_in_game=False,
                                viewer_in_game=False, kills_azrael=K0, kills_viewer=K0))
    assert d.etat is Etat.ABANDON
    abandon = [e for e in evts if e.type == "abandon"][0]
    assert abandon.donnees["rembourser"] is True
    assert not any(e.type == "verdict" for e in evts)


def test_viewer_illisible_les_3_manches_est_un_abandon_pas_un_verdict():
    """Azraël mesurable, viewer illisible (profil sans tracker épinglé, API
    silencieuse pour lui seul) sur les 3 manches : on ne compare pas 4 à
    rien. Une manche non mesurable pour un seul des deux ne compte pour
    personne, donc le duel entier finit en abandon — jamais en 'victoire'
    d'Azraël sur un 0 fantôme côté viewer."""
    d = duel_pret()
    for i in range(3):
        base_a = kills(i * 2)
        fin_a = kills(i * 2 + 3)
        d.avancer(Releve(t=i * 600, azrael_in_game=True, viewer_in_game=True,
                         kills_azrael=base_a, kills_viewer={}))
        d.avancer(Releve(t=i * 600 + 2, azrael_in_game=True, viewer_in_game=True,
                         kills_azrael=base_a, kills_viewer={}))
        d.avancer(Releve(t=i * 600 + 480, azrael_in_game=False,
                         viewer_in_game=False, kills_azrael=fin_a, kills_viewer={}))
        evts = d.avancer(Releve(t=i * 600 + 482, azrael_in_game=False,
                                viewer_in_game=False, kills_azrael=fin_a, kills_viewer={}))
    assert d.etat is Etat.ABANDON
    abandon = [e for e in evts if e.type == "abandon"][0]
    assert abandon.donnees["rembourser"] is True
    assert not any(e.type == "verdict" for e in evts)


def test_egalite_vraie_est_un_match_nul_sans_remboursement():
    d = duel_pret()
    for i in range(3):
        base = kills(i * 2)
        fin = kills(i * 2 + 2)
        d.avancer(Releve(t=i * 600, azrael_in_game=True, viewer_in_game=True,
                         kills_azrael=base, kills_viewer=base))
        d.avancer(Releve(t=i * 600 + 2, azrael_in_game=True, viewer_in_game=True,
                         kills_azrael=base, kills_viewer=base))
        d.avancer(Releve(t=i * 600 + 480, azrael_in_game=False, viewer_in_game=False,
                         kills_azrael=fin, kills_viewer=fin))
        evts = d.avancer(Releve(t=i * 600 + 482, azrael_in_game=False, viewer_in_game=False,
                                kills_azrael=fin, kills_viewer=fin))
    verdict = [e for e in evts if e.type == "verdict"][0]
    assert verdict.donnees["gagnant"] is None
    assert verdict.donnees["azrael"] == verdict.donnees["viewer"] == 6


def test_personne_ne_rejoint_dans_le_delai_abandon_et_remboursement():
    """Avant toute manche jouée (ATTENTE_SQUAD) : remboursement."""
    d = duel_pret()
    d.avancer(Releve(t=0, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=K0, kills_viewer=K0))
    evts = d.avancer(Releve(t=16 * 60, azrael_in_game=False, viewer_in_game=False,
                            kills_azrael=K0, kills_viewer=K0))
    assert d.etat is Etat.ABANDON
    assert [e for e in evts if e.type == "abandon"][0].donnees["rembourser"] is True


def test_abandon_apres_une_manche_jouee_ne_rembourse_pas_et_rend_verdict():
    """Après une manche déjà mesurée (ENTRE_MANCHES) : plus de remboursement,
    ce serait un raccourci pour abandonner dès qu'on perd — et l'API ne
    distingue pas un départ volontaire d'une coupure. Le verdict porte sur
    les manches réellement jouées, et le motif ne parle plus de squad."""
    d = duel_pret()
    d.avancer(Releve(t=0, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=K0, kills_viewer=K0))
    d.avancer(Releve(t=2, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=K0, kills_viewer=K0))
    # Le viewer gagne la manche 1, puis ne revient jamais.
    d.avancer(Releve(t=480, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=kills(2), kills_viewer=kills(5)))
    d.avancer(Releve(t=482, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=kills(2), kills_viewer=kills(5)))
    assert d.etat is Etat.ENTRE_MANCHES

    d.avancer(Releve(t=500, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=kills(2), kills_viewer=kills(5)))
    evts = d.avancer(Releve(t=500 + 16 * 60, azrael_in_game=False, viewer_in_game=False,
                            kills_azrael=kills(2), kills_viewer=kills(5)))
    assert d.etat is Etat.VERDICT
    abandon = [e for e in evts if e.type == "abandon"][0]
    assert abandon.donnees["rembourser"] is False
    assert abandon.donnees["manches_jouees"] == 1
    assert "squad" not in abandon.donnees["motif"].lower(), (
        "le motif de l'attente initiale mentirait ici : une manche a été jouée")
    # Les scores acquis ne sont pas jetés : ils font un verdict.
    verdict = [e for e in evts if e.type == "verdict"][0]
    assert verdict.donnees["azrael"] == 2
    assert verdict.donnees["viewer"] == 5
    assert verdict.donnees["gagnant"] == "viewer"


def test_abandon_apres_une_manche_NON_mesuree_rembourse_et_ne_rend_pas_de_verdict():
    """Même départ en cours de duel, mais la manche jouée n'a rien donné de
    mesurable (Mixtape, ou viewer illisible). Il n'y a alors rien à arbitrer :
    on rembourse, et surtout on n'annonce pas le 0-0 qu'on refuse partout
    ailleurs."""
    d = duel_pret()
    d.avancer(Releve(t=0, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=K0, kills_viewer=K0))
    d.avancer(Releve(t=2, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=K0, kills_viewer=K0))
    d.avancer(Releve(t=480, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=K0, kills_viewer=K0))
    d.avancer(Releve(t=482, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=K0, kills_viewer=K0))
    assert d.etat is Etat.ENTRE_MANCHES

    d.avancer(Releve(t=500, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=K0, kills_viewer=K0))
    evts = d.avancer(Releve(t=500 + 16 * 60, azrael_in_game=False, viewer_in_game=False,
                            kills_azrael=K0, kills_viewer=K0))
    assert d.etat is Etat.ABANDON
    abandon = [e for e in evts if e.type == "abandon"][0]
    assert abandon.donnees["rembourser"] is True
    assert not any(e.type == "verdict" for e in evts)


def test_un_hoquet_isole_ne_clot_pas_la_manche():
    """Une seule lecture 'hors partie' au milieu d'une manche est un hoquet
    du flag de présence EA, pas un vrai retour au lobby : elle ne doit ni
    clore la manche en cours ni en ouvrir une autre — une seule partie ne
    doit jamais consommer deux manches."""
    d = duel_pret()
    d.avancer(Releve(t=0, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=K0, kills_viewer=K0))
    d.avancer(Releve(t=2, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=K0, kills_viewer=K0))
    assert d.etat is Etat.MANCHE

    # Hoquet isolé : un seul relevé "hors partie" au milieu de la partie.
    evts = d.avancer(Releve(t=200, azrael_in_game=False, viewer_in_game=False,
                            kills_azrael=kills(2), kills_viewer=kills(1)))
    assert d.etat is Etat.MANCHE, "un relevé isolé ne clôt pas la manche"
    assert evts == []

    # La partie continue réellement.
    d.avancer(Releve(t=210, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=kills(2), kills_viewer=kills(1)))
    assert d.etat is Etat.MANCHE

    # Vrai retour au lobby, confirmé deux fois.
    d.avancer(Releve(t=480, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=kills(4), kills_viewer=kills(2)))
    evts = d.avancer(Releve(t=482, azrael_in_game=False, viewer_in_game=False,
                            kills_azrael=kills(4), kills_viewer=kills(2)))
    fin = [e for e in evts if e.type == "manche_fin"][0]
    assert fin.donnees["azrael"] == 4
    assert fin.donnees["viewer"] == 2
    assert fin.donnees["manche"] == 1, "une seule manche, pas deux"


def test_to_dict_est_une_photo_pas_une_reference():
    """Un appelant qui capture to_dict() puis laisse le duel continuer avant
    d'écrire (I/O async) ne doit jamais voir cette suite bouger la capture —
    sinon une manche encore en cours à l'instant du snapshot se retrouve
    comptée deux fois à la reprise."""
    d = duel_pret()
    d.avancer(Releve(t=0, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=K0, kills_viewer=K0))
    d.avancer(Releve(t=2, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=K0, kills_viewer=K0))
    assert d.etat is Etat.MANCHE

    snapshot = d.to_dict()

    d.avancer(Releve(t=480, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=kills(4), kills_viewer=kills(2)))
    d.avancer(Releve(t=482, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=kills(4), kills_viewer=kills(2)))

    assert snapshot["scores"] == [], "le snapshot ne doit pas voir la manche terminée après coup"
    assert snapshot["base_azrael"] == K0


def test_le_duel_survit_a_un_rebuild():
    """Le snapshot est pris EN PLEINE MANCHE — c'est là que les baselines
    comptent. Le duel repris depuis ce snapshot doit terminer la manche avec
    exactement le même score qu'un duel qui n'aurait jamais redémarré : un
    champ manquant à la sérialisation (base_azrael/base_viewer) ferait
    échouer ce calcul."""
    d = duel_pret()
    d.avancer(Releve(t=0, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=K0, kills_viewer=K0))
    d.avancer(Releve(t=2, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=K0, kills_viewer=K0))
    assert d.etat is Etat.MANCHE

    snapshot = d.to_dict()

    # Le duel de référence continue sans interruption.
    d.avancer(Releve(t=480, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=kills(4), kills_viewer=kills(2)))
    evts_ref = d.avancer(Releve(t=482, azrael_in_game=False, viewer_in_game=False,
                                kills_azrael=kills(4), kills_viewer=kills(2)))
    fin_ref = [e for e in evts_ref if e.type == "manche_fin"][0]

    # Le duel repris depuis le snapshot voit la même fin de manche.
    repris = Duel.from_dict(snapshot)
    assert repris.etat is Etat.MANCHE
    assert repris.viewer_nom == "Bob"
    repris.avancer(Releve(t=480, azrael_in_game=False, viewer_in_game=False,
                          kills_azrael=kills(4), kills_viewer=kills(2)))
    evts_repris = repris.avancer(Releve(t=482, azrael_in_game=False, viewer_in_game=False,
                                        kills_azrael=kills(4), kills_viewer=kills(2)))
    fin_repris = [e for e in evts_repris if e.type == "manche_fin"][0]

    assert fin_repris.donnees["manche"] == fin_ref.donnees["manche"] == 1
    assert fin_repris.donnees["azrael"] == fin_ref.donnees["azrael"] == 4
    assert fin_repris.donnees["viewer"] == fin_ref.donnees["viewer"] == 2


def test_le_delai_dattente_survit_a_un_rebuild():
    """L'autre champ que la reprise doit porter : l'instant où l'attente a
    commencé. Sans lui, chaque redémarrage du conteneur remettrait le compte à
    rebours à zéro — un viewer absent ferait attendre le duel indéfiniment."""
    d = duel_pret()
    d.avancer(Releve(t=0, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=K0, kills_viewer=K0))

    repris = Duel.from_dict(d.to_dict())
    evts = repris.avancer(Releve(t=16 * 60, azrael_in_game=False, viewer_in_game=False,
                                 kills_azrael=K0, kills_viewer=K0))
    assert repris.etat is Etat.ABANDON, "l'attente a bien commencé à t=0, pas à la reprise"
    assert [e for e in evts if e.type == "abandon"][0].donnees["rembourser"] is True


def test_le_delai_et_le_plafond_sont_des_champs_configurables():
    """Rien de figé en dur : un délai d'attente et un plafond de kills posés
    à la construction doivent atteindre `avancer()` — et survivre au
    redémarrage comme le reste de l'état."""
    court = Duel(viewer_nom="Bob", viewer_uid="42", azrael_uid="7", manches=3,
                 attente_squad_s=60)
    court.etat = Etat.ATTENTE_SQUAD
    court.avancer(Releve(t=0, azrael_in_game=False, viewer_in_game=False,
                         kills_azrael=K0, kills_viewer=K0))
    court.avancer(Releve(t=61, azrael_in_game=False, viewer_in_game=False,
                         kills_azrael=K0, kills_viewer=K0))
    assert court.etat is Etat.ABANDON, "le délai du duel, pas la constante du module"

    bas = Duel(viewer_nom="Bob", viewer_uid="42", azrael_uid="7", manches=3,
               plafond_kills_manche=2)
    bas.etat = Etat.ATTENTE_SQUAD
    bas.avancer(Releve(t=0, azrael_in_game=True, viewer_in_game=True,
                       kills_azrael=K0, kills_viewer=K0))
    bas.avancer(Releve(t=2, azrael_in_game=True, viewer_in_game=True,
                       kills_azrael=K0, kills_viewer=K0))
    bas.avancer(Releve(t=480, azrael_in_game=False, viewer_in_game=False,
                       kills_azrael=kills(4), kills_viewer=kills(4)))
    evts = bas.avancer(Releve(t=482, azrael_in_game=False, viewer_in_game=False,
                              kills_azrael=kills(4), kills_viewer=kills(4)))
    fin = [e for e in evts if e.type == "manche_fin"][0]
    assert fin.donnees["mesurable"] is False, (
        "+4 dépasse le plafond de 2 : le plafond du duel a bien été passé à score_manche")

    repris = Duel.from_dict(court.to_dict())
    assert repris.attente_squad_s == 60
    assert Duel.from_dict(bas.to_dict()).plafond_kills_manche == 2


def test_recommencer_remet_les_compteurs_a_zero():
    d = duel_pret()
    d.avancer(Releve(t=0, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=K0, kills_viewer=K0))
    d.avancer(Releve(t=2, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=K0, kills_viewer=K0))
    d.avancer(Releve(t=480, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=kills(4), kills_viewer=kills(2)))
    d.avancer(Releve(t=482, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=kills(4), kills_viewer=kills(2)))
    d.recommencer()
    assert d.scores == []
    assert d.etat is Etat.ATTENTE_SQUAD
    assert d.viewer_nom == "Bob", "le duelliste garde sa place"
