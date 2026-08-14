"""Wally doit RECONNAÎTRE ses propres réponses dans son contexte cognitif.

Le mécanisme existait : `notify_reply` inscrit ce qu'il vient d'envoyer dans
`recent_interactions` avec un drapeau `is_self`. Mais rien, dans le contexte
rendu, ne le désignait comme sien : sa réponse arrivait sous son pseudo, une
ligne comme une autre au milieu des autres.

Le 13/08 à 21:36, il pensait « je ne peux pas réellement écrire dans le chat en
ce moment » alors qu'il répondait à trois personnes toutes les vingt secondes —
et ses trois réponses étaient dans ce même contexte. Voir qu'il vient de parler
est le contre-exemple le moins cher.
"""
from bot.intelligence.attention_agent import AttentionContext
from bot.intelligence.reasoning_agent import ReasoningAgent


def _ctx(**kw):
    base = dict(
        emotion_state={"boredom": 0.1}, active_desires=[], active_goals=[],
        recent_thoughts=[], recent_interactions=[], time_of_day="night",
    )
    base.update(kw)
    return AttentionContext(**base)


def _agent(speak_enabled: bool = False):
    agent = ReasoningAgent.__new__(ReasoningAgent)  # pas d'I/O constructeur
    agent._channels_text = ""
    agent._capabilities_text = ""
    agent._channel_names = {"42": "général"}
    agent._speak_enabled = speak_enabled
    return agent


_ECHANGE = [
    {"channel": "42", "author": "Rina", "content": "wally tu penses quoi de moi ?"},
    {"channel": "42", "author": "Wally", "content": "que t'es infernale, et c'est un compliment",
     "is_self": True},
]


def test_ses_reponses_sont_designees_comme_siennes():
    texte = _agent()._format_context(_ctx(recent_interactions=list(_ECHANGE)))

    ligne = next(l for l in texte.splitlines() if "infernale" in l)
    assert "TOI" in ligne, f"rien ne dit que c'est lui qui a écrit ça :\n{ligne}"


def test_les_messages_des_autres_restent_a_leur_nom():
    texte = _agent()._format_context(_ctx(recent_interactions=list(_ECHANGE)))

    ligne = next(l for l in texte.splitlines() if "tu penses quoi" in l)
    assert "TOI" not in ligne
    assert "Rina" in ligne


def test_le_contenu_de_sa_reponse_reste_lisible():
    texte = _agent()._format_context(_ctx(recent_interactions=list(_ECHANGE)))
    assert "que t'es infernale, et c'est un compliment" in texte


def test_sans_initiative_le_contexte_nenseigne_plus_la_syntaxe_de_speak():
    """Le système retire l'enseignement de `[SPEAK]` ; ce rappel-là vivait dans
    le message USER et passait à travers."""
    texte = _agent(speak_enabled=False)._format_context(
        _ctx(recent_interactions=list(_ECHANGE))
    )
    assert "[SPEAK" not in texte
    assert "42" in texte, "il doit toujours savoir quel canal est actif"


def test_avec_initiative_le_canal_cible_est_toujours_donne():
    texte = _agent(speak_enabled=True)._format_context(
        _ctx(recent_interactions=list(_ECHANGE))
    )
    assert "[SPEAK" in texte
