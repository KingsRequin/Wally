"""Le catalogue des cartes ACTION / PASSIF et son lecteur.

⚠️ Ces tests portent sur les INVARIANTS du fichier, jamais sur les valeurs
elles-mêmes : asserter « il y a 46 cartes » ou « pizzas coûte 0 » figerait un
catalogue qui bouge à chaque passe de l'owner, et le test deviendrait la seule
chose à mettre à jour quand une carte entre. Ce qu'on tient ici, c'est que le
lecteur REFUSE ce qu'il doit refuser et que la sortie JSON reste lisible par le
front.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from bot.core import tcg_cartes_action as mod
from bot.core.tcg_cartes_action import (
    CARTES_ACTION,
    CATEGORIES,
    COULEUR_CATEGORIE,
    ICONE_CATEGORIE,
    LIBELLE_CATEGORIE,
    TYPES,
    en_json,
    par_categorie,
)


def _ecrire(tmp_path: Path, corps: str) -> Path:
    chemin = tmp_path / "cartes_action.yaml"
    chemin.write_text(textwrap.dedent(corps), encoding="utf-8")
    return chemin


VALIDE = """
    - cle: essai
      nom: Une carte d'essai
      court: ESSAI
      type: action
      categorie: attaque
"""


# ── Le catalogue réel ─────────────────────────────────────────────────────

def test_le_catalogue_de_prod_charge():
    """Le fichier livré est lisible et non vide — c'est le boot qui en dépend."""
    assert CARTES_ACTION
    assert all(c.type in TYPES for c in CARTES_ACTION.values())
    assert all(c.categorie in CATEGORIES for c in CARTES_ACTION.values())


def test_chaque_categorie_a_sa_couleur_son_icone_et_son_libelle():
    """Une catégorie ajoutée sans ses trois tables rendrait un `KeyError` au
    premier `en_json`, c'est-à-dire au premier chargement de la page."""
    for categorie in CATEGORIES:
        assert categorie in COULEUR_CATEGORIE
        assert categorie in ICONE_CATEGORIE
        assert categorie in LIBELLE_CATEGORIE


def test_aucune_categorie_ne_porte_l_or_du_cout():
    """L'or est RÉSERVÉ à la pastille de coût sur le recto.

    Deux choses différentes de la même couleur au même endroit se lisent comme
    la même chose : c'est pour ça que l'Aura est passée de l'or à la baie.
    """
    assert "#e1a947" not in {c.lower() for c in COULEUR_CATEGORIE.values()}


def test_les_icones_de_categorie_existent_sur_le_disque():
    for chemin in ICONE_CATEGORIE.values():
        sur_disque = mod.DOSSIER_ASSETS / chemin.removeprefix("/assets/")
        assert sur_disque.is_file(), f"icône de catégorie absente : {sur_disque}"


def test_par_categorie_rend_tout_le_monde_et_groupe_les_familles():
    liste = par_categorie()
    assert len(liste) == len(CARTES_ACTION)
    vues = [c.categorie for c in liste]
    # Chaque famille forme un bloc : le nombre de CHANGEMENTS de catégorie ne
    # dépasse pas le nombre de familles présentes.
    ruptures = sum(1 for a, b in zip(vues, vues[1:], strict=False) if a != b)
    assert ruptures == len(set(vues)) - 1


# ── La sortie JSON ────────────────────────────────────────────────────────

def test_en_json_sert_la_couleur_plutot_que_de_la_laisser_recopier():
    """Le front ne doit PAS tenir sa propre table de couleurs.

    Une table dupliquée diverge le jour où une teinte bouge, et le bandeau
    garde l'ancienne pendant que le cadre prend la nouvelle.
    """
    carte = next(iter(CARTES_ACTION.values()))
    sortie = en_json(carte)
    assert sortie["categorieCouleur"] == COULEUR_CATEGORIE[carte.categorie]
    assert sortie["categorieLabel"] == LIBELLE_CATEGORIE[carte.categorie]
    assert sortie["categorieIcone"].startswith(ICONE_CATEGORIE[carte.categorie])


def test_en_json_versionne_le_pochoir():
    """Sans empreinte, une icône retouchée reste figée quatre heures derrière
    Cloudflare, qui écrase le `Cache-Control` de l'origine."""
    avec_visuel = [c for c in CARTES_ACTION.values() if c.visuel]
    assert avec_visuel, "aucune carte au pochoir : le test ne prouve rien"
    for carte in avec_visuel:
        assert "?v=" in en_json(carte)["visuel"]


def test_en_json_rend_none_et_non_une_chaine_vide():
    """`""` est faux en JavaScript sans pour autant dire « absent »."""
    sans_visuel = [c for c in CARTES_ACTION.values() if not c.visuel]
    assert sans_visuel, "toutes les cartes ont un pochoir : le test ne prouve rien"
    assert en_json(sans_visuel[0])["visuel"] is None


def test_en_json_n_invente_aucune_cle():
    """Le front lit un contrat fixe ; une clé de plus ou de moins le casse en
    silence, puisqu'un champ absent vaut `undefined` sans lever."""
    attendues = {
        "cle", "nom", "court", "type", "categorie", "categorieLabel",
        "categorieCouleur", "categorieIcone", "cout", "regle", "visuel",
        "texte", "groupe", "semis", "arc", "faceCachee",
    }
    assert set(en_json(next(iter(CARTES_ACTION.values())))) == attendues


# ── Ce que le lecteur doit REFUSER ────────────────────────────────────────

def test_un_champ_inconnu_est_refuse(tmp_path):
    """Un réglage mal orthographié doit LEVER, pas être ignoré : c'est tout
    l'intérêt d'avoir sorti ces valeurs du code."""
    chemin = _ecrire(tmp_path, VALIDE + "      categorei: soin\n")
    with pytest.raises(ValueError, match="champ inconnu"):
        mod._lire(chemin)


def test_un_champ_obligatoire_manquant_est_refuse(tmp_path):
    chemin = _ecrire(tmp_path, """
        - cle: essai
          nom: Une carte d'essai
    """)
    with pytest.raises(ValueError, match="champ obligatoire manquant"):
        mod._lire(chemin)


def test_une_cle_en_double_est_refusee(tmp_path):
    chemin = _ecrire(tmp_path, VALIDE + VALIDE)
    with pytest.raises(ValueError, match="clé en double"):
        mod._lire(chemin)


def test_un_type_hors_vocabulaire_est_refuse(tmp_path):
    chemin = _ecrire(tmp_path, VALIDE.replace("type: action", "type: tactique"))
    with pytest.raises(ValueError, match="type="):
        mod._lire(chemin)


def test_une_categorie_hors_vocabulaire_est_refusee(tmp_path):
    chemin = _ecrire(tmp_path, VALIDE.replace("categorie: attaque",
                                              "categorie: energie"))
    with pytest.raises(ValueError, match="categorie="):
        mod._lire(chemin)


def test_un_pochoir_absent_du_disque_est_refuse(tmp_path):
    """Une carte au pochoir mort rendrait un CADRE VIDE annoncé comme illustré.

    C'est la même règle que l'entrée des héros, pour la même raison : le site
    affiche exactement ce contenu, et son compteur en dérive.
    """
    chemin = _ecrire(tmp_path, VALIDE + "      visuel: /assets/icones/nexistepas.svg\n")
    with pytest.raises(ValueError, match="introuvable sur le disque"):
        mod._lire(chemin)


def test_un_visuel_hors_assets_est_refuse(tmp_path):
    chemin = _ecrire(tmp_path, VALIDE + "      visuel: https://ailleurs/x.svg\n")
    with pytest.raises(ValueError, match="mal formé"):
        mod._lire(chemin)


def test_visuel_et_texte_ensemble_sont_refuses(tmp_path):
    """Les deux occupent la MÊME fenêtre d'illustration. Laisser passer
    laisserait le front en choisir un, en silence et sans règle."""
    chemin = _ecrire(tmp_path, VALIDE
                     + "      visuel: /assets/icones/full-pizza.svg\n"
                     + "      texte: FEUR\n")
    with pytest.raises(ValueError, match="occupent la fenêtre"):
        mod._lire(chemin)


def test_groupe_et_semis_ensemble_sont_refuses(tmp_path):
    chemin = _ecrire(tmp_path, VALIDE + "      groupe: 3\n      semis: 4\n")
    with pytest.raises(ValueError, match="occupent la fenêtre"):
        mod._lire(chemin)


def test_un_arc_sans_semis_est_refuse(tmp_path):
    """L'arc RANGE le semis en courbe ; sans semis il n'y a rien à ranger."""
    chemin = _ecrire(tmp_path, VALIDE + "      arc: true\n")
    with pytest.raises(ValueError, match="arc sans semis"):
        mod._lire(chemin)
