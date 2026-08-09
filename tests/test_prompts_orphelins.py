"""Aucun fichier de prompt ne doit traîner sans être chargé par le code.

Relevé le 2026-08-09 : quatre prompts n'avaient plus aucune référence —
`image_describe_system`, `memory_consolidation_system`, `memory_evaluate_system`,
`session_analysis_system`. Les fonctionnalités correspondantes tournaient depuis
longtemps avec d'autres textes (`memory_session_summary`, `user_portrait`…).

Ce n'était pas qu'un encombrement : l'onglet Prompts du panel admin liste le dossier
par `glob("*.md")`, donc ces quatre fichiers s'y affichaient comme éditables. Modifier
l'un d'eux en croyant changer un comportement n'aurait produit aucun effet — et rien
ne l'aurait signalé.

Ce test est le garde-fou qui rend le ménage inutile la prochaine fois : un prompt
qu'on cesse d'utiliser fait rougir la suite au lieu de se sédimenter en silence.
"""
import re
from pathlib import Path

import pytest

_RACINE = Path(__file__).parent.parent
_DOSSIERS = [
    _RACINE / "bot" / "persona" / "prompts",
    _RACINE / "bot" / "intelligence" / "persona" / "prompts",
]


def _sources_python() -> str:
    """Tout le code de `bot/`, concaténé une fois."""
    return "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in (_RACINE / "bot").rglob("*.py")
    )


@pytest.fixture(scope="module")
def code() -> str:
    return _sources_python()


def _prompts() -> list[Path]:
    return sorted(p for d in _DOSSIERS if d.exists() for p in d.glob("*.md"))


def test_il_y_a_bien_des_prompts_a_verifier():
    """Garde-fou du garde-fou : un glob cassé rendrait ce fichier vert et muet."""
    assert len(_prompts()) > 20


def test_aucun_prompt_nest_orphelin(code):
    """Chargé par `load_prompt("nom")`, par `"nom.md"`, ou pas chargé du tout."""
    orphelins = []
    for p in _prompts():
        nom = p.stem
        if re.search(rf'["\']{re.escape(nom)}(\.md)?["\']', code):
            continue
        orphelins.append(p.relative_to(_RACINE).as_posix())
    assert not orphelins, (
        "prompts sans aucune référence dans bot/ — ils s'affichent pourtant comme "
        f"éditables dans le panel admin : {orphelins}"
    )
