# tests/test_apex_tool.py
"""Le schéma de l'outil Apex, et ce qu'il empêche."""
from bot.core.apex.tool import APEX_LEGENDS_TOOL


def test_les_actions_offertes():
    enum = APEX_LEGENDS_TOOL["function"]["parameters"]["properties"]["action"]["enum"]
    assert enum == ["player_stats", "progression", "map_rotation", "crafting",
                    "predator", "server_status"]
    assert "news" not in enum


def test_la_progression_annonce_d_ou_vient_le_chiffre():
    """Il ne sort pas de l'API mais de relevés maison : le modèle doit le savoir,
    sinon il présentera « depuis le 12 » comme le total du mois."""
    desc = APEX_LEGENDS_TOOL["function"]["description"].lower()
    assert "progression" in desc
    assert "relevés" in desc


def test_la_description_nomme_ce_qui_est_hors_de_portee():
    """Sans ça, le modèle part chercher ailleurs et sature la boucle d'outils."""
    desc = APEX_LEGENDS_TOOL["function"]["description"].lower()
    assert "classement" in desc
    assert "historique" in desc
    assert "ne cherche pas ailleurs" in desc


def test_les_plateformes_acceptees():
    props = APEX_LEGENDS_TOOL["function"]["parameters"]["properties"]
    assert props["platform"]["enum"] == ["PC", "PS4", "X1"]


def test_le_service_expose_le_meme_outil():
    from bot.core.apex import ApexLegendsService
    assert ApexLegendsService().get_tool_definition() is APEX_LEGENDS_TOOL


def test_le_parametre_de_memorisation_est_reserve_a_son_propre_compte():
    props = APEX_LEGENDS_TOOL["function"]["parameters"]["properties"]
    assert props["remember"]["type"] == "boolean"
    desc = props["remember"]["description"].lower()
    assert "son propre" in desc
    assert "quelqu'un d'autre" in desc


def test_un_pseudo_vide_signifie_mes_stats():
    desc = APEX_LEGENDS_TOOL["function"]["description"]
    assert "VIDE" in desc


def test_la_description_montre_comment_retenir_un_compte():
    """La consigne ne suffit pas : c'est l'exemple qui déclenche l'appel."""
    desc = APEX_LEGENDS_TOOL["function"]["description"]
    assert "remember=true" in desc
    assert "mon pseudo Apex" in desc
    assert "player_name VIDE" in desc
