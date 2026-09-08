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
    """L'outil transmet la CLÉ résolue, et rien d'autre : c'est `show_widget`
    qui relit la fiche dans le registre (cf.
    `test_la_carte_publiee_sur_le_bus_porte_VRAIMENT_ses_valeurs`)."""
    bot, recu = bot_overlay
    reponse = json.loads(
        run_overlay_tool(bot, {"widget": "carte", "personne": "clacker"}))
    assert reponse["status"] == "ok"
    assert recu["carte"] == "claker"


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


def test_sans_nom_une_carte_est_tiree(bot_overlay):
    """« montre une carte » sans préciser qui doit marcher, comme pour un meme."""
    bot, recu = bot_overlay
    reponse = json.loads(run_overlay_tool(bot, {"widget": "carte"}))
    assert reponse["status"] == "ok"
    assert recu["carte"] in tcg_cartes.CARTES


def test_un_nom_vide_ou_blanc_vaut_pas_de_nom(bot_overlay):
    """Le modèle remplit parfois un paramètre facultatif d'une chaîne vide.
    La traiter comme un nom introuvable refuserait un appel légitime."""
    bot, recu = bot_overlay
    for vide in ("", "   ", None):
        recu.clear()
        reponse = json.loads(
            run_overlay_tool(bot, {"widget": "carte", "personne": vide}))
        assert reponse["status"] == "ok", vide
        assert recu.get("carte") in tcg_cartes.CARTES


def test_un_nom_introuvable_n_est_JAMAIS_remplace_par_un_tirage(bot_overlay):
    """🚨 Le point qui compte. Tirer au hasard sur un nom qu'on n'a pas trouvé
    montrerait la carte de quelqu'un d'AUTRE que celui dont on parlait, devant
    les viewers — et Wally l'annoncerait sous le nom demandé.
    """
    bot, recu = bot_overlay
    reponse = json.loads(
        run_overlay_tool(bot, {"widget": "carte", "personne": "quelquun-dautre"}))
    assert reponse["status"] == "rejected"
    assert not recu, "rien ne doit partir à l'écran"


def test_le_tirage_epuise_le_registre_avant_de_repeter():
    """Avec quatre cartes, un `random.choice` en répéterait une une fois sur
    quatre — visible tout de suite sur un stream. C'est le défaut payé sur le
    pendu (deux « peacekeeper » d'affilée).

    ⚠️ Un sac NEUF, et non le singleton du module : celui-ci est partagé avec
    les autres tests, qui en consomment. La première fenêtre observée y serait
    déjà entamée, et le test échouerait selon l'ORDRE d'exécution.
    """
    from bot.core.tirage import SacSansRemise

    n = len(tcg_cartes.CARTES)
    sac = SacSansRemise(lambda: list(tcg_cartes.CARTES))
    tires = [sac.tirer() for _ in range(n)]
    assert len(set(tires)) == n, tires


def test_le_tirage_ne_repete_pas_a_la_jointure_des_sacs():
    """Le seul endroit où le sans-remise ne protège de rien : la dernière du
    sac suivie de la première du suivant."""
    from bot.core.tirage import SacSansRemise

    sac = SacSansRemise(lambda: list(tcg_cartes.CARTES))
    suite = [sac.tirer() for _ in range(len(tcg_cartes.CARTES) * 6)]
    doublons = [(a, b) for a, b in zip(suite, suite[1:]) if a == b]
    assert not doublons, doublons


def _narrateur_qui_publie():
    """Un narrateur réel, dont on intercepte le seul flux de sortie.

    🚨 Les tests précédents s'arrêtaient à `show_widget`, remplacé par un
    MagicMock : ils voyaient les paramètres ENTRER et jamais ce qui SORT. Or
    `show_widget` filtre ses paramètres widget par widget, par liste blanche —
    la carte n'avait pas de branche et partait VIDE sur le bus. À l'écran :
    le cadre, « AZRAËL » par défaut, ATK 0/PV 0/AURA 0, et des images
    cherchées à `undefined.avif`.
    """
    from bot.intelligence.overlay_narrator import OverlayNarrator

    publie: dict = {}
    narrateur = OverlayNarrator.__new__(OverlayNarrator)
    narrateur._refus_motif = ""
    narrateur._refus_cible = ""
    narrateur._feed = MagicMock()
    narrateur._feed.widget.side_effect = (
        lambda kind, **p: publie.update({"kind": kind, **p}))
    narrateur._live = lambda: True
    narrateur._widget_affichable = lambda w: True
    narrateur.game_already_running = lambda w, **kw: None
    narrateur._mark_spoken = lambda: None
    return narrateur, publie


def test_la_carte_publiee_sur_le_bus_porte_VRAIMENT_ses_valeurs():
    """Le test qui manquait, et qui aurait vu le défaut : on lit ce qui part
    sur le flux, pas ce qu'on a passé à `show_widget`."""
    narrateur, publie = _narrateur_qui_publie()
    rendu = narrateur.show_widget("carte", "", carte="lilith")

    assert rendu is not None, "la carte a été refusée"
    assert publie["kind"] == "carte"
    assert publie["nom"] == "LILITH"
    # Les stats : c'est ce que l'owner a vu manquer à l'écran.
    assert (publie["cout"], publie["atk"], publie["pv"], publie["aura"]) == (7, 6, 6, 5)
    # Les illustrations : versionnées, et jamais « undefined ».
    assert publie["hero"].startswith("/assets/tcg-lilith-hero?v=")
    assert publie["fond"].startswith("/assets/tcg-lilith-fond?v=")
    assert publie["accent"] == "#e0332b"


def test_une_cle_inconnue_sur_le_bus_est_refusee_et_ne_publie_rien():
    narrateur, publie = _narrateur_qui_publie()
    assert narrateur.show_widget("carte", "", carte="fantome") is None
    assert not publie


def test_le_bus_recoit_le_cadrage_du_calque_de_survol():
    """rhae est la seule à deux visuels : sans son cadrage propre, le bond
    griffes en avant s'affiche au cadrage du portrait assis."""
    narrateur, publie = _narrateur_qui_publie()
    narrateur.show_widget("carte", "", carte="rhae")
    assert publie["hero3d"].startswith("/assets/tcg-rhae-hero-3d?v=")
    assert publie["hero3dCote"] == "-26%"
