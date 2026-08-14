# tests/test_conscience_de_ses_actes.py
"""Wally sait ce qu'il vient de faire, quel que soit le canal.

Le défaut de fond, formulé par le propriétaire après un live : « quand il
affichait les bingos, je lui disais d'arrêter, mais il n'était pas conscient
qu'il les affichait ». Ses voies d'action agissaient chacune sans que les
autres en sachent rien.

Ces tests portent sur le COMPORTEMENT attendu — ce qui entre dans la trace, ce
qui n'y entre jamais, et le fait qu'elle atteigne les trois endroits où il
décide — jamais sur la façon dont c'est écrit.
"""
import time

import pytest

import bot.core.self_trace as st
from bot.core.audit_log import journal, observe_event
from bot.core.overlay_feed import OverlayFeed
from bot.intelligence.attention_agent import AttentionContext
from bot.intelligence.gate import ResponseGate
from bot.intelligence.prompts import PromptBuilder
from bot.intelligence.reasoning_agent import ReasoningAgent

_EMOTIONS_FLAT = {"anger": 0.0, "joy": 0.0, "sadness": 0.0,
                  "curiosity": 0.0, "boredom": 0.0}


# ── ce qui entre dans la trace ────────────────────────────────────────────

def test_un_widget_affiche_est_un_acte_dont_il_se_souvient():
    """Le scénario d'origine : il relançait des bingos sans voir le sien."""
    OverlayFeed().widget("bingo", cells=["a", "b"])
    bloc = st.current_self_trace_block()
    assert bloc is not None
    assert "bingo" in bloc


def test_une_reponse_twitch_dit_a_qui_il_a_repondu():
    observe_event(None, "twitch", "azraelmalef", "message_out",
                  {"target": "Kassandre"})
    bloc = st.current_self_trace_block()
    assert "Kassandre" in bloc
    assert "azraelmalef" in bloc


def test_les_deux_canaux_cohabitent_dans_la_meme_trace():
    """Répondre huit fois sur Twitch et ignorer Discord : les deux se voient
    d'un seul coup d'œil, ce qui était impossible avec six traces séparées."""
    observe_event(None, "twitch", "azraelmalef", "message_out",
                  {"target": "Kassandre"})
    observe_event(None, "discord", "Serveur/général", "message_out",
                  {"target": "Bob"})
    bloc = st.current_self_trace_block()
    assert "Twitch" in bloc and "Discord" in bloc


def test_une_action_cognitive_spontanee_se_distingue_dune_reponse():
    observe_event(None, "discord", "Serveur/chambre", "message_out",
                  {"kind": "cognitive"})
    bloc = st.current_self_trace_block()
    # « de toi-même » seul ne prouvait rien : la consigne de bas de bloc porte
    # déjà « Tu n'ouvres pas le sujet de toi-même », et le test passait avec
    # l'acte rendu comme une réponse ordinaire (trouvé par mutation).
    assert "pris la parole de toi-même" in bloc
    assert "tu as répondu" not in bloc


def test_un_outil_utilise_entre_dans_la_trace():
    """« promis je note » : ce qu'il a réellement fait doit être lisible."""
    observe_event(None, "discord", "Serveur/général", "tool_called",
                  {"tool": "create_note"})
    assert "create_note" in st.current_self_trace_block()


def test_une_reaction_sans_reponse_est_un_acte():
    observe_event(None, "discord", "Serveur/général", "gate_decision",
                  {"decision": "react", "emoji": "😂"})
    bloc = st.current_self_trace_block()
    assert "😂" in bloc


def test_une_plateforme_inconnue_entre_sans_code_neuf():
    """Le prochain canal branché ne doit pas recréer l'angle mort : il suffit
    qu'il journalise, comme le veut la convention du projet."""
    observe_event(None, "kick", "un-salon", "message_out", {"target": "Zoé"})
    bloc = st.current_self_trace_block()
    assert "Zoé" in bloc and "un-salon" in bloc


def test_journal_alimente_la_trace_meme_sans_logger_cable():
    """Un `conv_log` absent ne doit pas le rendre aveugle à ses propres actes."""
    journal(None, "voice", "Chambre à coucher", "message_out",
            target="azrael_ttv")
    assert "azrael_ttv" in st.current_self_trace_block()


def test_une_demande_vocale_ne_nomme_pas_le_salon_ou_il_ecoute():
    """La réponse part dans le chat Twitch, donc elle est publique ; le salon
    vocal d'où venait la question, lui, ne regarde personne."""
    journal(None, "voice", "Chambre à coucher", "message_out",
            target="azrael_ttv")
    bloc = st.current_self_trace_block()
    assert "Chambre" not in bloc
    assert "vocal" in bloc


# ── ce qui n'y entre JAMAIS ───────────────────────────────────────────────

def test_une_bulle_ne_laisse_pas_son_texte_dans_la_trace():
    """Une bulle peut paraphraser une phrase entendue en vocal hors diffusion,
    et ce bloc part dans TOUS ses prompts. L'acte oui, les mots non."""
    OverlayFeed().say("Azraël vient de se faire remonter les bretelles")
    bloc = st.current_self_trace_block()
    assert "bretelles" not in bloc
    assert "bulle" in bloc


def test_un_widget_ne_laisse_pas_ses_parametres_dans_la_trace():
    """Le mot du pendu, un message épinglé, les cases d'un bingo : du texte
    libre qui n'a rien à faire dans un bloc rendu sur tous les canaux."""
    OverlayFeed().widget("hangman", word="wattson", hint="ingénieure")
    bloc = st.current_self_trace_block()
    assert "wattson" not in bloc
    assert "ingénieure" not in bloc


def test_un_dm_ne_dit_ni_avec_qui_ni_ou():
    """« tu as répondu à X en DM » dans un prompt de chat Twitch révélerait
    que X lui écrit en privé."""
    observe_event(None, "discord", "dm", "message_out", {"target": "Azraël"})
    bloc = st.current_self_trace_block()
    assert "Azraël" not in bloc
    assert "DM" in bloc


def test_une_replique_jamais_publiee_nest_pas_un_acte():
    """Helix rend 200 sans publier quand la chaîne filtre. Le journal garde la
    ligne pour qu'on voie la panne ; lui ne doit pas croire qu'il a répondu."""
    observe_event(None, "twitch", "azraelmalef", "message_out",
                  {"target": "Kassandre", "published": False})
    assert st.current_self_trace_block() is None


def test_un_outil_dont_leffet_passe_par_loverlay_ne_compte_quune_fois():
    feed = OverlayFeed()
    observe_event(None, "twitch", "azraelmalef", "tool_called",
                  {"tool": "show_overlay"})
    feed.widget("bingo", cells=["a"])
    bloc = st.current_self_trace_block()
    assert "show_overlay" not in bloc
    assert bloc.count("·") == 1


# ── la fenêtre : ni noyé, ni amnésique ────────────────────────────────────

def test_deux_memes_daffilee_se_comptent_au_lieu_de_sen_ecraser_un():
    """Une spectatrice l'a remarqué avant lui : « il en a sorti deux ? »"""
    feed = OverlayFeed()
    feed.widget("meme", src="/un")
    feed.widget("meme", src="/deux")
    bloc = st.current_self_trace_block()
    assert "×2" in bloc


def test_un_acte_trop_vieux_sort_de_la_trace():
    trace = st.SelfTrace(ttl=60.0)
    trace.record("tu as ouvert un bingo")
    trace._acts[-1][0] = time.monotonic() - 3600
    assert trace.render() == ""


def test_pas_de_bloc_quand_il_na_rien_fait():
    assert st.current_self_trace_block() is None


def test_la_forme_compacte_ne_porte_pas_les_consignes():
    """Elle tourne à chaque message reçu : elle doit rester bon marché."""
    OverlayFeed().widget("bingo", cells=["a"])
    complet = st.current_self_trace_block()
    compact = st.current_self_trace_block(limit=st.COMPACT_LIMIT, compact=True)
    assert "bingo" in compact
    assert len(compact) < len(complet) / 2


def test_la_trace_ne_garde_pas_plus_que_sa_fenetre():
    trace = st.SelfTrace(max_acts=3)
    for i in range(10):
        trace.record(f"acte {i}")
    assert trace.render().count("·") == 3


def test_le_lecteur_peut_demander_moins_dactes_que_la_fenetre():
    """La porte de réponse tourne à chaque message : son plafond doit tenir
    même quand le tampon est plein."""
    trace = st.SelfTrace(max_acts=12)
    for i in range(10):
        trace.record(f"acte {i}")
    rendu = trace.render(limit=3, compact=True)
    assert rendu.count("·") == 3
    assert "acte 9" in rendu and "acte 0" not in rendu


# ── perception PASSIVE : elle ne le fait jamais parler ────────────────────

def test_agir_ne_reveille_pas_la_cadence_cognitive():
    """Un bingo ouvert ferait sinon parler Wally en boucle pendant tout le
    live. Même contrat que `stream_feed` : aucun `notify_*`."""
    from bot.intelligence.cognitive_loop import CognitiveLoop

    loop = CognitiveLoop(None, None, None)
    avant = loop._last_relevant_activity_ts
    OverlayFeed().widget("bingo", cells=["a"])
    observe_event(None, "twitch", "azraelmalef", "message_out",
                  {"target": "Kassandre"})
    assert loop._last_relevant_activity_ts == avant
    assert not loop._reveil.is_set()
    assert loop._recent_interactions == []


# ── les trois endroits où il décide ───────────────────────────────────────

def test_le_prompt_des_conversations_porte_la_trace():
    OverlayFeed().widget("bingo", cells=["a"])
    out = PromptBuilder().build_system_prompt(emotion_state=_EMOTIONS_FLAT)
    assert "Ce que TU viens de faire" in out
    assert "bingo" in out


def test_le_prompt_des_conversations_est_muet_sans_acte():
    out = PromptBuilder().build_system_prompt(emotion_state=_EMOTIONS_FLAT)
    assert "Ce que TU viens de faire" not in out


def _ctx(**kw):
    base = dict(
        emotion_state={"boredom": 0.1}, active_desires=[], active_goals=[],
        recent_thoughts=[], recent_interactions=[], time_of_day="evening",
    )
    base.update(kw)
    return AttentionContext(**base)


def _agent():
    agent = ReasoningAgent.__new__(ReasoningAgent)  # pas d'I/O constructeur
    agent._channels_text = ""
    agent._capabilities_text = ""
    agent._channel_names = {}
    return agent


def test_le_contexte_cognitif_porte_la_trace():
    """Le seul chemin qui prend des initiatives était aussi le seul aveugle à
    leur résultat."""
    OverlayFeed().widget("bingo", cells=["a"])
    assert "bingo" in _agent()._format_context(_ctx())


def test_le_contexte_cognitif_est_muet_sans_acte():
    assert "Ce que TU viens de faire" not in _agent()._format_context(_ctx())


class _LLMEspion:
    """Capture le message utilisateur soumis à la porte de réponse."""

    def __init__(self):
        self.user_msg = ""

    async def complete_structured(self, system_prompt, messages, schema,
                                  schema_name="", purpose=""):
        self.user_msg = messages[-1]["content"]
        return {"decision": "RESPOND"}


class _FactsMuets:
    async def add(self, *a, **k):
        return None


@pytest.mark.asyncio
async def test_la_porte_de_reponse_voit_ce_quil_vient_de_faire(tmp_path):
    """Elle ne voyait que le canal courant : elle laissait passer un neuvième
    aller-retour sur Twitch sans savoir qu'il ignorait la même personne
    ailleurs."""
    llm = _LLMEspion()
    gate = ResponseGate(llm, _FactsMuets(), prompts_dir=tmp_path)
    OverlayFeed().widget("bingo", cells=["a"])
    # Le message reçu ne dit PAS « bingo » : il partait tel quel dans le prompt
    # de la porte, et le test passait même sans injection (trouvé par mutation).
    await gate.decide("arrête avec ça", "discord:1", _EMOTIONS_FLAT,
                      [], [], is_mentioned=True)
    assert "bingo" in llm.user_msg


@pytest.mark.asyncio
async def test_la_porte_de_reponse_reste_muette_sans_acte(tmp_path):
    llm = _LLMEspion()
    gate = ResponseGate(llm, _FactsMuets(), prompts_dir=tmp_path)
    await gate.decide("salut", "discord:1", _EMOTIONS_FLAT, [], [],
                      is_mentioned=True)
    assert "viens de faire" not in llm.user_msg


# ── ses actions cognitives ────────────────────────────────────────────────

class _MessageBidon:
    reactions = []

    def __init__(self):
        self.reactions = []
        self.reactions_posees = []

    async def add_reaction(self, emoji):
        self.reactions_posees.append(emoji)


class _MessageRefusant(_MessageBidon):
    async def add_reaction(self, emoji):
        raise RuntimeError("permissions manquantes")


class _CanalBidon:
    def __init__(self, message):
        self._message = message

    async def fetch_message(self, _id):
        return self._message


class _BotBidon:
    def __init__(self, message):
        self._canal = _CanalBidon(message)

    def get_channel(self, _id):
        return self._canal


@pytest.mark.asyncio
async def test_une_reaction_cognitive_reussie_entre_dans_la_trace():
    """Une ACT partie de sa propre pensée est un acte comme un autre."""
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision

    dispatcher = ActionDispatcher(bot=_BotBidon(_MessageBidon()))
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="react",
        act_args={"channel_id": "1", "message_id": "2", "emoji": "\U0001f602"},
    ))
    assert "react" in st.current_self_trace_block()


@pytest.mark.asyncio
async def test_une_reaction_refusee_par_discord_nest_pas_un_acte():
    """`_react` avale son exception et repart en silence : la compter d'office
    lui ferait croire qu'il a réagi alors qu'il n'a rien fait."""
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision

    dispatcher = ActionDispatcher(bot=_BotBidon(_MessageRefusant()))
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="react",
        act_args={"channel_id": "1", "message_id": "2", "emoji": "\U0001f602"},
    ))
    assert st.current_self_trace_block() is None


@pytest.mark.asyncio
async def test_une_action_dispatchee_ne_dit_jamais_ses_arguments():
    """Une note ou un souvenir portent du texte libre : la trace part sur tous
    les canaux, seul le NOM de l'action y a sa place."""
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision

    dispatcher = ActionDispatcher()
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="create_memory",
        act_args={"content": "le mot de passe est nougat"},
    ))
    assert "nougat" not in (st.current_self_trace_block() or "")
