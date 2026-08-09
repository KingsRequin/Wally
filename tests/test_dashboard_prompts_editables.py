"""Tout fichier persona ACTIF doit être éditable depuis l'onglet Prompts.

Relevé le 2026-08-09 : la liste `persona_files` de `list_prompts` était figée sur
huit fichiers et avait cessé de suivre le dossier. `CAPABILITIES.md` — le self-model,
lu à chaque réponse, et dont le contenu périmé venait justement de faire redemander à
Wally une capacité qu'il possédait — n'était pas éditable depuis l'UI. Idem
`EVENTS.md` et `USERS.md`.

Le POST les acceptait déjà (`^[A-Z_]+\\.md$`) : seule la lecture les ignorait, donc
rien ne signalait le trou.
"""
from pathlib import Path

_PERSONA = Path(__file__).parent.parent / "bot" / "persona"


def _fichiers_offerts_a_ledition() -> list[str]:
    """La liste en dur de `list_prompts`, lue dans la source.

    L'endpoint est une coroutine FastAPI qui prend une `Request` ; extraire la liste
    du source évite de monter toute l'app pour vérifier une constante.
    """
    import re

    src = (Path(__file__).parent.parent / "bot" / "dashboard" / "routes" / "admin.py").read_text()
    bloc = re.search(r"persona_files = \[(.*?)\]", src, re.DOTALL)
    assert bloc, "la liste `persona_files` a disparu de list_prompts"
    return re.findall(r'"([A-Z_]+\.md)"', bloc.group(1))


def test_tous_les_blocs_persona_du_dossier_sont_editables():
    presents = {p.name for p in _PERSONA.glob("*.md")}
    offerts = set(_fichiers_offerts_a_ledition())

    manquants = presents - offerts
    assert not manquants, (
        f"fichiers persona actifs absents de l'onglet Prompts : {sorted(manquants)}"
    )


def test_aucun_fichier_offert_nexiste_pas():
    """L'inverse : une entrée fantôme afficherait un éditeur vide qui écrit un fichier
    mort au premier enregistrement."""
    fantomes = [f for f in _fichiers_offerts_a_ledition() if not (_PERSONA / f).exists()]
    assert not fantomes, f"listés mais absents du dossier : {fantomes}"
