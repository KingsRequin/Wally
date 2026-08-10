"""Deux trackers d'un même libellé s'additionnent, et les légendes ont leurs chiffres.

Signalé le 2026-08-10 par le propriétaire : Wally annonçait « 92 182 kills » pour
Azraël, qui en a plus de cent mille — et refusait de donner ses kills par
légende, en affirmant que l'API ne les fournissait pas.

Deux défauts, une même racine : on jetait des données que l'API donnait.

  1. `total` porte DEUX trackers nommés « BR Kills » chez Azraël,
     `specialEvent_kills` = 92 182 et `kills` = 10 142. Le lecteur gardait le
     premier rencontré (`setdefault`) et ignorait l'autre. Ce ne sont pas des
     doublons : leur somme, 102 324, vaut EXACTEMENT la somme de ses « BR Kills »
     par légende. Idem pour « BR Damage ». Une valeur amputée de 10 % ne se voit
     pas — elle est juste fausse, annoncée avec le même aplomb.

  2. `legends.all.<Légende>.data` n'était jamais lu. La description de l'outil
     annonçait même « CE QUE CETTE API NE DONNE PAS : […] classement par
     légende » — Wally en concluait, logiquement, qu'il n'avait pas accès aux
     kills par légende. Or ils sont là, avec leur rang mondial.

Les fixtures sont des captures réelles des deux comptes (2026-08-08).
"""
import json
from pathlib import Path

import pytest

from bot.core.apex.reader import read_profile

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "apex"


def _profil(nom):
    return read_profile(json.loads((_FIXTURES / nom).read_text(encoding="utf-8")))


@pytest.fixture
def azrael():
    return _profil("bridge_azrael.json")


@pytest.fixture
def kingsrequin():
    return _profil("bridge_kingsrequin.json")


# ───────────────────────── le total amputé ─────────────────────────
def test_les_trackers_du_meme_libelle_sadditionnent(azrael):
    """92 182 + 10 142. Garder le premier annonçait 10 % de moins."""
    assert azrael.stats["kills"].value == 102_324
    assert azrael.stats["damage"].value == 30_286_591


def test_le_total_egale_la_somme_par_legende(azrael):
    """Le contrôle qui prouve que la somme est la bonne lecture, pas une
    heuristique : les deux chemins de calcul tombent sur le même nombre."""
    par_legende = sum(
        st["kills"].value for st in azrael.legend_stats.values() if "kills" in st
    )
    assert par_legende == azrael.stats["kills"].value == 102_324


def test_un_compte_sans_doublon_reste_inchange(kingsrequin):
    """KingsRequin n'a qu'un tracker par libellé — la correction ne doit rien
    gonfler chez lui."""
    assert kingsrequin.stats["kills"].value == 10_989


# ───────────────────────── les stats par légende ─────────────────────────
def test_les_kills_par_legende_sont_lus(azrael):
    """La demande d'origine : « Azraël, il a combien de kills avec Fuse ? »"""
    assert azrael.legend_stats["Fuse"]["kills"].value == 82_814
    assert azrael.legend_stats["Fuse"]["wins"].value == 3_136


def test_une_legende_a_deux_compteurs_les_additionne(azrael):
    """Rampart : `kills` = 982 et `specialEvent_kills` = 2 285."""
    assert azrael.legend_stats["Rampart"]["kills"].value == 3_267


def test_le_rang_mondial_vient_du_tracker_dominant(azrael):
    """Un classement porte sur UN compteur, jamais sur une somme. Celui de
    Rampart doit rester celui du tracker le plus gros, pas une moyenne."""
    assert azrael.legend_stats["Fuse"]["kills"].world_pos == 3
    rampart = azrael.legend_stats["Rampart"]["kills"]
    assert rampart.world_pos == 10_731


def test_global_nest_pas_une_legende(azrael, kingsrequin):
    """Il porte les totaux de carrière et le rang mondial. Le prendre pour une
    légende avait déjà donné « 92 182 kills, 3ᵉ mondial »."""
    assert "Global" not in azrael.legend_stats
    assert "Global" not in kingsrequin.legend_stats


def test_une_legende_sans_tracker_est_absente_pas_a_zero(kingsrequin):
    """KingsRequin n'a pas épinglé Fuse : son bloc n'a que `ImgAssets`.
    « 0 kill avec Fuse » serait un mensonge, pas une valeur par défaut."""
    assert "Fuse" not in kingsrequin.legend_stats
    assert set(kingsrequin.legend_stats) == {"Wraith", "Octane", "Pathfinder", "Mirage"}


def test_les_formes_degradees_ne_levent_pas():
    """L'API ne garantit rien : un bloc peut ne pas être un dict, `data` peut ne
    pas être une liste, une entrée peut être un entier."""
    base = {"global": {"name": "X", "uid": "1"}}
    for tordu in (
        {"legends": None},
        {"legends": {"all": None}},
        {"legends": {"all": ["pas", "un", "dict"]}},
        {"legends": {"all": {"Fuse": "une chaîne"}}},
        {"legends": {"all": {"Fuse": {"data": "pas une liste"}}}},
        {"legends": {"all": {"Fuse": {"data": [42, None, {"name": None}]}}}},
    ):
        profil = read_profile({**base, **tordu})
        assert profil is not None
        assert profil.legend_stats == {}


# ───────────────────────── le rendu offert au modèle ─────────────────────────
def _service():
    from bot.core.apex.service import ApexLegendsService

    return ApexLegendsService.__new__(ApexLegendsService)


def test_le_detail_dune_legende_demandee(azrael):
    rendu = _service()._render_profile(azrael, legend="Fuse")

    assert "Avec Fuse :" in rendu
    assert "82 814" in rendu
    # Le rang porte sur CE tracker, et le rendu doit le dire.
    assert "sur ce tracker" in rendu


def test_la_legende_se_demande_sans_respecter_la_casse(azrael):
    assert "Avec Fuse :" in _service()._render_profile(azrael, legend="fuse")


def test_une_legende_non_suivie_est_expliquee_pas_inventee(kingsrequin):
    rendu = _service()._render_profile(kingsrequin, legend="Fuse")

    assert "ce n'est pas un zéro" in rendu
    assert "Wraith" in rendu, "la liste des légendes suivies aide à rebondir"
    assert "0" not in rendu.split("Pas de compteur")[1][:40]


def test_le_resume_est_borne_et_annonce_le_reste(azrael):
    """Azraël suit 17 légendes : les déballer toutes noierait le rang et l'état."""
    rendu = _service()._render_profile(azrael)

    assert "Fuse" in rendu, "le podium doit répondre à « avec quoi il tape le plus »"
    corps = rendu.split("Par légende")[1]
    detaillees = [
        l for l in corps.splitlines()
        if l.startswith("  ") and " : " in l and "aussi suivies" not in l
    ]
    assert len(detaillees) <= 3, f"résumé non borné : {detaillees}"
    assert "aussi suivies" in rendu


def test_un_compte_sans_aucun_tracker_le_dit(azrael):
    from dataclasses import replace

    rendu = _service()._render_profile(replace(azrael, legend_stats={}))

    assert "aucun compteur par légende" in rendu


def test_loutil_annonce_les_stats_par_legende():
    """La description disait le CONTRAIRE — c'est elle qui faisait refuser Wally."""
    from bot.core.apex.tool import APEX_LEGENDS_TOOL

    fonction = APEX_LEGENDS_TOOL["function"]
    assert "legend" in fonction["parameters"]["properties"]
    description = fonction["description"]
    assert "PAR LÉGENDE" in description
    # Ce que l'API ne donne pas, c'est le TABLEAU de classement — pas les
    # chiffres d'un joueur avec une légende.
    assert "ne les confonds pas avec un classement" in description


def test_le_premier_mondial_ne_secrit_pas_1e():
    """Azraël est 1ᵉʳ mondial aux dégâts avec Fuse — le cas se voit en vrai."""
    from bot.core.apex.service import _rang

    assert _rang(1) == "1ᵉʳ"
    assert _rang(3) == "3ᵉ"
    assert _rang(432_897) == "432 897ᵉ"
