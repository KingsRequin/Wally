"""Le score d'une manche, mesuré sur des deltas de compteurs.

Trois faits établis le 2026-08-13 sur des parties réelles :
  - les quatre trackers bougent du MÊME montant (4 kills → +4 partout) ;
  - un tracker ré-épinglé saute de milliers d'un coup (+7793 sans un kill) ;
  - la Mixtape n'incrémente rien du tout (10 kills → 0).
"""
from bot.core.apex.duel import PLAFOND_KILLS_MANCHE, score_manche


def test_quatre_kills_donnent_quatre_pas_seize():
    """Tous les trackers bougent ensemble : les sommer quadruplerait le score."""
    avant = {"career_kills": 18782, "specialEvent_kills": 8522,
             "legend:career_kills": 18782, "legend:specialEvent_kills": 5967}
    apres = {"career_kills": 18786, "specialEvent_kills": 8526,
             "legend:career_kills": 18786, "legend:specialEvent_kills": 5971}
    assert score_manche(avant, apres) == 4


def test_un_seul_tracker_vivant_suffit():
    """Career Kills gelé, BR Kills vivant : le score est celui qui bouge."""
    avant = {"career_kills": 10989, "specialEvent_kills": 8522}
    apres = {"career_kills": 10989, "specialEvent_kills": 8524}
    assert score_manche(avant, apres) == 2


def test_un_tracker_epingle_en_cours_de_manche_est_ecarte():
    """+7793 mesuré au ré-épinglage, sans un kill joué. Sans ce filtre, il
    emporterait le duel."""
    avant = {"career_kills": 10989, "specialEvent_kills": 8522}
    apres = {"career_kills": 18782, "specialEvent_kills": 8524}
    assert score_manche(avant, apres) == 2


def test_cle_absente_du_releve_initial_ignoree():
    avant = {"career_kills": 100}
    apres = {"career_kills": 103, "nouveau_kills": 99999}
    assert score_manche(avant, apres) == 3


def test_delta_negatif_ignore():
    avant = {"a_kills": 100, "b_kills": 50}
    apres = {"a_kills": 90, "b_kills": 52}
    assert score_manche(avant, apres) == 2


def test_zero_kill_reel_vaut_zero_pas_none():
    """Une manche sans kill est un résultat, pas une absence de mesure."""
    avant = {"career_kills": 100, "specialEvent_kills": 50}
    apres = {"career_kills": 100, "specialEvent_kills": 50}
    assert score_manche(avant, apres) == 0


def test_aucun_tracker_commun_donne_none():
    """Non mesurable — jamais zéro. Un zéro inventé est un mensonge."""
    assert score_manche({}, {"career_kills": 100}) is None
    assert score_manche({"career_kills": 100}, {}) is None


def test_tous_les_deltas_ecartes_donne_none():
    avant = {"a_kills": 10}
    apres = {"a_kills": 10_000}
    assert score_manche(avant, apres) is None


def test_le_plafond_est_haut_pour_ne_jamais_mordre_sur_un_vrai_score():
    """Les records connus tournent autour de 25-30 kills."""
    assert PLAFOND_KILLS_MANCHE >= 25
    avant, apres = {"k_kills": 0}, {"k_kills": 25}
    assert score_manche(avant, apres) == 25


# ── Le plafond sépare deux ORDRES DE GRANDEUR ──────────────────────────────
def test_une_manche_genereuse_n_est_pas_un_artefact():
    """39 kills, mesurés le 2026-08-13 sur trois parties enchaînées, et jetés
    par un plafond calé à 30. Une manche généreuse — ou un découpage qui rate
    et fusionne deux parties — n'a rien à voir avec un tracker ré-épinglé.

    Le plafond doit laisser passer des dizaines : c'est le seul moyen de ne
    jamais reprendre à quelqu'un des kills qu'il a réellement faits.
    """
    assert score_manche({"k_kills": 0}, {"k_kills": 39}) == 39
    assert score_manche({"k_kills": 0}, {"k_kills": 60}) == 60


def test_le_rattrapage_d_un_tracker_reepingle_reste_ecarte():
    """Et il continue de séparer : +7793 d'un coup, c'est des semaines
    rattrapées, pas une partie."""
    avant = {"career_kills": 10989, "specialEvent_kills": 8522}
    apres = {"career_kills": 18782, "specialEvent_kills": 8524}
    assert score_manche(avant, apres) == 2


# ── Un zéro ne tient jamais lieu de témoin écarté ──────────────────────────
def test_un_zero_ne_remplace_pas_un_compteur_ecarte():
    """Le faux zéro annoncé en direct le 2026-08-13.

    Les deux compteurs vivants sont jetés comme aberrants ; restent deux
    trackers dépinglés, figés, qui n'ont rien mesuré et valent 0. Le maximum de
    [0, 0] a donné 0 — annoncé comme un score à quelqu'un qui venait de faire
    39 kills. Ce n'est pas un zéro : c'est une absence de mesure.
    """
    avant = {"specialEvent_kills": 93331, "legend:specialEvent_kills": 83963,
             "grandsoiree_kills": 1480, "kills": 10155}
    apres = {"specialEvent_kills": 93370, "legend:specialEvent_kills": 84002,
             "grandsoiree_kills": 1480, "kills": 10155}
    # Avec un plafond assez bas pour jeter les deux compteurs vivants.
    assert score_manche(avant, apres, plafond=30) is None
    # Et le plafond en vigueur les garde, donc le vrai score sort.
    assert score_manche(avant, apres) == 39


def test_un_zero_ne_remplace_pas_un_tracker_disparu():
    """Un tracker dépinglé EN COURS de manche disparaît du second relevé : on
    ne saura jamais ce qu'il avait à dire. Le compteur mort qui reste ne parle
    pas à sa place."""
    avant = {"specialEvent_kills": 8522, "grandsoiree_kills": 1480}
    apres = {"grandsoiree_kills": 1480}
    assert score_manche(avant, apres) is None


def test_un_zero_l_emporte_quand_rien_n_a_ete_perdu():
    """L'inverse doit rester vrai, sinon une manche sans kill deviendrait
    impossible à mesurer : tous les compteurs se lisent du début à la fin,
    aucun ne bouge — c'est un vrai 0, et il vaut 0."""
    avant = {"career_kills": 100, "specialEvent_kills": 50, "kills": 7}
    apres = {"career_kills": 100, "specialEvent_kills": 50, "kills": 7}
    assert score_manche(avant, apres) == 0


def test_un_compteur_vivant_l_emporte_sur_les_morts():
    """Un seul compteur qui bouge suffit à trancher : les zéros qui
    l'accompagnent sont des compteurs morts, pas un désaccord."""
    avant = {"specialEvent_kills": 8522, "grandsoiree_kills": 1480, "kills": 10155}
    apres = {"specialEvent_kills": 8525, "grandsoiree_kills": 1480, "kills": 10155}
    assert score_manche(avant, apres) == 3
