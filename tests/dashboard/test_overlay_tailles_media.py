"""Les boîtes mesurées voyagent avec le layout, jusqu'à la page et au panneau.

Le calcul lui-même est vérifié dans `tests/test_memes_enveloppe.py`. Ici, le
chemin : le serveur seul peut mesurer le dossier de memes — la page tourne dans
OBS et le panneau dans un navigateur, ni l'un ni l'autre n'y a accès. Si la
valeur ne fait pas le trajet, les deux retombent sur la table écrite à la main et
tout le mécanisme ne sert à rien.
"""
from math import ceil

import pytest
from PIL import Image

from bot.core.memes import MemeLibrary
from bot.core.overlay_layout import BOITE_MEDIA_MAX, PASSE_PARTOUT_MEDIA
from bot.dashboard.routes import overlay as routes_overlay


@pytest.fixture(autouse=True)
def _cache_neuf():
    """Le cache des boîtes vit au niveau du module : sans ce ménage, un test
    servirait la mesure du dossier d'un autre."""
    routes_overlay._tailles_cache.update(signature=None, value={})
    yield
    routes_overlay._tailles_cache.update(signature=None, value={})


def _dossier(tmp_path, formes):
    for i, (l, h) in enumerate(formes):
        Image.new("RGB", (l, h), (10, 20, 30)).save(tmp_path / f"m{i}.png")
    return MemeLibrary(tmp_path)


def test_la_page_recoit_la_boite_mesuree(tmp_path, overlay_client_avec):
    """Que des paysages : la boîte doit être plus basse que large. C'est ce qui
    distingue une mesure d'un carré écrit en dur."""
    client = overlay_client_avec(memes=_dossier(tmp_path, [(600, 400), (900, 500)]))
    tailles = client.get("/api/public/overlay-layout").json()["tailles"]
    marge = PASSE_PARTOUT_MEDIA["meme"]
    media = BOITE_MEDIA_MAX - marge          # la place nette, hors passe-partout
    # La LARGEUR sature : les deux sont plus larges que hauts. La HAUTEUR vient
    # du moins allongé des deux (1,5) — c'est lui qui monte le plus haut une fois
    # ramené à la largeur. La prendre sur le plus allongé (1,8) donnerait une
    # boîte trop basse, et le meme le plus carré déborderait.
    assert tailles["meme"] == [media + marge, ceil(media / 1.5) + marge]
    assert tailles["meme"][1] < tailles["meme"][0]


def test_le_panneau_recoit_la_meme_boite_que_la_page(tmp_path, overlay_client_avec):
    """Deux valeurs différentes ici, et le repère du panneau annoncerait une
    boîte que la page ne rendrait pas — le défaut d'origine, réinstallé par le
    chemin de données."""
    client = overlay_client_avec(memes=_dossier(tmp_path, [(349, 774), (444, 235)]))
    page = client.get("/api/public/overlay-layout").json()["tailles"]
    panneau = client.get(
        "/api/admin/overlay/layout",
        headers={"Authorization": "Bearer testtoken"}).json()["tailles"]
    assert page == panneau
    # Les deux extrêmes saturent les deux axes : boîte carrée, et c'est un
    # résultat du dossier, pas une hypothèse.
    assert page["meme"][0] == page["meme"][1] == BOITE_MEDIA_MAX


def test_sans_bibliotheque_la_page_se_sert_quand_meme(overlay_client_avec):
    """La boîte calculée est un CONFORT. Un dossier absent ne doit pas priver
    l'overlay de son layout en plein live — la table du JS prend le relais."""
    r = overlay_client_avec(memes=None).get("/api/public/overlay-layout")
    assert r.status_code == 200
    assert r.json()["tailles"] == {}
    assert r.json()["scene"]["elements"]


def test_un_dossier_vide_ne_donne_pas_une_boite_nulle(tmp_path, overlay_client_avec):
    """`{}` plutôt que des zéros : un repère d'un pixel serait pire que
    l'estimation qu'il remplace."""
    tailles = overlay_client_avec(memes=MemeLibrary(tmp_path)).get(
        "/api/public/overlay-layout").json()["tailles"]
    assert tailles == {}


def test_la_boite_suit_lajout_dun_meme(tmp_path, overlay_client_avec):
    """L'owner dépose des memes quand il veut. Le cache doit lâcher prise sur la
    signature du dossier, sinon la boîte reste figée jusqu'au redémarrage — et
    « redémarrer le bot pour qu'une image apparaisse serait absurde »."""
    library = _dossier(tmp_path, [(600, 400)])
    client = overlay_client_avec(memes=library)
    avant = client.get("/api/public/overlay-layout").json()["tailles"]["meme"]
    # Un portrait très haut : la boîte doit grandir en hauteur.
    Image.new("RGB", (300, 900), (0, 0, 0)).save(tmp_path / "portrait.png")
    apres = client.get("/api/public/overlay-layout").json()["tailles"]["meme"]
    assert apres[1] > avant[1], f"boîte figée : {avant} -> {apres}"
