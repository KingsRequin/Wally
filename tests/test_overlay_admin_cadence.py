"""La cadence du rotateur dans le panneau de mise en scène.

Deux réglages — durée d'affichage, pause — qui n'existent QUE sur l'élément
`rotator`. Ce que ces tests figent :

  1. Le panneau et le modèle décrivent les mêmes bornes. Deux tables qui disent
     la même chose dérivent au premier ajustement, et le panneau laisserait
     alors saisir une valeur que le serveur ramène en silence — on croit avoir
     réglé, rien ne bouge, et rien ne le dit.
  2. Les champs ne s'affichent que pour leur élément. La barre en compte déjà
     cinq ; « durée d'affichage » sur un dé est un réglage qu'aucun code ne lit.
  3. Rien ne s'écrit sur un élément qui ne porte pas le champ, même par un
     chemin détourné : un champ caché reste dans le document.

Sur le code d'avant, `OverlayAdmin.CHAMPS_PROPRES` est `undefined` et le premier
test échoue à la première ligne.
"""
import json
import subprocess
from pathlib import Path

import pytest

from bot.core.overlay_layout import CHAMPS_PROPRES, ELEMENTS

_STATIC = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"
_JS = (_STATIC / "overlay_admin.js").read_text(encoding="utf-8")

_PRELUDE = """
global.window = global;
global.navigator = {};
global.window.localStorage = {
  getItem: function () { return null; },
  setItem: function () {},
  removeItem: function () {},
};
require(%s);
require(%s);
const OA = window.OverlayAdmin;
""" % (json.dumps(str(_STATIC / "overlay_layout.js")),
       json.dumps(str(_STATIC / "overlay_admin.js")))

_SANS_NODE = subprocess.run(["which", "node"], capture_output=True).returncode != 0


def _table_du_panneau() -> dict:
    """`CHAMPS_PROPRES` tel que le navigateur le verra."""
    r = subprocess.run(
        ["node", "-e", _PRELUDE + "console.log(JSON.stringify(OA.CHAMPS_PROPRES));"],
        capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.skipif(_SANS_NODE, reason="node absent")
def test_le_panneau_et_le_modele_disent_les_memes_bornes():
    """Ce que le panneau propose de régler doit exister dans le modèle, avec
    les mêmes bornes et le même défaut.

    Le sens du test a été précisé le 2026-08-21, quand les réglages propres ont
    cessé d'être l'apanage du rotateur : ce n'est PAS une égalité des deux
    tables — le modèle en porte trente-six et le panneau n'en montre qu'une
    partie —, c'est une INCLUSION. Un champ affiché sans exister dans le modèle
    laisse saisir une valeur que le serveur ramène en silence : on croit avoir
    réglé, rien ne bouge, et rien ne le dit. C'est ce trou-là qu'on ferme, et
    l'inclusion le ferme aussi bien que l'égalité — sans se briser au prochain
    élément qui gagne un réglage."""
    table = _table_du_panneau()
    for cle, champs_js in table.items():
        assert cle in CHAMPS_PROPRES, (
            f"`{cle}` gagne des réglages propres côté panneau seulement"
        )
        modele = CHAMPS_PROPRES[cle]
        champs = {c[0]: c for c in champs_js}
        assert set(champs) <= set(modele), (
            f"`{cle}` : le panneau propose un champ que le modèle ignore"
        )
        for nom, champ in champs.items():
            mini, maxi, _auto = modele[nom]
            assert champ[2] == mini, f"borne basse de `{cle}.{nom}` désaccordée"
            assert champ[3] == maxi, f"borne haute de `{cle}.{nom}` désaccordée"
            assert champ[6] == ELEMENTS[cle][nom], (
                f"défaut de `{cle}.{nom}` désaccordé"
            )


@pytest.mark.skipif(_SANS_NODE, reason="node absent")
def test_les_libelles_sont_en_francais_et_portent_leur_unite():
    """Le propriétaire règle ça en plein live : « duree » et un nombre nu le
    laisseraient deviner s'il s'agit de secondes ou de millisecondes."""
    for champ in _table_du_panneau()["rotator"]:
        assert "(s)" in champ[1], f"le libellé `{champ[1]}` ne dit pas son unité"
        assert champ[5], f"le champ `{champ[0]}` n'a pas d'explication"


def test_un_champ_propre_est_cache_hors_de_son_element():
    """`hidden` sur le bloc, pas seulement un champ grisé : un réglage visible
    que rien ne lit est une promesse fausse."""
    assert "champ.bloc.hidden = !sien" in _JS


def test_un_champ_propre_refuse_decrire_hors_de_son_element():
    """La garde est au POINT D'ÉCRITURE et pas au rendu : un bloc caché reste
    dans le document, et un navigateur qui garde le focus — ou un script —
    poserait `duree` sur le premier élément venu. Même raisonnement que le
    cadenas, déjà payé ici."""
    assert "if (proprietaire && etat.elementCourant !== proprietaire) return;" in _JS
