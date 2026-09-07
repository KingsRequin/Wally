"""Le widget `carte` : l'enum de l'outil, la résolution, le refus, la trace."""
import json
from unittest.mock import MagicMock

import pytest

from bot.core import tcg_cartes
from bot.discord.handlers import run_overlay_tool
from bot.intelligence.overlay_narrator import OVERLAY_TOOL_SPEC


def test_carte_est_dans_l_enum_de_l_outil():
    props = OVERLAY_TOOL_SPEC["function"]["parameters"]["properties"]
    assert "carte" in props["widget"]["enum"]
    assert "carte" in props["widget"]["description"]


def test_le_parametre_personne_est_decrit():
    """Sans description, le modèle remplit `personne` au hasard — ou l'oublie."""
    props = OVERLAY_TOOL_SPEC["function"]["parameters"]["properties"]
    assert "personne" in props
    assert "carte" in props["personne"]["description"]


def test_la_spec_reste_serialisable_en_json():
    """Les fournisseurs la refusent sinon, et TOUS les appels d'outil échouent
    — pas seulement ceux de l'overlay."""
    assert json.loads(json.dumps(OVERLAY_TOOL_SPEC)) == OVERLAY_TOOL_SPEC


@pytest.fixture
def bot_overlay():
    """Un bot dont le narrateur accepte tout et retient ce qu'on lui passe."""
    recu: dict = {}
    narrateur = MagicMock()
    narrateur.show_widget.side_effect = (
        lambda w, c, **kw: (recu.update({"widget": w, **kw}) or {"kind": w}))
    narrateur.is_active.return_value = True
    bot = MagicMock()
    bot.overlay_narrator = narrateur
    return bot, recu


def test_un_nom_inconnu_est_refuse_en_nommant_ce_qui_existe(bot_overlay):
    """Sans la liste, Wally réessaie au hasard — et finit par annoncer une
    carte qui n'existe pas."""
    bot, recu = bot_overlay
    reponse = json.loads(run_overlay_tool(bot, {"widget": "carte", "personne": "toto"}))
    assert reponse["status"] == "rejected"
    for nom in tcg_cartes.noms_disponibles():
        assert nom in reponse["message"]
    assert not recu, "rien ne doit être publié sur un refus"


def test_un_alias_resout_vers_la_bonne_carte(bot_overlay):
    bot, recu = bot_overlay
    reponse = json.loads(
        run_overlay_tool(bot, {"widget": "carte", "personne": "clacker"}))
    assert reponse["status"] == "ok"
    assert recu["nom"] == "CLAKER"


def test_les_valeurs_voyagent_dans_l_evenement(bot_overlay):
    """Le widget ne doit rien aller chercher : tout ce qu'il dessine arrive
    avec l'événement du bus."""
    bot, recu = bot_overlay
    run_overlay_tool(bot, {"widget": "carte", "personne": "rhae"})
    for champ in ("nom", "classe", "ultime", "description", "ambiance",
                  "cout", "atk", "pv", "aura", "accent", "hero", "fond"):
        assert champ in recu, champ
    # rhae est la seule à deux visuels : son calque de survol doit suivre.
    assert recu["hero3d"] is not None


def test_le_pseudo_demande_ne_part_pas_au_widget(bot_overlay):
    """`personne` est consommé par la résolution. Le laisser passer donnerait
    au builder un paramètre qu'il ignore, et qui traînerait dans le tampon SSE
    rejoué à chaque reconnexion d'OBS."""
    bot, recu = bot_overlay
    run_overlay_tool(bot, {"widget": "carte", "personne": "lilith"})
    assert "personne" not in recu


def test_l_affichage_est_consigne_avec_le_nom(bot_overlay, monkeypatch):
    """`overlay_feed.widget()` ne consigne que le TYPE du widget. Sans cette
    trace, Wally montre une carte et ne sait pas de qui elle était."""
    bot, _ = bot_overlay
    vues: list[str] = []
    monkeypatch.setattr("bot.discord.handlers.note_act", vues.append)
    run_overlay_tool(bot, {"widget": "carte", "personne": "azrael"})
    assert any("AZRAËL" in v for v in vues), vues


def test_carte_est_connue_du_narrateur():
    """🚨 Sixième verrou du chantier, et le plus discret : `show_widget` refuse
    tout ce qui n'est pas dans `_WIDGETS`, et `widgets_disponibles` en dérive
    le filtrage de l'enum. Absente d'ici, la valeur aurait disparu de l'outil —
    Wally ne l'aurait jamais vue, et rien ne l'aurait dit.

    Le lien est vérifié dans les deux sens : l'outil ne doit pas proposer un
    widget que le narrateur ne sait pas afficher, et inversement.
    """
    from bot.intelligence.overlay_narrator import OverlayNarrator

    assert "carte" in OverlayNarrator._WIDGETS
    assert "carte" in OverlayNarrator._DIRECT_WIDGETS
    enum = OVERLAY_TOOL_SPEC["function"]["parameters"]["properties"]["widget"]["enum"]
    assert set(enum) <= set(OverlayNarrator._WIDGETS), (
        set(enum) - set(OverlayNarrator._WIDGETS))
