"""La boîte des memes est CALCULÉE depuis le dossier, pas écrite à la main.

La règle, dans les mots de l'owner : « prends la plus grande image en hauteur et
la plus grande en largeur, et ça définit la box ».

Appliquée aux FICHIERS, elle est inapplicable : le dossier réel monte à
2100 × 2100, plus grand que le canvas 1920 × 1080. Appliquée aux tailles
AFFICHÉES — chaque meme réduit pour tenir — elle est exacte, et c'est elle qui
est vérifiée ici.

Ce qui compte, et qu'un chiffre écrit à la main ne donnerait jamais : la boîte
ne réserve QUE ce que le dossier peut atteindre. Un dossier sans portrait rend
une boîte plus basse que large, sans que personne ne retouche quoi que ce soit.
Le dossier de production, lui, contient les deux extrêmes (0,45 et 1,89) : il
sature les deux axes, et la boîte y est carrée. Un test qui ne regarderait que
ce cas-là ne saurait pas distinguer « calculé » de « carré en dur ».
"""
from pathlib import Path

import pytest

from bot.core.memes import MemeLibrary

PIL = pytest.importorskip("PIL.Image")


def _image(dossier: Path, nom: str, largeur: int, hauteur: int) -> None:
    PIL.new("RGB", (largeur, hauteur), (10, 20, 30)).save(dossier / nom)


def test_un_dossier_aux_deux_extremes_donne_une_boite_carree(tmp_path):
    """Le cas de la production : un portrait très haut et un paysage très large
    saturent chacun un axe."""
    _image(tmp_path, "portrait.png", 349, 774)     # 0,45
    _image(tmp_path, "paysage.png", 444, 235)      # 1,89
    assert MemeLibrary(tmp_path).enveloppe_rendue(366) == (366, 366)


def test_un_dossier_sans_portrait_donne_une_boite_plus_basse():
    """LE test du lot. Si la boîte était carrée par principe, elle réserverait
    ici 366 px de haut pour un contenu qui n'en atteint jamais que 244 — 33 % de
    hauteur vide, exactement le défaut qu'on corrige."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        dossier = Path(d)
        _image(dossier, "a.png", 600, 400)     # 1,50
        _image(dossier, "b.png", 900, 500)     # 1,80
        # Le plus « haut » des deux, ramené à 366 de large, fait 244.
        assert MemeLibrary(dossier).enveloppe_rendue(366) == (366, 244)


def test_la_boite_ne_depasse_jamais_le_plafond(tmp_path):
    """Un meme de 2100 px de côté — il y en a un dans le dossier réel — ne doit
    pas emporter la boîte au-delà de ce qu'on accepte d'afficher."""
    _image(tmp_path, "enorme.png", 2100, 2100)
    assert MemeLibrary(tmp_path).enveloppe_rendue(400) == (400, 400)


def test_les_petits_memes_comptent_a_leur_taille_agrandie(tmp_path):
    """Le rotateur grossit les petits jusqu'à ×2 pour qu'ils ne paraissent pas
    perdus. Ne pas en tenir compte donnerait une boîte trop étroite pour eux."""
    _image(tmp_path, "petit.png", 100, 80)
    lib = MemeLibrary(tmp_path)
    assert lib.enveloppe_rendue(366) == (100, 80)          # laissé tel quel
    assert lib.enveloppe_rendue(366, 2.0) == (200, 160)     # grossi ×2


def test_un_dossier_vide_ne_dit_rien_plutot_que_zero(tmp_path):
    """`None`, jamais `(0, 0)` : « je ne sais pas » ne s'écrit pas en chiffres.
    L'appelant garde sa table — une boîte nulle serait un repère d'un pixel."""
    assert MemeLibrary(tmp_path).enveloppe_rendue(366) is None
    assert MemeLibrary(tmp_path / "nexiste-pas").enveloppe_rendue(366) is None


def test_un_fichier_illisible_ne_prive_pas_les_autres_de_leur_boite(tmp_path):
    """Un meme tronqué en cours de copie ne doit pas faire retomber TOUT le
    dossier sur la table."""
    _image(tmp_path, "bon.png", 600, 400)
    (tmp_path / "casse.png").write_bytes(b"ce n'est pas une image")
    assert MemeLibrary(tmp_path).enveloppe_rendue(366) == (366, 244)


def test_une_video_ne_compte_pas_mais_ne_casse_rien(tmp_path):
    """Ses dimensions ne se lisent pas sans décodeur. Sans danger : la boîte la
    borne à son tour (`max-width: 100%`), donc elle ne débordera pas."""
    _image(tmp_path, "bon.png", 600, 400)
    (tmp_path / "clip.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    assert MemeLibrary(tmp_path).enveloppe_rendue(366) == (366, 244)


def test_un_plafond_absurde_ne_rend_rien(tmp_path):
    _image(tmp_path, "bon.png", 600, 400)
    assert MemeLibrary(tmp_path).enveloppe_rendue(0) is None
    assert MemeLibrary(tmp_path).enveloppe_rendue(-10) is None


def test_le_dossier_reel_sature_ses_deux_axes():
    """Sur les memes de production : les deux extrêmes existent, donc la boîte
    est carrée — et c'est un RÉSULTAT, pas une hypothèse de départ."""
    dossier = Path("data/memes")
    if not dossier.is_dir():
        pytest.skip("dossier de memes absent")
    env = MemeLibrary(dossier).enveloppe_rendue(366, 2.0)
    assert env == (366, 366)
