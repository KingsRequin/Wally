"""Deux trackers d'un même libellé mesurent la MÊME chose — on garde le plus haut.

Signalé le 2026-08-18 par le propriétaire : Wally annonçait « 22 234 kills avec
Crypto » pour IronAnanas, qui en a 11 117. Exactement le double.

La cause est dans les données, pas dans l'API. Sous Crypto, IronAnanas publie
deux trackers « BR Kills » : `kills` = 11 117 et `specialEvent_kills` = 11 117.
Le MÊME compteur, exposé par deux badges épinglés en même temps. On les
additionnait.

Cette addition venait d'une lecture d'Azraël (`specialEvent_kills` = 92 182 et
`kills` = 10 142) validée par un contrôle qui ne contrôlait rien : « la somme par
légende vaut la somme globale ». Les deux membres appliquaient la même addition,
et l'API construit `total` en sommant les légendes clé par clé — l'égalité est
vraie par construction, quelle que soit la règle. Vérifié sur les deux comptes
le 2026-08-18 : la somme des `kills` par légende vaut exactement le `kills`
global, et pareil pour `specialEvent_kills`. Ce sont deux séries COMPLÈTES et
parallèles, pas deux moitiés qui se complètent.

Ce que Crypto prouve, lui, ne se discute pas : deux compteurs identiques au kill
près ne sont pas deux moitiés d'un total qui vaudrait leur double.
"""
import json
from pathlib import Path

import pytest

from bot.core.apex.reader import read_profile

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "apex"


def _profil(nom):
    return read_profile(json.loads((_FIXTURES / nom).read_text(encoding="utf-8")))


@pytest.fixture
def ironananas():
    return _profil("bridge_ironananas.json")


@pytest.fixture
def azrael():
    return _profil("bridge_azrael.json")


@pytest.fixture
def kingsrequin():
    return _profil("bridge_kingsrequin.json")


def test_deux_trackers_identiques_ne_doublent_pas_les_kills(ironananas):
    """Le défaut signalé : `kills` = `specialEvent_kills` = 11 117 sous Crypto."""
    assert ironananas.legend_stats["Crypto"]["kills"].value == 11_117


def test_le_tracker_le_plus_haut_gagne_quand_ils_different(ironananas):
    """Wattson : `kills` = 257 (badge retiré, valeur gelée) et
    `specialEvent_kills` = 704 (badge actif). 961 n'a jamais existé."""
    assert ironananas.legend_stats["Wattson"]["kills"].value == 704


def test_une_legende_a_un_seul_tracker_reste_intacte(ironananas):
    """Lifeline n'a que `kills` = 57 : rien à départager, rien à changer."""
    assert ironananas.legend_stats["Lifeline"]["kills"].value == 57


def test_le_total_de_carriere_ne_double_pas(azrael):
    """Azraël : `specialEvent_kills` = 92 182 et `kills` = 10 142 au global.
    Le plus haut est le compteur encore alimenté ; 102 324 était leur somme."""
    assert azrael.stats["kills"].value == 92_182


def test_un_compte_sans_doublon_reste_inchange(kingsrequin):
    """KingsRequin n'a qu'un tracker par libellé — rien ne doit bouger chez lui."""
    assert kingsrequin.stats["kills"].value == 10_989


def test_le_rang_mondial_reste_celui_du_tracker_retenu(azrael):
    """Un classement porte sur UN compteur. Il suit celui qu'on affiche."""
    assert azrael.legend_stats["Fuse"]["kills"].world_pos == 3
    assert azrael.legend_stats["Rampart"]["kills"].world_pos == 10_731
