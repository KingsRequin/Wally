# tests/test_overlay_rps_duel.py
"""Le chifoumi : un duel tranché sur-le-champ, plus un vote.

Le chat votait pendant quinze secondes et Wally jouait contre la majorité. Trop
long pour ce que c'est : on demande un chifoumi comme on demande un pile ou
face. Les deux coups sont désormais tirés, l'animation joue, le vainqueur
s'affiche — et Wally garde le droit de forcer le sien.
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.overlay_feed import OverlayFeed
from bot.discord.handlers import run_overlay_tool
from bot.intelligence.action_dispatcher import ActionDispatcher
from bot.intelligence.overlay_narrator import OverlayNarrator


def _narrateur(live=True):
    n = OverlayNarrator(OverlayFeed(), AsyncMock(), lambda: live)
    n._feed = MagicMock()
    return n


def _publie(n):
    return n._feed.widget.call_args.kwargs


MOVES = ("pierre", "feuille", "ciseaux")


def test_un_duel_se_joue_d_un_coup():
    n = _narrateur()
    out = n.show_widget("rps", "allez", opponent="KingsRequin")

    assert out is not None
    params = _publie(n)
    assert params["mine"] in MOVES
    assert params["theirs"] in MOVES
    assert params["opponent"] == "KingsRequin"
    assert params["outcome"] in ("wally", "opponent", "draw")


def test_le_verdict_suit_les_regles_du_jeu():
    n = _narrateur()
    for _ in range(40):                       # les tirages varient, la règle non
        n.show_widget("rps", "", opponent="X")
        p = _publie(n)
        mine, theirs, outcome = p["mine"], p["theirs"], p["outcome"]
        if mine == theirs:
            assert outcome == "draw"
        elif (mine, theirs) in (("pierre", "ciseaux"), ("feuille", "pierre"),
                                ("ciseaux", "feuille")):
            assert outcome == "wally"
        else:
            assert outcome == "opponent"


def test_wally_peut_forcer_son_coup():
    """Le tirage se fait côté serveur : c'est ce qui lui permet de tricher."""
    n = _narrateur()
    n.show_widget("rps", "je prends pierre", move="pierre", opponent="X")
    assert _publie(n)["mine"] == "pierre"


def test_un_coup_impose_invalide_retombe_sur_le_hasard():
    n = _narrateur()
    n.show_widget("rps", "", move="lance-flammes", opponent="X")
    assert _publie(n)["mine"] in MOVES


def test_sans_adversaire_nomme_on_joue_quand_meme():
    """Le nom vient du chat ou du vocal ; son absence ne bloque pas le duel."""
    n = _narrateur()
    assert n.show_widget("rps", "") is not None
    assert _publie(n)["opponent"]


def test_rien_hors_live():
    n = _narrateur(live=False)
    assert n.show_widget("rps", "", opponent="X") is None
    n._feed.widget.assert_not_called()


def test_le_resultat_est_rendu_a_l_appelant():
    """Wally doit pouvoir commenter le duel qu'il vient de provoquer."""
    n = _narrateur()
    out = n.show_widget("rps", "", move="ciseaux", opponent="Azra")
    assert out["mine"] == "ciseaux"
    assert out["opponent"] == "Azra"
    assert out["outcome"] in ("wally", "opponent", "draw")


def test_deux_duels_de_suite_sont_permis():
    """Plus de manche à clore : rien ne reste ouvert entre deux demandes."""
    n = _narrateur()
    assert n.show_widget("rps", "", opponent="X") is not None
    assert n.show_widget("rps", "", opponent="Y") is not None


# ── l'adversaire vient de l'appelant ────────────────────────────────────────


def _bot_narrateur():
    narrator = MagicMock()
    narrator.show_widget.return_value = {
        "widget": "rps", "mine": "pierre", "theirs": "ciseaux",
        "opponent": "KingsRequin", "outcome": "wally",
    }
    narrator.is_active.return_value = True
    return SimpleNamespace(overlay_narrator=narrator), narrator


def test_l_adversaire_ne_vient_pas_du_modele():
    """Le nom affiché sous la main adverse est celui de qui a parlé.

    S'il venait des arguments du LLM, Wally pourrait faire jouer — et perdre —
    quelqu'un qui n'a rien demandé. `opponent` n'est donc pas dans le schéma, et
    l'appelant écrase ce que le modèle aurait glissé.
    """
    bot, narrator = _bot_narrateur()
    run_overlay_tool(bot, {"widget": "rps", "opponent": "Azraël"},
                     requester="KingsRequin")
    assert narrator.show_widget.call_args.kwargs["opponent"] == "KingsRequin"


def test_les_autres_widgets_ne_recoivent_pas_d_adversaire():
    """`opponent` est propre au chifoumi : l'injecter partout polluerait les
    paramètres publiés de tous les autres widgets."""
    bot, narrator = _bot_narrateur()
    run_overlay_tool(bot, {"widget": "coinflip"}, requester="KingsRequin")
    assert "opponent" not in narrator.show_widget.call_args.kwargs


@pytest.mark.asyncio
async def test_sur_initiative_personne_n_est_designe():
    """Chemin cognitif : Wally lance le duel tout seul, sans sollicitation. Le
    modèle ne doit pas pouvoir nommer sa victime."""
    narrator = MagicMock()
    narrator.show_widget.return_value = {"widget": "rps", "outcome": "draw"}
    dispatcher = ActionDispatcher(overlay_narrator=narrator)
    await dispatcher._act("show_overlay", {"widget": "rps", "opponent": "Azraël"})
    assert "opponent" not in narrator.show_widget.call_args.kwargs


def test_le_compte_rendu_nomme_le_gagnant():
    """C'est ce que Wally annonce dans le chat : s'il est faux, il félicite le
    perdant. L'ancien message parlait du vote du chat, qui n'existe plus."""
    bot, _ = _bot_narrateur()
    message = json.loads(run_overlay_tool(
        bot, {"widget": "rps"}, requester="KingsRequin"))["message"]
    assert "KingsRequin a joué ciseaux" in message
    assert "toi pierre" in message
    assert "tu gagnes" in message
