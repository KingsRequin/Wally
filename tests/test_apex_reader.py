# tests/test_apex_reader.py
"""Lecture d'une réponse /bridge — la forme change d'un joueur à l'autre.

Les deux fixtures sont des réponses RÉELLES capturées le 2026-08-08. Elles ne
diffèrent pas par hasard : les trackers dépendent de ce que le joueur a épinglé
en jeu, et changent au fil des saisons. Un code qui lit `career_kills` en dur
marche pour l'un et casse pour l'autre.
"""
import json
import pathlib

import pytest

from bot.core.apex.reader import read_profile

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "apex"


def _payload(name):
    return json.loads((FIXTURES / f"bridge_{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("who", ["kingsrequin", "azrael"])
def test_les_kills_sortent_des_deux_formes(who):
    profil = read_profile(_payload(who))
    assert profil.stats["kills"].value > 0


def test_le_libelle_reel_est_conserve():
    """« BR Kills » et « Career Kills » ne se traduisent pas l'un en l'autre."""
    assert read_profile(_payload("azrael")).stats["kills"].label == "BR Kills"
    assert read_profile(_payload("kingsrequin")).stats["kills"].label == "Career Kills"


def test_une_notion_absente_est_absente_pas_zero():
    """« Azraël : 0 réanimation » serait un mensonge, pas une valeur par défaut.

    Le cas est réel : KingsRequin publie « Career Revives », Azraël ne publie
    aucun tracker de réanimation."""
    assert "revives" not in read_profile(_payload("azrael")).stats
    assert read_profile(_payload("kingsrequin")).stats["revives"].value > 0


def test_le_top_pourcent_du_ladder_quand_c_est_un_nombre():
    assert read_profile(_payload("azrael")).rank.top_percent == pytest.approx(49.45)


def test_no_game_this_split_ne_devient_pas_un_nombre():
    assert read_profile(_payload("kingsrequin")).rank.top_percent is None


def test_une_position_de_ladder_a_moins_un_est_absente():
    for who in ("kingsrequin", "azrael"):
        assert read_profile(_payload(who)).rank.ladder_pos is None


def test_le_rang_mondial_vient_du_bloc_global_seulement():
    """« BR Kills » sous Revenant classe les kills FAITS AVEC Revenant.

    Le rapprocher du total carrière annonçait « 3ᵉ mondial » là où le bloc
    `Global` — le seul qui classe le total — ne dit rien du tout."""
    kills = read_profile(_payload("kingsrequin")).stats["kills"]
    assert kills.world_pos == 432897
    assert kills.top_percent == pytest.approx(21.41)


def test_sans_bloc_global_aucun_rang_mondial_n_est_invente():
    kills = read_profile(_payload("azrael")).stats["kills"]
    # 92 182 (`specialEvent_kills`) et 10 142 (`kills`) : deux badges du même
    # compteur, on garde le plus haut. Leur somme, 102 324, a été affichée
    # pendant huit jours — voir test_apex_trackers_meme_libelle.py.
    assert kills.value == 92182
    assert kills.world_pos is None
    assert kills.top_percent is None


def test_identite_et_etat_en_jeu():
    profil = read_profile(_payload("azrael"))
    # L'API rend la casse officielle du compte, pas celle qu'on a demandée.
    assert profil.name == "Azrael_TTV"
    assert profil.uid == "2274044345"
    assert profil.level == 1354
    assert profil.rank.name == "Gold"
    assert profil.rank.div == 3
    assert profil.legend == "Fuse"
    assert profil.state


def test_une_reponse_d_erreur_ne_donne_pas_de_profil():
    assert read_profile({"Error": "Player not found"}) is None
    assert read_profile({}) is None
