"""`escJs` doit survivre au décodage d'entités du navigateur.

Une valeur posée dans `onclick="foo('…')"` traverse DEUX parseurs : le parseur
HTML décode les entités de l'attribut, PUIS le contenu est compilé comme du
JavaScript. `escAttr` seul écrivait `&#39;` pour une apostrophe — redevenue `'`
au décodage, elle fermait la chaîne JS. Un pseudo Discord valant
`x');alert(1)//` exécutait donc du code à l'ouverture de l'onglet Mémoire, et
le jeton admin vit en `localStorage` sur la même origine.

Le test charge les VRAIES fonctions de `app.js` (pas une copie qui divergerait),
rejoue le décodage du navigateur, puis vérifie que le JS obtenu est un appel
unique dont l'argument redonne la valeur d'origine, au caractère près.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static" / "app.js"

# Chaînes d'évasion, plus des valeurs légitimes qui doivent ressortir INTACTES
# (un nom avec apostrophe est banal — l'échappement ne doit pas l'abîmer).
CHARGES = [
    "x');alert('PWNED",
    "x\\');alert(1)//",
    '" onmouseover="alert(1)',
    "<img src=x onerror=alert(1)>",
    "L'ami \"guillemets\" & co",
    "a&#39;b",
    "multi\nligne",
    "Azraël",
]

# NOTE SÉCURITÉ — `eval()` est ici volontaire et c'est le sujet du test.
# Il ne sert pas à parser des données : il reproduit exactement ce que fait un
# navigateur avec un attribut `onclick`, c'est-à-dire COMPILER la chaîne comme
# du JavaScript. Sans cette étape, le test ne prouverait rien de l'évasion.
# Les seules entrées sont `CHARGES`, écrites en dur ci-dessus, et le fichier
# `app.js` du dépôt. Ce code ne tourne qu'en test, jamais en production.
_RUNNER = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');

// Extrait une fonction de app.js par équilibrage d'accolades : le test porte
// sur le code réellement servi, pas sur une réécriture.
function grab(name) {
  const start = src.indexOf('function ' + name + '(');
  if (start < 0) throw new Error('fonction introuvable : ' + name);
  let depth = 0;
  for (let k = src.indexOf('{', start); k < src.length; k++) {
    if (src[k] === '{') depth++;
    else if (src[k] === '}') { depth--; if (depth === 0) return src.slice(start, k + 1); }
  }
  throw new Error('accolades déséquilibrées : ' + name);
}
eval(grab('escAttr'));
eval(grab('escJs'));

// Ce que fait le parseur HTML sur une valeur d'attribut, avant compilation JS.
const htmlDecode = (s) => s
  .replace(/&quot;/g, '"').replace(/&#39;/g, "'")
  .replace(/&lt;/g, '<').replace(/&gt;/g, '>')
  .replace(/&amp;/g, '&');

const charges = JSON.parse(process.argv[3]);
const out = [];
for (const nom of charges) {
  const js = htmlDecode("cible('" + escJs(nom) + "','discord:1')");
  let appels = 0, recu = null;
  const cible = (a) => { appels++; recu = a; };
  let erreur = null;
  try { eval(js); } catch (e) { erreur = e.message; }
  out.push({ nom, appels, recu, erreur });
}
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def resultats(tmp_path_factory):
    if shutil.which("node") is None:
        pytest.skip("node absent — échappement JS non vérifiable ici")
    runner = tmp_path_factory.mktemp("xss") / "runner.js"
    runner.write_text(_RUNNER, encoding="utf-8")
    proc = subprocess.run(
        ["node", str(runner), str(APP_JS), json.dumps(CHARGES)],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return {r["nom"]: r for r in json.loads(proc.stdout)}


@pytest.mark.parametrize("charge", CHARGES)
def test_aucune_evasion_de_chaine_js(charge, resultats):
    r = resultats[charge]
    assert r["erreur"] is None, f"JS invalide produit : {r['erreur']}"
    assert r["appels"] == 1, "du code supplémentaire a été exécuté — évasion"
    assert r["recu"] == charge, "la valeur a été altérée par l'échappement"


def test_escattr_reste_sur_pour_un_attribut_simple():
    """`escAttr` sert encore pour `data-…`, `title`, `value`. Il échappait `\"`
    mais pas `&` : une valeur contenant littéralement `&quot;` cassait alors
    l'attribut."""
    if shutil.which("node") is None:
        pytest.skip("node absent")
    source = APP_JS.read_text(encoding="utf-8")
    debut = source.index("function escAttr(")
    corps = source[debut:debut + 400]
    # L'ordre compte : `&` doit être remplacé EN PREMIER.
    assert corps.index("&amp;") < corps.index("&quot;")
    assert "'" in corps and "&#39;" in corps
