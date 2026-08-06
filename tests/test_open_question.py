"""Une question de Wally restée en suspens vaut invitation à répondre.

Sans ça : il demande « entre quoi et quoi ? », on répond « pizza et burger », et
il ignore — la réponse ne contient ni son nom ni de mention. Le dialogue
s'interrompt de lui-même, ce qui est le contraire d'un compagnon.
"""
import time

from bot.discord.handlers import (
    _OPEN_QUESTION_WINDOW_S,
    _consume_open_question,
    _note_open_question,
    _open_questions,
)


def setup_function():
    _open_questions.clear()


def test_une_reponse_a_sa_question_declenche():
    _note_open_question(10, 99, "entre quoi et quoi ?")
    assert _consume_open_question(10, 99) is True


def test_une_reponse_sans_question_ne_declenche_pas():
    _note_open_question(10, 99, "voilà, c'est fait.")
    assert _consume_open_question(10, 99) is False


def test_la_fenetre_ne_vaut_que_pour_l_interlocuteur():
    """Sinon tout le salon lui parlerait pendant trois minutes."""
    _note_open_question(10, 99, "tu préfères quoi ?")
    assert _consume_open_question(10, 1234) is False
    assert _consume_open_question(10, 99) is True


def test_la_fenetre_ne_vaut_que_dans_le_salon_concerne():
    _note_open_question(10, 99, "tu préfères quoi ?")
    assert _consume_open_question(77, 99) is False


def test_la_fenetre_ne_sert_qu_une_fois():
    """Il ne s'accroche pas au fil : il évite juste de laisser sa question sans suite."""
    _note_open_question(10, 99, "alors ?")
    assert _consume_open_question(10, 99) is True
    assert _consume_open_question(10, 99) is False


def test_une_question_trop_vieille_ne_declenche_plus():
    _note_open_question(10, 99, "alors ?")
    _open_questions[(10, 99)] = time.monotonic() - _OPEN_QUESTION_WINDOW_S - 1
    assert _consume_open_question(10, 99) is False


def test_les_questions_jamais_honorees_sont_purgees():
    """Le process tourne des semaines : le dict ne doit pas gonfler."""
    for uid in range(50):
        _note_open_question(10, uid, "?")
        _open_questions[(10, uid)] = time.monotonic() - _OPEN_QUESTION_WINDOW_S - 1
    _note_open_question(10, 999, "une question fraîche ?")
    assert list(_open_questions) == [(10, 999)]


def test_les_cles_texte_marchent_aussi():
    """Twitch identifie salons et utilisateurs par des chaînes."""
    _note_open_question("azrael_ttv", "12345", "tu veux quoi au juste ?")
    assert _consume_open_question("azrael_ttv", "12345") is True
