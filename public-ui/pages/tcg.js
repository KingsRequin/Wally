// public-ui/pages/tcg.js — la collection de cartes
//
// Port de la maquette Claude Design `Galerie Cartes.dc.html` : les cartes
// TERMINÉES, ajoutées au fur et à mesure. Elle a remplacé l'annonce du TCG et
// la maquette du plateau (`/demo/plateau-tcg`), retirée le 2026-09-09 : c'était
// un concept, redessiné depuis, et il portait un SECOND catalogue de héros aux
// chiffres divergents de ceux d'ici.
//
// Les cartes viennent de `GET /api/public/tcg/cartes` — la même source que
// l'outil de Wally et le widget de l'overlay. Le compteur en DÉRIVE, il ne
// s'écrit pas. Le moteur de règles vit côté serveur, en Python.

import { h, inclinaisonDisponible, pageFooter, surInclinaison } from '../app.js';
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
  let geste = 'Survole-les pour voir les couches se séparer.';
  if (inclinaisonDisponible()) {
    geste = 'Penche ton téléphone pour voir les couches se séparer.';
  } else if (window.matchMedia('(hover: none)').matches) {
    geste = 'Touche-les pour voir les couches se séparer.';
  }
  return `Les cartes finies, ajoutées au fur et à mesure. ${geste}`;
}

/** Fait suivre le gyroscope à la carte que le lecteur a devant les yeux.
 *
 * Sur un ordinateur il suffit de PASSER la souris sur une carte ; l'équivalent
 * au téléphone n'est pas un appui, c'est d'avoir la carte devant soi. Celle
 * qui traverse la bande centrale de l'écran s'ouvre donc, et suit
 * l'inclinaison ; les autres restent à plat.
 *
 * 🚨 UNE seule carte ouverte à la fois, et c'est délibéré : la 3D d'une carte
 * coûte neuf calques GPU au lieu d'un (cf. `set3d` dans le composant). Toutes
 * les ouvrir parce qu'elles sont à l'écran ferait ramer la page sur le
 * matériel même qui a le gyroscope.
 *
 * ⚠️ La bande centrale est déléguée à un `IntersectionObserver` plutôt que
 * recalculée au défilement : mesurer la position de N cartes à chaque image
 * coûte un reflow par image, sur mobile, pendant qu'on scrolle.
 *
 * ⚠️ Rien à faire ici pour l'autorisation iOS : `app.js` la demande au premier
 * appui sur la page, une fois pour tout le site.
 */
function brancherGyroscope(rendues) {
  let ouverte = null;

  const oeil = new IntersectionObserver((entrees) => {
    entrees.forEach((e) => {
      if (!e.isIntersecting) return;
      const carte = rendues.find((r) => r.noeud === e.target);
      if (!carte || carte === ouverte) return;
      if (ouverte) { ouverte.incliner(0, 0); ouverte.fermer(); }
      ouverte = carte;
      carte.ouvrir();
    });
    // `-45%` en haut ET en bas : il ne reste que le dixième central de
    // l'écran. Deux cartes n'y tiennent pas ensemble, donc l'ouverture ne
    // clignote pas entre deux voisines pendant le défilement.
  }, { rootMargin: '-45% 0px -45% 0px' });
  rendues.forEach((r) => oeil.observe(r.noeud));

  // `x` et `y` arrivent dans [−1, 1] ; `incliner` attend [−0.5, 0.5]. Le
  // facteur donne donc la course COMPLÈTE d'un curseur passant d'un bord à
  // l'autre — pareil qu'à la souris, ce qui est ce qu'on veut.
  const stop = surInclinaison((x, y) => {
    if (ouverte) ouverte.incliner(x * 0.5, y * 0.5);
  });

  return () => { oeil.disconnect(); stop(); };
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

  // Le gyroscope remplace le survol ET le tap : les cartes sont alors pilotées
  // par la page, et le composant ne branche aucun écouteur (`interactif`).
  // Laisser le tap ouvrir une carte que le centrage refermerait aussitôt
  // n'aurait donné qu'un clignotement.
  const auGyroscope = inclinaisonDisponible();
  const rendues = [];
  let debrancherGyro = null;
  // La page peut être quittée pendant que la requête est en vol : sans ce
  // drapeau, on insérerait des cartes dans un `<main>` que le routeur a déjà
  // vidé, et elles resteraient abonnées à la boucle d'animation pour toujours.
  let vivante = true;

  const remplir = (liste) => {
    if (!vivante) return;
    grille.textContent = '';
    liste.forEach((carte) => {
      const rendu = carteHero(carte, { interactif: !auGyroscope });
      const noeud = h('div', { class: 'tcgal-case' },
        rendu.boite,
        h('div', { class: 'tcgal-legende', text: carte.legende }),
      );
      rendues.push({ ...rendu, noeud });
      grille.appendChild(noeud);
    });
    if (auGyroscope) debrancherGyro = brancherGyroscope(rendues);
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
    if (debrancherGyro) debrancherGyro();
    rendues.forEach((r) => r.detruire());
    demonterStyles();
    lien.remove();
  };
}

export function unmount() {
  if (_demonter) _demonter();
  _demonter = null;
}
