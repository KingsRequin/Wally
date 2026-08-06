"""OverlayNarrator — budget de parole et condensation des pensées.

Le risque du projet est produit : un compagnon qui commente sans arrêt devient
insupportable, et un overlay ne se scrolle pas. Le budget doit donc REFUSER,
pas seulement être suggéré dans un prompt.
"""
import time
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
    assert n.show_widget("coinflip", "on verra bien") is None
    assert q.empty()


def test_un_widget_inconnu_est_refuse():
    n, feed, _ = _narrator()
    assert n.show_widget("roulette_russe", "hé hé") is None


def test_le_resultat_est_decide_cote_serveur():
    """Le navigateur ne tire rien : c'est ce qui permet à Wally de commenter son
    propre tirage — et de tricher."""
    n, feed, _ = _narrator()
    q = feed.subscribe()
    assert n.show_widget("coinflip", "évidemment") is not None
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


# ── widgets de la phase 4 ──

def _with_status(started_at, live=True):
    feed = OverlayFeed()
    llm = AsyncMock()
    n = OverlayNarrator(feed, llm, lambda: live,
                        stream_status=lambda: {"started_at": started_at})
    return n, feed


def test_la_roue_refuse_moins_de_deux_options():
    n, feed, _ = _narrator()
    assert n.show_widget("wheel", "on tranche", options=["seule"]) is None


def test_la_roue_borne_l_index_gagnant():
    n, feed, _ = _narrator()
    q = feed.subscribe()
    n.show_widget("wheel", "allez", result=99, options=["a", "b", "c"])
    assert q.get_nowait()["params"]["index"] == 2


def test_la_roue_est_plafonnee_a_huit_parts():
    n, feed, _ = _narrator()
    q = feed.subscribe()
    n.show_widget("wheel", "", options=[f"opt{i}" for i in range(20)])
    assert len(q.get_nowait()["params"]["options"]) == 8


def test_le_compte_a_rebours_exige_une_duree():
    n, feed, _ = _narrator()
    assert n.show_widget("countdown", "attention") is None
    assert n.show_widget("countdown", "attention", result=30) is not None


def test_la_jauge_borne_le_pourcentage():
    n, feed, _ = _narrator()
    q = feed.subscribe()
    n.show_widget("gauge", "objectif", result=250, label="subs")
    assert q.get_nowait()["params"]["percent"] == 100.0


def test_le_message_epingle_exige_un_texte():
    n, feed, _ = _narrator()
    assert n.show_widget("pinned", "", author="Jubeii") is None
    assert n.show_widget("pinned", "", author="Jubeii", text="gg les gars") is not None


def test_uptime_calcule_depuis_le_debut_du_live():
    from datetime import datetime, timedelta, timezone
    started = (datetime.now(timezone.utc) - timedelta(hours=3, minutes=12)).isoformat()
    n, feed = _with_status(started)
    q = feed.subscribe()
    assert n.show_widget("uptime") is not None
    e = q.get_nowait()
    assert e["kind"] == "counter"          # même rendu que le compteur
    assert e["params"]["text"] == "en live depuis 3h12"


def test_uptime_en_minutes_pour_un_live_recent():
    from datetime import datetime, timedelta, timezone
    started = (datetime.now(timezone.utc) - timedelta(minutes=25)).isoformat()
    n, feed = _with_status(started)
    q = feed.subscribe()
    n.show_widget("uptime")
    assert q.get_nowait()["params"]["text"] == "en live depuis 25 min"


def test_uptime_sans_date_de_debut_ne_s_affiche_pas():
    """Rien à afficher plutôt qu'un compteur faux."""
    n, _ = _with_status(None)
    assert n.show_widget("uptime") is None


def test_uptime_avec_date_illisible():
    n, _ = _with_status("pas-une-date")
    assert n.show_widget("uptime") is None


# ── saluts (widget 9) ──

@pytest.mark.asyncio
async def test_un_inconnu_est_salue():
    n, feed, _ = _narrator(reply="tiens un nouveau")
    q = feed.subscribe()
    await n.on_chat_message("Nouveau", "salut", days_since=None)
    bubbles = [q.get_nowait() for _ in range(q.qsize())]
    assert any(e["type"] == "bubble" for e in bubbles)


@pytest.mark.asyncio
async def test_un_habitue_vu_hier_n_est_pas_salue():
    """Sinon il saluerait les mêmes personnes à chaque live."""
    n, feed, llm = _narrator()
    await n.on_chat_message("Regulier", "salut", days_since=1.0)
    llm.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_un_revenant_apres_une_semaine_est_salue():
    n, feed, llm = _narrator(reply="revoilà Jubeii")
    await n.on_chat_message("Jubeii", "salut", days_since=26.0)
    llm.complete.assert_awaited()


@pytest.mark.asyncio
async def test_on_ne_salue_qu_une_fois_par_live():
    n, feed, llm = _narrator(interval=0.0)
    n._event_interval = 0.0   # on teste le salut, pas le budget
    await n.on_chat_message("Nouveau", "salut", days_since=None)
    await n.on_chat_message("Nouveau", "encore moi", days_since=None)
    assert llm.complete.await_count == 1


@pytest.mark.asyncio
async def test_reset_live_permet_de_resaluer_au_stream_suivant():
    n, feed, llm = _narrator(interval=0.0)
    n._event_interval = 0.0   # on teste le salut, pas le budget
    await n.on_chat_message("Nouveau", "salut", days_since=None)
    n.reset_live()
    await n.on_chat_message("Nouveau", "salut", days_since=None)
    assert llm.complete.await_count == 2


# ── sondage (widget 6) ──

def test_un_sondage_exige_une_question_et_deux_options():
    n, _, _ = _narrator()
    assert n.start_poll("", ["oui", "non"]) is False
    assert n.start_poll("chocolat ?", ["oui"]) is False
    assert n.start_poll("chocolat ?", ["oui", "non"]) is True


def test_pas_de_sondage_hors_live():
    n, _, _ = _narrator(live=False)
    assert n.start_poll("chocolat ?", ["oui", "non"]) is False


@pytest.mark.asyncio
async def test_les_votes_du_chat_sont_comptes():
    n, feed, _ = _narrator()
    n.start_poll("vous aimez le chocolat ?", ["oui", "non"], seconds=30)
    q = feed.subscribe()
    await n.on_chat_message("alice", "1")
    await n.on_chat_message("bob", "1")
    await n.on_chat_message("carol", "2")
    last = None
    while not q.empty():
        e = q.get_nowait()
        if e["type"] == "widget":
            last = e
    assert last["kind"] == "poll"
    assert last["params"]["tally"] == [2, 1]


@pytest.mark.asyncio
async def test_un_seul_vote_par_personne_mais_changement_d_avis_permis():
    n, feed, _ = _narrator()
    n.start_poll("chocolat ?", ["oui", "non"], seconds=30)
    q = feed.subscribe()
    await n.on_chat_message("alice", "1")
    await n.on_chat_message("alice", "2")   # elle change d'avis
    last = None
    while not q.empty():
        e = q.get_nowait()
        if e["type"] == "widget":
            last = e
    assert last["params"]["tally"] == [0, 1]


@pytest.mark.asyncio
async def test_un_message_qui_contient_un_chiffre_n_est_pas_un_vote():
    """« j'ai 2 chats » ne doit pas compter."""
    n, feed, _ = _narrator()
    n.start_poll("chocolat ?", ["oui", "non"], seconds=30)
    await n.on_chat_message("alice", "j'ai 2 chats")
    await n.on_chat_message("bob", "42")        # hors options
    assert sum(n._poll["votes"].values()) == 0
    assert len(n._poll["votes"]) == 0


def test_la_duree_du_sondage_est_bornee():
    n, _, _ = _narrator()
    n.start_poll("q ?", ["a", "b"], seconds=9999)
    import time as _t
    assert n._poll["ends_at"] - _t.monotonic() <= 121


def test_un_nouveau_live_efface_les_saluts_du_precedent():
    """Le process tourne des semaines : sans ça, plus personne n'est jamais
    salué après le tout premier live."""
    live = {"on": True}
    feed, llm = OverlayFeed(), AsyncMock()
    n = OverlayNarrator(feed, llm, lambda: live["on"])
    n._live()                      # premier live
    n._greeted.add("alice")
    live["on"] = False
    n._live()                      # fin du live
    live["on"] = True
    n._live()                      # live suivant
    assert n._greeted == set()


def test_le_widget_poll_est_route_vers_le_sondage():
    n, feed, _ = _narrator()
    q = feed.subscribe()
    assert n.show_widget(
        "poll", "", question="vous aimez le chocolat ?",
        options=["Oui", "Non"], seconds=30,
    ) is not None
    events = [q.get_nowait() for _ in range(q.qsize())]
    widget = next(e for e in events if e["type"] == "widget")
    assert widget["kind"] == "poll"
    assert widget["params"]["options"] == ["Oui", "Non"]
    assert widget["params"]["seconds"] == 30
    # le commentaire ferait doublon avec la question affichée
    assert not [e for e in events if e["type"] == "bubble"]


def test_le_widget_poll_refuse_une_question_vide():
    n, _, _ = _narrator()
    assert n.show_widget("poll", "", options=["Oui", "Non"]) is None


# ── mode test hors live (widget de réglage) ──

@pytest.mark.asyncio
async def test_le_mode_test_fait_parler_hors_live():
    n, feed, llm = _narrator(live=False, reply="je teste")
    n.force_live(30)
    assert await n.on_thought("une pensée") == "je teste"


@pytest.mark.asyncio
async def test_le_mode_test_expire_tout_seul():
    """Oublié actif, il ferait parler Wally dans le vide à un appel LLM la bulle."""
    n, feed, llm = _narrator(live=False)
    n.force_live(30)
    n._force_until = time.monotonic() - 1     # échéance dépassée
    assert n.is_active() is False
    assert await n.on_thought("une pensée") is None
    llm.complete.assert_not_awaited()


def test_le_mode_test_se_coupe():
    n, _, _ = _narrator(live=False)
    n.force_live(30)
    assert n.force_live(0) == 0.0
    assert n.is_active() is False


def test_la_duree_du_mode_test_est_plafonnee():
    n, _, _ = _narrator(live=False)
    assert n.force_live(9999) == 120
    assert n.force_live_remaining() <= 120


def test_un_vrai_live_reste_prioritaire_apres_expiration():
    """Couper le mode test ne doit pas faire taire Wally pendant un vrai live."""
    n, _, _ = _narrator(live=True)
    n.force_live(30)
    n.force_live(0)
    assert n.is_active() is True


# ── clôture du sondage ──

def test_la_cloture_designe_le_gagnant():
    n, feed, _ = _narrator()
    n.start_poll("chocolat ?", ["Oui", "Non"], seconds=30)
    n._count_vote("alice", "1"); n._count_vote("bob", "1"); n._count_vote("carol", "2")
    r = n.close_poll()
    assert r["winner"] == "Oui"
    assert r["tally"] == [2, 1]
    assert r["tied"] is False


def test_la_cloture_affiche_le_resultat_a_l_ecran():
    """Sans ça le dépouillement s'efface sans jamais annoncer de gagnant."""
    n, feed, _ = _narrator()
    n.start_poll("chocolat ?", ["Oui", "Non"], seconds=30)
    n._count_vote("alice", "1")
    q = feed.subscribe()
    n.close_poll()
    last = [e for e in (q.get_nowait() for _ in range(q.qsize())) if e["type"] == "widget"][-1]
    assert last["params"]["final"] is True
    assert last["params"]["winner"] == 0
    assert last["params"]["seconds"] == 0


def test_une_egalite_ne_designe_personne():
    n, _, _ = _narrator()
    n.start_poll("chocolat ?", ["Oui", "Non"], seconds=30)
    n._count_vote("alice", "1"); n._count_vote("bob", "2")
    r = n.close_poll()
    assert r["tied"] is True and r["winner"] is None


def test_un_sondage_sans_vote_se_clot_quand_meme():
    n, _, _ = _narrator()
    n.start_poll("chocolat ?", ["Oui", "Non"], seconds=30)
    r = n.close_poll()
    assert r["total"] == 0 and r["winner"] is None
    assert "personne n'a voté" in n.poll_result_line()


def test_wally_peut_enoncer_le_resultat():
    """« Alors, ça a donné quoi ? » doit avoir une réponse."""
    n, _, _ = _narrator()
    assert n.poll_result_line() == ""          # aucun sondage encore
    n.start_poll("vous aimez le chocolat ?", ["Oui", "Non"], seconds=30)
    n._count_vote("alice", "1")
    n.close_poll()
    line = n.poll_result_line()
    assert "Oui l'emporte" in line and "vous aimez le chocolat ?" in line


def test_le_resultat_est_consigne_dans_le_flux_du_stream():
    """C'est ce qui le rend visible dans le prompt — donc répondable. Et sans
    réveiller le narrateur : Wally n'a pas à réagir à son propre résultat."""
    from unittest.mock import MagicMock
    feed_stream = MagicMock()
    n, _, _ = _narrator()
    n._stream_feed = feed_stream
    n.start_poll("chocolat ?", ["Oui", "Non"], seconds=30)
    n._count_vote("alice", "1")
    n.close_poll()
    args, kwargs = feed_stream.record.call_args
    assert kwargs["notify"] is False
    assert "Oui" in args[0]


@pytest.mark.asyncio
async def test_le_sondage_se_clot_tout_seul_a_l_echeance():
    import asyncio
    n, feed, _ = _narrator()
    n.start_poll("chocolat ?", ["Oui", "Non"], seconds=5)
    n._poll["ends_at"] = time.monotonic()      # échéance immédiate
    n._poll_task.cancel()
    n._schedule_poll_close(0)
    await asyncio.sleep(0.05)
    assert n._poll is None                      # clos sans intervention
    assert n._last_poll is not None


# ── le tirage remonte à l'appelant ──

def test_le_tirage_du_de_est_rendu_a_l_appelant():
    """« lance un dé » doit pouvoir répondre le résultat, pas « c'est à l'écran »."""
    n, _, _ = _narrator()
    out = n.show_widget("dice", "allez")
    assert out["widget"] == "dice" and 1 <= out["result"] <= 6


def test_le_tirage_de_la_roue_est_rendu_a_l_appelant():
    n, _, _ = _narrator()
    out = n.show_widget("wheel", "", options=["A", "B", "C"])
    assert out["options"][out["index"]] in ("A", "B", "C")


def test_un_commentaire_trop_long_n_affiche_que_le_widget():
    """Non borné, il poussait le décor hors du cadre OBS — le LLM l'écrit
    librement, contrairement aux pensées qui passent par la condensation."""
    n, feed, _ = _narrator()
    q = feed.subscribe()
    assert n.show_widget("dice", "x" * 200) is not None
    events = [q.get_nowait() for _ in range(q.qsize())]
    assert [e for e in events if e["type"] == "widget"]      # le dé s'affiche
    assert not [e for e in events if e["type"] == "bubble"]  # la bulle, non


def test_un_commentaire_court_reste_affiche():
    n, feed, _ = _narrator()
    q = feed.subscribe()
    n.show_widget("dice", "allez, on tente")
    events = [q.get_nowait() for _ in range(q.qsize())]
    assert [e for e in events if e["type"] == "bubble"]
