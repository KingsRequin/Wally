"""La veille des questions sans réponse, jouée sur l'adaptateur Twitch.

Le chemin complet : un message qui pose une question entre au registre, mûrit,
passe devant le gate, et — si le gate dit oui — part dans le chat. Les cas
rejouent le 13/08 à 21h14, où « comment on fait pour remettre le jeu en
français depuis la maj ? » est restée sans réponse de Wally.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.intelligence import pending_question as pq
from bot.intelligence import thread_sense as ts
from bot.twitch.handlers import _spontaneous_respond_twitch, _veiller_questions

from tests.test_twitch_handlers import make_bot


@pytest.fixture(autouse=True)
def _vider_le_cooldown_spontane():
    """`_spontaneous_cooldowns` est un dict de MODULE, antérieur à ce fichier.

    Il fuite d'un test à l'autre : le premier qui déclenche une intervention
    pose un cooldown de 300 s sur le canal, et tous les suivants qui réutilisent
    le même identifiant de canal repartent bâillonnés — sans que rien ne le
    dise. Deux tests de ce fichier sont tombés là-dedans à l'écriture.
    """
    from bot.twitch.handlers import _spontaneous_cooldowns
    _spontaneous_cooldowns.clear()
    yield
    _spontaneous_cooldowns.clear()


def _bot(delai=45, oubli=300, cooldown=300, decision="RESPOND"):
    bot = make_bot()
    bot.config.bot.unanswered_question_enabled = True
    bot.config.bot.unanswered_question_delay_seconds = delai
    bot.config.bot.unanswered_question_forget_seconds = oubli
    bot.config.bot.spontaneous_cooldown_seconds = cooldown
    bot._channel_ids = {}          # chaîne maison
    bot.persona.fil_directives = {}
    bot.persona.user_directive = MagicMock(return_value=None)
    bot.emotion.get_secondary_emotions = MagicMock(return_value=[])
    bot.db.get_alias_map = AsyncMock(return_value={})
    bot.discord_bot = SimpleNamespace(response_gate=SimpleNamespace(
        decide=AsyncMock(return_value=SimpleNamespace(decision=decision, reason="motif"))
    ))
    bot.cognitive_loop = None
    return bot


_QUESTION = "comment on fait pour remettre le jeu en français depuis la maj ?"


@pytest.mark.asyncio
async def test_une_question_toute_fraiche_ne_declenche_rien():
    bot = _bot()
    await _veiller_questions(bot, "azrael_ttv", "42", _QUESTION, "nico", "777")
    bot.twitch_api.send_message.assert_not_awaited()
    assert pq.en_attente("azrael_ttv") == 1


@pytest.mark.asyncio
async def test_la_question_mure_part_dans_le_chat(monkeypatch):
    bot = _bot()
    await _veiller_questions(bot, "azrael_ttv", "42", _QUESTION, "nico", "777")
    depart = pq.time.monotonic()
    monkeypatch.setattr(pq.time, "monotonic", lambda: depart + 60)
    await _veiller_questions(bot, "azrael_ttv", "42", "autre chose", "semy", "888")
    bot.twitch_api.send_message.assert_awaited()


@pytest.mark.asyncio
async def test_un_refus_du_gate_laisse_wally_muet(monkeypatch):
    bot = _bot(decision="IGNORE")
    await _veiller_questions(bot, "azrael_ttv", "42", _QUESTION, "nico", "777")
    depart = pq.time.monotonic()
    monkeypatch.setattr(pq.time, "monotonic", lambda: depart + 60)
    await _veiller_questions(bot, "azrael_ttv", "42", "autre chose", "semy", "888")
    bot.twitch_api.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_le_gate_absent_laisse_wally_muet(monkeypatch):
    """Gate désactivé en config : ce chemin n'a pas de repli « réponds »."""
    bot = _bot()
    bot.discord_bot = SimpleNamespace(response_gate=None)
    await _veiller_questions(bot, "azrael_ttv", "42", _QUESTION, "nico", "777")
    depart = pq.time.monotonic()
    monkeypatch.setattr(pq.time, "monotonic", lambda: depart + 60)
    await _veiller_questions(bot, "azrael_ttv", "42", "autre chose", "semy", "888")
    bot.twitch_api.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_le_drapeau_de_config_coupe_toute_la_veille():
    bot = _bot()
    bot.config.bot.unanswered_question_enabled = False
    await _veiller_questions(bot, "azrael_ttv", "42", _QUESTION, "nico", "777")
    assert pq.en_attente("azrael_ttv") == 0


@pytest.mark.asyncio
async def test_une_seule_intervention_par_fenetre_de_cooldown(monkeypatch):
    """Un chat qui pose cinq questions ne doit pas déclencher cinq réponses."""
    bot = _bot()
    depart = pq.time.monotonic()
    await _veiller_questions(bot, "azrael_ttv", "42", _QUESTION, "nico", "777")
    await _veiller_questions(bot, "azrael_ttv", "42",
                             "et le serveur il ouvre à quelle heure ?", "semy", "888")
    monkeypatch.setattr(pq.time, "monotonic", lambda: depart + 60)
    await _veiller_questions(bot, "azrael_ttv", "42", "rien de spécial", "toto", "999")
    await _veiller_questions(bot, "azrael_ttv", "42", "rien non plus", "toto", "999")
    assert bot.twitch_api.send_message.await_count == 1


@pytest.mark.asyncio
async def test_l_intervention_compte_dans_le_fil_sous_l_id_de_la_personne(monkeypatch):
    """Le chemin principal indexe le fil sur l'id numérique.

    Mesurer le pseudo ici ouvrirait un second compteur pour le même
    interlocuteur, et la profondeur repartirait de zéro au message suivant —
    exactement l'angle mort qu'on vient de combler.
    """
    bot = _bot()
    await _veiller_questions(bot, "azrael_ttv", "42", _QUESTION, "nico", "777")
    depart = pq.time.monotonic()
    monkeypatch.setattr(pq.time, "monotonic", lambda: depart + 60)
    await _veiller_questions(bot, "azrael_ttv", "42", "autre chose", "semy", "888")
    assert ts.profondeur("azrael_ttv", "777") == 1
    assert ts.profondeur("azrael_ttv", "nico") == 0


@pytest.mark.asyncio
async def test_le_chemin_spontane_retire_aussi_le_tic():
    """Sans ça, il recolle le marqueur que le chemin principal vient d'ôter."""
    bot = _bot()
    for i in range(3):
        ts.note_reponse("azrael_ttv", "777", f"message numéro {i} 😄")
    bot.llm.complete = AsyncMock(return_value="il faut passer par les options 😄")
    await _spontaneous_respond_twitch(
        bot, "azrael_ttv", "42", "nico", _QUESTION, personne="777",
    )
    envoye = bot.twitch_api.send_message.await_args.kwargs["text"]
    assert envoye == "il faut passer par les options"
