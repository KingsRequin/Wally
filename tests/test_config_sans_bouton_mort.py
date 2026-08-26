"""Tout réglage exposé doit avoir un CONSOMMATEUR.

Le 2026-08-26, huit réglages de `config.yaml` ne servaient à rien : six lus
nulle part (`spontaneous_memory_probability`, `memory_recall_min_score`,
`memory_search_min_score`, `history_limit`, `random_avatar_chance`,
`transition_minutes`), deux écrits par le dashboard sans lecteur
(`cost_alert_threshold`, `notification_guild_id`).

C'est la pire forme de défaut silencieux : on tourne un bouton, rien ne bouge,
et rien ne dit que le bouton n'est branché sur rien. Deux d'entre eux
portaient même une fonctionnalité que le CLAUDE.md décrivait en détail et qui
n'a jamais existé.

Une consigne ne suffit pas — c'est la leçon de tout le dépôt. Ce test est le
MÉCANISME : un champ de config ajouté sans consommateur fait échouer la suite,
tout de suite, chez celui qui l'ajoute.

Ce qu'il vérifie exactement : chaque champ des dataclasses de `bot/config.py`
est LU quelque part dans `bot/` (ailleurs qu'en affectation). Il ne dit pas que
la lecture est correcte, seulement qu'elle existe — c'est déjà tout ce qui
manquait aux huit.
"""
import ast
import re
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parent.parent
_CONFIG = _RACINE / "bot" / "config.py"

# Les champs dont l'absence de lecteur est DÉLIBÉRÉE. Chacun porte sa raison :
# une exemption sans motif est une porte ouverte, et c'est exactement comme ça
# que les huit sont entrés.
_EXEMPTS = {
    # La section `openai:` est LEGACY, tenue en phase avec `llm:` pour qu'un
    # ancien `config.yaml` reste lisible. Ses champs sont donc écrits en
    # miroir et lus par personne — c'est le but.
    "primary_model": "miroir legacy de llm.primary.model",
    "secondary_model": "miroir legacy de llm.secondary.model",
    "model": "miroir legacy",
    "api_key": "secret lu depuis .env, jamais depuis la dataclass",
}


def _champs_de_config() -> dict[str, str]:
    """Les champs de toutes les dataclasses de `bot/config.py` → leur classe."""
    arbre = ast.parse(_CONFIG.read_text(encoding="utf-8"))
    champs: dict[str, str] = {}
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.ClassDef):
            continue
        for corps in noeud.body:
            # `nom: type = defaut` — une annotation, pas une simple affectation
            if isinstance(corps, ast.AnnAssign) and isinstance(corps.target, ast.Name):
                champs.setdefault(corps.target.id, noeud.name)
    return champs


def _sources_hors_config() -> list[tuple[Path, str]]:
    return [
        (f, f.read_text(encoding="utf-8", errors="ignore"))
        for f in (_RACINE / "bot").rglob("*.py")
        if f != _CONFIG
    ]


@pytest.mark.parametrize("champ,classe", sorted(_champs_de_config().items()))
def test_chaque_reglage_a_un_lecteur(champ, classe):
    if champ in _EXEMPTS:
        pytest.skip(f"exempté : {_EXEMPTS[champ]}")

    # Deux façons de lire un réglage dans ce dépôt, et il faut les deux :
    # l'attribut direct et le `getattr(cfg, "champ", défaut)` — très employé
    # pour rester tolérant à une config ancienne, y compris imbriqué et coupé
    # sur plusieurs lignes, d'où le `DOTALL` et la fenêtre large.
    #
    # Une LECTURE, pas une écriture : `x.champ = v` ne compte pas, sinon un
    # réglage que seul le dashboard écrit passerait pour vivant.
    #
    # ⚠️ L'accès par clé (`d["champ"]`) est VOLONTAIREMENT absent. Il paraît
    # naturel, et c'est un faux témoin : les routes lisent le PAYLOAD HTTP avec
    # `d["cost_alert_threshold"]` avant de l'écrire dans la config. Ma première
    # version comptait ça comme une lecture — et laissait donc passer les deux
    # seuls boutons morts qu'elle devait attraper. La config de ce projet est
    # faite de dataclasses ; elle ne se lit jamais par clé.
    n = re.escape(champ)
    lecture = re.compile(
        rf"\.{n}\b(?!\s*=(?!=))"                      # cfg.champ (hors affectation)
        rf"|getattr\(.{{0,200}}?[\"']{n}[\"']",        # getattr(cfg, "champ", …)
        re.DOTALL,
    )
    for chemin, source in _sources_hors_config():
        if lecture.search(source):
            return
    pytest.fail(
        f"`{classe}.{champ}` est exposé dans config.yaml mais AUCUN code ne le lit.\n"
        f"   Soit on le branche, soit on le retire — un bouton qui ne fait rien\n"
        f"   est pire qu'un bouton absent. S'il est délibérément muet (miroir\n"
        f"   legacy, secret lu ailleurs), l'ajouter à `_EXEMPTS` AVEC sa raison."
    )
