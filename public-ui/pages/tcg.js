// public-ui/pages/tcg.js — la collection de cartes
//
// Port de la maquette Claude Design `Galerie Cartes.dc.html` : les cartes
// TERMINÉES, ajoutées au fur et à mesure. Elle a remplacé l'annonce du TCG et
// la maquette du plateau, qui vivent désormais sur `/demo/plateau-tcg`.
//
// La page ne consomme AUCUNE API : les cartes sont écrites à la main dans
// `tcg-collection.js`, et le compteur en DÉRIVE. Le moteur de règles vit côté
// serveur, en Python.

import { h, pageFooter } from '../app.js';
import { CARTES } from './tcg-collection.js';
import { carteHero, monterStylesCarte } from './tcg-carte-hero.js';

const FEUILLE = '/pages/tcg.css';

let _demonter = null;

/** L'invitation à manipuler les cartes.
 *
 * « Survole-les » n'a aucun sens au doigt, et c'est là que le site est
 * majoritairement lu : la phrase suit le moyen de pointage, pas la largeur
 * d'écran (une tablette large n'a pas de curseur non plus).
 */
function invitation() {
  const geste = window.matchMedia('(hover: none)').matches
    ? 'Touche-les pour voir les couches se séparer.'
    : 'Survole-les pour voir les couches se séparer.';
  return `Les cartes finies, ajoutées au fur et à mesure. ${geste}`;
}

export function mount(el) {
  const lien = document.createElement('link');
  lien.rel = 'stylesheet';
  lien.href = FEUILLE;
  document.head.appendChild(lien);
  const demonterStyles = monterStylesCarte();

  const rendues = CARTES.map((entree) => {
    const { boite, detruire } = carteHero(entree.carte);
    return {
      detruire,
      case_: h('div', { class: 'tcgal-case' },
        boite,
        h('div', { class: 'tcgal-legende', text: entree.legende }),
      ),
    };
  });

  const pluriel = CARTES.length > 1 ? 'CARTES TERMINÉES' : 'CARTE TERMINÉE';

  el.appendChild(h('section', { class: 'tcgal' },
    h('div', { class: 'tcgal-inner' },
      h('header', { class: 'tcgal-head' },
        h('h1', { class: 'tcgal-titre', text: 'La collection' }),
        h('span', { class: 'tcgal-compte', text: `${CARTES.length} ${pluriel}` }),
      ),
      h('p', { class: 'tcgal-chapo', text: invitation() }),
      // Les chiffres des cartes sont des PLACEHOLDERS (cf. l'en-tête de
      // `tcg-collection.js`). Le dire À L'ÉCRAN et pas seulement en
      // commentaire : sans ça, le premier lecteur construit un deck sur des
      // valeurs qui vont toutes bouger, et c'est nous qui l'y avons invité.
      h('p', { class: 'tcgal-avis' },
        h('strong', { text: 'Les chiffres ne sont pas définitifs.' }),
        ' Coût, ATK, PV et AURA sont provisoires : ils sont là pour montrer'
        + ' la carte, pas pour être joués. Les vraies valeurs sont calculées'
        + ' ailleurs et arrivent carte par carte.',
      ),
      h('div', { class: 'tcgal-grille' }, ...rendues.map((r) => r.case_)),
    ),
  ));
  el.appendChild(pageFooter());

  _demonter = () => {
    rendues.forEach((r) => r.detruire());
    demonterStyles();
    lien.remove();
  };
}

export function unmount() {
  if (_demonter) _demonter();
  _demonter = null;
}
