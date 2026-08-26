"""Le sac doit épuiser son stock avant de répéter, jointure comprise."""
import random

from bot.core.tirage import SacSansRemise


def test_le_stock_est_epuise_avant_toute_repetition():
    stock = [f"p{i}" for i in range(10)]
    sac = SacSansRemise(lambda: stock)
    tirees = [sac.tirer() for _ in range(10)]
    assert sorted(tirees) == sorted(stock), "une phrase est sortie deux fois"


def test_deux_tirages_consecutifs_ne_repetent_jamais_a_la_jointure():
    """Le seul endroit où le sans-remise ne protège de rien : la recharge.

    Sans le garde, un sac de N phrases répète immédiatement une fois sur N —
    la dernière du sac vidé peut ressortir en tête du suivant.
    """
    stock = ["a", "b"]
    random.seed(0)
    sac = SacSansRemise(lambda: stock)
    suite = [sac.tirer() for _ in range(40)]
    doublons = [i for i in range(1, len(suite)) if suite[i] == suite[i - 1]]
    assert not doublons, f"répétition immédiate aux positions {doublons}"


def test_le_stock_est_relu_a_chaque_recharge():
    """Un /reload-persona doit changer les phrases sans redémarrage."""
    courant = ["vieux"]
    sac = SacSansRemise(lambda: courant)
    assert sac.tirer() == "vieux"
    courant[:] = ["neuf1", "neuf2"]
    assert sac.tirer() in ("neuf1", "neuf2")


def test_un_stock_vide_rend_none_sans_lever():
    """Vider le fichier de phrases éteint la fonction — ce n'est pas une panne."""
    sac = SacSansRemise(lambda: [])
    assert sac.tirer() is None
    assert sac.tirer() is None


def test_un_stock_a_une_seule_entree_la_ressert():
    """Pas de garde possible ici : une seule phrase, on la répète ou on se tait.

    On la ressert — c'est le choix de l'auteur du fichier, pas une panne.
    """
    sac = SacSansRemise(lambda: ["seule"])
    assert [sac.tirer() for _ in range(3)] == ["seule"] * 3


def test_une_source_qui_rend_none_ne_casse_rien():
    sac = SacSansRemise(lambda: None)  # type: ignore[arg-type,return-value]
    assert sac.tirer() is None
