# tests/test_overlay_widget_reload_race.py
"""Rechargement de la page pendant un widget sticky (bingo) en cours.

`chargerLayout()` fait un `fetch` qui traverse une lecture SQLite. L'
EventSource, lui, reçoit `feed.recent()` immédiatement depuis la mémoire, sans
aucun `await` — un widget déjà réémis peut donc s'afficher avant que
`chargerLayout()` n'ait répondu. Tant que `reglages` vaut encore `{}`, tout
widget est traité comme `solo` par le défaut prudent (`estSolo()`) et
`widget-on` efface l'avatar. Rien ne rattrapait ça ensuite : la classe n'était
retouchée qu'au widget SUIVANT — reproduit plusieurs fois par soirée
(changement de scène OBS, rebuild en plein bingo).
"""
from pathlib import Path

_JS = Path("bot/dashboard/static/overlay.js")


def _bloc_charger_layout() -> str:
    src = _JS.read_text(encoding="utf-8")
    i = src.index("async function chargerLayout()")
    fin = src.index("\n  }", i)
    return src[i:fin]


def test_une_scene_sans_elements_ne_fait_pas_mourir_le_rendu():
    """`data.scene.elements` peut être absent (scène sans `elements`) : sans
    repli, `reglages` deviendrait `undefined` et `estSolo()` lèverait à la
    première lecture, pour tous les widgets, jusqu'au prochain rechargement.
    """
    bloc = _bloc_charger_layout()
    assert "data.scene.elements || {}" in bloc


def test_le_widget_deja_affiche_est_reevalue_apres_larrivee_du_layout():
    """Le widget affiché par l'EventSource avant la réponse du fetch doit voir
    sa classe `widget-on` réévaluée une fois `reglages` connu — sinon un
    widget non-solo affiché avant coup reste catalogué solo pour toute sa
    durée, et l'avatar reste effacé à tort jusqu'au widget suivant.
    """
    assert "majWidgetOn()" in _bloc_charger_layout()


def test_widget_on_est_un_etat_derive_et_non_un_evenement():
    """`widget-on` efface l'avatar ET la bulle : posée à l'arrivée d'un widget
    puis retirée « quand il n'y a plus rien nulle part », elle restait
    accrochée dès qu'une carte survivait à son tour de piste, et Wally
    disparaissait sans revenir.

    L'invariant, et non la ligne : UN SEUL endroit écrit la classe, et il la
    RECALCULE depuis ce qui est réellement à l'écran. Tant qu'il en est ainsi,
    aucune séquence d'événements ne peut la laisser en travers.
    """
    src = _JS.read_text(encoding="utf-8")
    assert src.count('classList.toggle("widget-on"') == 1
    assert 'classList.add("widget-on")' not in src
    assert 'classList.remove("widget-on")' not in src
    # Et ce seul écrivain lit l'ÉCRAN, pas le `kind` qu'on vient de publier :
    # `…EnPlace()` parcourt les widgets réellement montés. Le réglage consulté a
    # changé (`solo` → `wally_visible`, cf. test_overlay_wally_visible.py) ;
    # l'invariant testé ici, lui, ne dépend pas duquel des deux il s'agit.
    i = src.index('classList.toggle("widget-on"')
    assert "EnPlace()" in src[i:i + 200]


def test_un_element_masque_ne_reclame_pas_la_scene():
    """Un élément masqué dans la scène n'occupe rien : le traiter en `solo`
    effaçait l'avatar pour ne rien montrer à la place — l'écran perdait Wally
    et ne gagnait rien, le temps de la durée d'affichage."""
    src = _JS.read_text(encoding="utf-8")
    i = src.index("function estSolo(kind)")
    bloc = src[i:src.index("\n  }", i)]
    assert "el.hidden" in bloc
