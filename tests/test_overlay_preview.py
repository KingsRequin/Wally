"""Le bouton Tester ne doit JAMAIS surgir sur la scène en direct.

C'est tout l'intérêt du champ `scene` sur les événements : on règle la scène de
fin pendant que le live tourne sur celle du jeu.
"""
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bot.dashboard.routes.overlay import admin_router


class _FeedEspion:
    """Retient ce qui est publié. `OverlayFeed.publish` est synchrone."""

    def __init__(self):
        self.publies = []

    def publish(self, event):
        self.publies.append(event)


@pytest.fixture
def preview():
    app = FastAPI()
    app.include_router(admin_router, prefix="/api/admin")
    feed = _FeedEspion()
    app.state.wally = MagicMock()
    app.state.wally.overlay_feed = feed
    # `charger_layout` accepte `db=None` et rend les défauts : les trois
    # scènes par défaut suffisent à ce test, pas besoin de base.
    app.state.wally.db = None
    app.state.wally.memes.list.return_value = []
    app.state.wally.config.bot.dashboard_token = "testtoken"
    return TestClient(app), feed


_AUTH = {"Authorization": "Bearer testtoken"}


def test_la_previsualisation_cible_une_seule_scene(preview):
    client, feed = preview
    r = client.post("/api/admin/overlay/preview",
                    json={"scene": "fin", "element": "dice"}, headers=_AUTH)
    assert r.status_code == 200
    evt = feed.publies[-1]
    assert evt["scene"] == "fin"       # et surtout pas None
    assert evt["type"] == "widget"
    assert evt["kind"] == "dice"
    assert evt["params"]["result"] == "4"   # l'échantillon, pas un widget vide


def test_aucun_evenement_ne_part_sans_scene(preview):
    """Un événement sans slug vise TOUTES les pages, donc l'antenne."""
    client, feed = preview
    r = client.post("/api/admin/overlay/preview",
                    json={"element": "dice"}, headers=_AUTH)
    assert r.status_code == 400
    assert feed.publies == []


def test_tout_afficher_envoie_des_fantomes_de_la_scene(preview):
    client, feed = preview
    r = client.post("/api/admin/overlay/preview",
                    json={"scene": "en-jeu", "tous": True}, headers=_AUTH)
    assert r.status_code == 200
    evt = feed.publies[-1]
    assert evt["type"] == "ghosts"
    assert evt["scene"] == "en-jeu"
    assert "avatar" in evt["elements"]


def test_un_element_inconnu_est_refuse(preview):
    client, feed = preview
    r = client.post("/api/admin/overlay/preview",
                    json={"scene": "en-jeu", "element": "licorne"}, headers=_AUTH)
    assert r.status_code == 400
    assert feed.publies == []


def test_une_scene_inconnue_est_refusee_pour_les_fantomes(preview):
    """Contrairement à la page, qui sert le défaut : ici c'est un appel admin,
    et une scène inconnue est une erreur de l'appelant, pas un écran noir."""
    client, feed = preview
    r = client.post("/api/admin/overlay/preview",
                    json={"scene": "fantome", "tous": True}, headers=_AUTH)
    assert r.status_code == 404
    assert feed.publies == []


def test_un_element_hors_widget_dit_pourquoi_plutot_que_de_se_taire(preview):
    """`rotator` et `image` n'ont pas de builder : publier un widget de ce nom
    ne ferait RIEN côté page, et le ▶ passerait pour cassé."""
    client, feed = preview
    for cle in ("rotator", "image", "apex_progress"):
        r = client.post("/api/admin/overlay/preview",
                        json={"scene": "en-jeu", "element": cle}, headers=_AUTH)
        assert r.status_code == 200, cle
        assert r.json()["affiche"] is False, cle
        assert r.json()["raison"], cle
    assert feed.publies == []


def test_le_play_de_lavatar_le_rend_visible_au_lieu_de_le_nier(preview):
    """L'avatar est à l'écran en permanence — SAUF quand une carte `solo` prend
    la scène et l'efface. Répondre « il est déjà là » à quelqu'un qui le voit
    effacé est pire que ne rien répondre : le message contredit l'écran, et on
    cherche la panne ailleurs. Le ▶ dégage donc la scène, ce qui le rend
    réellement visible."""
    client, feed = preview
    r = client.post("/api/admin/overlay/preview",
                    json={"scene": "en-jeu", "element": "avatar"}, headers=_AUTH)
    assert r.status_code == 200
    assert r.json()["affiche"] is True
    assert r.json()["message"]
    # Sur CETTE scène seulement : dégager la scène de fin qu'on prépare ne doit
    # pas balayer l'écran du live en cours.
    assert feed.publies == [{"type": "clear", "scene": "en-jeu"}]


def test_la_bulle_passe_par_son_propre_evenement(preview):
    """Elle n'est pas un widget : un `{"type": "widget", "kind": "bubble"}`
    n'aurait aucun builder et ne se serait jamais affiché."""
    client, feed = preview
    r = client.post("/api/admin/overlay/preview",
                    json={"scene": "fin", "element": "bubble"}, headers=_AUTH)
    assert r.status_code == 200
    evt = feed.publies[-1]
    assert evt["type"] == "bubble"
    assert evt["scene"] == "fin"
    assert evt["text"]


def test_un_essai_de_pendu_ne_reste_pas_collant(preview):
    """`sticky` est rejoué SANS jamais périmer par `OverlayFeed.recent()` : un
    pendu d'essai hanterait la scène à chaque reconnexion d'OBS."""
    client, feed = preview
    r = client.post("/api/admin/overlay/preview",
                    json={"scene": "fin", "element": "hangman"}, headers=_AUTH)
    assert r.status_code == 200
    assert "sticky" not in feed.publies[-1]["params"]


def test_chaque_widget_placable_a_un_echantillon(preview):
    """Un widget sans paramètre se construit vide et ne dit rien de son
    encombrement — or c'est exactement ce qu'on cherche à voir en le plaçant."""
    from bot.core.overlay_layout import ELEMENTS
    from bot.dashboard.routes.overlay import _ECHANTILLONS, _HORS_WIDGET

    # `bubble` et `avatar` ne sont pas des widgets : la bulle a son propre
    # événement, l'avatar est là en permanence et son ▶ dégage la scène.
    sans = [cle for cle in ELEMENTS
            if cle not in _HORS_WIDGET and cle not in ("bubble", "avatar")
            and not _ECHANTILLONS.get(cle)
            and cle not in ("meme", "planning")]
    assert sans == [], f"widgets sans échantillon : {sans}"


def test_meme_et_planning_recoivent_une_vraie_image(preview):
    """Leur seul paramètre est une URL : sans elle, le widget s'affiche en
    image cassée, de taille nulle, et le placement reste aveugle."""
    client, feed = preview
    client.app.state.wally.memes.list.return_value = [{"name": "un chat.webp"}]
    r = client.post("/api/admin/overlay/preview",
                    json={"scene": "fin", "element": "meme"}, headers=_AUTH)
    assert r.status_code == 200
    assert feed.publies[-1]["params"]["src"] == "/api/public/meme/un%20chat.webp"

    r = client.post("/api/admin/overlay/preview",
                    json={"scene": "fin", "element": "planning"}, headers=_AUTH)
    assert r.status_code == 200
    assert feed.publies[-1]["params"]["src"].endswith(".webp")


def test_une_bibliotheque_de_memes_vide_le_dit(preview):
    """Sans image, le widget s'afficherait en carré cassé de 13 px et le ▶
    passerait pour une panne. On ne publie rien, on dit pourquoi."""
    client, feed = preview
    client.app.state.wally.memes.list.return_value = []
    r = client.post("/api/admin/overlay/preview",
                    json={"scene": "fin", "element": "meme"}, headers=_AUTH)
    assert r.status_code == 200
    assert r.json()["affiche"] is False
    assert "meme" in r.json()["raison"].lower()
    assert feed.publies == []
