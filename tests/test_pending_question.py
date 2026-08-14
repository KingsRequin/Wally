"""Les questions posées au chat que personne ne relève.

Le 13/08, 89 réponses sur 89 partaient d'une mention explicite de son nom.
À 21h14 : « comment on fait pour remettre le jeu en français depuis la maj ? ».
Le chat a répondu « utilise Duolingo », Wally s'est tu.

Ce n'est PAS le retour de la parole spontanée : la brèche est étroite, et le
`ResponseGate` garde le dernier mot.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.intelligence import pending_question as pq


@pytest.fixture(autouse=True)
def _repartir_a_neuf():
    pq.oublier_tout()
    yield
    pq.oublier_tout()


def _gate(decision, reason="parce que"):
    faux = SimpleNamespace()
    faux.decide = AsyncMock(return_value=SimpleNamespace(decision=decision, reason=reason))
    return faux


# ── ce qui compte comme une question ──────────────────────────────────────

@pytest.mark.parametrize("texte, retenue", [
    ("comment on fait pour remettre le jeu en français depuis la maj ?", True),
    ("quelqu'un sait à quelle heure commence le stream ?", True),
    ("quoi ?", False),                       # ponctuation de conversation
    ("hein ?", False),
    ("il a encore raté son saut", False),    # pas une question
    ("@KingsRequin tu viens jouer ou pas ?", False),   # déjà adressée
    ("https://klipy.com/gifs/rat-cool ?", False),      # un lien et rien d'autre
    # La moitié des messages Discord du 13/08 sont des GIF nus. Un lien est UN
    # jeton quoi qu'il pèse : le compter comme de la matière ferait passer
    # « <gif> c'est quoi ça ? » pour une vraie demande.
    ("https://tenor.com/view/cat-looking-around-gif-22814538 c'est quoi ça ?", False),
    ("", False),
])
def test_ce_qui_entre_au_registre(texte, retenue):
    assert pq.ressemble_a_une_question(texte) is retenue
    assert pq.noter("live", "nico", texte) is retenue


# ── maturation ────────────────────────────────────────────────────────────

def test_une_question_toute_fraiche_n_est_pas_relevee():
    pq.noter("live", "nico", "quelqu'un sait comment repasser le jeu en français ?")
    assert pq.relever("live", delai_s=45, oubli_s=300) is None
    assert pq.en_attente("live") == 1


def test_la_question_mure_est_relevee_avec_son_age(monkeypatch):
    pq.noter("live", "nico", "quelqu'un sait comment repasser le jeu en français ?")
    depart = pq.time.monotonic()
    monkeypatch.setattr(pq.time, "monotonic", lambda: depart + 60)
    relevee = pq.relever("live", delai_s=45, oubli_s=300)
    assert relevee is not None
    assert relevee["auteur"] == "nico"
    assert 55 <= relevee["age_s"] <= 65


def test_une_question_relevee_ne_ressort_jamais_deux_fois(monkeypatch):
    """Sinon un refus du gate se rejoue à chaque message du canal."""
    pq.noter("live", "nico", "quelqu'un sait comment repasser le jeu en français ?")
    depart = pq.time.monotonic()
    monkeypatch.setattr(pq.time, "monotonic", lambda: depart + 60)
    assert pq.relever("live", delai_s=45, oubli_s=300) is not None
    assert pq.relever("live", delai_s=45, oubli_s=300) is None
    assert pq.en_attente("live") == 0


def test_une_question_trop_vieille_est_oubliee_sans_etre_relevee(monkeypatch):
    pq.noter("live", "nico", "quelqu'un sait comment repasser le jeu en français ?")
    depart = pq.time.monotonic()
    monkeypatch.setattr(pq.time, "monotonic", lambda: depart + 999)
    assert pq.relever("live", delai_s=45, oubli_s=300) is None
    assert pq.en_attente("live") == 0


def test_la_plus_ancienne_passe_la_premiere(monkeypatch):
    depart = pq.time.monotonic()
    pq.noter("live", "nico", "première question du chat, celle-là ?")
    monkeypatch.setattr(pq.time, "monotonic", lambda: depart + 10)
    pq.noter("live", "semy", "seconde question du chat, celle-ci ?")
    monkeypatch.setattr(pq.time, "monotonic", lambda: depart + 60)
    assert pq.relever("live", delai_s=45, oubli_s=300)["auteur"] == "nico"


def test_les_canaux_ne_se_melangent_pas():
    pq.noter("live", "nico", "quelqu'un sait comment faire ça ?")
    assert pq.en_attente("live") == 1
    assert pq.en_attente("discussions") == 0


def test_la_charge_voyage_avec_la_question(monkeypatch):
    """Côté Discord, le message d'origine — sans lui, pas de réponse en citation."""
    sentinelle = object()
    pq.noter("salon", "nico", "quelqu'un sait comment faire ça ?", charge=sentinelle)
    depart = pq.time.monotonic()
    monkeypatch.setattr(pq.time, "monotonic", lambda: depart + 60)
    assert pq.relever("salon", delai_s=45, oubli_s=300)["charge"] is sentinelle


# ── la décision revient au gate ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_le_gate_peut_faire_taire_wally():
    question = {"texte": "et le jeu en français ?", "age_s": 60.0}
    repondre, motif = await pq.le_gate_veut_repondre(
        _gate("IGNORE", "le chat a déjà répondu"),
        question, auteur_uid="twitch:nico", emotion_state={"joy": 0.3},
    )
    assert repondre is False
    assert "déjà répondu" in motif


@pytest.mark.asyncio
async def test_le_gate_peut_le_faire_parler():
    question = {"texte": "et le jeu en français ?", "age_s": 60.0}
    repondre, _ = await pq.le_gate_veut_repondre(
        _gate("RESPOND"), question,
        auteur_uid="twitch:nico", emotion_state={"joy": 0.3},
    )
    assert repondre is True


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["REACT", "DEFER"])
async def test_un_emoji_ou_un_plus_tard_ne_valent_pas_prise_de_parole(decision):
    """Personne n'attend un emoji de quelqu'un qu'il n'a pas sollicité."""
    question = {"texte": "et le jeu en français ?", "age_s": 60.0}
    repondre, _ = await pq.le_gate_veut_repondre(
        _gate(decision), question,
        auteur_uid="twitch:nico", emotion_state={"joy": 0.3},
    )
    assert repondre is False


@pytest.mark.asyncio
async def test_sans_gate_wally_se_tait():
    question = {"texte": "et le jeu en français ?", "age_s": 60.0}
    repondre, _ = await pq.le_gate_veut_repondre(
        None, question, auteur_uid="twitch:nico", emotion_state={},
    )
    assert repondre is False


@pytest.mark.asyncio
async def test_une_panne_du_gate_ne_le_fait_pas_parler():
    """À l'inverse du chemin « on t'a appelé », où le repli est RESPOND.

    Une panne ne doit pas ouvrir la bouche de Wally là où personne ne lui a
    rien demandé.
    """
    casse = SimpleNamespace(decide=AsyncMock(side_effect=RuntimeError("502")))
    question = {"texte": "et le jeu en français ?", "age_s": 60.0}
    repondre, motif = await pq.le_gate_veut_repondre(
        casse, question, auteur_uid="twitch:nico", emotion_state={},
    )
    assert repondre is False
    assert "502" in motif


@pytest.mark.asyncio
async def test_le_gate_recoit_l_age_et_le_fil():
    """Sans eux, il ne peut pas juger si quelqu'un a déjà répondu."""
    gate = _gate("IGNORE")
    fil = [{"author": "aze", "content": "utilise Duolingo"}]
    await pq.le_gate_veut_repondre(
        gate, {"texte": "et le jeu en français ?", "age_s": 62.0},
        auteur_uid="twitch:nico", emotion_state={}, fil=fil,
    )
    appel = gate.decide.await_args.kwargs
    assert appel["unanswered_question_age_s"] == 62.0
    assert appel["recent_messages"] == fil
    assert appel["is_triggered"] is False and appel["is_mentioned"] is False


# ── le gate sait qu'il s'agit d'une question laissée en l'air ─────────────

@pytest.mark.asyncio
async def test_le_gate_nomme_ce_qui_l_a_reveille():
    """Un prompt qui ment sur ce qui l'a réveillé produit des réponses hors-sol.

    Précédent du projet : les faux raids annoncés par l'overlay.
    """
    from bot.intelligence.gate import ResponseGate

    llm = SimpleNamespace(complete_structured=AsyncMock(return_value={"decision": "IGNORE"}))
    gate = ResponseGate(llm, fact_store=SimpleNamespace(add=AsyncMock()))
    await gate.decide(
        message_content="et le jeu en français ?",
        author_user_id="twitch:nico",
        emotion_state={"joy": 0.3},
        relationship_facts=[], active_desires=[],
        unanswered_question_age_s=62.0,
    )
    envoye = llm.complete_structured.await_args.kwargs["messages"][0]["content"]
    assert "62" in envoye
    assert "passif" not in envoye.lower()


@pytest.mark.asyncio
async def test_hors_de_ce_chemin_le_message_reste_passif():
    from bot.intelligence.gate import ResponseGate

    llm = SimpleNamespace(complete_structured=AsyncMock(return_value={"decision": "IGNORE"}))
    gate = ResponseGate(llm, fact_store=SimpleNamespace(add=AsyncMock()))
    await gate.decide(
        message_content="il a encore raté son saut",
        author_user_id="twitch:nico",
        emotion_state={"joy": 0.3},
        relationship_facts=[], active_desires=[],
    )
    envoye = llm.complete_structured.await_args.kwargs["messages"][0]["content"]
    assert "passif" in envoye.lower()


@pytest.mark.asyncio
async def test_la_profondeur_du_fil_arrive_au_gate():
    from bot.intelligence.gate import ResponseGate

    llm = SimpleNamespace(complete_structured=AsyncMock(return_value={"decision": "IGNORE"}))
    gate = ResponseGate(llm, fact_store=SimpleNamespace(add=AsyncMock()))
    await gate.decide(
        message_content="et sinon ?",
        author_user_id="twitch:kassandre",
        emotion_state={"joy": 0.3},
        relationship_facts=[], active_desires=[],
        is_triggered=True, thread_depth=11,
    )
    envoye = llm.complete_structured.await_args.kwargs["messages"][0]["content"]
    assert "11 fois d'affilée" in envoye


@pytest.mark.asyncio
async def test_un_premier_echange_ne_parle_pas_de_profondeur():
    from bot.intelligence.gate import ResponseGate

    llm = SimpleNamespace(complete_structured=AsyncMock(return_value={"decision": "IGNORE"}))
    gate = ResponseGate(llm, fact_store=SimpleNamespace(add=AsyncMock()))
    await gate.decide(
        message_content="salut wally",
        author_user_id="twitch:kassandre",
        emotion_state={"joy": 0.3},
        relationship_facts=[], active_desires=[],
        is_triggered=True, thread_depth=1,
    )
    envoye = llm.complete_structured.await_args.kwargs["messages"][0]["content"]
    assert "d'affilée" not in envoye


# ── branchement des deux adaptateurs ──────────────────────────────────────

@pytest.mark.parametrize("module", ["bot.discord.handlers", "bot.twitch.handlers"])
def test_les_deux_adaptateurs_veillent(module):
    """92 messages Discord contre 568 Twitch le 13/08, et une seule réponse d'un
    côté contre 89 de l'autre : brancher la veille d'un seul côté referait
    exactement le défaut qu'on corrige."""
    import importlib
    import inspect

    source = inspect.getsource(importlib.import_module(module))
    # L'APPEL, pas la définition : chercher « _veiller_questions( » tout court
    # trouvait le `async def` et laissait passer un handler qui ne l'appelle
    # jamais — la veille pouvait être débranchée sans qu'un test bronche.
    assert "_fire(_veiller_questions(" in source
    assert "pending_question.noter(" in source
    assert "le_gate_veut_repondre(" in source
