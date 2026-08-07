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
