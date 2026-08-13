"""Le sous-onglet « Comptes Apex » est-il branché de bout en bout ?

Un onglet se câble à QUATRE endroits d'`app.js` : la pastille, le panneau qui
la reçoit, la branche du sélecteur, et la fonction de rendu. En rater un donne
une pastille qui ne fait rien — sans erreur, sans trace, et personne ne le voit
tant qu'on ne clique pas dessus.

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
    'data-subtab="apex"',                    # la pastille
    'id="memoire-sub-apex"',                 # le panneau qui la reçoit
    "subtab === 'apex'",                     # la branche du sélecteur
    "function renderApexProfilesTab",        # la fonction de rendu
])
def test_le_sous_onglet_est_cable(source, morceau):
    assert morceau in source


def test_les_classes_css_du_registre_existent(source):
    """Une classe posée par le JS mais absente du CSS donne un écran nu."""
    css = STYLE.read_text(encoding="utf-8")
    for classe in ("apex-grid", "apex-card", "apex-name-chip", "apex-owner",
                   "apex-link-form", "apex-mini-btn"):
        assert f".{classe}" in css, f"classe {classe} posée par le JS, absente du CSS"


def test_les_routes_apex_appelees_par_le_front_existent():
    """Chaque `/api/admin/apex/...` du JS doit correspondre à une route montée."""
    from bot.dashboard.app import create_dashboard_app
    from tests.test_dashboard_apex_profils import _make_config
    from unittest.mock import MagicMock
    from bot.dashboard.state import AppState

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
