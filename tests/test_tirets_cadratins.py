"""Les « — » de Wally : un tic d'IA que personne n'écrit en tapant au clavier.

Demande de l'owner (2026-08-30) : « supprime tous les — qui font trop IA sur
les messages écrits ».

La source n'est pas le code : c'est le MODÈLE, qui en pose dans presque chaque
réponse. Une consigne de prompt se contourne, un mécanisme non — c'est déjà la
raison d'être de ce module, écrit pour les didascalies de roleplay.

Le remplacement n'est pas une suppression : « ouais — enfin bref » deviendrait
« ouais enfin bref », deux propositions collées. C'est une virgule qu'un humain
aurait tapée.
"""
import pytest

from bot.core.text_clean import retirer_tirets_cadratins


@pytest.mark.parametrize("avant, apres", [
    # L'incise, le cas de très loin le plus fréquent.
    ("c'est prêt — enfin je crois", "c'est prêt, enfin je crois"),
    ("Le sondage est ouvert — ne l'invente pas.", "Le sondage est ouvert, ne l'invente pas."),
    # Le demi-cadratin est le même tic, en plus discret.
    ("ça marche – à peu près", "ça marche, à peu près"),
    # Collé aux mots : le modèle le fait aussi.
    ("ouais—non", "ouais, non"),
    # Déjà ponctué : une virgule de plus ferait « ,, ».
    ("bon, — on verra", "bon, on verra"),
    ("attends : — non en fait", "attends : non en fait"),
    # En fin de texte, il n'introduit plus rien.
    ("je sais pas —", "je sais pas"),
    ("je sais pas — ", "je sais pas"),
    # Plusieurs dans la même phrase.
    ("a — b — c", "a, b, c"),
])
def test_le_tiret_devient_la_ponctuation_qu_un_humain_aurait_tapee(avant, apres):
    assert retirer_tirets_cadratins(avant) == apres


@pytest.mark.parametrize("texte", [
    # Une PUCE de liste ou un tiret de dialogue : c'est de la mise en forme
    # voulue, pas un tic. Le remplacer par une virgule casserait la liste.
    "voilà le plan :\n— d'abord ça\n— ensuite ça",
    "— et toi ?",
    # Un intervalle numérique n'est pas une incise.
    "entre 1000–128000 tokens",
    # Rien à faire.
    "une phrase parfaitement normale",
    "",
])
def test_ce_qui_n_est_pas_un_tic_reste_intact(texte):
    assert retirer_tirets_cadratins(texte) == texte


def test_un_texte_qui_n_etait_que_des_tirets_ne_devient_pas_vide():
    """Le séparateur décoratif employé seul sur une ligne reste lisible."""
    assert retirer_tirets_cadratins("—") == "—"


def test_le_nettoyage_de_sortie_l_applique():
    """Le point d'entrée unique des messages sortants le porte.

    Sans ça il faudrait se souvenir de l'appeler sur chacun des chemins de
    sortie, et le prochain en serait dépourvu, en silence.
    """
    from bot.core.text_clean import strip_stage_directions

    assert "—" not in strip_stage_directions("c'est prêt — enfin je crois")
