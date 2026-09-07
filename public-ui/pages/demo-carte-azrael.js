// public-ui/pages/demo-carte-azrael.js — une carte seule, en démonstration
//
// Page HORS NAVIGATION, servie à `/demo/carte-azrael` : une URL qu'on donne à
// la main pour montrer une carte du TCG en grand, sans le reste de la
// collection. Elle n'est ni dans la barre du haut, ni dans celle du pouce, ni
// dans les ancres héritées.
//
// Le rendu de la carte vient de `tcg-carte-hero.js` et ses valeurs de
// `tcg-collection.js` : cette page n'écrit AUCUNE donnée de jeu. Une seconde
// définition d'Azraël ici divergerait de la collection au premier réglage.

import { h } from '../app.js';
import { CARTES } from './tcg-collection.js';
import { carteHero, monterStylesCarte } from './tcg-carte-hero.js';

const FEUILLE = '/pages/demo-carte-azrael.css';

const AZRAEL = CARTES.find((e) => e.carte.nom === 'AZRAËL');

let _demonter = null;

export function mount(el) {
  const lien = document.createElement('link');
  lien.rel = 'stylesheet';
  lien.href = FEUILLE;
  document.head.appendChild(lien);
  const demonterStyles = monterStylesCarte();

  const { boite, detruire } = carteHero(AZRAEL.carte);
  el.appendChild(h('section', { class: 'dca-scene' },
    boite,
    h('div', { class: 'dca-note', text: 'MAQUETTE — LA CARTE NE SE JOUE PAS ENCORE' }),
  ));

  _demonter = () => {
    detruire();
    demonterStyles();
    lien.remove();
  };
}

export function unmount() {
  if (_demonter) _demonter();
  _demonter = null;
}
