"""Le bouton Tester ne doit JAMAIS surgir sur la scène en direct.

C'est tout l'intérêt du champ `scene` sur les événements : on règle la scène de
fin pendant que le live tourne sur celle du jeu.
"""
import json
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bot.core.overlay_layout import layout_par_defaut
from bot.core.overlay_layout_store import LAYOUT_KEY
from bot.dashboard.routes.overlay import admin_router


class _FeedEspion:
    """Retient ce qui est publié. `OverlayFeed.publish` est synchrone."""

    def __init__(self):
        self.publies = []

    def publish(self, event):
        self.publies.append(event)


class _StateLayout:
    """Une base qui ne sert QUE le layout, comme `test_overlay_layout_store`."""

    def __init__(self, layout=None):
        self.rows = {}
        if layout is not None:
            self.rows[LAYOUT_KEY] = json.dumps(layout)

    async def get_state(self, key):
        return self.rows.get(key)

    async def set_state(self, key, value):
        self.rows[key] = value


class _Base(_StateLayout):
    """La même, plus la galerie : le ▶ de l'image lit les deux."""

    def __init__(self, image, layout=None):
        super().__init__(layout)
        self.image = image
        self.filtres = []

    async def get_random_gallery_image(self, filtre):
        self.filtres.append(filtre)
        return self.image


class _ConfigImage:
    """Les réglages d'image, tels que `OverlayImageConfig` les porte."""
    display_duration = 15
    animation_in = "fadeIn"
    animation_out = "fadeOut"
    animation_duration = 1.0
    random_filter = "all"


_CONFIG_IMAGE = _ConfigImage()


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
    """`apex_progress` n'a pas de builder : publier un widget de ce nom ne
    ferait RIEN côté page, et le ▶ passerait pour cassé.

    `rotator` et `image` étaient ici jusqu'au 2026-08-15, avec pour raison
    « c'est une source OBS à part ». Ils ont maintenant leur déclencheur : ce
    test EXIGEAIT le défaut, ne pas les y remettre.
    """
    client, feed = preview
    r = client.post("/api/admin/overlay/preview",
                    json={"scene": "en-jeu", "element": "apex_progress"},
                    headers=_AUTH)
    assert r.status_code == 200
    assert r.json()["affiche"] is False
    assert r.json()["raison"]
    assert feed.publies == []


def test_le_play_du_rotateur_le_fait_passer_au_media_suivant(preview):
    """Il tourne déjà tout seul : le seul geste utile est de le faire avancer
    sous les yeux de celui qui règle sa place. Répondre « c'est une source OBS
    à part » à quelqu'un qui vient de lui donner une position était absurde."""
    client, feed = preview
    r = client.post("/api/admin/overlay/preview",
                    json={"scene": "fin", "element": "rotator"}, headers=_AUTH)
    assert r.status_code == 200
    assert r.json()["affiche"] is True
    # Sur CETTE scène seulement, comme tout le reste du panneau.
    assert feed.publies == [{"type": "rotator", "scene": "fin"}]


def test_le_play_de_limage_pousse_une_vraie_image_sur_la_seule_scene(preview):
    """L'image passe par son PROPRE flux (celui qu'alimente `!image`), pas par
    le bus des widgets. Le slug voyage avec : sans lui, régler la scène de fin
    projetterait une image de la galerie en plein live."""
    client, feed = preview
    etat = client.app.state.wally
    etat.db = _Base({"id": "img-1", "username": "KingsRequin", "title": "Bière"})
    etat.config.overlay_image = _CONFIG_IMAGE
    images = _FeedEspion()
    etat.overlay_image_feed = images

    r = client.post("/api/admin/overlay/preview",
                    json={"scene": "fin", "element": "image"}, headers=_AUTH)

    assert r.status_code == 200
    assert r.json()["affiche"] is True
    assert images.publies == [{
        "image_url": "/api/public/gallery/img-1/image",
        "title": "Bière",
        "username": "KingsRequin",
        "display_duration": 15,
        "animation_in": "fadeIn",
        "animation_out": "fadeOut",
        "animation_duration": 1.0,
        "scene": "fin",
    }]
    # Rien sur le bus des widgets : ce serait un `kind` sans builder.
    assert feed.publies == []


def test_une_galerie_vide_le_dit_au_lieu_de_publier_une_image_absente(preview):
    client, feed = preview
    etat = client.app.state.wally
    etat.db = _Base(None)
    etat.config.overlay_image = _CONFIG_IMAGE
    images = _FeedEspion()
    etat.overlay_image_feed = images

    r = client.post("/api/admin/overlay/preview",
                    json={"scene": "fin", "element": "image"}, headers=_AUTH)

    assert r.status_code == 200
    assert r.json()["affiche"] is False
    assert r.json()["raison"]
    assert images.publies == []


def test_un_element_masque_dans_la_scene_ne_ment_pas(preview):
    """Le conteneur d'un élément masqué porte `display: none` : rien de ce
    qu'on publierait ne s'afficherait. Un ▶ qui répond « affiché » pendant que
    l'écran ne bouge pas envoie chercher la panne ailleurs.

    Vaut pour TOUS les éléments, y compris l'avatar — dégager la scène ne le
    ferait pas revenir s'il est éteint dessus.
    """
    client, feed = preview
    layout = layout_par_defaut()
    for scene in layout["scenes"]:
        scene["elements"]["dice"]["hidden"] = True
        scene["elements"]["avatar"]["hidden"] = True
    client.app.state.wally.db = _StateLayout(layout)

    for cle in ("dice", "avatar"):
        r = client.post("/api/admin/overlay/preview",
                        json={"scene": "fin", "element": cle}, headers=_AUTH)
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

    # Quatre éléments ne sont pas des widgets et ont chacun leur déclencheur :
    # la bulle a son propre événement, l'avatar est là en permanence et son ▶
    # dégage la scène, le rotateur passe au média suivant, l'image de la
    # galerie part par le flux d'images. Aucun échantillon à leur écrire.
    _HORS_BUILDER = ("bubble", "avatar", "rotator", "image")
    # Les deux spectacles plein écran reçoivent bien des paramètres — mais
    # calculés sur le dossier de memes au moment du ▶ (`_SPECTACLES_ENTIERS`),
    # pas écrits dans la table. Une constante d'essai n'en montrait qu'un bout :
    # 58 memes sur 135, mesurés dans le navigateur. Le test qui suit vérifie
    # qu'ils ne partent pas nus pour autant.
    from bot.dashboard.routes.overlay import _SPECTACLES_ENTIERS
    sans = [cle for cle in ELEMENTS
            if cle not in _HORS_WIDGET and cle not in _HORS_BUILDER
            and not _ECHANTILLONS.get(cle)
            and cle not in _SPECTACLES_ENTIERS
            and cle not in ("meme", "planning")]
    assert sans == [], f"widgets sans échantillon : {sans}"


def test_les_spectacles_plein_ecran_partent_avec_LEUR_duree(preview):
    """Elle vient du dossier, par le narrateur : leur ▶ ne règle aucune
    position (la carte couvre l'écran), il ne sert qu'à juger l'effet — donc il
    doit le montrer en entier, comme un vrai achat."""
    client, feed = preview
    narrateur = client.app.state.wally.discord_bot.overlay_narrator
    narrateur._duree_avalanche.return_value = 50
    narrateur._duree_virus.return_value = 30

    for cle, attendu in (("meme_storm", 50), ("virus_popup", 30)):
        r = client.post("/api/admin/overlay/preview",
                        json={"scene": "fin", "element": cle}, headers=_AUTH)
        assert r.status_code == 200
        params = feed.publies[-1]["params"]
        assert params["seconds"] == attendu, cle
        # La carte doit survivre au spectacle : c'est ce qui coupait le spam au
        # bout des vingt secondes de l'essai.
        assert params["duration"] > attendu, cle


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
