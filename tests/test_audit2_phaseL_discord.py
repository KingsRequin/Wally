# tests/test_audit2_phaseL_discord.py
"""Phase L du second audit : Discord.

A2-react — la passe miroir voyait le tag `[react:emoji]` et le supprimait dès
           qu'elle réécrivait quoi que ce soit.
A2-emoji — l'emoji du gate n'avait ni repli ni log : sur un mot inventé par le
           modèle, Wally ne laissait AUCUNE trace.
A2-quest — une question posée en spontané n'armait jamais de suite.
A2-boot  — deux tâches de démarrage sans référence forte ni remontée d'erreur.
A2-mots  — les réactions passives matchaient des sous-chaînes.
"""
import inspect

import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.discord.handlers import _pick_passive_emoji


# ────────────────────────────── A2-react ──────────────────────────────
def test_le_tag_de_reaction_est_extrait_avant_la_passe_miroir():
    from bot.discord import handlers

    src = inspect.getsource(handlers._respond)
    assert src.index("_parse_react_tag(reply)") < src.index("await _mirror_pass(")


def test_les_deux_chemins_traitent_le_tag_dans_le_meme_ordre():
    from bot.discord import handlers

    spont = inspect.getsource(handlers._spontaneous_respond)
    assert spont.index("_parse_react_tag(reply)") < spont.index("await _mirror_pass(")


# ────────────────────────────── A2-emoji ──────────────────────────────
def test_un_emoji_refuse_retombe_sur_l_humeur():
    from bot.discord import handlers

    src = inspect.getsource(handlers.handle_message)
    i = src.index('if decision in ("IGNORE", "DEFER", "REACT"):')
    bloc = src[i:i + 1200]
    assert "_mood_emoji(bot.emotion.get_state())" in bloc
    assert "except Exception:\n            pass" not in bloc
    # Deux tentatives : l'emoji du gate, puis le repli d'humeur.
    assert bloc.count("add_reaction(") == 2


# ────────────────────────────── A2-quest ──────────────────────────────
def test_une_question_spontanee_arme_une_suite():
    from bot.discord import handlers

    src = inspect.getsource(handlers._spontaneous_respond)
    assert "_note_open_question(message.channel.id, message.author.id, reply)" in src


# ────────────────────────────── A2-boot ──────────────────────────────
def test_les_taches_de_boot_gardent_une_reference():
    from bot.discord import bot as bot_mod

    src = inspect.getsource(bot_mod)
    assert "_fire(run_emote_description(self))" in src
    assert "_fire(run_catchup(self))" in src
    assert "self.loop.create_task(run_catchup" not in src
    assert "self.loop.create_task(run_emote_description" not in src


# ────────────────────────────── A2-mots ──────────────────────────────
@pytest.mark.parametrize("phrase", [
    "j'ai une suggestion",      # contient « gg »
    "c'est annulé",             # contient « nul »
    "je fais du jogging",
    "nulle part ailleurs",
])
def test_une_sous_chaine_ne_declenche_plus_de_reaction(phrase):
    assert _pick_passive_emoji(phrase, 0.0) is None


@pytest.mark.parametrize("phrase,attendus", [
    ("gg les gars", ("🔥", "👏")),
    ("bien joué", ("🔥", "👏")),          # entrée multi-mots, testée autrement
    ("mdr", ("😂", "💀")),
    ("putain c'est nul", ("😤", "💀")),
])
def test_les_vrais_signaux_declenchent_toujours(phrase, attendus):
    assert _pick_passive_emoji(phrase, 0.0) in attendus


def test_une_question_declenche_la_curiosite():
    assert _pick_passive_emoji("tu crois vraiment ?", 0.8) == "🤔"
    assert _pick_passive_emoji("tu crois vraiment ?", 0.1) is None
