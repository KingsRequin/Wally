"""Les trackers de kills BRUTS, pour un delta de partie.

`_read_stats` ne convient pas : il prend le PREMIER alias connu et jette les
autres. Un joueur dont « Career Kills » est gelé (tracker retiré de sa bannière,
valeur figée au jour du retrait) et dont « BR Kills » est vivant verrait son
score bloqué à zéro.
"""
from bot.core.apex.reader import read_kill_trackers


def test_prend_tous_les_trackers_de_kills_de_total():
    payload = {
        "total": {
            "career_kills": {"name": "Career Kills", "value": 18788},
            "specialEvent_kills": {"name": "BR Kills", "value": 8528},
            "specialEvent_damage": {"name": "BR Damage", "value": 27324446},
        }
    }
    assert read_kill_trackers(payload) == {
        "career_kills": 18788,
        "specialEvent_kills": 8528,
    }


def test_inclut_les_trackers_de_la_legende_selectionnee_prefixes():
    """`legends.selected.data` est une LISTE, là où `total` est un dict.
    Ne traiter que la seconde forme rend les stats de légende vides EN SILENCE."""
    payload = {
        "total": {"career_kills": {"name": "Career Kills", "value": 100}},
        "legends": {"selected": {"LegendName": "Mirage", "data": [
            {"name": "BR Kills", "value": 5973, "key": "specialEvent_kills"},
            {"name": "Bamboozles", "value": 4210, "key": "bamboozles"},
        ]}},
    }
    assert read_kill_trackers(payload) == {
        "career_kills": 100,
        "legend:specialEvent_kills": 5973,
    }


def test_ignore_les_valeurs_non_numeriques():
    payload = {"total": {"k": {"name": "BR Kills", "value": "No game this split"}}}
    assert read_kill_trackers(payload) == {}


def test_paye_le_payload_casse_sans_lever():
    for casse in ({}, {"total": None}, {"total": []}, {"legends": {"selected": {"data": {}}}}):
        assert read_kill_trackers(casse) == {}


def test_une_liste_ne_traverse_pas_le_or():
    """`or {}` ne protège pas d'un type inattendu : une LISTE est vraie."""
    assert read_kill_trackers({"total": [1, 2, 3]}) == {}
