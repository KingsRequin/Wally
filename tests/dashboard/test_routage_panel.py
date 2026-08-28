"""Le routeur par hash du panel admin, et sa cohérence avec la sidebar.

Ce que ces tests attrapent, et qu'aucun autre outil ne voyait : une entrée de
sidebar qui pointe vers une route absente de la table, ou une route dont le
panneau n'existe pas dans `index.html`. Les deux se traduisent en prod par un
clic qui ne fait RIEN — pas d'erreur JS, pas de log, une page qui reste sur la
précédente. C'est exactement la signature de panne que les garde-fous du projet
visent : quelque chose échoue, personne n'est prévenu.

Ils ne remplacent pas `scripts/smoke_front.py`, qui seul EXÉCUTE le JavaScript
et prouve qu'un panneau monte. Ils vérifient la table, pas le rendu.
"""
from __future__ import annotations

import pathlib
import re

import pytest

_STATIC = pathlib.Path(__file__).resolve().parents[2] / "bot" / "dashboard" / "static"


@pytest.fixture(scope="module")
def js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def routes(js: str) -> dict[str, dict[str, str]]:
    """La table `ROUTES` d'`app.js`, lue telle qu'elle est écrite."""
    bloc = re.search(r"^const ROUTES = \{$(.*?)^\};$", js, re.S | re.M)
    assert bloc, "table ROUTES introuvable dans app.js"
    trouvees: dict[str, dict[str, str]] = {}
    for cle, corps in re.findall(r"^  '([^']+)': \{$(.*?)^  \},$", bloc.group(1),
                                 re.S | re.M):
        champs = {}
        for nom in ("titre", "pane", "sub"):
            m = re.search(nom + r": '((?:[^'\\]|\\.)*)'", corps)
            if m:
                champs[nom] = m.group(1)
        trouvees[cle] = champs
    assert trouvees, "aucune route lue — le format de la table a changé"
    return trouvees


@pytest.fixture(scope="module")
def routes_sidebar(html: str) -> list[str]:
    return re.findall(r'data-route="([^"]+)"', html)


def test_chaque_entree_de_sidebar_a_sa_route(routes, routes_sidebar):
    """Une entrée qui pointe vers une route absente est un clic mort."""
    inconnues = [r for r in routes_sidebar if r not in routes]
    assert not inconnues, (
        f"entrées de sidebar sans route dans ROUTES : {inconnues}. "
        "Le clic ne ferait rien, en silence."
    )


def test_chaque_route_est_atteignable_depuis_la_sidebar(routes, routes_sidebar):
    """Une route sans entrée n'est accessible qu'en tapant l'URL à la main.

    Quand la fiche personne arrivera (`cerveau/personnes/{id}`, phase 4), elle
    fera exception : c'est une vue de détail, ouverte depuis une ligne de liste.
    Il faudra alors l'exclure ICI, explicitement, plutôt que d'assouplir la règle.
    """
    orphelines = [r for r in routes if r not in routes_sidebar]
    assert not orphelines, (
        f"routes absentes de la sidebar : {orphelines}"
    )


def test_chaque_route_designe_un_panneau_qui_existe(routes, html):
    """`pane` nomme un `<div id="tab-…">` d'`index.html`. Sinon la page reste
    vide sans que rien ne le dise."""
    presents = set(re.findall(r'id="tab-([^"]+)"', html))
    manquants = {
        cle: champs["pane"]
        for cle, champs in routes.items()
        if champs.get("pane") and champs["pane"] not in presents
    }
    assert not manquants, f"routes dont le panneau n'existe pas : {manquants}"


def test_les_anciens_hash_retombent_sur_une_route_valide(js, routes):
    """Un signet posé avant la refonte doit ouvrir la bonne page, pas la
    page d'accueil."""
    bloc = re.search(r"^const ROUTES_LEGACY = \{$(.*?)^\};$", js, re.S | re.M)
    assert bloc, "table ROUTES_LEGACY introuvable"
    paires = re.findall(r"^  '([^']+)':\s+'([^']+)',$", bloc.group(1), re.M)
    assert paires, "aucune redirection lue"
    casses = {vieux: cible for vieux, cible in paires if cible not in routes}
    assert not casses, f"redirections vers une route inexistante : {casses}"

    # Les sept onglets d'avant la refonte, plus les quatre noms déjà redirigés.
    anciens = {vieux for vieux, _ in paires}
    attendus = {
        "admin-parametres", "admin-memoire", "admin-actions", "admin-prompts",
        "admin-scene", "admin-systeme", "admin-voice",
        "admin-config", "admin-logs", "admin-twitch", "admin-overlay",
    }
    assert attendus <= anciens, (
        f"anciens hash oubliés : {sorted(attendus - anciens)}"
    )


def test_la_route_par_defaut_existe(js, routes):
    m = re.search(r"const ROUTE_DEFAUT = '([^']+)';", js)
    assert m, "ROUTE_DEFAUT introuvable"
    assert m.group(1) in routes, f"route par défaut inconnue : {m.group(1)}"


def test_la_sidebar_navigue_par_lien_pas_par_onclick(html):
    """Le `href` est ce qui rend l'URL partageable, le rechargement fidèle et le
    clic-milieu possible. Un `onclick` ne donne rien de tout ça."""
    nav = re.search(r'<nav class="sidebar-nav".*?</nav>', html, re.S)
    assert nav, "sidebar-nav introuvable"
    entrees = re.findall(r'<a class="sidebar-item"[^>]*>', nav.group(0))
    assert entrees, "aucune entrée de sidebar"
    for balise in entrees:
        assert "onclick" not in balise, f"entrée pilotée par onclick : {balise}"
        route = re.search(r'data-route="([^"]+)"', balise)
        href = re.search(r'href="([^"]+)"', balise)
        assert route and href, f"entrée sans data-route ou sans href : {balise}"
        assert href.group(1) == "#/" + route.group(1), (
            f"href et data-route désaccordés : {balise}"
        )


def test_le_routeur_ecrit_dans_un_titre_qui_existe(html, js):
    """`_appliquerRoute` remplit `#page-title` et `#page-sub`. Absents, le titre
    de page ne s'afficherait jamais — et rien ne le signalerait."""
    assert 'id="page-head"' in html
    for ident in ("page-title", "page-sub"):
        assert f'id="{ident}"' in html, f"#{ident} absent d'index.html"
        assert f"getElementById('{ident}')" in js, f"#{ident} jamais écrit"


def test_showtab_a_bien_disparu(js, html):
    """L'ancien aiguillage ne doit pas survivre à côté du routeur : deux
    chemins vers la même page, c'est deux comportements qui divergent."""
    assert "function showTab" not in js
    assert "showTab(" not in html
