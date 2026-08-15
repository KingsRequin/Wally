"""Chaque élément de l'overlay doit avoir un libellé lisible.

Sans ce test, ajouter un widget dans `ELEMENTS` sans le déclarer ici le laisse
sans nom ni description dans le panneau de mise en scène — le streamer verrait
une clé technique nue, ou pire, un widget absent du panneau.
"""
from bot.core.overlay_elements import LIBELLES
from bot.core.overlay_layout import ELEMENTS


def test_libelles_couvre_exactement_elements():
    manquants = set(ELEMENTS) - set(LIBELLES)
    assert not manquants, f"libellés absents pour : {sorted(manquants)}"
    en_trop = set(LIBELLES) - set(ELEMENTS)
    assert not en_trop, f"libellés pour des éléments inconnus : {sorted(en_trop)}"


def test_aucun_nom_ni_description_vide():
    for cle, libelle in LIBELLES.items():
        nom = libelle.get("nom", "")
        description = libelle.get("description", "")
        assert nom.strip(), f"nom vide pour {cle}"
        assert description.strip(), f"description vide pour {cle}"
