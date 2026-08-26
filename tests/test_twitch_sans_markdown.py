"""Le chat Twitch n'a pas de markdown — un lien Discord y sort en charabia.

Constat de l'owner le 2026-08-26 : « les patch notes donnés dans le chat Twitch
comportent les liens comme sur Discord, il faut les enlever ».

La convention de citation façon Perplexity — « colle son marqueur cliquable
juste après la phrase, ex. [¹](<url>), garde les chevrons » — vient de
`WebSearchService` et du recall RSS. Elle est juste sur Discord, qui rend le
markdown et masque l'aperçu grâce aux chevrons. Sur Twitch, le chat est du
TEXTE BRUT : le viewer lit `[²](<https://steamstore-a.akamaihd.net/…>)` en
toutes lettres, au milieu d'une phrase de deux lignes.

Le portage sur Twitch était délibéré — un commentaire de `handlers.py` dit
même vouloir que « les marqueurs de citation survivent à la troncature, comme
côté Discord ». C'est la plateforme qui n'avait pas été vérifiée.

Deux gardes, parce que le prompt n'est pas un contrat : le bloc RSS cesse de
demander des marqueurs sur Twitch, et le texte publié est nettoyé de toute
façon — `web_search` porte la même consigne, et un modèle écrit du markdown
sans qu'on le lui demande.
"""
import pytest

from bot.core.text_clean import retirer_liens_markdown


# Les deux premières sont des lignes RÉELLES publiées sur azrael_ttv.
@pytest.mark.parametrize("sale,propre", [
    (
        "Elle s'est pris un gros nerf [²](<https://steamstore-a.akamaihd.net/x>)",
        "Elle s'est pris un gros nerf",
    ),
    (
        "C'est le patch Marked, sorti le 4 août [⁴](<https://store.steampowered.com/n>) "
        "et World's Edge est remaniée.",
        "C'est le patch Marked, sorti le 4 août et World's Edge est remaniée.",
    ),
    # Un lien NOMMÉ garde son texte : l'information est dans le libellé, pas
    # dans l'URL. Tout jeter effacerait le sujet de la phrase.
    (
        "Va voir [le patch note](https://x.fr) pour les détails",
        "Va voir le patch note pour les détails",
    ),
    # Sans chevrons non plus — le modèle les oublie une fois sur deux.
    ("Nerf de Maggie [¹](https://x.fr)", "Nerf de Maggie"),
    # Plusieurs marqueurs dans la même phrase.
    ("A [¹](<https://a.fr>) et B [²](<https://b.fr>) sont sortis",
     "A et B sont sortis"),
])
def test_les_liens_markdown_sont_retires(sale, propre):
    assert retirer_liens_markdown(sale) == propre


# ── ce qu'il ne faut SURTOUT pas casser ────────────────────────────────
@pytest.mark.parametrize("texte", [
    # Une URL NUE est volontaire sur Twitch, et c'est même le seul lien qui y
    # marche. Wally publie le planning comme ça.
    "https://heywally.fr/static/fichiers/planning.webp",
    "Voilà, c'est affiché. https://heywally.fr/static/fichiers/planning.webp",
    # Des crochets sans lien derrière — un pendu, un tableau de score.
    "Le mot : [_ _ _ _ _]",
    "KingsRequin [3 kills] vs Azraël [7 kills]",
    # Une parenthèse qui suit des crochets sans être une URL.
    "Il a dit [texte] (et il avait raison)",
])
def test_ce_qui_n_est_pas_un_lien_reste_intact(texte):
    assert retirer_liens_markdown(texte) == texte


def test_le_vide_ne_casse_rien():
    assert retirer_liens_markdown("") == ""
    assert retirer_liens_markdown(None) == ""
