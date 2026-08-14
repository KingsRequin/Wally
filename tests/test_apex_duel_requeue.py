# tests/test_apex_duel_requeue.py
"""La requeue : trois parties enchaînées sans jamais repasser par le lobby.

Le premier duel réel, le 2026-08-13 au soir, a dû être annulé. Le streamer et
le duelliste ont enchaîné TROIS parties en requeue ; `isInGame` n'est pas
retombé une seule fois, aucune frontière de manche n'a été vue, et les trois
parties se sont additionnées en une seule manche.

Le second marqueur ajouté ici est l'expérience gagnée : elle est attribuée à la
FIN de chaque partie, requeue ou pas (mesuré le matin même : 77 % → 87 % pile
au retour au lobby, immobile pendant toute la partie). Il vient EN PLUS du
retour au lobby, qui reste le cas nominal.

Les chiffres des relevés sont ceux de la soirée :

    Azraël      specialEvent_kills        93331 → 93370   (+39)
                legend:specialEvent_kills 83963 → 84002   (+39)
                grandsoiree_kills          1480 →  1480   ( 0)  ← compteur mort
                kills                     10155 → 10155   ( 0)  ← compteur mort
    KingsRequin career_kills              18839 → 18861   (+22)
"""
from bot.core.apex.duel import Duel, Etat, Releve

# Le niveau d'Azraël au moment du duel, et sa barre d'expérience. L'index qui
# voyage dans le relevé est monotone : `niveau × 100 + pourcentage`.
NIVEAU = 285


def xp(niveau: int, pourcent: float) -> float:
    return niveau * 100.0 + pourcent


def azrael_kills(n: int) -> dict:
    """Les quatre trackers d'Azraël après `n` kills — dont DEUX qui sont morts.

    `grandsoiree_kills` et `kills` ne sont plus épinglés : ils gardent leur
    valeur, quoi qu'il fasse en jeu. Ce sont eux qui, une fois les deux vrais
    compteurs jetés par le plafond, ont annoncé « 0 kill » en direct.
    """
    return {"specialEvent_kills": 93331 + n,
            "legend:specialEvent_kills": 83963 + n,
            "grandsoiree_kills": 1480,
            "kills": 10155}


def viewer_kills(n: int) -> dict:
    return {"career_kills": 18839 + n}


def duel_pret(**champs) -> Duel:
    """Un duel prêt à jouer, sans marge de lobby — on ne repasse pas par le
    lobby, c'est tout le sujet."""
    d = Duel(viewer_nom="KingsRequin", viewer_uid="1012242925358",
             azrael_uid="2274044345", manches=3, marge_lobby_s=0, **champs)
    d.etat = Etat.ATTENTE_SQUAD
    return d


def relever(d: Duel, t: float, *, kills_a: int, kills_v: int,
            niveau: int = NIVEAU, pourcent: float = 77.0,
            en_partie: bool = True) -> list:
    return d.avancer(Releve(
        t=t, azrael_in_game=en_partie, viewer_in_game=en_partie,
        kills_azrael=azrael_kills(kills_a), kills_viewer=viewer_kills(kills_v),
        progression_azrael=xp(niveau, pourcent)))


# ── Le scénario de la soirée, rejoué de bout en bout ────────────────────────
def test_trois_parties_en_requeue_donnent_trois_manches_et_un_score_juste():
    """Le test qui prouve le correctif : la soirée du 2026-08-13, rejouée.

    Trois parties d'affilée sans un seul relevé hors partie. Attendu : trois
    manches, 39 kills pour Azraël (12 + 15 + 12), 22 pour le duelliste
    (8 + 9 + 5), et Azraël vainqueur. Mesuré ce soir-là : UNE manche,
    `{'azrael': 0, 'viewer': 22}`.
    """
    d = duel_pret()
    # Deux relevés concordants pour entrer en partie : la manche 1 démarre ici.
    relever(d, 0, kills_a=0, kills_v=0)
    relever(d, 2, kills_a=0, kills_v=0)
    assert d.etat is Etat.MANCHE

    # ── Partie 1 : Azraël 12, le duelliste 8. L'XP tombe à la fin.
    relever(d, 480, kills_a=12, kills_v=8)
    relever(d, 482, kills_a=12, kills_v=8, pourcent=87.0)
    evts = relever(d, 484, kills_a=12, kills_v=8, pourcent=87.0)
    fin1 = [e for e in evts if e.type == "manche_fin"][0]
    assert (fin1.donnees["azrael"], fin1.donnees["viewer"]) == (12, 8)
    assert fin1.donnees["mesurable"] is True
    assert d.etat is Etat.ENTRE_MANCHES

    # Requeue : personne n'est jamais sorti de partie, la manche 2 démarre.
    relever(d, 486, kills_a=12, kills_v=8, pourcent=87.0)
    relever(d, 488, kills_a=12, kills_v=8, pourcent=87.0)
    assert d.etat is Etat.MANCHE

    # ── Partie 2 : Azraël 15, le duelliste 9.
    relever(d, 960, kills_a=27, kills_v=17, pourcent=87.0)
    relever(d, 962, kills_a=27, kills_v=17, pourcent=97.0)
    evts = relever(d, 964, kills_a=27, kills_v=17, pourcent=97.0)
    fin2 = [e for e in evts if e.type == "manche_fin"][0]
    assert (fin2.donnees["azrael"], fin2.donnees["viewer"]) == (15, 9)

    relever(d, 966, kills_a=27, kills_v=17, pourcent=97.0)
    relever(d, 968, kills_a=27, kills_v=17, pourcent=97.0)
    assert d.etat is Etat.MANCHE

    # ── Partie 3 : Azraël 12, le duelliste 5 — et il passe niveau 286, donc le
    # pourcentage RETOMBE (97 % → 5 %) au moment même où l'XP est gagnée.
    relever(d, 1440, kills_a=39, kills_v=22, pourcent=97.0)
    relever(d, 1442, kills_a=39, kills_v=22, niveau=286, pourcent=5.0)
    evts = relever(d, 1444, kills_a=39, kills_v=22, niveau=286, pourcent=5.0)
    fin3 = [e for e in evts if e.type == "manche_fin"][0]
    assert (fin3.donnees["azrael"], fin3.donnees["viewer"]) == (12, 5)

    verdict = [e for e in evts if e.type == "verdict"][0]
    assert (verdict.donnees["azrael"], verdict.donnees["viewer"]) == (39, 22)
    assert verdict.donnees["gagnant"] == "azrael"
    assert verdict.donnees["manches_comptees"] == 3
    assert d.etat is Etat.VERDICT


def test_les_deux_compteurs_morts_n_ecrivent_jamais_le_score():
    """Le faux zéro de la soirée, isolé : deux trackers figés, deux vivants.

    Le score d'une manche doit venir des compteurs qui bougent, jamais de ceux
    qui ne bougent plus.
    """
    d = duel_pret()
    relever(d, 0, kills_a=0, kills_v=0)
    relever(d, 2, kills_a=0, kills_v=0)
    relever(d, 480, kills_a=39, kills_v=22)
    relever(d, 482, kills_a=39, kills_v=22, pourcent=87.0)
    evts = relever(d, 484, kills_a=39, kills_v=22, pourcent=87.0)

    fin = [e for e in evts if e.type == "manche_fin"][0]
    assert fin.donnees["azrael"] == 39, "39 kills réels, pas un artefact"
    assert fin.donnees["viewer"] == 22


# ── Les trois façons de se tromper sur l'expérience ─────────────────────────
def test_une_hausse_lue_une_seule_fois_ne_clot_rien():
    """Le patron du debounce de retour au lobby, appliqué à l'expérience : une
    lecture qui monte puis se rétracte est un hoquet, pas une fin de partie."""
    d = duel_pret()
    relever(d, 0, kills_a=0, kills_v=0)
    relever(d, 2, kills_a=0, kills_v=0)

    relever(d, 480, kills_a=4, kills_v=1, pourcent=87.0)
    assert d.etat is Etat.MANCHE, "une seule lecture ne clôt pas une manche"
    relever(d, 482, kills_a=4, kills_v=1, pourcent=77.0)
    assert d.etat is Etat.MANCHE, "la hausse s'est rétractée : c'était un hoquet"
    assert d.scores == []

    # Et la vraie fin, ensuite, se voit toujours.
    relever(d, 484, kills_a=4, kills_v=1, pourcent=87.0)
    relever(d, 486, kills_a=4, kills_v=1, pourcent=87.0)
    assert d.etat is Etat.ENTRE_MANCHES
    assert d.scores[0]["azrael"] == 4


def test_l_xp_en_retard_de_la_partie_precedente_ne_clot_pas_la_manche_suivante():
    """L'XP arrive avec un décalage : celle de la partie d'AVANT peut tomber
    juste après le début de la manche en cours. Trop tôt pour être la sienne —
    une partie d'Apex ne se termine pas en trente secondes.

    Et elle est ABSORBÉE, pas seulement ignorée : laissée au-dessus de la
    référence, elle clôturerait la manche à la seconde où le plancher est
    franchi, avec un score de zéro kill.
    """
    d = duel_pret()
    relever(d, 0, kills_a=0, kills_v=0)
    relever(d, 2, kills_a=0, kills_v=0)
    assert d.etat is Etat.MANCHE

    # +10 % à t+28 s : c'est l'XP de la partie précédente qui se publie.
    relever(d, 30, kills_a=1, kills_v=0, pourcent=87.0)
    relever(d, 32, kills_a=1, kills_v=0, pourcent=87.0)
    assert d.etat is Etat.MANCHE, "trop tôt : ce n'est pas la fin de CETTE partie"
    # Bien au-delà du plancher, la même valeur ne doit toujours rien clore.
    relever(d, 300, kills_a=3, kills_v=2, pourcent=87.0)
    relever(d, 302, kills_a=3, kills_v=2, pourcent=87.0)
    assert d.etat is Etat.MANCHE, "la hausse en retard a rejoint la référence"
    assert d.scores == []

    # La vraie fin, elle, clôt la manche — sur TOUS les kills de la manche.
    relever(d, 600, kills_a=6, kills_v=3, pourcent=97.0)
    relever(d, 602, kills_a=6, kills_v=3, pourcent=97.0)
    assert d.etat is Etat.ENTRE_MANCHES
    assert d.scores[0] == {"azrael": 6, "viewer": 3,
                           "azrael_lu": 6, "viewer_lu": 3}


def test_le_retour_au_lobby_reste_le_marqueur_nominal():
    """En PLUS, jamais à la place : une partie qui repasse par le lobby se clôt
    comme avant, sans que l'expérience ait eu à bouger."""
    d = duel_pret()
    relever(d, 0, kills_a=0, kills_v=0)
    relever(d, 2, kills_a=0, kills_v=0)
    relever(d, 480, kills_a=5, kills_v=2, en_partie=False)
    evts = relever(d, 482, kills_a=5, kills_v=2, en_partie=False)

    fin = [e for e in evts if e.type == "manche_fin"][0]
    assert (fin.donnees["azrael"], fin.donnees["viewer"]) == (5, 2)


def test_une_progression_illisible_ne_conclut_rien():
    """Un payload dégradé ne porte pas de niveau : l'absence ne clôt aucune
    manche, et n'en fait pas dérailler une non plus."""
    d = duel_pret()
    for t in (0, 2, 480, 482, 900):
        d.avancer(Releve(t=t, azrael_in_game=True, viewer_in_game=True,
                         kills_azrael=azrael_kills(3), kills_viewer=viewer_kills(1),
                         progression_azrael=None))
    assert d.etat is Etat.MANCHE
    assert d.scores == []


# ── Reprise après rebuild ──────────────────────────────────────────────────
def test_un_etat_ecrit_par_la_version_en_production_se_recharge():
    """Un duel persisté avant l'existence de ce signal doit se reprendre.

    Sans référence d'expérience, la première lecture ne conclut rien : elle
    SERT de référence. Un duel repris ne se clôt jamais sur le premier relevé
    venu — mais la manche d'après, elle, se découpe normalement.
    """
    ancien = duel_pret().to_dict()
    for cle in ("base_progression", "t_manche", "delai_min_manche_s"):
        ancien.pop(cle)
    ancien["etat"] = Etat.MANCHE.value
    ancien["base_azrael"] = azrael_kills(0)
    ancien["base_viewer"] = viewer_kills(0)

    repris = Duel.from_dict(ancien)
    assert repris.etat is Etat.MANCHE

    relever(repris, 1000, kills_a=7, kills_v=3, pourcent=87.0)
    assert repris.etat is Etat.MANCHE, "la première lecture sert de référence"
    relever(repris, 1002, kills_a=7, kills_v=3, pourcent=87.0)
    assert repris.etat is Etat.MANCHE

    relever(repris, 1500, kills_a=9, kills_v=4, pourcent=97.0)
    evts = relever(repris, 1502, kills_a=9, kills_v=4, pourcent=97.0)
    fin = [e for e in evts if e.type == "manche_fin"][0]
    assert (fin.donnees["azrael"], fin.donnees["viewer"]) == (9, 4)


def test_la_reference_d_experience_traverse_un_rebuild():
    """Sérialisée, comme la baseline des kills : en requeue l'expérience est le
    SEUL marqueur de fin, et la reperdre à chaque rebuild rendrait la manche en
    cours interminable."""
    d = duel_pret()
    relever(d, 0, kills_a=0, kills_v=0)
    relever(d, 2, kills_a=0, kills_v=0)

    repris = Duel.from_dict(d.to_dict())
    relever(repris, 480, kills_a=4, kills_v=1, pourcent=87.0)
    evts = relever(repris, 482, kills_a=4, kills_v=1, pourcent=87.0)
    fin = [e for e in evts if e.type == "manche_fin"][0]
    assert fin.donnees["azrael"] == 4


def test_l_xp_d_une_manche_ne_clot_pas_la_suivante():
    """La fenêtre d'expérience se referme avec celle des kills.

    Laissée ouverte, la référence de la manche 1 resterait sous la valeur
    courante pendant toute la manche 2, qui se clôrait donc au premier relevé
    passé le plancher — sur zéro kill.
    """
    d = duel_pret()
    relever(d, 0, kills_a=0, kills_v=0)
    relever(d, 2, kills_a=0, kills_v=0)
    relever(d, 480, kills_a=4, kills_v=1, pourcent=87.0)
    relever(d, 482, kills_a=4, kills_v=1, pourcent=87.0)
    assert d.etat is Etat.ENTRE_MANCHES

    relever(d, 484, kills_a=4, kills_v=1, pourcent=87.0)
    relever(d, 486, kills_a=4, kills_v=1, pourcent=87.0)
    assert d.etat is Etat.MANCHE
    relever(d, 600, kills_a=6, kills_v=2, pourcent=87.0)
    relever(d, 602, kills_a=6, kills_v=2, pourcent=87.0)
    assert len(d.scores) == 1, "l'XP de la manche 1 n'a pas clos la manche 2"
