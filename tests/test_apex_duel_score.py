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
