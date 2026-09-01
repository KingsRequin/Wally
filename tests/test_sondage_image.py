"""La carte PNG du sondage Discord."""
from __future__ import annotations

import io

import pytest

from bot.core.sondage import creer
from bot.core.sondage_image import POLICE, rendre

Image = pytest.importorskip("PIL.Image")


def _sondage(n: int = 3, **kw):
    s = creer("Quel jeu ce soir, sérieusement ?",
              [f"Option {i + 1}" for i in range(n)], channel_id=1, **kw)
    assert s is not None
    return s


def _ouvrir(octets: bytes):
    image = Image.open(io.BytesIO(octets))
    image.load()
    return image


def test_rend_un_png_lisible():
    image = _ouvrir(rendre(_sondage()))
    assert image.format == "PNG"
    assert image.width == 620 and image.height > 120


def test_la_hauteur_suit_le_nombre_d_options():
    petite = _ouvrir(rendre(_sondage(2))).height
    grande = _ouvrir(rendre(_sondage(9))).height
    assert grande > petite


def test_une_question_longue_passe_a_la_ligne():
    court = _ouvrir(rendre(_sondage())).height
    long = creer("Est-ce que " + "vraiment " * 12 + "?", ["a", "b"], channel_id=1)
    assert long is not None
    assert _ouvrir(rendre(long)).height > court


def _pixels_clairs(octets: bytes) -> int:
    """Combien de pixels sont allumés — les barres pleines dominent le compte.

    ⚠️ `convert("RGB")` JETTE l'alpha au lieu de composer : la piste des barres,
    blanche à 10 %, en ressortait blanc franc et tout comptait pour clair.
    """
    image = _ouvrir(octets)
    fond = Image.new("RGB", image.size, (0, 0, 0))
    fond.paste(image, mask=image.split()[3])
    return sum(1 for pixel in fond.getdata() if sum(pixel) > 260)


def test_le_sablier_se_vide_avec_le_temps():
    """Il restait plein tout du long : `ends_at` seul ne dit pas quelle FRACTION
    du temps a coulé — d'où la durée gardée à part."""
    s = _sondage(duree_s=600, maintenant=1_000.0)
    debut = _pixels_clairs(rendre(s, maintenant=1_010.0))
    fin = _pixels_clairs(rendre(s, maintenant=1_580.0))
    # Le sablier fait 568 × 5 px : ce qui s'éteint entre les deux, c'est lui.
    assert debut - fin > 1_500


def test_un_sondage_sans_duree_n_a_pas_de_sablier():
    sans = _pixels_clairs(rendre(_sondage()))
    avec = _pixels_clairs(rendre(_sondage(duree_s=600, maintenant=1_000.0),
                                 maintenant=1_000.0))
    assert avec - sans > 1_500


def test_les_votes_changent_l_image():
    s = _sondage()
    avant = rendre(s)
    s.voter("u1", 0)
    assert rendre(s) != avant


def test_le_rendu_est_deterministe():
    """Sans ça, chaque redessin produirait une pièce jointe différente pour la
    même donnée — et Discord rechargerait l'image pour rien."""
    s = _sondage(duree_s=600, maintenant=1_000.0)
    s.voter("u1", 1)
    assert rendre(s, maintenant=1_100.0) == rendre(s, maintenant=1_100.0)


def test_un_sondage_clos_se_rend_aussi():
    s = _sondage()
    s.voter("u1", 0)
    s.clos = True
    assert _ouvrir(rendre(s)).format == "PNG"


def test_sans_aucun_vote_les_barres_sont_vides():
    """Zéro vote sur zéro total : la division ne doit pas lever."""
    assert _ouvrir(rendre(_sondage())).format == "PNG"


def test_la_police_de_l_overlay_est_bien_la():
    """Fredoka n'existait qu'en .woff2, que Pillow ne sait pas lire : le .ttf
    committé à côté est ce qui donne au sondage le visage de l'overlay."""
    assert POLICE.exists()


def test_le_rendu_survit_a_l_absence_de_police(monkeypatch):
    import bot.core.sondage_image as module

    monkeypatch.setattr(module, "POLICE", module.POLICE.with_name("absente.ttf"))
    module._police.cache_clear()
    try:
        assert _ouvrir(rendre(_sondage())).format == "PNG"
    finally:
        module._police.cache_clear()
