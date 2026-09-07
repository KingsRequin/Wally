"""Une illustration n'est pas du code : elle doit pouvoir être revalidée.

`no-store` interdit AU NAVIGATEUR de garder quoi que ce soit. Posé sur tout
`public-ui/`, il fait retélécharger ~1 Mo d'illustrations à chaque visite de
`/tcg` — mesuré le 2026-09-07 — et le referait à chaque affichage de carte sur
l'overlay, qui tourne en continu dans OBS.

Le `no-store` reste sur le HTML, le JS et le CSS : c'est LUI qui rend le front
modifiable sans rebuild, et le retirer ferait servir du JavaScript périmé après
une correction.
"""
import pytest

from bot.dashboard.app import _entete_cache


@pytest.mark.parametrize("chemin", [
    "assets/tcg-azrael-hero.avif",
    "assets/tcg-claker-fond.webp",
    "vendor/archivo-black-400.woff2",
    "wally.webm",
    "ASSETS/EN-MAJUSCULES.PNG",
])
def test_les_medias_sont_revalidables(chemin):
    """`no-cache` fait REVALIDER, il n'interdit pas de garder : le navigateur
    envoie son ETag et reçoit un 304 sans corps."""
    entete = _entete_cache(chemin)
    assert "no-store" not in entete
    assert "no-cache" in entete


@pytest.mark.parametrize("chemin", [
    "index.html",
    "app.js",
    "style.css",
    "pages/tcg.js",
    "partage/tcg-carte.css",
    "",
])
def test_le_code_du_front_n_est_jamais_garde(chemin):
    assert "no-store" in _entete_cache(chemin)


def test_les_entetes_du_site_public_sont_bien_servies(overlay_client):
    """Cloudflare IGNORE `Cache-Control` sur une image et pose le sien : un
    `no-cache` ressortait en `max-age=14400` en prod le 2026-09-07. Ce sont
    `CDN-Cache-Control` et son équivalent Cloudflare qui tranchent pour l'edge.

    On lit la RÉPONSE, jamais le source de la classe : un test qui cherche une
    chaîne dans une implémentation passe encore le jour où l'en-tête est posé
    au mauvais endroit, ou écrasé deux lignes plus bas.
    """
    image = overlay_client.get("/assets/tcg-azrael-hero.avif")
    assert image.status_code == 200
    assert image.headers["cache-control"] == "no-cache"
    assert image.headers["cdn-cache-control"] == "no-cache"
    assert image.headers["cloudflare-cdn-cache-control"] == "no-cache"

    code = overlay_client.get("/app.js")
    assert code.status_code == 200
    assert "no-store" in code.headers["cache-control"]
    assert "no-store" in code.headers["cdn-cache-control"]


def test_une_route_spa_inconnue_ne_fait_pas_garder_du_html(overlay_client):
    """`/route-inconnue.png` retombe sur `index.html`. Poser `no-cache` parce
    que le CHEMIN finit par `.png` ferait garder du HTML sous une extension
    d'image — et le site resterait figé sur une version pour ses visiteurs.
    """
    r = overlay_client.get("/route-inconnue.png")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "no-store" in r.headers["cache-control"]


def test_la_police_vendoree_est_servie_comme_une_police(overlay_client):
    """`mimetypes` ignore `.woff2` dans l'image Docker, comme il ignorait
    `.webp` puis `.avif` — troisième fois le même trou.
    """
    r = overlay_client.get("/vendor/archivo-black-400.woff2")
    assert r.status_code == 200
    assert r.headers["content-type"] == "font/woff2"
    assert r.headers["cache-control"] == "no-cache"


def test_aucun_max_age_long_sur_les_medias():
    """Nos noms de fichiers sont STABLES : `generer_illustrations_tcg.py`
    réécrit `tcg-azrael-hero.avif` en place. Un `max-age` long, et pire
    `immutable`, figerait une illustration retouchée dans le navigateur de
    chaque visiteur jusqu'à expiration.
    """
    entete = _entete_cache("assets/tcg-azrael-hero.avif")
    assert "immutable" not in entete
    assert "max-age" not in entete


def test_les_polices_du_dashboard_sont_revalidables(overlay_client):
    """🚨 Régression introduite le 2026-09-07 en vendorant Inter : les polices
    du panneau vivent sous `/static`, où `NoCacheStaticFiles` posait `no-store`
    sans distinction. 260 ko repartaient à CHAQUE ouverture du panneau, là où
    Google en servait 48 cachés un an — la dépendance externe était supprimée
    et le réseau y perdait.
    """
    r = overlay_client.get("/static/vendor/inter-400.woff2")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["cdn-cache-control"] == "no-cache"


def test_le_code_du_dashboard_reste_non_garde(overlay_client):
    """Le pendant : `/static/app.js` doit rester corrigible sans rebuild."""
    r = overlay_client.get("/static/app.js")
    assert r.status_code == 200
    assert "no-store" in r.headers["cache-control"]
    assert "no-store" in r.headers["cdn-cache-control"]
