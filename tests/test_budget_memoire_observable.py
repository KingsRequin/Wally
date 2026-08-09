"""On doit pouvoir SAVOIR ce que le budget mémoire jette, pas le supposer.

Question de l'owner le 2026-08-09 : « pourquoi à chaque message il cherche
query='kingsrequin' -> 20 faits ? ». Réponse : `_third_party_mention_context`
agrège aussi le pseudo des AUTEURS du prélude, donc quiconque a parlé récemment
devient un « tiers mentionné » et ses souvenirs sont rechargés à chaque message.

Mais la vraie question qui se pose ensuite est : ce travail sert-il ? Ce bloc part en
priorité 6, la dernière, et `assemble_memory_context` s'arrête net dès les 800 tokens
atteints — après le rappel principal, le recall de session, les blagues et les topics.
Vingt faits pèsent à eux seuls ~320 tokens. Il est donc probable qu'ils soient jetés
la plupart du temps, requête comprise.

Probable, mais pas mesuré : l'assemblage était muet. Optimiser sans cette mesure
serait deviner — d'où ce fichier, qui rend l'arbitrage observable AVANT d'y toucher.
"""
import pytest

from bot.intelligence.prompts import assemble_memory_context


def _capture(niveau="DEBUG"):
    from loguru import logger

    lignes: list[str] = []
    sink = logger.add(lambda m: lignes.append(str(m)), level=niveau)
    return lignes, sink


def test_le_budget_est_journalise_avec_le_nom_des_blocs():
    from loguru import logger

    lignes, sink = _capture()
    try:
        assemble_memory_context(
            [(1, "a" * 400, "semantique"), (6, "b" * 400, "tiers")], max_tokens=100
        )
    finally:
        logger.remove(sink)

    trace = " ".join(lignes)
    assert "semantique" in trace, f"le bloc retenu n'est pas nommé :\n{trace}"
    assert "tiers" in trace, f"le bloc jeté n'est pas nommé :\n{trace}"


def test_un_bloc_entierement_jete_est_signale_comme_tel():
    """Le cas qui intéresse : le travail est fait, le résultat n'arrive jamais."""
    from loguru import logger

    lignes, sink = _capture()
    try:
        # 400 caractères = 100 tokens : le premier bloc consomme tout le budget.
        assemble_memory_context(
            [(1, "a" * 400, "semantique"), (6, "b" * 400, "tiers")], max_tokens=100
        )
    finally:
        logger.remove(sink)

    trace = " ".join(lignes)
    assert "jeté" in trace.lower() or "jetés" in trace.lower(), (
        f"rien n'indique qu'un bloc a été perdu :\n{trace}"
    )


def test_rien_nest_signale_quand_tout_passe():
    from loguru import logger

    lignes, sink = _capture()
    try:
        assemble_memory_context([(1, "court", "semantique")], max_tokens=800)
    finally:
        logger.remove(sink)

    trace = " ".join(lignes).lower()
    assert "jeté" not in trace


def test_les_appels_sans_label_fonctionnent_toujours():
    """Rétrocompatibilité : les parts à deux éléments restent valides."""
    sortie = assemble_memory_context([(1, "alpha"), (2, "beta")], max_tokens=800)
    assert sortie == "alpha\nbeta"


def test_le_contenu_assemble_est_inchange():
    """L'instrumentation ne doit RIEN changer au prompt produit."""
    parts = [(6, "tiers", "tiers"), (1, "principal", "semantique")]
    assert assemble_memory_context(parts, max_tokens=800) == "principal\ntiers"


def test_la_troncature_reste_marquee():
    """Budget 100t : le 1er bloc en prend 50, il reste 200 caractères au second —
    au-dessus du seuil de 50 en dessous duquel le bloc est jeté plutôt que coupé."""
    sortie = assemble_memory_context(
        [(1, "a" * 200, "semantique"), (2, "b" * 400, "recall")], max_tokens=100
    )
    assert sortie.endswith("…")
    assert sortie.startswith("a" * 200)


@pytest.mark.parametrize("budget", [0, 10])
def test_un_budget_minuscule_ne_leve_pas(budget):
    assemble_memory_context([(1, "a" * 500, "semantique")], max_tokens=budget)
