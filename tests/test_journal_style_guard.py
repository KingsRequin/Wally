"""Garde anti-répétition stylistique du journal.

Les tics ne sont pas listés en dur : ils sont relevés dans les entrées passées.
Ces tests vérifient que le relevé attrape les vraies répétitions sans écraser
le français courant.
"""
from bot.intelligence.journal import (
    _build_style_avoidance_block,
    _detect_overused_phrases,
    _extract_incipit,
    _journal_body,
)


def _entries(*contents: str) -> list[dict]:
    return [{"date": f"2026-08-{i:02d}", "content": c} for i, c in enumerate(contents, 1)]


# ── incipit ──

def test_incipit_courte_ligne_prise_entiere():
    assert _extract_incipit("Bon.\n\nLa suite du journal.") == "Bon."


def test_incipit_longue_ligne_tronquee_aux_premiers_mots():
    incipit = _extract_incipit(
        "Azraël est passé ce matin avec une question sur son classement de la semaine dernière."
    )
    assert incipit.startswith("Azraël est passé ce matin")
    assert incipit.endswith("…")


def test_incipit_ignore_les_titres_markdown():
    assert _extract_incipit("# Journal du 04/08\n\nRequin a validé le truc.") == (
        "Requin a validé le truc."
    )


def test_incipit_entree_vide():
    assert _extract_incipit("") == ""


# ── corps ──

def test_journal_body_retire_les_titres():
    body = _journal_body("Texte.\n## Pensée du soir\nLa chute.")
    assert "Pensée du soir" not in body
    assert "La chute." in body


# ── expressions sur-utilisées ──

def test_detecte_une_expression_presente_dans_la_majorite_des_entrees():
    entries = _entries(
        "Enfin bref, la journée a traîné.",
        "Requin est passé. Enfin bref.",
        "Rien à signaler, enfin bref, j'ai attendu.",
        "Enfin bref. Azraël a râlé.",
        "Une journée sans rien de spécial.",
    )
    assert "enfin bref" in _detect_overused_phrases(entries)


def test_ignore_une_expression_ponctuelle():
    entries = _entries(
        "Enfin bref, la journée a traîné.",
        "Requin est passé ce matin.",
        "Azraël a posé une question.",
        "Personne n'est venu.",
        "Une journée calme.",
    )
    assert "enfin bref" not in _detect_overused_phrases(entries)


def test_ne_bannit_pas_la_grammaire_courante():
    """« je suis » est inévitable dans un journal à la 1re personne — pas un tic."""
    entries = _entries(*["Je suis là. Je suis resté toute la journée." for _ in range(6)])
    assert "je suis" not in _detect_overused_phrases(entries)


def test_garde_le_ngramme_le_plus_long():
    entries = _entries(*["Une pensée du soir de plus, chaque fois." for _ in range(5)])
    phrases = _detect_overused_phrases(entries)
    assert "pensée du soir" in phrases
    assert "pensée du" not in phrases


def test_historique_trop_mince_ne_signale_rien():
    entries = _entries("Enfin bref.", "Enfin bref.")
    assert _detect_overused_phrases(entries) == []


# ── bloc injecté ──

def test_bloc_vide_sans_historique():
    assert _build_style_avoidance_block([]) == ""


def test_bloc_dedoublonne_les_ouvertures_identiques():
    block = _build_style_avoidance_block(_entries("Bon.\nUn.", "Bon.\nDeux.", "Pfff.\nTrois."))
    assert block.count('"Bon."') == 1
    assert '"Pfff."' in block


def test_bloc_liste_ouvertures_et_expressions():
    # Contexte variable autour du tic, comme dans les vraies entrées : seul
    # « enfin bref » traverse toutes les entrées.
    entries = _entries(
        "Bon.\n\nRequin a validé le truc, enfin bref, c'était long.",
        "Bon.\n\nAzraël a râlé sur son bras. Enfin bref.",
        "Pfff.\n\nEnfin bref, personne n'est venu avant midi.",
        "Bon.\n\nKassandre a posé une question, enfin bref, j'ai répondu.",
        "Bon.\n\nUne panne de DNS au réveil. Enfin bref, réglé.",
        "Bon.\n\nTaKi voulait un résumé de patch note. Enfin bref.",
    )
    block = _build_style_avoidance_block(entries)
    assert '"Bon."' in block
    assert '"Pfff."' in block
    assert '"enfin bref"' in block
