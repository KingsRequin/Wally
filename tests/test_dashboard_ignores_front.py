"""Le sous-onglet « Ignorés » est-il branché de bout en bout ?

Un sous-onglet se câble à TROIS endroits d'`app.js` — la pastille, le panneau
qui la reçoit, la branche du sélecteur — plus la fonction de rendu. En rater un
donne une pastille qui ne fait rien : sans erreur, sans trace, et personne ne
le voit tant qu'on ne clique pas dessus.

Ces tests lisent le fichier en TEXTE : ils ne prouvent pas que le panneau
MONTE. C'est `scripts/smoke_front.py` qui l'exécute, et c'est lui qui a
attrapé le panneau vide la première fois (la route vivait dans l'image, pas
dans le bind-mount).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
APP_JS = RACINE / "bot" / "dashboard" / "static" / "app.js"
STYLE = RACINE / "bot" / "dashboard" / "static" / "style.css"
SMOKE = RACINE / "scripts" / "smoke_front.py"


@pytest.fixture(scope="module")
def source() -> str:
    return APP_JS.read_text(encoding="utf-8")


@pytest.mark.parametrize("morceau", [
    'data-subtab="ignores"',                 # la pastille
    'id="memoire-sub-ignores"',              # le panneau qui la reçoit
    "subtab === 'ignores'",                  # la branche du sélecteur
    "function renderIgnoresTab",             # la fonction de rendu
])
def test_le_sous_onglet_est_cable(source, morceau):
    assert morceau in source


def test_les_classes_css_posees_par_le_panneau_existent(source):
    """Une classe posée par le JS mais absente du CSS donne un écran nu."""
    css = STYLE.read_text(encoding="utf-8")
    for classe in ("apex-link-form", "apex-hint", "apex-link-row",
                   "apex-people-box", "apex-people-menu", "apex-people-item",
                   "apex-people-nom", "apex-people-id", "apex-people-vide",
                   "twitch-channel-card"):
        assert f".{classe}" in css, f"classe {classe} posée par le JS, absente du CSS"


def test_le_socle_nest_pas_recopie_dans_le_javascript(source):
    """LE point du panneau. Une liste de bots dupliquée au front diverge du jour
    où quelqu'un en ajoute un au module Python, et le panneau annonce alors le
    contraire du code qui décide."""
    from bot.twitch.handlers import _KNOWN_BOTS

    presents = sorted(b for b in _KNOWN_BOTS if f'"{b}"' in source or f"'{b}'" in source)
    assert not presents, f"socle recopié dans app.js : {presents}"


def test_lancien_panneau_twitch_ne_survit_pas_en_double(source):
    """Deux écrans pour la même liste, c'est deux écrans à tenir en phase — et
    celui qu'on oublie affiche un état périmé sans le dire."""
    assert "ignored-users-section" not in source
    assert "renderIgnoredUsers" not in source
    # …mais l'ancien emplacement doit RENVOYER au nouveau, sinon on le cherche.
    # Le nouveau, depuis la refonte, est la page Personnes et son filtre.
    assert "Personnes</strong>, filtre « Ignorés »" in source
    assert "Mémoire → Ignorés" not in source, (
        "ce chemin n'existe plus : l'onglet Mémoire n'a plus de sous-onglet "
        "Utilisateurs, et « Ignorés » est devenu un filtre de Personnes"
    )


def test_les_routes_appelees_par_le_panneau_existent():
    """Une route renommée d'un côté et pas de l'autre passe tous les tests
    Python du monde et ne casse que dans le navigateur."""
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
    # Les trois routes dont ce panneau dépend, y compris celles qu'il ne fait
    # que réutiliser : c'est justement une route d'ailleurs qui se renomme sans
    # qu'on pense à ce panneau-ci.
    for url in ("/api/admin/ignored", "/api/admin/chat-bans",
                "/api/admin/config", "/api/admin/apex/personnes"):
        assert f"'{url}'" in source, f"{url} n'est plus appelée par app.js"
        assert any(m == url or m.startswith(url + "/{") for m in montees), \
            f"{url} appelée par app.js, aucune route montée derrière"


def test_le_smoke_test_parcourt_le_nouveau_sous_onglet():
    """Un panneau hors du parcours du smoke test peut mourir sans un bruit —
    les sous-onglets de Mémoire y ont manqué jusqu'ici."""
    smoke = SMOKE.read_text(encoding="utf-8")
    assert '("Ignorés", "memoire-sub-ignores")' in smoke
    # Et ses voisins avec lui : c'est la famille entière qui n'était pas vue.
    #
    # `memoire-sub-users` a quitté cette liste le 2026-08-28 : il est devenu la
    # page Personnes, que `_verifier_personnes` parcourt à part — annuaire,
    # filtres, ouverture d'une fiche et rechargement. Le panneau n'est donc pas
    # sorti du parcours, il a changé de nom et de porte d'entrée.
    for ident in ("memoire-sub-global", "memoire-sub-notes",
                  "memoire-sub-apex", "memoire-sub-self", "memoire-sub-dashboard"):
        assert ident in smoke, f"{ident} hors du parcours du smoke test"
    assert "_verifier_personnes" in smoke, (
        "la page Personnes a remplacé l'onglet Utilisateurs et doit être "
        "parcourue, sinon l'annuaire peut mourir sans un bruit"
    )


def test_les_ids_du_smoke_test_existent_vraiment(source):
    """Un id attendu par le smoke test mais absent du JS le ferait échouer en
    annonçant un panneau mort qui n'a jamais existé sous ce nom."""
    attendus = set(re.findall(r'\("[^"]+", "(memoire-sub-[a-z]+)"\)',
                              SMOKE.read_text(encoding="utf-8")))
    assert attendus, "aucun id relevé — le test ne prouverait rien"
    for ident in attendus:
        assert f'id="{ident}"' in source, f"{ident} attendu par le smoke test, absent d'app.js"
