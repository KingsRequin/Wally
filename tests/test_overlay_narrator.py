"""OverlayNarrator — budget de parole et condensation des pensées.

Le risque du projet est produit : un compagnon qui commente sans arrêt devient
insupportable, et un overlay ne se scrolle pas. Le budget doit donc REFUSER,
pas seulement être suggéré dans un prompt.
"""
from unittest.mock import AsyncMock

import pytest

from bot.core.overlay_feed import OverlayFeed
from bot.intelligence.overlay_narrator import OverlayNarrator


def _narrator(live=True, reply="je m'ennuie ferme", interval=90.0):
    feed = OverlayFeed()
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=reply)
    return OverlayNarrator(feed, llm, lambda: live, min_interval_s=interval), feed, llm


# ── hors live ──

@pytest.mark.asyncio
async def test_rien_ne_sort_hors_live():
    """Personne ne regarde : ni bulle, ni appel LLM payé pour rien."""
    n, feed, llm = _narrator(live=False)
    q = feed.subscribe()
    assert await n.on_thought("une longue pensée introspective") is None
    llm.complete.assert_not_awaited()
    assert q.empty()


@pytest.mark.asyncio
async def test_une_sonde_de_live_cassee_fait_taire():
    """En cas de doute sur l'état du stream, on se tait."""
    feed = OverlayFeed()
    llm = AsyncMock()
    def _boom():
        raise RuntimeError("API twitch HS")
    n = OverlayNarrator(feed, llm, _boom)
    assert await n.on_thought("pensée") is None
    llm.complete.assert_not_awaited()


# ── budget ──

@pytest.mark.asyncio
async def test_le_budget_refuse_la_deuxieme_bulle():
    n, feed, llm = _narrator()
    assert await n.on_thought("première pensée") is not None
    assert await n.on_thought("deuxième pensée") is None   # trop tôt
    assert llm.complete.await_count == 1                    # pas payé pour rien


@pytest.mark.asyncio
async def test_le_creneau_est_reserve_avant_la_condensation():
    """Deux pensées quasi simultanées ne doivent pas passer toutes les deux
    pendant que la première attend encore le LLM."""
    n, feed, llm = _narrator()
    slow = []

    async def _slow_complete(*a, **kw):
        slow.append(1)
        if len(slow) == 1:
            assert n._may_speak() is False   # créneau déjà pris
        return "ok court"

    llm.complete = _slow_complete
    await n.on_thought("pensée")
    assert len(slow) == 1


@pytest.mark.asyncio
async def test_le_budget_se_libere_apres_l_intervalle():
    n, _, _ = _narrator(interval=0.0)
    assert await n.on_thought("une") is not None
    assert await n.on_thought("deux") is not None


# ── condensation ──

@pytest.mark.asyncio
async def test_la_pensee_publiee_est_une_bulle_de_pensee():
    n, feed, _ = _narrator(reply="personne parle, je m'ennuie")
    q = feed.subscribe()
    await n.on_thought("longue rumination sur le silence du serveur")

    kinds = []
    while not q.empty():
        kinds.append(q.get_nowait())
    thinking = [e for e in kinds if e["type"] == "thinking"]
    bubbles = [e for e in kinds if e["type"] == "bubble"]
    assert thinking and thinking[0]["active"] is True     # les trois points d'abord
    assert bubbles[0]["mode"] == "thought"
    assert bubbles[0]["text"] == "personne parle, je m'ennuie"


@pytest.mark.asyncio
async def test_rien_a_dire_eteint_les_points():
    """Le prompt répond RIEN quand la pensée n'intéresse pas un spectateur."""
    n, feed, _ = _narrator(reply="RIEN")
    q = feed.subscribe()
    assert await n.on_thought("méta-rumination sur ma propre nature") is None
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert [e["active"] for e in events if e["type"] == "thinking"] == [True, False]
    assert not [e for e in events if e["type"] == "bubble"]


@pytest.mark.asyncio
async def test_une_condensation_trop_longue_est_rejetee():
    n, _, _ = _narrator(reply="mot " * 60)
    assert await n.on_thought("pensée") is None


@pytest.mark.asyncio
async def test_un_llm_en_erreur_ne_casse_rien():
    n, feed, llm = _narrator()
    llm.complete = AsyncMock(side_effect=RuntimeError("API down"))
    assert await n.on_thought("pensée") is None


@pytest.mark.asyncio
async def test_pensee_vide_ignoree():
    n, feed, llm = _narrator()
    assert await n.on_thought("   ") is None
    llm.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_les_guillemets_du_modele_sont_retires():
    n, _, _ = _narrator(reply='"je m\'ennuie ferme"')
    assert await n.on_thought("pensée") == "je m'ennuie ferme"


# ── événements du stream ──

@pytest.mark.asyncio
async def test_un_evenement_fort_fait_reagir_l_avatar():
    n, feed, _ = _narrator(reply="du monde débarque")
    q = feed.subscribe()
    assert await n.on_stream_event("Un raid de 42 personnes arrive") is not None
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert [e for e in events if e["type"] == "react"], "l'avatar n'a pas réagi"
    bubble = [e for e in events if e["type"] == "bubble"][0]
    assert bubble["mode"] == "speech"   # réaction, pas pensée


@pytest.mark.asyncio
async def test_un_evenement_neutre_ne_fait_pas_reagir_l_avatar():
    n, feed, _ = _narrator(reply="il change encore de jeu")
    q = feed.subscribe()
    await n.on_stream_event("Le jeu passe à Apex Legends")
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert not [e for e in events if e["type"] == "react"]


@pytest.mark.asyncio
async def test_un_evenement_passe_meme_si_une_pensee_vient_de_parler():
    """Se taire sur un raid parce qu'une pensée vient de passer serait absurde :
    les deux budgets sont distincts."""
    n, _, _ = _narrator()
    assert await n.on_thought("une pensée") is not None
    assert await n.on_stream_event("Un raid arrive") is not None


@pytest.mark.asyncio
async def test_une_reaction_consomme_aussi_le_budget_des_pensees():
    """Sinon une bulle de pensée s'empilerait juste derrière la réaction."""
    n, _, _ = _narrator()
    assert await n.on_stream_event("Un raid arrive") is not None
    assert await n.on_thought("une pensée dans la foulée") is None


@pytest.mark.asyncio
async def test_pas_de_reaction_hors_live():
    n, _, llm = _narrator(live=False)
    assert await n.on_stream_event("Un raid arrive") is None
    llm.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_le_budget_evenement_limite_les_rafales():
    """Une salve de subs ne doit pas produire une bulle par sub."""
    n, _, _ = _narrator()
    assert await n.on_stream_event("Un sub arrive") is not None
    assert await n.on_stream_event("Un autre sub arrive") is None


# ── widgets décidés par Wally ──

def test_un_widget_ne_s_affiche_pas_hors_live():
    n, feed, _ = _narrator(live=False)
    q = feed.subscribe()
    assert n.show_widget("coinflip", "on verra bien") is False
    assert q.empty()


def test_un_widget_inconnu_est_refuse():
    n, feed, _ = _narrator()
    assert n.show_widget("roulette_russe", "hé hé") is False


def test_le_resultat_est_decide_cote_serveur():
    """Le navigateur ne tire rien : c'est ce qui permet à Wally de commenter son
    propre tirage — et de tricher."""
    n, feed, _ = _narrator()
    q = feed.subscribe()
    assert n.show_widget("coinflip", "évidemment") is True
    widget = q.get_nowait()
    assert widget["type"] == "widget"
    assert widget["params"]["result"] in ("heads", "tails")


def test_wally_peut_forcer_le_resultat():
    n, feed, _ = _narrator()
    q = feed.subscribe()
    n.show_widget("coinflip", "je le sentais", result="tails")
    assert q.get_nowait()["params"]["result"] == "tails"


def test_le_de_est_borne_a_six_faces():
    n, feed, _ = _narrator()
    q = feed.subscribe()
    n.show_widget("dice", "allez", result=99)
    assert q.get_nowait()["params"]["result"] == 6


def test_un_de_sans_resultat_est_tire_au_hasard():
    n, feed, _ = _narrator()
    q = feed.subscribe()
    n.show_widget("dice", "au pif")
    assert 1 <= q.get_nowait()["params"]["result"] <= 6


def test_le_commentaire_accompagne_le_widget():
    """C'est le commentaire qui fait le personnage, pas l'animation."""
    n, feed, _ = _narrator()
    q = feed.subscribe()
    n.show_widget("coinflip", "bon, pile alors")
    events = [q.get_nowait() for _ in range(2)]
    assert events[0]["type"] == "widget"
    assert events[1]["type"] == "bubble" and events[1]["text"] == "bon, pile alors"


def test_le_widget_consomme_le_budget_des_bulles():
    n, _, _ = _narrator()
    n.show_widget("coinflip", "et voilà")
    assert n._may_speak() is False
