"""Défauts relevés à la relecture du chantier overlay (2026-08-07).

Chacun de ces tests échouait avant sa correction. Ils sont regroupés ici parce
qu'ils partagent une racine : des fonctionnalités livrées mais inatteignables en
live, que les tests existants ne voyaient pas — ils appelaient chaque méthode
isolément, alors que la production les enchaîne.
"""
import time
from unittest.mock import AsyncMock

import pytest

from bot.core.overlay_feed import OverlayFeed
from bot.intelligence.overlay_narrator import OVERLAY_TOOL_SPEC, OverlayNarrator


def _n(live=True, reply="dix fois, quand même", interval=90.0):
    feed = OverlayFeed()
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=reply)
    return OverlayNarrator(feed, llm, lambda: live, min_interval_s=interval), feed


def _events(q, kind):
    return [e for e in (q.get_nowait() for _ in range(q.qsize())) if e["type"] == kind]


def _bubbles(q):
    return [e["text"] for e in _events(q, "bubble")]


# ── 1. paliers de compteur ──

@pytest.mark.asyncio
async def test_le_palier_passe_juste_apres_son_compteur():
    """Les appelants font `show_counter()` PUIS `on_counter_milestone()`.

    Le compteur consommait le budget des événements, que le palier testait une
    microseconde plus tard : le commentaire ne passait jamais — sauf quand le
    compteur lui-même avait été refusé, exactement à l'envers.
    """
    n, feed = _n(interval=0.0)
    q = feed.subscribe()
    assert n.show_counter("pas rechargé : 10") is True
    assert await n.on_counter_milestone("pas rechargé", 10) == "dix fois, quand même"
    assert _bubbles(q) == ["dix fois, quand même"]


@pytest.mark.asyncio
async def test_le_palier_reste_soumis_au_budget_des_bulles():
    """Le budget doit refuser : deux paliers coup sur coup ne passent pas."""
    n, _ = _n(interval=90.0)
    assert await n.on_counter_milestone("pas rechargé", 10) is not None
    assert await n.on_counter_milestone("pas rechargé", 25) is None


# ── 2. schéma de l'outil ──

def test_le_schema_declare_tout_ce_que_show_widget_lit():
    """`hangman` était dans l'enum sans `word` ni `hint` : le modèle ne pouvait
    pas les transmettre, donc le pendu ne se lançait jamais par la voix."""
    props = OVERLAY_TOOL_SPEC["function"]["parameters"]["properties"]
    for name in ("word", "hint", "close", "move", "done"):
        assert name in props, f"{name} lu par show_widget mais absent du schéma"


def test_chaque_widget_de_lenum_est_decrit():
    """Un widget listé sans description, c'est un widget que Wally n'utilise pas."""
    params = OVERLAY_TOOL_SPEC["function"]["parameters"]["properties"]["widget"]
    for name in params["enum"]:
        assert name in params["description"], f"{name} n'est pas décrit"


def test_le_pendu_se_lance_par_show_widget():
    """L'indice n'est plus publié au lancement (2026-08-07 : il résolvait le
    pendu d'entrée), mais il doit toujours ARRIVER jusqu'au narrateur — c'est ce
    que ce test couvrait à l'origine. On le vérifie donc là où il apparaît : à
    deux essais restants. Voir `tests/test_hangman.py` pour le détail."""
    n, feed = _n()
    q = feed.subscribe()
    out = n.show_widget("hangman", "à vous", word="chaussette", hint="ça se perd")
    assert out is not None and out["widget"] == "hangman"
    assert _events(q, "widget")[-1]["params"]["hint"] == ""

    for lettre in ("z", "k", "w", "x"):     # 4 fautes sur 6
        n._count_hangman("alice", lettre)
    assert _events(q, "widget")[-1]["params"]["hint"] == "ça se perd"


# ── 3. widgets pilotés ailleurs ──

@pytest.mark.parametrize("widget", ["quote", "prediction", "clip"])
def test_les_widgets_pilotes_ailleurs_ne_publient_pas_de_carte_vide(widget):
    """Ils sont dans `_WIDGETS` (self-model) mais `show_widget` n'a aucune
    branche pour eux : le contrôle tombait au bout avec `params = {}` et Wally
    annonçait une citation qui n'existait pas."""
    n, feed = _n()
    q = feed.subscribe()
    assert n.show_widget(widget, "un commentaire") is None
    assert _events(q, "widget") == []


def test_tout_widget_rendu_a_bien_une_branche():
    """Garde-fou : un widget ajouté à `_DIRECT_WIDGETS` sans branche
    retomberait sur la publication vide, en silence."""
    n, feed = _n()
    for widget in OverlayNarrator._DIRECT_WIDGETS:
        q = feed.subscribe()
        # Appel volontairement nu : sans données, chaque branche doit REFUSER.
        # Une absence de branche, elle, publierait un widget vide.
        out = n.show_widget(widget)
        published = _events(q, "widget")
        feed.unsubscribe(q)
        if out is None:
            assert published == [], f"{widget} a publié malgré un refus"
        else:
            assert published and published[0]["params"], \
                f"{widget} a publié une carte vide"


# ── 4. salut ──

@pytest.mark.asyncio
async def test_deux_saluts_identiques_ne_passent_pas_deux_fois():
    """Le salut était le seul producteur de bulle sans garde anti-répétition :
    deux arrivées rapprochées donnaient deux fois « du monde arrive »."""
    n, feed = _n(reply="tiens, du monde qui arrive", interval=0.0)
    n._event_interval = 0.0
    q = feed.subscribe()
    await n._maybe_greet("alice", None)
    await n._maybe_greet("bob", None)
    assert len(_bubbles(q)) == 1


@pytest.mark.asyncio
async def test_le_salut_dedupliqu_les_bulles_suivantes():
    """Sans `_remember_bubble`, la bulle d'après n'était pas comparée au salut."""
    n, _ = _n(reply="tiens, du monde qui arrive", interval=0.0)
    n._event_interval = 0.0
    await n._maybe_greet("alice", None)
    assert await n.on_stream_event("trois personnes viennent d'arriver") is None


# ── 5. thinking non apparié ──

@pytest.mark.asyncio
async def test_une_reaction_repetee_sans_thinking_neteint_rien():
    """Le vocal passif appelle `show_thinking=False` à chaque phrase entendue.
    Un `thinking(False)` non apparié effaçait la bulle affichée juste avant."""
    n, feed = _n(reply="toujours la même chose ici", interval=0.0)
    n._event_interval = 0.0
    await n.on_stream_event("un truc se passe")
    q = feed.subscribe()
    assert await n.on_stream_event("un autre truc", show_thinking=False) is None
    assert _events(q, "thinking") == []


# ── 6. sondage écrasé ──

def test_un_nouveau_sondage_clot_le_precedent():
    """Sinon les votes du premier partaient sans gagnant, et `_last_poll`
    gardait le résultat de l'avant-dernier — celui que le prompt relit."""
    n, _ = _n()
    assert n.start_poll("le premier ?", ["a", "b"], seconds=30)
    n._count_vote("alice", "1")
    assert n.start_poll("le second ?", ["c", "d"], seconds=30)
    assert "le premier" in (n.poll_result_line() or "")


# ── 7. chifoumi resté ouvert ──

def test_un_chifoumi_perime_se_clot_au_vote_suivant():
    """La tâche de clôture peut être perdue (ouverture hors boucle asyncio) :
    `self._rps` restait renseigné et bloquait toutes les manches suivantes."""
    n, _ = _n()
    assert n.start_rps(seconds=5)
    n._rps["ends_at"] = time.monotonic() - 1
    n._count_rps("alice", "pierre")
    assert n._rps is None
    assert n.start_rps(seconds=5) is True


# ── 8. purge du détecteur de vagues d'emotes ──

def test_le_detecteur_demotes_oublie_ce_qui_est_retombe():
    """`_seen` n'était purgé que si le MÊME token réapparaissait : tout mot en
    capitales tapé une fois restait en mémoire jusqu'au redémarrage."""
    from bot.core.emote_wave import EmoteWaveDetector

    d = EmoteWaveDetector()
    for i in range(200):
        d.feed(f"viewer{i}", f"TOKEN{i}", now=1000.0 + i * 0.01)
    assert len(d._seen) == 200          # tout est encore dans la fenêtre
    d.feed("quelqu-un", "AutreChose", now=2000.0)
    assert len(d._seen) == 1            # une seule entrée vivante


def test_lemote_annonce_ne_depend_pas_du_hachage():
    """Deux emotes au seuil sur la même ligne : c'est le premier du MESSAGE qui
    est annoncé, pas celui que l'ordre du set fait sortir en tête."""
    from bot.core.emote_wave import EmoteWaveDetector

    d = EmoteWaveDetector(min_people=2)
    d.feed("alice", "KEKW PogChamp", now=1000.0)
    assert d.feed("bob", "KEKW PogChamp", now=1000.5) == "KEKW"


# ── 9. route de test admin ──

def test_le_feed_accepte_un_widget_qui_a_son_propre_kind():
    """`/api/admin/overlay/test` faisait `widget(widget, **params)` : un `kind`
    dans les params — nom réel d'un paramètre de `goal` — donnait un 500."""
    feed = OverlayFeed()
    q = feed.subscribe()
    feed.widget("goal", kind="follow", percent=50)
    assert _events(q, "widget")[-1]["params"]["kind"] == "follow"
