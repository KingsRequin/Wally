# tests/test_apex_tool.py
"""Le schéma de l'outil Apex, et ce qu'il empêche."""
from bot.core.apex.tool import APEX_LEGENDS_TOOL


def test_les_actions_offertes():
    enum = APEX_LEGENDS_TOOL["function"]["parameters"]["properties"]["action"]["enum"]
    assert enum == ["player_stats", "map_rotation", "crafting", "predator", "server_status"]
    assert "news" not in enum


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
