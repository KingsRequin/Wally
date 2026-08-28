"""Le registre « Comptes Apex » est-il branché de bout en bout ?

Il était un sous-onglet de Mémoire ; depuis la refonte du 2026-08-28, c'est une
SECTION de la page Personnes — « Comptes Apex » y est devenu un filtre de
l'annuaire, et son formulaire de liaison une section ancrée au sommaire.

Le câblage a changé de forme, pas de nature : une section se déclare à trois
endroits — le conteneur dans le HTML de la page, l'ancre du sommaire, et
l'appel qui la remplit. En rater un donne un écran nu ou une ancre qui ne mène
nulle part : sans erreur, sans trace, et personne ne le voit tant qu'on ne
descend pas jusque-là.

Le second test compare les URL appelées par le front aux routes réellement
déclarées : une route renommée d'un côté et pas de l'autre passe tous les tests
Python du monde et ne casse que dans le navigateur.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static" / "app.js"
STYLE = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static" / "style.css"


@pytest.fixture(scope="module")
def source() -> str:
    return APP_JS.read_text(encoding="utf-8")


@pytest.mark.parametrize("morceau", [
    "['pers-apex', 'Lier un compte Apex']",                    # l'ancre du sommaire
    'id="pers-apex"',                                          # le conteneur
    "renderApexProfilesTab(document.getElementById('pers-apex'))",  # l'appel
    "function renderApexProfilesTab",                          # la fonction de rendu
])
def test_la_section_est_cablee(source, morceau):
    assert morceau in source, f"chaînon manquant du câblage : {morceau}"


def test_lancien_sous_onglet_ne_survit_pas(source):
    """Deux chemins vers le même registre, c'est deux écrans à tenir en phase —
    et celui qu'on oublie affiche un état périmé sans le dire."""
    assert "memoire-sub-apex" not in source
    assert 'data-subtab="apex"' not in source


def test_les_classes_css_du_registre_existent(source):
    """Une classe posée par le JS mais absente du CSS donne un écran nu."""
    css = STYLE.read_text(encoding="utf-8")
    for classe in ("apex-grid", "apex-card", "apex-name-chip", "apex-owner",
                   "apex-link-form", "apex-mini-btn", "apex-orphelin",
                   "apex-people-box", "apex-people-menu", "apex-people-item",
                   "apex-people-via"):
        assert f".{classe}" in css, f"classe {classe} posée par le JS, absente du CSS"


def test_les_routes_apex_appelees_par_le_front_existent():
    """Chaque `/api/admin/apex/...` du JS doit correspondre à une route montée."""
    from unittest.mock import MagicMock

    from bot.dashboard.app import create_dashboard_app
    from bot.dashboard.state import AppState
    from tests.test_dashboard_apex_profils import _make_config

    emotion = MagicMock()
    emotion.get_state.return_value = {}
    app = create_dashboard_app(AppState(
        config=_make_config(), db=MagicMock(), emotion=emotion, memory=MagicMock(),
        persona=MagicMock(), primary_llm=MagicMock(), secondary_llm=MagicMock(),
        image_client=MagicMock(), token_manager=MagicMock(), twitch_api=None,
        discord_bot=None, twitch_bot=None,
    ))
    montees = {r.path for r in app.routes if hasattr(r, "path")}

    source = APP_JS.read_text(encoding="utf-8")
    appelees = set(re.findall(r"['\"](/api/admin/apex/[^'\"?]*)", source))
    assert appelees, "aucun appel trouvé — le test ne prouverait rien"

    for url in appelees:
        # Le front concatène des identifiants : on compare sur le préfixe
        # littéral, en acceptant qu'une route monte un paramètre derrière.
        assert any(
            m == url.rstrip("/") or m.startswith(url.rstrip("/") + "/{")
            for m in montees
        ), f"{url} appelée par app.js, aucune route montée derrière"
