"""Wally doit savoir ce qu'il sait faire — et ça se vérifie.

Ce dépôt a déjà payé l'inverse : le 2026-08-09, Wally a demandé par `code_fix`
une capacité qu'il possédait depuis quatre jours. L'enquête avait conclu qu'il
manquait « une description de son PRÉSENT », pas un historique de demandes.

Cinq capacités ont été construites les 17 et 18 août — musique, paris, kills,
et deux récompenses de points de chaîne — sans que sa fiche bouge d'une ligne.
Personne ne l'aurait vu : le bot marche parfaitement, il ignore simplement ce
qu'il fait. Ce fichier rend l'oubli bruyant.

Il ne vérifie PAS une formulation (ce serait figer la plume) mais la PRÉSENCE
d'un point d'ancrage par capacité livrée.
"""
from pathlib import Path

import pytest

_FICHE = Path(__file__).resolve().parents[1] / "bot" / "persona" / "CAPABILITIES.md"


@pytest.fixture(scope="module")
def fiche() -> str:
    return _FICHE.read_text(encoding="utf-8").lower()


@pytest.mark.parametrize("capacite,indices", [
    # §12 — le compteur de kills, affiché tout seul en fin de partie.
    ("compteur de kills Apex", ("kills", "partie")),
    # §13 — les paris Twitch qu'il résout lui-même.
    ("paris sur les kills", ("pari", "mise")),
    # §10 — la musique d'Azraël : la dire, et la piloter pour les modos.
    ("musique du live", ("écoute", "musique")),
    # §9 et §14 — ce que les points de chaîne déclenchent chez lui.
    ("récompenses de points de chaîne", ("points de chaîne", "récompense")),
    ("attaque de memes", ("memes", "blue screen")),
    ("forcer une humeur", ("émotions", "rendus")),
    # §11 — déjà présent, et il doit le rester.
    ("parler en vocal sur demande d'un modo", ("voix haute", "vocal")),
])
def test_chaque_capacite_livree_figure_dans_sa_fiche(fiche, capacite, indices):
    manquants = [i for i in indices if i not in fiche]
    assert not manquants, (
        f"« {capacite} » n'est pas dans CAPABILITIES.md (mots absents : "
        f"{manquants}). Wally ignore qu'il sait le faire — et répondra qu'il ne "
        f"sait pas si on le lui demande.")


def test_la_fiche_dit_aussi_ce_qu_il_NE_peut_pas_faire():
    """La moitié qui l'empêche d'inventer. Une fiche qui n'énumère que des
    pouvoirs produit un vantard."""
    texte = _FICHE.read_text(encoding="utf-8")
    assert "## Ce que je ne peux PAS faire" in texte


def test_les_capacites_conditionnelles_restent_HONNETES(fiche):
    """Trois de ces capacités dépendent de quelque chose d'extérieur : une
    extension installée chez Azraël, une autorisation Twitch, des récompenses
    qu'il a laissées en place.

    La fiche doit donc dire « quand », pas « toujours » — sinon Wally promet à
    un viewer une récompense qui n'existe pas, ce qui est exactement
    l'hallucination de capacité que ce fichier combat.
    """
    assert "n'existent que si" in fiche or "que si" in fiche
    assert "je ne sais pas" in fiche
