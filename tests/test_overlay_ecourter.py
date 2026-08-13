"""Coupe des textes affichés sur l'overlay.

Repéré en prod : le propriétaire demande « affiche bonjour », et l'overlay
montre « Bonjour. Enfin un truc qui marche dans c ». Exactement 40 caractères —
la limite du widget, appliquée par une tranche brute. Le viewer voit une phrase
amputée en plein mot, et rien ne lui signale qu'il en manque.
"""
from bot.core.overlay_feed import ecourter


def test_la_coupe_recule_jusqu_au_mot_precedent():
    """Le cas vécu : la tranche tombait au milieu de « ce »."""
    dit = "Bonjour. Enfin un truc qui marche dans ce bazar"
    coupe = ecourter(dit, 40)
    assert coupe == "Bonjour. Enfin un truc qui marche…"
    assert len(coupe) <= 40


def test_un_texte_assez_court_est_rendu_intact():
    assert ecourter("Salut", 40) == "Salut"
    assert ecourter("", 40) == ""


def test_la_limite_est_toujours_tenue():
    """Le « … » compris : sinon la coupe déborde de la place réservée."""
    for n in range(6, 60):
        assert len(ecourter("un deux trois quatre cinq six sept huit neuf", n)) <= n


def test_un_mot_plus_long_que_la_limite_est_coupe_net():
    """Reculer jusqu'à l'espace précédent rendrait une chaîne vide, ou si courte
    qu'elle ne dirait plus rien. Mieux vaut couper le mot."""
    assert ecourter("Anticonstitutionnellement", 12) == "Anticonstit…"


def test_la_ponctuation_ne_precede_pas_les_points_de_suspension():
    """« marche dans, … » se lit comme une faute de frappe."""
    assert ecourter("On y va, mais alors vraiment très loin", 14) == "On y va…"


def test_les_espaces_multiples_sont_normalises():
    """Le texte vient d'un LLM : retours à la ligne et doubles espaces compris."""
    assert ecourter("Deux\n\nlignes   ici", 40) == "Deux lignes ici"
