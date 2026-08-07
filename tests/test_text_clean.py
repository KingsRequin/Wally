"""Didascalies de roleplay dans les réponses.

Vu en prod le 2026-08-07 : « (Je lance un coup d'œil au message, un sourcil levé
par la curiosité, puis je réponds avec un ton détaché mais intrigué) Oh ? ». La
consigne existait déjà dans VOICE.md — mais pour les astérisques, et le modèle
est passé par les parenthèses.
"""
from bot.core.text_clean import strip_stage_directions as clean


def test_le_cas_reel_vu_en_production():
    brut = ("(Je lance un coup d'œil au message, un sourcil levé par la curiosité, "
            "puis je réponds avec un ton détaché mais intrigué)\n"
            "Oh ? Un coup de main pour quoi au juste ?")
    assert clean(brut) == "Oh ? Un coup de main pour quoi au juste ?"


def test_une_didascalie_entre_asterisques_saute_aussi():
    assert clean("*soupire longuement*\nouais bon") == "ouais bon"


def test_une_didascalie_sur_la_meme_ligne_que_la_replique():
    assert clean("(je hausse les épaules) ouais bof") == "ouais bof"


def test_plusieurs_didascalies_enchainees():
    assert clean("(il réfléchit) *se gratte la tête* alors") == "alors"


def test_une_incise_en_milieu_de_phrase_est_preservee():
    """« (si on veut) » est une vraie parenthèse, pas une mise en scène."""
    t = "ouais enfin (si on veut) c'est discutable"
    assert clean(t) == t


def test_une_parenthese_courte_en_tete_est_preservee():
    """Trop brève pour être une didascalie — on ne coupe pas au hasard."""
    t = "(bref) passons à autre chose"
    assert clean(t) == t


def test_une_didascalie_en_fin_de_message_saute():
    assert clean("c'est noté\n(il s'éloigne en marmonnant)") == "c'est noté"


def test_un_message_entierement_en_didascalie_est_laisse_tel_quel():
    """Mieux vaut un message étrange que pas de message du tout."""
    t = "(il hausse les épaules sans rien dire)"
    assert clean(t) == t


def test_un_texte_normal_n_est_pas_touche():
    t = "salut, ça va ? j'ai regardé ton clip hier"
    assert clean(t) == t


def test_le_vide_ne_leve_pas():
    assert clean("") == ""
    assert clean(None) is None


def test_les_sauts_de_ligne_utiles_survivent():
    assert clean("première ligne\n\nseconde ligne") == "première ligne\n\nseconde ligne"
