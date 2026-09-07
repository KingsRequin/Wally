// public-ui/pages/demo-carte-azrael.js — une carte seule, en démonstration
//
// Page HORS NAVIGATION, servie à `/demo/carte-azrael` : une URL qu'on donne à
// la main pour montrer une carte du TCG en grand, sans le reste de la
// collection. Elle n'est ni dans la barre du haut, ni dans celle du pouce, ni
// dans les ancres héritées.
//
// Le rendu de la carte vient de `tcg-carte.js` et ses valeurs de la même
// source que la collection (`GET /api/public/tcg/cartes`) : cette page n'écrit
// AUCUNE donnée de jeu. Une seconde définition d'Azraël ici divergerait au
// premier réglage.

import { h } from '../app.js';
import { cartes } from './tcg-donnees.js';
import { carteHero, monterStylesCarte } from '../partage/tcg-carte.js';

const FEUILLE = '/pages/demo-carte-azrael.css';

let _demonter = null;

export function mount(el) {
  const lien = document.createElement('link');
  lien.rel = 'stylesheet';
  lien.href = FEUILLE;
  document.head.appendChild(lien);
  const demonterStyles = monterStylesCarte();

  const scene = h('section', { class: 'dca-scene' },
    h('div', { class: 'dca-note', text: 'MAQUETTE — LA CARTE NE SE JOUE PAS ENCORE,'
      + ' ET SES CHIFFRES SONT PROVISOIRES' }),
  );
  el.appendChild(scene);

  let vivante = true;
  let detruireCarte = null;

  cartes().then((liste) => {
    if (!vivante) return;
    const azrael = liste.find((c) => c.cle === 'azrael');
    if (!azrael) {
      // Elle a disparu du registre : le dire plutôt que rendre une scène vide,
      // qui se lirait comme un défaut d'affichage.
      scene.prepend(h('p', { class: 'dca-note', text: "Azraël n'est plus dans la collection." }));
      return;
    }
    const carte = carteHero(azrael);
    detruireCarte = carte.detruire;
    scene.prepend(carte.boite);
  }).catch((e) => {
    if (!vivante) return;
    console.warn('Démo carte : chargement échoué', e);
    scene.prepend(h('p', { class: 'dca-note', text: "La carte n'a pas pu être chargée." }));
  });

  _demonter = () => {
    vivante = false;
    if (detruireCarte) detruireCarte();
    demonterStyles();
    lien.remove();
  };
}

export function unmount() {
  if (_demonter) _demonter();
  _demonter = null;
}
