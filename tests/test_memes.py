"""Bibliothèque de memes déposés à la main.

Wally ne VOIT pas ces images : sa seule prise dessus est la description. Et le
dossier est relu à chaque tirage — redémarrer le bot pour qu'une image apparaisse
serait absurde.
"""
import pytest

from bot.core.memes import MemeLibrary


@pytest.fixture
def lib(tmp_path):
    (tmp_path / "azrael-blame-le-ping.jpg").write_bytes(b"x")
    (tmp_path / "requin_rage.png").write_bytes(b"x")
    (tmp_path / "notes.md").write_text("pas une image")
    return MemeLibrary(tmp_path)


def test_seules_les_images_sont_listees(lib):
    noms = {m["name"] for m in lib.list()}
    assert noms == {"azrael-blame-le-ping.jpg", "requin_rage.png"}


def test_le_nom_du_fichier_sert_de_description(lib):
    m = next(m for m in lib.list() if m["name"].startswith("azrael"))
    assert m["description"] == "azrael blame le ping"


def test_un_fichier_texte_prime_sur_le_nom(tmp_path):
    (tmp_path / "truc.jpg").write_bytes(b"x")
    (tmp_path / "truc.txt").write_text("le jour où il a rage quit en pleine game")
    assert MemeLibrary(tmp_path).list()[0]["description"].startswith("le jour où")


def test_deux_images_de_meme_nom_ont_chacune_leur_description(tmp_path):
    """`chat.gif` et `chat.jpg` sont deux images DIFFÉRENTES.

    Avec le seul `with_suffix(".txt")`, elles se partageaient `chat.txt` et
    héritaient de la même description : Wally en commentait une en décrivant
    l'autre. Dix paires du dossier de prod étaient dans ce cas.
    """
    (tmp_path / "chat.gif").write_bytes(b"x")
    (tmp_path / "chat.jpg").write_bytes(b"x")
    (tmp_path / "chat.gif.txt").write_text("un chat qui tombe du canapé")
    (tmp_path / "chat.jpg.txt").write_text("un chat qui hurle sur son maître")
    par_nom = {m["name"]: m["description"] for m in MemeLibrary(tmp_path).list()}
    assert par_nom["chat.gif"] == "un chat qui tombe du canapé"
    assert par_nom["chat.jpg"] == "un chat qui hurle sur son maître"


def test_l_extension_complete_prime_sur_l_ancienne_forme(tmp_path):
    """L'ancienne forme reste acceptée : les .txt déjà déposés valent toujours."""
    (tmp_path / "truc.jpg").write_bytes(b"x")
    (tmp_path / "truc.txt").write_text("ancienne forme")
    assert MemeLibrary(tmp_path).list()[0]["description"] == "ancienne forme"
    (tmp_path / "truc.jpg.txt").write_text("nouvelle forme")
    assert MemeLibrary(tmp_path).list()[0]["description"] == "nouvelle forme"


def test_un_mot_vide_ne_suffit_pas_a_retenir_un_meme(tmp_path):
    """« qui », « pas », « une » passent le filtre de longueur et figurent dans
    presque toutes les descriptions. En retenant tout meme ayant UN mot en
    commun, « chat qui hurle » retenait quasi tout le dossier et retombait sur
    un tirage au hasard. On garde les meilleurs, pas les vaguement concernés."""
    (tmp_path / "a.jpg").write_bytes(b"x")
    (tmp_path / "a.txt").write_text("un chien qui dort tranquillement")
    (tmp_path / "b.jpg").write_bytes(b"x")
    (tmp_path / "b.txt").write_text("un chat qui hurle sur son maître")
    lib = MemeLibrary(tmp_path)
    assert {lib.pick("chat qui hurle")["name"] for _ in range(12)} == {"b.jpg"}


def test_sans_aucune_correspondance_le_tirage_reste_ouvert(tmp_path):
    """Un sujet hors-sujet ne doit pas rendre None : mieux vaut un meme au
    hasard que pas de meme du tout."""
    (tmp_path / "a.jpg").write_bytes(b"x")
    (tmp_path / "a.txt").write_text("un chien qui dort")
    assert MemeLibrary(tmp_path).pick("astrophysique quantique")["name"] == "a.jpg"


def test_un_dossier_absent_ne_leve_pas(tmp_path):
    assert MemeLibrary(tmp_path / "nexiste-pas").list() == []
    assert MemeLibrary(tmp_path / "nexiste-pas").pick() is None


def test_une_image_trop_lourde_est_ignoree(tmp_path):
    """Elle mettrait plus de temps à charger que le widget à passer."""
    (tmp_path / "enorme.png").write_bytes(b"x" * (9 * 1024 * 1024))
    assert MemeLibrary(tmp_path).list() == []


def test_le_dossier_est_relu_a_chaque_fois(tmp_path):
    """Déposer une image ne doit pas demander de redémarrage."""
    lib = MemeLibrary(tmp_path)
    assert lib.list() == []
    (tmp_path / "nouveau.gif").write_bytes(b"x")
    assert len(lib.list()) == 1


def test_jamais_deux_fois_le_meme_d_affilee(lib):
    """Deux fois la même image passerait pour un bug."""
    premier = lib.pick()["name"]
    assert lib.pick()["name"] != premier


def test_avec_un_seul_meme_il_se_repete_quand_meme(tmp_path):
    (tmp_path / "seul.jpg").write_bytes(b"x")
    lib = MemeLibrary(tmp_path)
    assert lib.pick()["name"] == "seul.jpg"
    assert lib.pick()["name"] == "seul.jpg"


def test_un_indice_oriente_le_choix(lib):
    """« montre le meme du ping » doit tomber sur le bon."""
    for _ in range(5):
        assert lib.pick("le ping")["name"] == "azrael-blame-le-ping.jpg"


def test_un_indice_sans_correspondance_retombe_sur_le_hasard(lib):
    assert lib.pick("licorne quantique") is not None


# ── sécurité : les fichiers sont servis publiquement ──

def test_un_nom_ne_peut_pas_remonter_l_arborescence(lib, tmp_path):
    (tmp_path.parent / "secret.png").write_bytes(b"x")
    assert lib.resolve("../secret.png") is None


def test_un_nom_valide_est_resolu(lib):
    assert lib.resolve("requin_rage.png") is not None


def test_un_fichier_absent_ou_non_image_est_refuse(lib):
    assert lib.resolve("notes.md") is None
    assert lib.resolve("inconnu.png") is None
    assert lib.resolve("") is None


# ── widget ──

def test_le_widget_choisit_une_image_et_sa_description(tmp_path):
    from unittest.mock import MagicMock

    from bot.core.overlay_feed import OverlayFeed
    from bot.intelligence.overlay_narrator import OverlayNarrator

    (tmp_path / "azrael-blame-le-ping.jpg").write_bytes(b"x")
    feed = OverlayFeed()
    n = OverlayNarrator(feed, MagicMock(), lambda: True, memes=MemeLibrary(tmp_path))
    q = feed.subscribe()
    out = n.show_widget("meme", "")
    assert out["name"] == "azrael-blame-le-ping.jpg"
    ev = [e for e in (q.get_nowait() for _ in range(q.qsize())) if e["type"] == "widget"][0]
    assert ev["params"]["src"].endswith("azrael-blame-le-ping.jpg")
    assert ev["params"]["caption"] == "azrael blame le ping"


def test_le_widget_ne_montre_rien_si_le_dossier_est_vide(tmp_path):
    from unittest.mock import MagicMock

    from bot.core.overlay_feed import OverlayFeed
    from bot.intelligence.overlay_narrator import OverlayNarrator

    n = OverlayNarrator(OverlayFeed(), MagicMock(), lambda: True,
                        memes=MemeLibrary(tmp_path))
    assert n.show_widget("meme", "") is None


def test_un_nom_avec_espaces_est_encode_dans_l_url(tmp_path):
    """Sans encodage, l'overlay demanderait une URL tronquée au premier espace."""
    from unittest.mock import MagicMock

    from bot.core.overlay_feed import OverlayFeed
    from bot.intelligence.overlay_narrator import OverlayNarrator

    (tmp_path / "le chat de requin.png").write_bytes(b"x")
    feed = OverlayFeed()
    n = OverlayNarrator(feed, MagicMock(), lambda: True, memes=MemeLibrary(tmp_path))
    q = feed.subscribe()
    n.show_widget("meme", "")
    ev = [e for e in (q.get_nowait() for _ in range(q.qsize())) if e["type"] == "widget"][0]
    assert ev["params"]["src"].endswith("le%20chat%20de%20requin.png")


def test_le_webp_est_servi_comme_une_image(tmp_path):
    """Sans type explicite, l'overlay recevait `application/octet-stream`.

    L'image Docker (Python 3.12, sans /etc/mime.types) ignore `.webp` :
    `FileResponse` retombait alors sur le type générique. Le navigateur d'OBS
    renifle le contenu d'un `<img>` et affichait quand même, mais rien ne
    l'oblige — et le dossier de prod compte seize webp.
    """
    from bot.core.memes import media_type

    assert media_type(tmp_path / "requin.webp") == "image/webp"
    assert media_type(tmp_path / "requin.WEBP") == "image/webp"
    assert media_type(tmp_path / "requin.gif") == "image/gif"
    assert media_type(tmp_path / "requin.jpeg") == "image/jpeg"


@pytest.mark.asyncio
async def test_la_route_annonce_le_type_meme_sans_table_mime_systeme(tmp_path, monkeypatch):
    """Le test simule l'image Docker : `mimetypes` y ignore tout.

    Sans ce décor, le test passerait sur la machine de dev (Debian fournit
    /etc/mime.types, qui connaît `.webp`) et raterait le défaut là où il vit :
    dans le conteneur.
    """
    import starlette.responses

    from bot.dashboard.routes.overlay import get_meme

    # On patche la référence de starlette, pas `mimetypes.guess_type` : le module
    # importe le symbole directement, et patcher la table d'origine ne changeait
    # rien — le test passait alors même sur le code défaillant.
    monkeypatch.setattr(starlette.responses, "guess_type", lambda *a, **k: (None, None))
    (tmp_path / "requin.webp").write_bytes(b"x")
    state = type("W", (), {"memes": MemeLibrary(tmp_path)})()
    req = type("R", (), {"app": type("A", (), {"state": type("S", (), {"wally": state})()})()})()

    resp = await get_meme("requin.webp", req)
    assert resp.media_type == "image/webp"
