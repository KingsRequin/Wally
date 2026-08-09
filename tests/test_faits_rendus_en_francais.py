"""Un fait rendu depuis son triplet doit se lire en français.

Le vocabulaire des prédicats est anglais (`is`, `has`, `plays`…) — c'est un
choix volontaire : un ensemble fermé, stable, sur lequel la déduplication
s'appuie. Mais `_render_content()` recollait `subject + predicate + object` tel
quel, et cette phrase part au prompt que Wally lit sur les gens :

    polylrose has piscine
    polylrose is mange sur le sol
    mks_zedd plays Apex Legends
    polylrose knows mécaniques de fragments héritages

460 faits actifs étaient dans cet état. Le prédicat reste anglais en base (la
colonne `predicate` sert à la dédup) ; seul le texte lisible est traduit.
"""
from __future__ import annotations

from bot.intelligence.memory.vocab import PREDICATES, render_triplet


def test_les_prédicats_courants_se_lisent_en_francais():
    assert render_triplet("mks_zedd", "plays", "Apex Legends") == "mks_zedd joue à Apex Legends"
    assert render_triplet("polylrose", "has", "une piscine") == "polylrose a une piscine"
    assert render_triplet("Azraël", "is", "développeur") == "Azraël est développeur"
    assert render_triplet("Cluth", "uses", "Neovim") == "Cluth utilise Neovim"


def test_les_préférences_négatives_gardent_leur_sens():
    assert render_triplet("Cluth", "dislikes", "les smurfs") == "Cluth n'aime pas les smurfs"


def test_tout_le_vocabulaire_ferme_est_traduit():
    """Un prédicat oublié ressortirait en anglais dans le prompt."""
    manquants = [
        p for p in PREDICATES
        if p in render_triplet("X", p, "quelque chose")
    ]
    assert not manquants, f"prédicats non traduits : {manquants}"


def test_un_predicat_inconnu_ne_fait_pas_perdre_le_fait():
    """Hors vocabulaire, mieux vaut une phrase imparfaite qu'un fait vide."""
    rendu = render_triplet("X", "yodels", "en montagne")
    assert "X" in rendu and "en montagne" in rendu


def test_un_triplet_incomplet_reste_lisible():
    assert render_triplet("", "plays", "Apex") == "joue à Apex"
    assert render_triplet("Cluth", "plays", "") == "Cluth joue à"
    assert render_triplet("", "", "") == ""


def test_les_espaces_parasites_sont_nettoyes():
    assert render_triplet("  Cluth  ", "plays", "  Apex  ") == "Cluth joue à Apex"


# ── Les deux chemins d'écriture doivent passer par là ────────────────────────

def test_ingest_rend_le_fait_en_francais():
    from bot.intelligence.memory.ingest import _Candidate, _render_content

    cand = _Candidate(
        subject="mks_zedd", predicate="plays", object="Apex Legends",
        category="FAIT", confidence_source="explicit", importance=0.5,
    )
    assert _render_content(cand) == "mks_zedd joue à Apex Legends"
