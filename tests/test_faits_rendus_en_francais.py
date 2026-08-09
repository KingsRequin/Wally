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


# ── Quand le modèle choisit mal son prédicat ─────────────────────────────────
#
# Le LLM met parfois `is` devant un objet qui est déjà une action conjuguée :
# « kingsrequin is va bien », « polylrose is mange sur le sol », « azrael_ttv is
# mange vite ». Traduire mécaniquement donne « kingsrequin est va bien ». Le
# verbe de liaison est alors de trop — la phrase se tient sans lui.

def test_un_objet_deja_conjugue_ne_prend_pas_de_verbe_de_liaison():
    assert render_triplet("kingsrequin", "is", "va bien") == "kingsrequin va bien"
    assert render_triplet("polylrose", "is", "mange sur le sol") == "polylrose mange sur le sol"
    assert render_triplet("mks_zedd", "is", "fait de la pizza") == "mks_zedd fait de la pizza"
    assert render_triplet("lilith", "is", "veut que les gens parlent") == "lilith veut que les gens parlent"


def test_un_vrai_attribut_garde_son_verbe():
    """La garde ne doit pas manger le verbe d'un attribut légitime."""
    assert render_triplet("Azraël", "is", "développeur") == "Azraël est développeur"
    assert render_triplet("Cluth", "is", "classé Diamant 3") == "Cluth est classé Diamant 3"
    assert render_triplet("X", "is", "fatigué") == "X est fatigué"


def test_la_garde_ne_touche_que_les_verbes_de_liaison():
    """`joue à`, `utilise`… portent le sens : jamais escamotés."""
    assert render_triplet("X", "plays", "va bien") == "X joue à va bien"


def test_has_garde_son_auxiliaire_qui_forme_un_passe_compose():
    """« polylrose a fait un métier stressant » se tient : c'est un passé
    composé. L'escamoter donnerait un présent — un autre sens."""
    assert render_triplet("polylrose", "has", "fait un métier stressant") == (
        "polylrose a fait un métier stressant"
    )
    assert render_triplet("mks_zedd", "has", "mange peu") == "mks_zedd a mange peu"


# ── Les deux chemins d'écriture doivent passer par là ────────────────────────

def test_ingest_rend_le_fait_en_francais():
    from bot.intelligence.memory.ingest import _Candidate, _render_content

    cand = _Candidate(
        subject="mks_zedd", predicate="plays", object="Apex Legends",
        category="FAIT", confidence_source="explicit", importance=0.5,
    )
    assert _render_content(cand) == "mks_zedd joue à Apex Legends"
