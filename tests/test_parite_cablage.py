"""Le service existe, l'outil sait s'en servir — mais personne ne l'a branché.

`test_parite_plateformes.py` compare les listes d'OUTILS que les deux
adaptateurs construisent, avec un bot factice qui possède tout. Il ne pouvait
donc pas voir le défaut du 2026-08-21 : l'outil musique était bien écrit des
deux côtés, avec sa garde `if getattr(bot, "music", None) is not None`, mais
`main.py` ne posait le service que sur `twitch_bot`. Côté Discord, la garde
était donc toujours fausse et l'outil n'était JAMAIS proposé, alors que
`CAPABILITIES.md` promet de savoir répondre à qui demande. Aucun test, aucun
log, aucune erreur : Wally était simplement incapable, et personne ne l'a su
avant que quelqu'un le lui demande.

Ce fichier regarde donc le CÂBLAGE lui-même, dans `main.py`, et non les listes
d'outils. Comme pour la parité des outils, il ne réclame pas l'identité : il
réclame que la liste des écarts soit TENUE. Tout service posé d'un seul côté et
absent de l'inventaire ci-dessous fait échouer ce test, avec son nom.
"""
import ast
from pathlib import Path

_MAIN = Path(__file__).resolve().parents[1] / "bot" / "main.py"

# Écarts assumés, avec leur raison. Modifier cette table est un acte délibéré.
_DISCORD_SEULEMENT = {
    "journal": "le journal quotidien se rédige et se poste sur Discord",
    "vision": "seul Discord porte des pièces jointes à regarder",
    "history_search": "fouille les JSONL Discord — fuiterait vers un chat public",
    "update_checker": "prévient le créateur en DM Discord",
    "dashboard_state": "l'état du dashboard, câblé au moment où il existe",
    "_twitch_bot": "la référence croisée elle-même",
}
_TWITCH_SEULEMENT = {
    "discord_bot": "la référence croisée elle-même",
    "stream_feed": "le flux du live, qui n'existe que côté Twitch",
    "stream_watcher": "surveille la chaîne Twitch",
    "apex_watcher": "suit les parties pendant le live Twitch",
    "duel_runner": "les duels se paient en points de chaîne Twitch",
    "prediction_kills": "les paris engagent les points de chaîne Twitch",
}


def _services_poses() -> dict[str, set[str]]:
    """Ce que `main.py` pose sur chaque adaptateur, lu dans l'arbre syntaxique.

    Sur l'AST et non par `grep` : une ligne commentée ou une chaîne de
    documentation qui parle d'un service ne doit pas compter comme un câblage.
    """
    poses: dict[str, set[str]] = {"discord_bot": set(), "twitch_bot": set()}
    arbre = ast.parse(_MAIN.read_text(encoding="utf-8"))
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Assign):
            continue
        for cible in noeud.targets:
            if (isinstance(cible, ast.Attribute)
                    and isinstance(cible.value, ast.Name)
                    and cible.value.id in poses):
                poses[cible.value.id].add(cible.attr)
    return poses


def test_les_deux_adaptateurs_recoivent_les_memes_services():
    poses = _services_poses()
    discord, twitch = poses["discord_bot"], poses["twitch_bot"]
    # La garde de la garde : si les noms d'adaptateurs changent dans `main.py`,
    # ce test passerait au vert sur deux ensembles vides.
    assert len(discord) > 5 and len(twitch) > 5, (
        "aucun câblage trouvé dans main.py — les variables ont dû être "
        "renommées, et ce test ne surveille plus rien."
    )

    surplus_discord = (discord - twitch) - set(_DISCORD_SEULEMENT)
    surplus_twitch = (twitch - discord) - set(_TWITCH_SEULEMENT)

    assert not surplus_discord, (
        f"services posés sur Discord et pas sur Twitch : {sorted(surplus_discord)}. "
        "Soit c'est un oubli — branche-les côté Twitch — soit c'est un choix, et "
        "il faut l'inscrire dans _DISCORD_SEULEMENT avec sa raison."
    )
    assert not surplus_twitch, (
        f"services posés sur Twitch et pas sur Discord : {sorted(surplus_twitch)}. "
        "C'est exactement le défaut de la musique : l'outil existait des deux "
        "côtés, le service d'un seul, et la garde `getattr(bot, ...)` se taisait."
    )


def test_les_ecarts_declares_existent_vraiment():
    """Un écart qu'on a fini par corriger doit sortir de la table, sinon elle
    devient un cimetière qui autorise silencieusement le prochain oubli."""
    poses = _services_poses()
    discord, twitch = poses["discord_bot"], poses["twitch_bot"]
    perimes_d = set(_DISCORD_SEULEMENT) - (discord - twitch)
    perimes_t = set(_TWITCH_SEULEMENT) - (twitch - discord)
    assert not perimes_d, f"écarts Discord déclarés mais inexistants : {sorted(perimes_d)}"
    assert not perimes_t, f"écarts Twitch déclarés mais inexistants : {sorted(perimes_t)}"


def test_la_musique_est_branchee_des_DEUX_cotes():
    """Le cas qui a coûté la capacité : nommé à part pour qu'un futur ménage
    dans les tables ci-dessus ne puisse pas le rouvrir en silence."""
    poses = _services_poses()
    assert "music" in poses["discord_bot"]
    assert "music" in poses["twitch_bot"]
