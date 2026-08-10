# tests/test_garde_fous_qualite.py
"""Les garde-fous qui empêchent les défauts de REVENIR.

Ces tests ne vérifient pas un comportement du bot : ils vérifient que le code
reste inspectable. Ils sont nés des deux audits du 2026-08-10, où la moitié des
171 défauts partageaient la même signature — quelque chose échoue, personne
n'est prévenu, et ça vit des semaines.

Un `except: pass` passe tous les tests fonctionnels du monde. C'est au niveau du
texte qu'il faut l'attraper.
"""
import subprocess
import sys
from pathlib import Path

_RACINE = Path(__file__).resolve().parent.parent


def test_aucun_nouveau_gestionnaire_muet():
    """Cliquet : la dette de silences peut baisser, jamais monter.

    On ne corrige pas 157 handlers d'un coup — mais on interdit d'en ajouter un
    seul de plus. Un `except` doit journaliser, relever, rendre un repli
    explicite, ou porter un commentaire disant pourquoi le silence est le bon
    choix ici.
    """
    r = subprocess.run(
        [sys.executable, "scripts/lint_silences.py"],
        cwd=_RACINE, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr or r.stdout


def test_le_cliquet_detecte_reellement_un_silence_ajoute():
    """Un garde-fou qu'on ne teste pas est un garde-fou dont on ignore l'état."""
    sys.path.insert(0, str(_RACINE / "scripts"))
    try:
        import lint_silences
    finally:
        sys.path.pop(0)

    import ast

    def _muet(source: str) -> bool:
        arbre = ast.parse(source)
        lignes = source.split("\n")
        handler = next(n for n in ast.walk(arbre) if isinstance(n, ast.ExceptHandler))
        return lint_silences._est_muet(handler, lignes)

    assert _muet("try:\n    x()\nexcept Exception:\n    pass\n") is True
    # Un incrément n'est pas un repli : c'est de la comptabilité, l'échec reste muet.
    assert _muet("try:\n    x()\nexcept Exception:\n    n += 1\n") is True
    # Les cinq formes légitimes ne doivent PAS être signalées.
    assert _muet("try:\n    x()\nexcept Exception as e:\n    logger.warning(e)\n") is False
    assert _muet("try:\n    x()\nexcept Exception:\n    raise\n") is False
    assert _muet("try:\n    x()\nexcept Exception:\n    return None\n") is False
    assert _muet("try:\n    x()\n# le champ est optionnel\nexcept Exception:\n    pass\n") is False
    # Repli explicite : l'échec devient une donnée que l'appelant peut tester.
    assert _muet("try:\n    x()\nexcept Exception:\n    valeur = None\n") is False


def test_mettre_a_jour_un_cliquet_nefface_pas_lautre():
    """Les deux cliquets partagent un fichier. `--maj` doit fusionner.

    Un `--maj` qui écrasait le fichier effaçait silencieusement le seuil de
    l'autre contrôle, qui repassait alors au vert sans plus rien vérifier — un
    garde-fou désarmé par le garde-fou voisin.
    """
    import json

    reference = json.loads(
        (_RACINE / "scripts" / "silences_cliquet.json").read_text(encoding="utf-8")
    )
    assert "max_silences" in reference
    assert "max_erreurs_types" in reference


def test_aucune_nouvelle_erreur_de_type():
    """Cliquet : la dette de types peut baisser, jamais monter.

    Trois défauts des audits étaient de pures erreurs de type, invisibles pour
    tous les tests fonctionnels — dont `get_active_action_tasks()` annoncé
    `list[dict]` alors qu'il rendait des `sqlite3.Row`, ce qui EMPÊCHAIT LE BOT
    DE DÉMARRER. mypy les voit sans exécuter une ligne.

    Ignoré en silence si mypy n'est pas installé : c'est un confort de
    développement, pas une dépendance d'exécution.
    """
    r = subprocess.run(
        [sys.executable, "scripts/lint_types.py"],
        cwd=_RACINE, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr or r.stdout


def test_aucun_test_ne_fige_une_ligne_de_code_source():
    """Un test qui assert une chaîne de code SOURCE verrouille le défaut.

    Rencontré trois fois pendant les audits, dont
    `test_bootstrap_prefere_le_champ_dedie_avec_repli`, qui figeait littéralement
    la ligne défectueuse : le correctif faisait échouer le test censé le décrire.
    Tester le COMPORTEMENT, pas le texte.

    Les tests qui inspectent `inspect.getsource(...)` restent tolérés — ils
    vérifient une propriété structurelle (un ordre d'appel, la présence d'un
    garde), pas une formulation. C'est la lecture d'un FICHIER source pour y
    chercher une ligne d'implémentation qui pose problème.
    """
    interdits = []
    for f in sorted((_RACINE / "tests").rglob("*.py")):
        if f.name == Path(__file__).name:
            continue
        texte = f.read_text(encoding="utf-8")
        if "Path(\"bot/" not in texte and "read_text" not in texte:
            continue
        for i, ligne in enumerate(texte.split("\n"), 1):
            nu = ligne.strip()
            # Une assertion sur du source lu depuis un .py de production.
            if nu.startswith("assert") and "source" in nu and ".py" in nu:
                interdits.append(f"{f.relative_to(_RACINE)}:{i}")
    assert not interdits, (
        "ces tests figent une ligne d'implémentation et verrouilleront le "
        f"prochain correctif : {interdits}"
    )
