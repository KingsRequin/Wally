// public-ui/pages/tcg.js — la collection de cartes
//
// Port de la maquette Claude Design `Galerie Cartes.dc.html` : les cartes
// TERMINÉES, ajoutées au fur et à mesure. Elle a remplacé l'annonce du TCG et
// la maquette du plateau, qui vivent désormais sur `/demo/plateau-tcg`.
//
// Les cartes viennent de `GET /api/public/tcg/cartes` — la même source que
// l'outil de Wally et le widget de l'overlay. Le compteur en DÉRIVE, il ne
// s'écrit pas. Le moteur de règles vit côté serveur, en Python.

import { h, pageFooter } from '../app.js';
import { cartes } from './tcg-donnees.js';
import { carteHero, monterStylesCarte } from '../partage/tcg-carte.js';

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

/** Le bandeau qui dit que les chiffres ne valent rien.
 *
 * Le dire À L'ÉCRAN et pas seulement en commentaire : sans ça, le premier
 * lecteur construit un deck sur des valeurs qui vont toutes bouger, et c'est
 * nous qui l'y avons invité.
 */
function avis() {
  return h('p', { class: 'tcgal-avis' },
    h('strong', { text: 'Les chiffres ne sont pas définitifs.' }),
    ' Coût, ATK, PV et AURA sont provisoires : ils sont là pour montrer'
    + ' la carte, pas pour être joués. Les vraies valeurs sont calculées'
    + ' ailleurs et arrivent carte par carte.',
  );
}

export function mount(el) {
  const lien = document.createElement('link');
  lien.rel = 'stylesheet';
  lien.href = FEUILLE;
  document.head.appendChild(lien);
  const demonterStyles = monterStylesCarte();

  const compte = h('span', { class: 'tcgal-compte', text: '' });
  const grille = h('div', { class: 'tcgal-grille' });
  el.appendChild(h('section', { class: 'tcgal' },
    h('div', { class: 'tcgal-inner' },
      h('header', { class: 'tcgal-head' },
        h('h1', { class: 'tcgal-titre', text: 'La collection' }),
        compte,
      ),
      h('p', { class: 'tcgal-chapo', text: invitation() }),
      avis(),
      grille,
    ),
  ));
  el.appendChild(pageFooter());

  const rendues = [];
  // La page peut être quittée pendant que la requête est en vol : sans ce
  // drapeau, on insérerait des cartes dans un `<main>` que le routeur a déjà
  // vidé, et elles resteraient abonnées à la boucle d'animation pour toujours.
  let vivante = true;

  const remplir = (liste) => {
    if (!vivante) return;
    grille.textContent = '';
    liste.forEach((carte) => {
      const { boite, detruire } = carteHero(carte);
      rendues.push(detruire);
      grille.appendChild(h('div', { class: 'tcgal-case' },
        boite,
        h('div', { class: 'tcgal-legende', text: carte.legende }),
      ));
    });
    const pluriel = liste.length > 1 ? 'CARTES TERMINÉES' : 'CARTE TERMINÉE';
    compte.textContent = `${liste.length} ${pluriel}`;
  };

  // Un échec doit se DIRE. Une grille vide se lit « il n'y a pas de cartes »,
  // ce qui est faux — l'absence n'est pas le vide, et un visiteur qui tombe
  // dessus repart en croyant la collection abandonnée.
  const echouer = (e) => {
    if (!vivante) return;
    console.warn('TCG : cartes non chargées', e);
    compte.textContent = '';
    grille.textContent = '';
    const reessayer = h('button', {
      class: 'btn btn-ghost',
      text: 'Réessayer',
      onclick: () => {
        grille.textContent = '';
        cartes().then(remplir).catch(echouer);
      },
    });
    grille.appendChild(h('div', { class: 'tcgal-echec' },
      h('p', { text: "Les cartes n'ont pas pu être chargées." }),
      reessayer,
    ));
  };

  cartes().then(remplir).catch(echouer);

  _demonter = () => {
    vivante = false;
    rendues.forEach((detruire) => detruire());
    demonterStyles();
    lien.remove();
  };
}

export function unmount() {
  if (_demonter) _demonter();
  _demonter = null;
}
