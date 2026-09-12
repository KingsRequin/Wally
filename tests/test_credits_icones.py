"""Les crédits d'icônes ne peuvent pas prendre du retard en silence.

🚨 Ce n'est pas un test de confort : les icônes de game-icons.net sont sous
**CC BY 3.0**, une licence qui oblige à créditer l'AUTEUR de chaque dessin. Une
icône ajoutée au catalogue sans sa ligne dans le manifeste, c'est une image
affichée sans droit — et rien à l'écran ne le signale, ni au moment de
l'ajout, ni jamais.

Le manifeste (`public-ui/assets/icones/AUTEURS.json`) est lu par la page
`/credits`, qui n'écrit aucun nom elle-même.
"""

from __future__ import annotations

import json
from pathlib import Path

DOSSIER_ICONES = Path("public-ui/assets/icones")
MANIFESTE = DOSSIER_ICONES / "AUTEURS.json"
DOSSIER_APEX = Path("public-ui/assets/apex")
PAGE_CREDITS = Path("public-ui/pages/credits.js")


def _manifeste() -> dict:
    return json.loads(MANIFESTE.read_text(encoding="utf-8"))


def _sur_disque() -> set[str]:
    return {p.stem for p in DOSSIER_ICONES.glob("*.svg")}


def _creditees(manifeste: dict) -> set[str]:
    return {nom for lot in manifeste["auteurs"].values() for nom in lot}


def test_toute_icone_du_dossier_est_creditee():
    """La condition de la licence, vérifiée à chaque suite."""
    manquantes = _sur_disque() - _creditees(_manifeste())
    assert not manquantes, (
        "icône(s) affichée(s) sans crédit d'auteur, ce que CC BY 3.0 interdit : "
        f"{sorted(manquantes)} — les ajouter à {MANIFESTE}"
    )


def test_aucun_credit_ne_pointe_vers_un_fichier_absent():
    """L'autre sens : un crédit orphelin gonfle la page et ment sur ce qu'on
    utilise. C'est la moitié qu'on oublie de vérifier."""
    orphelins = _creditees(_manifeste()) - _sur_disque()
    assert not orphelins, (
        f"crédit(s) sans fichier correspondant : {sorted(orphelins)}")


def test_le_manifeste_nomme_sa_licence_et_sa_source():
    """Sans elles, la page ne peut pas dire SOUS QUELLE licence elle crédite,
    et un crédit sans licence ne vaut rien."""
    manifeste = _manifeste()
    assert manifeste["_licence"] == "CC BY 3.0"
    assert manifeste["_source"].startswith("https://")


def test_aucune_icone_ne_garde_le_fond_noir_de_game_icons():
    """game-icons livre un fond noir plein cadre dans chaque fichier.

    Laissé en place, le `mask-image` du pochoir rend un CARRÉ OPAQUE : c'est le
    fond qui masque, pas le dessin. La carte affiche alors un bloc de couleur,
    sans erreur ni avertissement.
    """
    fautives = [p.name for p in DOSSIER_ICONES.glob("*.svg")
                if "M0 0h512v512H0z" in p.read_text(encoding="utf-8")]
    assert not fautives, (
        f"fond plein cadre non retiré, le pochoir rendra un carré : {fautives}")


def test_la_page_credits_nomme_les_trois_sources_demandees():
    """Arbitrage de l'owner du 2026-09-12 : game-icons, Apex Legends ET le wiki.

    Le wiki est nommé à part parce que c'est de LUI que viennent les icônes
    tirées du jeu — créditer seulement Apex laisserait l'hébergeur sans
    mention, alors que c'est son travail qu'on reprend.
    """
    page = PAGE_CREDITS.read_text(encoding="utf-8")
    for source in ("game-icons.net", "Apex Legends", "apexlegends.wiki.gg"):
        assert source in page, f"source non créditée sur /credits : {source}"


def test_la_page_credits_ne_recopie_aucun_nom_d_auteur():
    """La liste est LUE, jamais écrite dans le JS.

    Une liste recopiée reste en arrière dès la première icône ajoutée, et le
    test ci-dessus ne la verrait pas : il vérifie le manifeste, pas la page.
    """
    page = PAGE_CREDITS.read_text(encoding="utf-8")
    assert "AUTEURS.json" in page, "la page doit lire le manifeste"
    en_dur = [a for a in _manifeste()["auteurs"] if f'"{a}"' in page or f"'{a}'" in page]
    assert not en_dur, f"auteur(s) recopié(s) en dur dans la page : {en_dur}"


def test_les_visuels_apex_sont_bien_la():
    """Ils ne viennent pas de game-icons et ne sont pas dans le manifeste : ce
    sont les icônes du jeu, créditées en bloc à Apex Legends et au wiki."""
    assert list(DOSSIER_APEX.glob("*.svg")), (
        f"aucun visuel Apex dans {DOSSIER_APEX} — les cartes qui les utilisent "
        "seraient refusées au chargement du catalogue")
