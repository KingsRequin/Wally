"""L'avalanche fait passer TOUT le stock, et va jusqu'en bas de l'écran.

Retour de l'owner après le premier essai en direct : « les memes disparaissent
avant d'arriver en bas, et y a pas tous les memes — je veux exactement ce que tu
as fait, mais tous les memes doivent passer ; je sais que ça cache l'écran et que
c'est long, c'est fait pour. »

Trois causes distinctes, toutes ici sauf la chute (CSS, cf.
`test_avalanche_chute.py`) :

  1. **Le tirage était AVEC REMISE** — `medias[random()]` à chaque lâcher. Sur
     134 médias et 120 lâchers, la loi des tirages avec remise laisse ~40 % du
     dossier au vestiaire et fait repasser d'autres memes trois fois. Un stock
     se parcourt, il ne se tire pas.
  2. **La durée était une constante (30 s)**, donc le nombre de lâchers aussi :
     ajouter des memes au dossier n'en faisait pas passer un de plus. Elle
     dérive maintenant du stock — c'est le stock qui commande, pas le chrono.
  3. **Un dossier vide encaissait quand même 50 000 points.** Le JS s'en
     remettait à un refus « déjà fait en amont » qui n'existait pas.
"""
from unittest.mock import MagicMock

import pytest


def _narrateur(nb_medias: int, live: bool = True):
    from bot.intelligence.overlay_narrator import OverlayNarrator
    memes = MagicMock()
    memes.list_medias.return_value = [
        {"name": f"m{i}.webp", "genre": "image"} for i in range(nb_medias)
    ]
    n = OverlayNarrator(
        overlay_feed=MagicMock(), llm=MagicMock(), is_live=lambda: live, memes=memes,
    )
    return n


def _widget(n):
    """Les kwargs du `feed.widget(...)` publié, ou None si rien n'est parti."""
    appels = n._feed.widget.call_args_list
    return appels[-1].kwargs if appels else None


def test_la_duree_derive_du_STOCK_et_non_d_une_constante():
    """134 memes à ~4/s font une bonne demi-minute de plus que les 30 s figées.
    Le chiffre exact n'est pas le sujet : le sujet est qu'il BOUGE avec le
    dossier."""
    court = _narrateur(20)
    long = _narrateur(134)
    assert court.show_meme_storm() is True
    assert long.show_meme_storm() is True
    assert _widget(long)["seconds"] > _widget(court)["seconds"]


def test_tout_le_stock_a_le_temps_de_passer():
    """La fenêtre doit tenir le débit annoncé au client : sinon la carte se
    retire pendant qu'il reste des memes à lâcher, et on retombe sur « il n'y a
    pas tous les memes »."""
    from bot.intelligence.overlay_narrator import OverlayNarrator
    n = _narrateur(134)
    n.show_meme_storm()
    secondes = _widget(n)["seconds"]
    assert secondes >= 134 / OverlayNarrator.AVALANCHE_PAR_SECONDE


def test_le_dernier_meme_a_le_temps_de_TOMBER():
    """Le lâcher n'est pas l'arrivée : un meme lancé à la dernière seconde met
    encore ~5 s à traverser l'écran. Sans cette marge, la fin de l'avalanche
    s'évapore en plein vol — le défaut que l'owner décrit."""
    from bot.intelligence.overlay_narrator import OverlayNarrator
    n = _narrateur(134)
    n.show_meme_storm()
    w = _widget(n)
    assert w["seconds"] >= 134 / OverlayNarrator.AVALANCHE_PAR_SECONDE \
        + OverlayNarrator.AVALANCHE_CHUTE_S
    # La carte reste au moins aussi longtemps que l'effet qu'elle porte.
    assert w["duration"] >= w["seconds"]


def test_un_dossier_VIDE_ne_prend_pas_les_points():
    """50 000 points pour un écran vide. L'appelant rembourse sur un refus —
    encore faut-il refuser."""
    n = _narrateur(0)
    assert n.show_meme_storm() is False
    assert _widget(n) is None


def test_un_stock_illisible_ne_bloque_pas_l_avalanche():
    """La bibliothèque peut lever (dossier démonté en plein live). Le doute
    profite au viewer qui a PAYÉ : on lance avec la durée par défaut plutôt que
    de lui prendre ses points."""
    n = _narrateur(10)
    n._memes.list_medias.side_effect = OSError("dossier absent")
    assert n.show_meme_storm() is True
    assert _widget(n) is not None


def test_un_stock_enorme_ne_confisque_pas_l_ecran_une_heure():
    """Filet : le jour où le dossier passe à 5 000 memes, la fenêtre est bornée
    et c'est la densité qui monte côté client, pas la durée."""
    from bot.intelligence.overlay_narrator import OverlayNarrator
    n = _narrateur(5000)
    n.show_meme_storm()
    assert _widget(n)["seconds"] <= OverlayNarrator.AVALANCHE_MAX_S


def test_une_duree_imposee_reste_prioritaire():
    """Le paramètre existant sert aux essais depuis le panneau : il ne doit pas
    être écrasé par le calcul."""
    n = _narrateur(134)
    n.show_meme_storm(seconds=8)
    assert _widget(n)["seconds"] == 8


def test_hors_live_rien_ne_part():
    n = _narrateur(134, live=False)
    assert n.show_meme_storm() is False
    assert _widget(n) is None


@pytest.mark.parametrize("nb", [1, 2, 3])
def test_un_tout_petit_stock_reste_visible(nb):
    """Trois memes ne font pas une avalanche d'une seconde : le temps de chute
    est un plancher, pas un supplément proportionnel."""
    from bot.intelligence.overlay_narrator import OverlayNarrator
    n = _narrateur(nb)
    assert n.show_meme_storm() is True
    assert _widget(n)["seconds"] >= OverlayNarrator.AVALANCHE_CHUTE_S
