"""Un module qui n'est QU'un outil vit dans `bot/tools/`, nulle part ailleurs.

Sans ce filet, la règle du dossier ne tient qu'à la mémoire de celui qui écrit
le prochain outil — et l'histoire du dépôt dit que cette mémoire-là ne tient
pas : `follow_tool`, `music_tool` et `shoutout_tool` ont TOUS LES TROIS atterri
dans `bot/core/` en portant le même aveu dans leur en-tête, « rangé là pour ne
pas faire de cycle avec `discord/handlers` ». Trois fois le même contournement,
à des mois d'écart, par la même personne.

Le test porte sur le NOM de fichier plutôt que sur son contenu : un fichier
`*_tool.py` annonce lui-même qu'il n'est qu'un outil. Un service qui expose son
propre outil (`web_search.py`, `scrape.py`, `history_search.py`,
`prediction_kills.py`, `apex/tool.py`) ne porte pas ce suffixe et n'est donc pas
visé — il garde sa définition collée à la logique qu'elle appelle.
"""
from pathlib import Path

_RACINE = Path(__file__).resolve().parents[1] / "bot"


def test_aucun_module_outil_hors_du_dossier_tools():
    egares = [
        p.relative_to(_RACINE).as_posix()
        for p in _RACINE.rglob("*_tool.py")
        if p.parent.name != "tools"
    ]
    assert not egares, (
        f"Ces modules-outils vivent hors de `bot/tools/` : {egares}. "
        "Un fichier `*_tool.py` n'est QUE la définition d'un outil et son "
        "exécutant : il se range dans `bot/tools/`. Si c'est en réalité un "
        "service qui expose son outil, il ne doit pas porter ce suffixe."
    )


def test_le_dossier_tools_n_est_pas_vide():
    """Le pendant du test précédent : une règle qui ne garde plus rien passerait
    au vert en ayant tout perdu."""
    outils = list((_RACINE / "tools").glob("*_tool.py"))
    assert len(outils) >= 3, f"seulement {len(outils)} outil(s) rangé(s)"
