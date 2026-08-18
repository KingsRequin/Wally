"""Les légendes ont leurs chiffres, et deux trackers d'un libellé n'en font qu'un.

Signalé le 2026-08-10 par le propriétaire : Wally refusait de donner les kills
par légende d'Azraël, en affirmant que l'API ne les fournissait pas.
`legends.all.<Légende>.data` n'était jamais lu ; la description de l'outil
annonçait même « CE QUE CETTE API NE DONNE PAS : […] classement par légende ».
Wally en concluait, logiquement, qu'il n'y avait pas accès. Or tout est là, avec
les rangs mondiaux — c'est l'objet de ce fichier.

La même passe avait cru corriger un second défaut, et en a créé un : `total`
porte DEUX trackers « BR Kills » chez Azraël (`specialEvent_kills` = 92 182 et
`kills` = 10 142), et on s'est mis à les ADDITIONNER. Le contrôle qui validait
l'addition — « la somme par légende vaut la somme globale » — appliquait la même
addition des deux côtés, sur un `total` que l'API construit justement en sommant
les légendes clé par clé. Vrai par construction, donc muet.

Corrigé le 2026-08-18 : on garde le plus haut. Le récit complet et la preuve qui
tranche sont dans test_apex_trackers_meme_libelle.py.

Les fixtures sont des captures réelles des comptes (2026-08-08).
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


# ───────────────────────── le total ─────────────────────────
def test_le_plus_haut_tracker_du_libelle_gagne(azrael):
    """92 182 et 10 142 sont deux badges du même compteur, pas deux moitiés.
    Le second est gelé depuis qu'il a quitté son emplacement."""
    assert azrael.stats["kills"].value == 92_182
    # Idem « BR Damage » : 29 917 822 et 368 769, jamais leur somme.
    assert azrael.stats["damage"].value == 29_917_822


def test_un_compte_sans_doublon_reste_inchange(kingsrequin):
    """KingsRequin n'a qu'un tracker par libellé — la correction ne doit rien
    gonfler chez lui."""
    assert kingsrequin.stats["kills"].value == 10_989


# ───────────────────────── les stats par légende ─────────────────────────
def test_les_kills_par_legende_sont_lus(azrael):
    """La demande d'origine : « Azraël, il a combien de kills avec Fuse ? »"""
    assert azrael.legend_stats["Fuse"]["kills"].value == 82_814
    assert azrael.legend_stats["Fuse"]["wins"].value == 3_136


def test_une_legende_a_deux_compteurs_garde_le_plus_haut(azrael):
    """Rampart : `kills` = 982 et `specialEvent_kills` = 2 285. Pas 3 267."""
    assert azrael.legend_stats["Rampart"]["kills"].value == 2_285


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
    # Les deux classements que l'API donne réellement.
    assert "3ᵉ mondial" in rendu and "2ᵉ sur sa plateforme" in rendu


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
    assert "ne les confonds pas avec un palmarès" in description


def test_le_premier_mondial_ne_secrit_pas_1e():
    """Azraël est 1ᵉʳ mondial aux dégâts avec Fuse — le cas se voit en vrai."""
    from bot.core.apex.service import _rang

    assert _rang(1) == "1ᵉʳ"
    assert _rang(3) == "3ᵉ"
    assert _rang(432_897) == "432 897ᵉ"


# ───────────────────── le rang plateforme, et le pays qui n'existe pas ─────
def test_le_rang_par_plateforme_est_lu(azrael):
    """`rankPlatformSpecific` arrivait à chaque appel et était jeté. C'est
    souvent le chiffre parlant : 10ᵉ mondial aux wins avec Fuse, 3ᵉ sur PC."""
    fuse = azrael.legend_stats["Fuse"]
    assert fuse["kills"].platform_pos == 2 and fuse["kills"].world_pos == 3
    assert fuse["wins"].platform_pos == 3 and fuse["wins"].world_pos == 10


def test_not_calculated_yet_reste_une_absence(azrael):
    """L'API écrit « NOT_CALCULATED_YET » là où on attend un entier — ce n'est
    ni un rang, ni un zéro."""
    mirage = azrael.legend_stats["Mirage"]["kills"]
    assert mirage.platform_pos is None


def test_les_deux_classements_sont_rendus(azrael):
    rendu = _service()._render_profile(azrael, legend="Fuse")

    assert "3ᵉ mondial, top 0.01 % — 2ᵉ sur sa plateforme" in rendu


def test_loutil_dit_que_le_rang_par_pays_nexiste_pas():
    """Vérifié le 2026-08-10 avec notre clé : `/leaderboard` répond
    « You must be whitelisted », et `/bridge` ne porte aucune notion de pays.
    L'outil doit le dire pour éviter une cascade `web_search`/`scrape_url`."""
    from bot.core.apex.tool import APEX_LEGENDS_TOOL

    description = APEX_LEGENDS_TOOL["function"]["description"]
    assert "AUCUN classement par PAYS" in description
    # Et proposer le repli qui existe vraiment.
    assert "sur SA PLATEFORME" in description
