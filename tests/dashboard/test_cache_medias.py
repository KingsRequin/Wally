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


def test_aucun_max_age_long_sur_les_medias():
    """Nos noms de fichiers sont STABLES : `generer_illustrations_tcg.py`
    réécrit `tcg-azrael-hero.avif` en place. Un `max-age` long, et pire
    `immutable`, figerait une illustration retouchée dans le navigateur de
    chaque visiteur jusqu'à expiration.
    """
    entete = _entete_cache("assets/tcg-azrael-hero.avif")
    assert "immutable" not in entete
    assert "max-age" not in entete
