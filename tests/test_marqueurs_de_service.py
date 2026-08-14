"""Un marqueur interne ne doit JAMAIS finir devant quelqu'un.

`RIEN` est le mot par lequel le modèle dit « il n'y a rien à afficher ». Le garde
testait une égalité exacte après nettoyage : tout ce qui l'entourait passait donc
à l'écran de l'overlay, devant les spectateurs.

    21:24:08   `RIEN`                                     (seul, avec ses backticks)
    21:40:41   Il parle comme un vieux sage. RIEN
    21:54:24   C'est le genre de moment où l'on se tait. RIEN

12 occurrences sur 5 jours. Même famille, même jour : une bulle affichée avec ses
backticks Markdown en clair (l'overlay ne rend pas le Markdown), et le `OK` de la
passe miroir Discord, épelé lui aussi entre backticks dans son prompt.

Le piège inverse compte autant : « personne dit rien » est une bulle parfaitement
valable. D'où la règle sur la CASSE — le marqueur est un mot de service, écrit
comme le prompt l'épelle.
"""
import pytest

from bot.intelligence.prompts import marqueur_de_service, nettoyer_decorations


# ── ce qui doit être refusé ──────────────────────────────────────────────────

@pytest.mark.parametrize("sortie", [
    "RIEN",
    "`RIEN`",
    "RIEN.",
    "  rien  ",
    "«RIEN»",
    "Il parle comme un vieux sage. RIEN",
    "C'est le genre de moment où l'on se tait. RIEN",
    "je préfère me taire — RIEN",
    "aucune idée, RIEN.",
])
def test_le_marqueur_est_reconnu_meme_habille(sortie):
    assert marqueur_de_service(sortie, "RIEN")


# ── ce qui doit passer ───────────────────────────────────────────────────────

@pytest.mark.parametrize("sortie", [
    "personne dit rien",
    "il comprend rien à Apex",
    "RIEN à signaler chez Azraël",      # en tête : le mot a son sens ordinaire
    "je m'ennuie ferme",
    "",
])
def test_une_vraie_bulle_nest_pas_prise_pour_le_marqueur(sortie):
    assert not marqueur_de_service(sortie, "RIEN")


def test_un_marqueur_vide_ne_refuse_rien():
    assert not marqueur_de_service("une phrase quelconque", "")


# ── décorations : ce qui s'affiche ───────────────────────────────────────────

@pytest.mark.parametrize("brut,attendu", [
    ("`je m'ennuie ferme`", "je m'ennuie ferme"),
    ('"toujours pas de nouvelles"', "toujours pas de nouvelles"),
    ("«  il rage encore  »", "il rage encore"),
    ("  personne\n  parle  ", "personne parle"),
    ("**gros silence**", "gros silence"),
])
def test_les_decorations_ne_montent_pas_a_lecran(brut, attendu):
    assert nettoyer_decorations(brut) == attendu
