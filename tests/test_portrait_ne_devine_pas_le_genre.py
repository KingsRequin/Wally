# tests/test_portrait_ne_devine_pas_le_genre.py
"""Le portrait ne genre personne sans un fait qui l'établisse.

Constaté en prod le 2026-08-24 : 58 des 126 portraits parlaient au féminin alors
que 3 personnes seulement avaient un fait de genre en base. Le modèle le
déduisait du pseudo, et se contredisait dans la phrase même (« toineleviking est
un joueur (…) séduite (…) elle », « Jubeii (…) père de famille (…) elle »).

La consigne seule dans le prompt ne suffisait pas : elle laissait au modèle le
soin de juger ce qui « établit » le genre. On tranche donc AVANT l'appel, sur ce
que la base affirme, et la ligne part dans le payload.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.intelligence.memory.user_modeler import UserModeler, genre_etabli


def _make(faits):
    db = MagicMock()
    db.get_users_with_recent_facts = AsyncMock(return_value=["discord:610550333042589752"])
    db.get_active_facts_for_user = AsyncMock(
        return_value=[{"content": f, "category": "FAIT"} for f in faits]
    )
    db.get_superseded_facts_for_user = AsyncMock(return_value=[])
    # Le genre passe par sa propre requête : la fabrique sert les mêmes faits.
    db.get_gender_facts_for_user = AsyncMock(
        return_value=[{"content": f, "category": "FAIT"} for f in faits]
    )
    db.get_trust_score = AsyncMock(return_value=0.5)
    db.get_love_score = AsyncMock(return_value=0.2)
    db.upsert_user_profile = AsyncMock()
    db.get_memory_username = AsyncMock(return_value="KingsRequin")
    llm = MagicMock()
    llm.complete_structured = AsyncMock(return_value={"portrait": "portrait test"})
    return UserModeler(db, llm), llm


def _payload(llm):
    return llm.complete_structured.await_args.args[1][0]["content"]


def test_aucun_fait_de_genre_rend_none():
    assert genre_etabli([{"content": "joue à Apex tous les soirs"}]) is None


def test_les_formulations_du_fact_extractor_sont_reconnues():
    assert genre_etabli([{"content": "KingsRequin est un homme (pronom il)"}]) == "masculin"
    assert genre_etabli([{"content": "kingsrequin est une femme (pronom elle)"}]) == "féminin"
    assert genre_etabli([{"content": "lilio___ est un homme (bonhomme)"}]) == "masculin"


def test_deux_faits_opposes_rendent_none():
    """Un portrait neutre est moins faux qu'un portrait qui tranche à pile ou face.

    Le cas vécu : #14897 « est une femme » (6 août) et #18462 « est un homme »
    (19 août) coexistaient, actifs tous les deux — la correction de l'intéressé
    venait du `fact_extractor`, un chemin d'écriture qui ne supersede rien.
    """
    assert genre_etabli(
        [{"content": "est une femme (pronom elle)"}, {"content": "est un homme (pronom il)"}]
    ) is None


def test_un_contenu_vide_ne_casse_rien():
    assert genre_etabli([{"content": None}, {}]) is None


@pytest.mark.asyncio
async def test_sans_fait_le_payload_interdit_les_pronoms():
    c, llm = _make(["joue à Apex", "élève des fourmis"])
    await c.refresh_profiles(since="2026-08-09T00:00:00")
    p = _payload(llm)
    assert "Genre : INCONNU" in p
    assert "n'emploie ni « il », ni « elle »" in p


@pytest.mark.asyncio
async def test_avec_un_fait_le_payload_impose_ce_genre():
    c, llm = _make(["KingsRequin est un homme (pronom il), pas une femme"])
    await c.refresh_profiles(since="2026-08-09T00:00:00")
    assert "Genre : masculin" in _payload(llm)


@pytest.mark.asyncio
async def test_la_consigne_precede_les_traits():
    """Placée après les faits, elle se lirait comme un trait parmi d'autres."""
    c, llm = _make(["élève des fourmis"])
    await c.refresh_profiles(since="2026-08-09T00:00:00")
    p = _payload(llm)
    assert p.index("Genre :") < p.index("élève des fourmis")


def test_le_prompt_renvoie_a_la_ligne_du_contexte():
    from bot.intelligence.memory.user_modeler import _PORTRAIT_PROMPT
    assert "Genre :" in _PORTRAIT_PROMPT
    assert "INCONNU" in _PORTRAIT_PROMPT


@pytest.mark.asyncio
async def test_le_genre_se_cherche_hors_du_plafond_du_portrait():
    """Les 50 faits servis au portrait sont plafonnés PAR IMPORTANCE.

    KingsRequin a 922 faits actifs : sa correction du 19 août (« est un homme »)
    n'était pas dans les 50 premiers, et le portrait est resté au féminin cinq
    jours. Le genre passe donc par une requête dédiée, sans plafond — un
    `limit=` généreux serait retombé dans le même piège en quelques semaines.
    """
    c, llm = _make(["élève des fourmis"])
    await c.refresh_profiles(since="2026-08-09T00:00:00")
    c._db.get_gender_facts_for_user.assert_awaited_once_with("discord:610550333042589752")


@pytest.mark.asyncio
async def test_un_fait_de_genre_hors_du_top_50_est_quand_meme_vu():
    """Le cas vécu, de bout en bout : le lot servi ne dit rien, la base si."""
    c, llm = _make(["élève des fourmis", "joue à Apex"])
    c._db.get_gender_facts_for_user = AsyncMock(
        return_value=[{"content": "KingsRequin est un homme (pronom il)", "category": "FAIT"}]
    )
    await c.refresh_profiles(since="2026-08-09T00:00:00")
    assert "Genre : masculin" in _payload(llm)
