"""L'autorisation vocale se DÉRIVE de qui parle, elle ne se déduit pas d'une liste.

`_answer()` donnait à tout demandeur de `voice.requesters` le badge
`broadcaster` et les rôles `moderator` + `admin`. Le commentaire disait vrai au
moment où il a été écrit — « les deux seuls demandeurs sont le streamer et le
créateur du bot » —, et c'est encore vrai aujourd'hui.

Mais cette liste sert AUSSI à déclarer les comptes Apex (`seed_known_accounts`,
`uid_declare`). Y ajouter un troisième joueur pour un duel ou une courbe de
progression lui donnerait, sans que rien ne le dise : le contrôle du duel
(badge `broadcaster`), et la parole en vocal (`admin`). Une liste qui sert à
deux choses finit par autoriser ce qu'elle ne voulait qu'identifier.

L'appartenance dit QUI EST QUI ; la config dit qui a le DROIT.
"""
import pytest

from bot.discord.voice.request import droits_du_demandeur

_STREAMER = {"twitch_id": "659251746", "twitch_login": "azrael_ttv",
             "discord_id": "419172225451556874"}
_OWNER = {"twitch_id": "105904256", "twitch_login": "kingsrequin",
          "discord_id": "610550333042589752"}
_JOUEUR_APEX = {"twitch_id": "999", "twitch_login": "un_pote",
                "discord_id": "888", "apex_name": "UnPote"}

_BROADCASTER_ID = "659251746"
_OWNER_DISCORD = "610550333042589752"


def _droits(requester):
    return droits_du_demandeur(
        requester, broadcaster_id=_BROADCASTER_ID, owner_discord_id=_OWNER_DISCORD
    )


def test_le_streamer_garde_son_badge_broadcaster():
    roles, badges = _droits(_STREAMER)
    assert badges == [{"set_id": "broadcaster"}]
    assert "admin" in roles


def test_le_createur_est_admin_mais_n_est_PAS_le_broadcaster():
    """Il commande le bot, il ne possède pas la chaîne.

    Le badge `broadcaster` dit « c'est sa chaîne » — l'emprunter pour dire
    « il a le droit » mélange deux questions, et c'est ce mélange qui rendait
    le droit contagieux.
    """
    roles, badges = _droits(_OWNER)
    assert badges == []
    assert "admin" in roles


def test_un_joueur_apex_ajoute_a_la_liste_n_herite_de_RIEN():
    """Le cas qui motive tout : la liste identifie, elle n'autorise pas."""
    roles, badges = _droits(_JOUEUR_APEX)
    assert badges == []
    assert roles == ["everyone"]
    assert "admin" not in roles and "moderator" not in roles


@pytest.mark.parametrize("requester", [{}, {"twitch_id": None}, {"discord_id": ""}])
def test_un_demandeur_incomplet_ne_gagne_rien(requester):
    """Le défaut sûr : un champ vide ne vaut pas un champ égal.

    `"" == ""` est vrai en Python — sans garde, un requester sans `twitch_id`
    face à un `broadcaster_id` absent de la config serait promu broadcaster.
    """
    roles, badges = droits_du_demandeur(
        requester, broadcaster_id="", owner_discord_id=""
    )
    assert badges == []
    assert roles == ["everyone"]
