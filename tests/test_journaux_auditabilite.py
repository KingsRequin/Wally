"""Rendre le comportement de Wally auditable — et ne jamais casser ce qu'on observe.

Trois analyses d'un vrai live se sont heurtées aux mêmes angles morts : l'overlay
absent des traces structurées, le filtre qui ne dit jamais ce qu'il rejette, les
silences invisibles par construction, le chemin vocal qui n'écrit presque rien,
et une pensée sans lien avec les actions qu'elle produit.

Ces tests vérifient le COMPORTEMENT du journal — ce qu'il contient et ce qu'il
refuse de contenir — jamais la forme d'une ligne d'implémentation. Et le premier
d'entre eux vérifie la règle qui prime sur toutes les autres : **une panne
d'écriture ne remonte jamais à l'appelant.**
"""
from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core import audit_log
from bot.core.audit_log import (
    ReceptionTracker, conv_log_of, journal, observe_reception, reset_reception,
)


class _Journal:
    """Un ConversationLogger de test : garde tout, ne bloque rien."""

    def __init__(self) -> None:
        self.lines: list[tuple[str, str, str, dict]] = []

    def log(self, platform, channel, event_type, /, **fields):
        self.lines.append((platform, channel, event_type, fields))

    def of(self, event_type: str) -> list[dict]:
        return [f for _p, _c, t, f in self.lines if t == event_type]

    def types(self) -> list[str]:
        return [t for _p, _c, t, _f in self.lines]


class _JournalCasse:
    """Un logger en panne : toute écriture lève."""

    def log(self, *a, **kw):
        raise RuntimeError("disque plein")


@pytest.fixture(autouse=True)
def _reception_propre():
    reset_reception()
    yield
    reset_reception()


# ── La règle qui prime : un journal ne casse jamais son sujet ────────────────

def test_une_panne_decriture_ne_remonte_jamais():
    """Logger en panne, logger absent, champ non sérialisable : rien ne lève."""
    assert journal(_JournalCasse(), "overlay", "bulles", "x", a=1) is False
    assert journal(None, "overlay", "bulles", "x", a=1) is False
    assert journal(_Journal(), "overlay", "bulles", "x", obj=object()) is True


def test_le_masquage_des_secrets_sapplique_a_lecriture():
    """Le mot d'un pendu en cours ne doit pas fuiter PAR le journal."""
    from bot.core.secret_guard import clear_secrets, guard_secret

    clear_secrets()
    guard_secret("orchidée")
    try:
        jrnl = _Journal()
        journal(jrnl, "overlay", "bulles", "essai",
                texte="le mot est orchidée", liste=["encore ORCHIDEE"],
                imbrique={"k": "orchidee !"})
        ecrit = jrnl.of("essai")[0]
        assert "orchid" not in str(ecrit).lower()
    finally:
        clear_secrets()


def test_les_champs_texte_sont_bornes():
    """Ce bot tourne 24 h/24 : un champ libre ne doit pas peser une page."""
    jrnl = _Journal()
    journal(jrnl, "overlay", "bulles", "essai", texte="a" * 100_000)
    assert len(jrnl.of("essai")[0]["texte"]) < 1000


def test_conv_log_of_prend_le_premier_disponible():
    porteur = SimpleNamespace(conv_log="LE_BON")
    assert conv_log_of(None, SimpleNamespace(), porteur) == "LE_BON"
    assert conv_log_of(None, SimpleNamespace()) is None


# ── Signal de réception ──────────────────────────────────────────────────────

def test_la_reception_compte_ce_qui_suit_dans_la_fenetre():
    suivi = ReceptionTracker(window_s=60.0)
    t0 = 1000.0
    suivi.spoke("twitch", "azrael", "trace-1", now=t0)
    suivi.heard("twitch", "azrael", "bob", "mdr", now=t0 + 5)
    suivi.heard("twitch", "azrael", "carol", "ah ouais", now=t0 + 30)
    suivi.heard("twitch", "azrael", "dave", "trop tard", now=t0 + 90)
    suivi.heard("twitch", "autre_chaine", "eve", "ailleurs", now=t0 + 5)

    assert suivi.due(now=t0 + 30) == []          # fenêtre encore ouverte
    (_plat, _chan, fiche), = suivi.due(now=t0 + 120)
    assert fiche["trace_id"] == "trace-1"
    assert fiche["replies"] == 2
    assert fiche["authors"] == ["bob", "carol"]
    assert fiche["first_delay_s"] == 5.0


def test_un_silence_total_est_une_fiche_a_zero():
    """« Personne n'a réagi » est l'information, pas une absence de fiche."""
    suivi = ReceptionTracker(window_s=60.0)
    suivi.spoke("overlay", "bulles", "trace-1", now=1000.0)
    (_p, _c, fiche), = suivi.due(now=1100.0)
    assert fiche["replies"] == 0
    assert fiche["first_delay_s"] is None


def test_observe_reception_ecrit_la_fiche_quand_la_fenetre_se_ferme():
    jrnl = _Journal()
    observe_reception(jrnl, "twitch", "azrael", "message_out", {"trace_id": "t1"})
    observe_reception(jrnl, "twitch", "azrael", "message_in",
                      {"author": "bob", "content": "salut"})
    assert jrnl.of("reception") == []
    # La fenêtre se ferme : la fiche part au prochain événement observé.
    audit_log._RECEPTION._pending[0]["ts"] -= 120
    observe_reception(jrnl, "twitch", "azrael", "message_in",
                      {"author": "carol", "content": "hep"})
    fiche, = jrnl.of("reception")
    assert fiche["trace_id"] == "t1" and fiche["replies"] == 1


# ── Overlay : ce qui monte à l'écran, et ce qui est jeté ─────────────────────

def _narrateur(jrnl, condense="Une réplique courte.", emotion=None):
    from bot.intelligence.overlay_narrator import OverlayNarrator

    llm = MagicMock()
    llm.complete = AsyncMock(return_value=condense)
    moteur = None
    if emotion is not None:
        moteur = SimpleNamespace(get_state=lambda: emotion)
    n = OverlayNarrator(MagicMock(), llm, lambda: True, conv_log=jrnl, emotion=moteur)
    n._min_interval = 0.0
    n._event_interval = 0.0
    n._overheard_interval = 0.0
    return n


@pytest.mark.asyncio
async def test_une_bulle_publiee_porte_son_declencheur_et_lhumeur():
    jrnl = _Journal()
    n = _narrateur(jrnl, emotion={"joy": 0.8, "anger": 0.1})

    dit = await n.on_thought("je me demande si le patch a changé le recul du Flatline")

    assert dit == "Une réplique courte."
    bulle, = jrnl.of("overlay_bubble")
    assert "Flatline" in bulle["entree"]          # ce qui l'a déclenchée
    assert bulle["texte"] == "Une réplique courte."
    assert bulle["source"] == "thought"
    assert bulle["emotion"]["joy"] == 0.8
    assert isinstance(bulle["condense_ms"], int)


@pytest.mark.asyncio
async def test_le_texte_rejete_est_enregistre_avec_son_motif():
    """424 « pensée sans intérêt (RIEN) » en un jour, sans jamais dire QUOI."""
    jrnl = _Journal()
    n = _narrateur(jrnl, condense="RIEN")

    assert await n.on_thought("une pensée introspective sans intérêt public") is None

    refus, = jrnl.of("overlay_rejected")
    assert "RIEN" in refus["motif"]
    assert "introspective" in refus["entree"]
    assert jrnl.of("overlay_bubble") == []


@pytest.fixture
def _vocal_diffuse(monkeypatch):
    """La parole vocale est diffusée au live (donc consignable)."""
    import bot.intelligence.overlay_narrator as narrator_mod

    monkeypatch.setattr(narrator_mod, "_vocal_diffuse", lambda: True)


@pytest.mark.asyncio
async def test_le_vocal_non_diffuse_ne_produit_aucune_bulle():
    """Le mode test de l'overlay suffit à faire passer de la parole PRIVÉE par
    `on_overheard`. Une bulle la publierait aussi sûrement qu'une citation :
    paraphraser sur un écran public reste publier.

    Ce test disait l'inverse jusqu'au 2026-08-14 — il exigeait qu'une bulle
    parte, en se contentant de vérifier que le JOURNAL, lui, était caviardé.
    """
    jrnl = _Journal()
    n = _narrateur(jrnl, condense="Ils parlent de leur boulot.")

    dit = await n.on_overheard("Azraël (vocal) : mon salaire c'est 2400 net")

    assert dit is None
    assert jrnl.of("overlay_bubble") == []
    n._feed.say.assert_not_called()
    # Le refus est compté, pas silencieux : il repart avec la prochaine ligne.
    assert n._budget_refus == {"vocal non diffusé": 1}


@pytest.mark.asyncio
async def test_le_vocal_diffuse_est_consigne_en_clair(_vocal_diffuse):
    """Pendant un live, ce vocal est déjà entendu par les viewers."""
    jrnl = _Journal()
    n = _narrateur(jrnl, condense="Il compte ses chutes comme des trophées.")

    await n.on_overheard("Azraël (vocal) : j'ai encore raté le saut")

    bulle, = jrnl.of("overlay_bubble")
    assert "raté le saut" in bulle["entree"]
    assert bulle["texte"] == "Il compte ses chutes comme des trophées."


@pytest.mark.asyncio
async def test_une_replique_deja_dite_est_enregistree_avec_son_candidat(_vocal_diffuse):
    """« Déjà dit » est un verdict sur le TEXTE : sans lui, on ne peut rien juger."""
    jrnl = _Journal()
    n = _narrateur(jrnl, condense="Le chat s'emballe pour rien.")

    await n.on_overheard("Bob (vocal) : ça part en cacahuète")
    await n.on_overheard("Carol (vocal) : ça part vraiment en cacahuète")

    refus = [r for r in jrnl.of("overlay_rejected") if r["motif"] == "déjà dit"]
    assert len(refus) == 1
    assert refus[0]["candidat"] == "Le chat s'emballe pour rien."


@pytest.mark.asyncio
async def test_les_refus_de_budget_sont_comptes_pas_ecrits_un_par_un(_vocal_diffuse):
    """`on_overheard` passe à CHAQUE phrase du live : une ligne par refus
    noierait le journal sous le bruit qu'il sert à écarter."""
    jrnl = _Journal()
    n = _narrateur(jrnl)
    n._overheard_interval = 3600.0      # tout est refusé sauf la première

    for i in range(5):
        await n.on_overheard(f"Bob (vocal) : phrase {i}")

    assert len(jrnl.of("overlay_rejected")) == 0
    bulle, = jrnl.of("overlay_bubble")
    # La première passe ; les quatre suivantes sont comptées, pas écrites…
    assert bulle["budget_ignores"] == {}
    n._min_interval = 3600.0
    await n.on_thought("une pensée de plus")
    assert sum(n._budget_refus.values()) == 5


@pytest.mark.asyncio
async def test_un_journal_en_panne_nempeche_pas_la_bulle():
    """La règle qui prime, vérifiée sur le chemin le plus chaud."""
    n = _narrateur(_JournalCasse())
    assert await n.on_thought("une pensée") == "Une réplique courte."
    n._feed.think_aloud.assert_called_once()


@pytest.mark.asyncio
async def test_le_chat_qui_suit_une_bulle_est_compte():
    """Le seul retour spectateur exploitable d'un live."""
    jrnl = _Journal()
    n = _narrateur(jrnl)

    await n.on_thought("une pensée")
    await n.on_chat_message("bob", "mdr le bot")
    audit_log._RECEPTION._pending[0]["ts"] -= 120
    await n.on_chat_message("carol", "hep")

    fiche, = jrnl.of("reception")
    assert fiche["replies"] == 1 and fiche["authors"] == ["bob"]


# ── Vocal : la demande, les outils, la réponse, les temps ───────────────────

def _bot_vocal(jrnl):
    twitch_bot = SimpleNamespace(
        conv_log=jrnl,
        llm=SimpleNamespace(complete_with_tools=AsyncMock(
            return_value=("C'est noté.", []))),
        twitch_api=SimpleNamespace(send_message=AsyncMock(return_value=True)),
    )
    bot = SimpleNamespace(
        conv_log=jrnl,
        _twitch_bot=twitch_bot,
        overlay_narrator=SimpleNamespace(is_active=lambda: True),
        config=SimpleNamespace(
            bot=SimpleNamespace(name="Wally", trigger_names=[]),
            voice=SimpleNamespace(requesters=[
                {"discord_id": "42", "twitch_login": "azrael"}]),
        ),
    )
    return bot


@pytest.fixture
def _diffusion_ouverte(monkeypatch):
    """Le salon 7 est diffusé au live ; tout le reste ne l'est pas."""
    import bot.discord.voice.request as request_mod

    monkeypatch.setattr(request_mod, "voice_is_broadcast", lambda cid: cid == 7)


@pytest.mark.asyncio
async def test_une_demande_vocale_laisse_une_trace_complete(_diffusion_ouverte):
    """« promis je note » sans rien noter : indétectable avant ce journal."""
    from bot.discord.voice.request import handle_voice_request

    jrnl = _Journal()
    bot = _bot_vocal(jrnl)

    async def _avec_outil(system, messages, tools, executor, **kw):
        await executor("remember", '{"fact": "Lilio est un homme"}')
        return ("C'est noté.", [])

    bot._twitch_bot.llm.complete_with_tools = AsyncMock(side_effect=_avec_outil)
    executed = AsyncMock(return_value='{"status": "ok"}')

    import bot.twitch.handlers as th
    original = th.make_tool_executor
    th.make_tool_executor = lambda *a, **kw: executed
    try:
        await handle_voice_request(
            bot, "42", "Azraël", "Wally, Lilio c'est un homme",
            channel_id=7, channel_name="stream", stt_ms=1200.0,
        )
    finally:
        th.make_tool_executor = original

    entree, = jrnl.of("message_in")
    assert entree["content"] == "Wally, Lilio c'est un homme"
    assert entree["author"] == "Azraël"
    appel, = jrnl.of("tool_called")
    assert appel["tool"] == "remember"
    resultat, = jrnl.of("tool_result")
    assert "ok" in resultat["result"]
    sortie, = jrnl.of("message_out")
    assert sortie["content"] == "C'est noté."
    # Le délai perçu court depuis la FIN DE LA PHRASE, transcription comprise.
    assert sortie["stt_ms"] == 1200
    assert sortie["total_ms"] >= 1200
    assert appel["trace_id"] == entree["trace_id"] == sortie["trace_id"]


@pytest.mark.asyncio
async def test_le_vocal_hors_diffusion_nentre_dans_aucun_journal(_diffusion_ouverte):
    """La confidentialité se joue à l'écriture : hors live, RIEN n'est écrit —
    pas même le nom de qui parlait."""
    from bot.discord.voice.request import handle_voice_request

    jrnl = _Journal()
    bot = _bot_vocal(jrnl)

    await handle_voice_request(
        bot, "42", "Azraël", "Wally, un secret entre nous",
        channel_id=999, channel_name="prive", stt_ms=800.0,
    )

    assert jrnl.lines == []
    # La réponse, elle, part quand même : le journal n'est pas une garde métier.
    bot._twitch_bot.twitch_api.send_message.assert_awaited()


@pytest.mark.asyncio
async def test_une_demande_vocale_sans_reponse_dit_pourquoi(_diffusion_ouverte):
    from bot.discord.voice.request import handle_voice_request

    jrnl = _Journal()
    bot = _bot_vocal(jrnl)
    bot._twitch_bot.llm.complete_with_tools = AsyncMock(return_value=("", []))

    await handle_voice_request(bot, "42", "Azraël", "Wally tu fais quoi",
                               channel_id=7, channel_name="stream")

    silence, = jrnl.of("gate_decision")
    assert silence["decision"] == "silence"
    assert "vide" in silence["reason"]
    assert jrnl.of("message_out") == []


# ── Vocal : les quasi-déclenchements ────────────────────────────────────────

@pytest.mark.parametrize("phrase, mot, regle", [
    ("passe-moi la balle", "balle", "jamais son nom"),
    ("il est dans la salle", "salle", "jamais son nom"),
    ("regarde la vallée", "vallee", "initiale différente"),
])
def test_un_mot_qui_frole_son_nom_est_nomme(phrase, mot, regle):
    """La détection répondait « non » en silence : rien ne disait si la
    tolérance était trop serrée ou trop lâche."""
    from bot.discord.voice.request import address_match

    verdict = address_match(phrase, ["wally"])
    assert verdict.addressed is False
    assert verdict.word == mot
    assert verdict.rule == regle


@pytest.mark.parametrize("phrase", ["wally tu fais quoi", "wallis tu dors", "eh walli"])
def test_ce_qui_le_nomme_le_nomme_toujours(phrase):
    from bot.discord.voice.request import address_match, is_addressed

    assert is_addressed(phrase, ["wally"]) is True
    assert address_match(phrase, ["wally"]).addressed is True


def test_une_phrase_sans_rapport_ne_produit_aucun_quasi():
    from bot.discord.voice.request import address_match

    verdict = address_match("on mange des pâtes ce soir", ["wally"])
    assert verdict.addressed is False and verdict.word == ""


def test_le_quasi_declenchement_respecte_la_frontiere_de_diffusion(monkeypatch):
    import bot.discord.voice.request as request_mod

    jrnl = _Journal()
    bot = _bot_vocal(jrnl)
    monkeypatch.setattr(request_mod, "voice_is_broadcast", lambda cid: cid == 7)

    request_mod.journal_near_miss(bot, 999, "prive", "Azraël",
                                  "passe-moi la balle", ["wally"])
    assert jrnl.lines == []

    request_mod.journal_near_miss(bot, 7, "stream", "Azraël",
                                  "passe-moi la balle", ["wally"])
    quasi, = jrnl.of("voice_near_miss")
    assert quasi["word"] == "balle" and quasi["speaker"] == "Azraël"


# ── Silences sur Twitch ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_un_message_twitch_sans_reponse_laisse_une_decision(monkeypatch):
    """479 messages sans réponse sur un live, et aucun événement pour eux."""
    from tests.test_twitch_handlers import make_bot, make_payload
    from bot.twitch.handlers import handle_message

    monkeypatch.setenv("TWITCH_BOT_NICK", "wallybot")
    jrnl = _Journal()
    bot = make_bot(trigger_names=["wally"])
    bot.conv_log = jrnl

    await handle_message(bot, make_payload(content="salut les gens"))

    gate, = jrnl.of("gate_decision")
    assert gate["decision"] == "silence"
    assert gate["reason"] == "non interpellé"
    assert gate["trace_id"] == jrnl.of("message_in")[0]["trace_id"]


@pytest.mark.asyncio
async def test_une_reponse_twitch_dit_aussi_pourquoi(monkeypatch):
    from tests.test_twitch_handlers import make_bot, make_payload
    from bot.twitch.handlers import handle_message

    monkeypatch.setenv("TWITCH_BOT_NICK", "wallybot")
    jrnl = _Journal()
    bot = make_bot(trigger_names=["wally"])
    bot.conv_log = jrnl

    await handle_message(bot, make_payload(content="wally ça va ?"))

    gate = jrnl.of("gate_decision")[0]
    assert gate["decision"] == "respond" and gate["reason"]


# ── Pensée → action ─────────────────────────────────────────────────────────

def _dispatcher(feed=None, facts=None, bot=None):
    from bot.intelligence.action_dispatcher import ActionDispatcher

    return ActionDispatcher(bot=bot, feed=feed, fact_store=facts)


class _Feed:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def publish(self, event):
        self.events.append(event)


@pytest.mark.asyncio
async def test_une_action_porte_lidentifiant_de_la_pensee():
    """think et act étaient deux lignes voisines sans rien qui les relie."""
    from bot.intelligence.meta_agent import MetaDecision

    feed = _Feed()
    facts = SimpleNamespace(add=AsyncMock())
    disp = _dispatcher(feed=feed, facts=facts)

    await disp.dispatch(MetaDecision(
        action="ACT", act_name="create_memory",
        act_args={"fact_content": "le patch a changé le Flatline"},
        thought_id="think:abc",
    ))

    act, = [e for e in feed.events if e["type"] == "ACT"]
    assert act["thought_id"] == "think:abc"


@pytest.mark.asyncio
async def test_une_action_qui_ne_produit_rien_est_journalisee():
    """20 % des actions décidées ne laissaient AUCUNE trace."""
    from bot.intelligence.meta_agent import MetaDecision

    jrnl = _Journal()
    feed = _Feed()
    facts = SimpleNamespace(add=AsyncMock())
    disp = _dispatcher(feed=feed, facts=facts, bot=SimpleNamespace(conv_log=jrnl))

    # Argument manquant : la branche existe mais se tait.
    await disp.dispatch(MetaDecision(action="ACT", act_name="create_memory",
                                     act_args={}, thought_id="think:1"))
    # Outil que le dispatcher ne connaît pas du tout.
    await disp.dispatch(MetaDecision(action="ACT", act_name="fais_le_cafe",
                                     act_args={"x": 1}, thought_id="think:1"))

    silencieuse, inconnue = jrnl.of("act_rejected")
    assert silencieuse["act_name"] == "create_memory"
    assert "silencieuse" in silencieuse["reason"]
    assert inconnue["reason"] == "outil inconnu"
    assert silencieuse["thought_id"] == inconnue["thought_id"] == "think:1"
    assert [e for e in feed.events if e["type"] == "ACT"] == []


@pytest.mark.asyncio
async def test_une_action_aboutie_nest_pas_comptee_comme_rejetee():
    from bot.intelligence.meta_agent import MetaDecision

    jrnl = _Journal()
    facts = SimpleNamespace(add=AsyncMock())
    disp = _dispatcher(feed=_Feed(), facts=facts,
                       bot=SimpleNamespace(conv_log=jrnl))

    await disp.dispatch(MetaDecision(action="ACT", act_name="create_goal",
                                     act_args={"description": "finir le patch note"}))

    assert jrnl.of("act_rejected") == []


@pytest.mark.asyncio
async def test_la_pensee_porte_son_identifiant_et_son_humeur():
    from bot.intelligence.cognitive_loop import CognitiveLoop
    from bot.intelligence.meta_agent import MetaDecision

    class _Attention:
        async def build_context(self, *a, **kw):
            return SimpleNamespace()

    decisions = [MetaDecision(action="ACT", act_name="create_memory",
                              act_args={"fact_content": "x"})]

    class _Reasoning:
        async def reason(self, context):
            return SimpleNamespace(thought_text="une vraie pensée",
                                   decisions=decisions, thought_fact_id=None)

    class _Dispatcher:
        def __init__(self):
            self.vus = []

        async def dispatch(self, decision):
            self.vus.append(decision)

    feed, disp = _Feed(), _Dispatcher()
    loop = CognitiveLoop(
        _Attention(), _Reasoning(), disp, feed=feed,
        emotion_engine=SimpleNamespace(get_state=lambda: {"curiosity": 0.6}),
    )
    loop._last_relevant_activity_ts = time.monotonic()

    await loop._tick()

    think, = [e for e in feed.events if e["type"] == "THINK"]
    decide, = [e for e in feed.events if e["type"] == "DECIDE"]
    assert think["thought_id"]
    assert think["emotion"] == {"curiosity": 0.6}
    # L'identifiant voyage jusqu'à l'action, sans quoi on ne sait pas laquelle
    # vient de quel raisonnement.
    assert decide["thought_id"] == think["thought_id"]
    assert disp.vus[0].thought_id == think["thought_id"]
