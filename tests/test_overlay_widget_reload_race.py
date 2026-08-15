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
    bloc = _bloc_charger_layout()
    assert "currentWidget()" in bloc
    assert "widget-on" in bloc
