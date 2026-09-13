// public-ui/pages/wallycard.js — l'écran titre de Wallycard (`/wallycard`)
//
// Un menu de jeu vidéo : Jouer, Bibliothèque, Règles. Le style est celui du dos
// de carte « purgatoire », référence validée du projet de design : trame
// losange posée depuis le centre, plaque de titre à losanges or, banderoles en
// miroir. Il n'invente rien, il reprend.
//
// 🚨 Une entrée qui ne mène à rien est DÉSACTIVÉE et le dit (« bientôt »). Un
// bouton cliquable qui ne fait rien est le défaut que ce dépôt traque partout
// ailleurs : on clique, rien ne bouge, rien ne l'explique.

import { h, pageFooter } from '../app.js';

const FEUILLE = '/pages/wallycard.css';

const DEFILE = 'WALLYCARD · JEU DE CARTES DE LA COMMU · ';

// Les entrées du menu. `route` absente = pas encore livrée : l'entrée s'affiche
// grisée avec la mention « bientôt », et reste hors de la tabulation.
const ENTREES = [
  { libelle: 'Jouer', detail: 'Les parties arrivent' },
  { libelle: 'Bibliothèque', detail: 'Les cartes et tes decks', route: '/wallycard/bibliotheque' },
  { libelle: 'Règles', detail: 'Le livre des règles' },
];

// Les étincelles de la trame. ÉNUMÉRÉES sur la grille, jamais posées à la main
// (un semis écrit un par un laisse toujours une rangée dehors), et PEU
// nombreuses : chaque point est un calque animé en boucle. Le retard dépend de
// la distance au centre, donc les points en miroir battent ensemble.
const PAS = 6;
function etincelles() {
  const pts = [];
  for (let m = -PAS; m <= PAS; m += 1) {
    for (let n = -3; n <= 3; n += 1) {
      if ((m + n) % 2 !== 0 || (Math.abs(m) + Math.abs(n)) % 3 !== 0) continue;
      pts.push({
        l: `calc(50% + ${m * 3.4}em)`,
        t: `calc(50% + ${n * 3.4}em)`,
        d: `${((Math.abs(m) * 2 + Math.abs(n) * 5) % 12) * 0.5}s`,
      });
    }
  }
  return pts;
}

function banderole(bord) {
  // Deux copies du texte : l'animation translate de −50 %, soit une copie
  // exactement, et la boucle se ferme sans couture.
  return h('div', { class: 'wcm-banderole', 'data-bord': bord, 'aria-hidden': 'true' },
    h('div', { class: 'wcm-defile' },
      h('span', { text: DEFILE.repeat(4) }),
      h('span', { text: DEFILE.repeat(4) }),
    ),
  );
}

function entree({ libelle, detail, route }) {
  const contenu = [
    h('span', { class: 'wcm-entree-libelle', text: libelle }),
    h('span', { class: 'wcm-entree-detail', text: route ? detail : 'Bientôt' }),
  ];
  if (!route) {
    return h('span', { class: 'wcm-entree', 'aria-disabled': 'true' }, ...contenu);
  }
  // `data-route` : le routeur intercepte le clic, pas de rechargement complet.
  return h('a', { class: 'wcm-entree', href: route, 'data-route': route }, ...contenu);
}

let _lien = null;

export function mount(el) {
  _lien = document.createElement('link');
  _lien.rel = 'stylesheet';
  _lien.href = FEUILLE;
  document.head.appendChild(_lien);

  el.appendChild(h('section', { class: 'wcm' },
    h('div', { class: 'wcm-trame', 'aria-hidden': 'true' }),
    h('div', { class: 'wcm-vignette', 'aria-hidden': 'true' }),
    h('div', { class: 'wcm-etincelles', 'aria-hidden': 'true' },
      etincelles().map((p) => h('span', {
        class: 'wcm-etincelle',
        style: `left:${p.l};top:${p.t};animation-delay:${p.d}`,
      })),
    ),
    banderole('haut'),
    h('div', { class: 'wcm-centre' },
      h('div', { class: 'wcm-plaque' },
        h('span', { class: 'wcm-sur', text: 'LE JEU DE CARTES DE LA COMMU' }),
        h('h1', { class: 'wcm-titre', text: 'WALLYCARD' }),
        h('span', { class: 'wcm-trait', 'aria-hidden': 'true' }),
        h('nav', { class: 'wcm-menu', 'aria-label': 'Menu de Wallycard' },
          ENTREES.map(entree)),
        ['hg', 'hd', 'bg', 'bd'].map((coin) =>
          h('span', { class: 'wcm-coin', 'data-coin': coin, 'aria-hidden': 'true' })),
      ),
    ),
    banderole('bas'),
  ));
  el.appendChild(pageFooter());
}

export function unmount() {
  if (_lien) _lien.remove();
  _lien = null;
}
