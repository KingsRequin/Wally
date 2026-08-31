# tests/intelligence/core/test_cognitive_extrait_coupe.py
"""Un aperçu du flux cognitif doit DIRE qu'il est coupé.

`texte[:160]` s'arrêtait au milieu d'un mot, sans le moindre signe : sur le
site, une pensée de Wally finissait sur « C'est » et rien ne distinguait la
coupure d'une phrase inachevée. Constaté sur téléphone le 2026-08-31 — le
défaut n'avait rien de mobile, il était là sur tous les écrans.

Et la pensée de Wally, elle, part désormais ENTIÈRE dans `full` : le panneau
sait déjà déplier. Le message d'une PERSONNE, non — le flux est public, et
l'aperçu y est une limite voulue.
"""
from bot.intelligence.cognitive_loop import _EXTRAIT_MAX, _extrait


def test_un_texte_court_passe_intact():
    assert _extrait("une pensée brève") == "une pensée brève"


def test_un_texte_long_annonce_sa_coupure():
    coupe = _extrait("a" * 400)
    assert coupe.endswith("…")
    assert len(coupe) == _EXTRAIT_MAX + 1


def test_la_coupure_ne_laisse_pas_d_espace_avant_les_points():
    """« mot … » se lit comme une hésitation ; « mot… » comme une coupure."""
    texte = "x" * (_EXTRAIT_MAX - 1) + " suite qui déborde"
    assert not _extrait(texte).endswith(" …")


def test_pile_a_la_limite_rien_n_est_ajoute():
    assert _extrait("b" * _EXTRAIT_MAX) == "b" * _EXTRAIT_MAX


def test_ni_none_ni_vide_ne_lèvent():
    assert _extrait(None) == ""
    assert _extrait("   ") == ""
